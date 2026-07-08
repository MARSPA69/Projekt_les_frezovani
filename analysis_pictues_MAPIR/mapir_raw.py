"""
Nacitani RAW souboru z MAPIR Survey 3N (NIR kamera).

PROC RAW A NE JPG:
    JPG export z MAPIRu je white-balancovany nahled, ve kterem jsou vsechny
    tri kanaly temer identicke (korelace R<->B ~ 0.998). Spektralni informace
    NIR vs Red je v nem nenavratne slita dohromady, takze NDVI = (NIR-Red)/
    (NIR+Red) z JPG vyjde ~ 0 (falesny "vazny stres"). Pouzitelna NDVI data
    jsou POUZE v RAW souboru.

FORMAT RAW:
    12-bit packed Bayer, 4000 x 3000 px (12 MPx) = 18 000 000 bajtu.
    Kazde 2 pixely jsou ulozeny ve 3 bajtech (MIPI RAW12).

SPEKTRALNI ROZLOZENI (empiricky overeno na testovaci sade):
    Senzor je sloupcove prokladany na dve pasma:
        - sude sloupce  = NIR (850 nm)  -- vysoke DN (vegetace silne odrazi)
        - liche sloupce = Red (660 nm)  -- nizke DN (chlorofyl pohlcuje)
    Vysledna dve pasma jsou co-registrovana (sousedni NIR/Red pixely = stejne
    misto sceny), takze NDVI se pocita bez dalsiho demozaikovani.

NAVAZNOST NA PIPELINE:
    Funkce vraci synteticky BGR nosic (uint8), kde
        R kanal (index 2) = NIR
        B kanal (index 0) = Red
    coz presne odpovida ndvi_processor.extract_channels() (NIR=R, Red=B).
    Zbytek aplikace (kalibrace, ROI, indexy) tak funguje beze zmeny.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import cv2

# Nativni rozliseni senzoru Survey 3N
RAW_WIDTH = 4000
RAW_HEIGHT = 3000
RAW_BYTES = RAW_WIDTH * RAW_HEIGHT * 3 // 2  # 12-bit packed = 1.5 B/px

# Prah pro detekci den/noc podle prumerneho DN v Red pasmu (12-bit).
# Ve dne je Red band osvetleny (mean DN ~ 60-170), v noci kolabuje k ~0.
# Bez osvetleneho Red pasma nelze pocitat platne NDVI.
DAYNIGHT_RED_DN_THRESHOLD = 20.0


@dataclass
class RawLoad:
    """Vysledek nacteni RAW: nosic + radiometricke/day-night metadata."""
    carrier_bgr: np.ndarray   # synteticky BGR (R=NIR, B=Red), uint8
    is_night: bool            # True = nocni snimek (NDVI neplatne)
    nir_mean_dn: float        # prumer NIR pasma v DN (0..4095)
    red_mean_dn: float        # prumer Red pasma v DN (0..4095)
    black_level: float        # odhadnuta dark konstanta (DN)
    dark_applied: bool        # byla dark konstanta odectena?
    note: str                 # lidsky citelny popis (den/noc + co se stalo)


def is_raw_filename(name: str) -> bool:
    """True pokud jde o MAPIR RAW soubor podle pripony."""
    return bool(name) and name.lower().endswith(".raw")


def _unpack_raw12(data: bytes, width: int, height: int) -> np.ndarray:
    """Rozbali 12-bit packed (RAW12) buffer na uint16 Bayer pole height x width."""
    buf = np.frombuffer(data, dtype=np.uint8)
    expected = width * height * 3 // 2
    if buf.size != expected:
        raise ValueError(
            f"Neocekavana velikost RAW: {buf.size} B "
            f"(cekano {expected} B pro {width}x{height} 12-bit). "
            "Je to opravdu RAW z MAPIR Survey 3N?"
        )
    d = buf.reshape(-1, 3).astype(np.uint16)
    p0 = (d[:, 0] << 4) | (d[:, 1] >> 4)
    p1 = ((d[:, 1] & 0x0F) << 8) | d[:, 2]
    px = np.empty(p0.size + p1.size, dtype=np.uint16)
    px[0::2] = p0
    px[1::2] = p1
    return px.reshape(height, width)


def split_nir_red(bayer: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Rozdeli Bayer pole na (nir, red) podle parity sloupcu.
    Ktere pasmo je NIR se urci automaticky podle jasu (NIR vegetace >> Red).
    Vraci dve co-registrovana pole float32 (height x width/2), DN 0..4095.
    """
    even = bayer[:, 0::2].astype(np.float32)
    odd = bayer[:, 1::2].astype(np.float32)
    if even.mean() >= odd.mean():
        return even, odd
    return odd, even


def estimate_black_level(bayer: np.ndarray) -> float:
    """
    Odhad dark konstanty (sensor black level) z nejtmavsich pixelu snimku.
    Pouzivame robustni nizky percentil misto absolutniho minima (odolne vuci
    vadnym pixelum). Slouzi jako dark-frame nahrada, kdyz nemame krytku.
    """
    return float(np.percentile(bayer, 0.5))


def classify_daynight(red_mean_dn: float) -> bool:
    """True = nocni snimek (Red pasmo neni osvetleno -> NDVI neplatne)."""
    return red_mean_dn < DAYNIGHT_RED_DN_THRESHOLD


def load_mapir_raw(data: bytes,
                   width: int = RAW_WIDTH,
                   height: int = RAW_HEIGHT,
                   apply_dark_at_night: bool = True) -> RawLoad:
    """
    Nacte MAPIR Survey 3N RAW a vrati `RawLoad` se syntetickym co-registrovanym
    BGR nosicem (uint8, height x width), kde R kanal = NIR a B kanal = Red.

    Den/noc:
        Automaticky se klasifikuje podle prumeru Red pasma (DAYNIGHT_RED_DN_
        THRESHOLD). Nocni snimky nemaji osvetlene Red pasmo, takze NDVI z nich
        NENI platne - jsou oznaceny `is_night=True`.

    Dark konstanta:
        U NOCNICH snimku se automaticky odecte odhadnuta dark konstanta
        (black level), aby zbytkovy sum senzoru nefabrikoval falesne NDVI.
        DENNI snimky maji dostatecny signal a dark subtrakci zamerne
        NEAPLIKUJEME (zbytecne by zvysovala saturaci NDVI vegetace).

    NDVI je scale-invariantni, takze 12-bit DN skalujeme na 8-bit (/16) kvuli
    kompatibilite se zbytkem pipeline (kalibrace pracuje v rozsahu 0..255).
    """
    bayer = _unpack_raw12(data, width, height)
    nir, red = split_nir_red(bayer)  # height x width/2, DN 0..4095

    nir_mean = float(nir.mean())
    red_mean = float(red.mean())
    is_night = classify_daynight(red_mean)
    black = estimate_black_level(bayer)

    dark_applied = False
    if is_night and apply_dark_at_night:
        nir = np.clip(nir - black, 0.0, None)
        red = np.clip(red - black, 0.0, None)
        dark_applied = True
        note = (f"NOC (Red DN={red_mean:.1f} < {DAYNIGHT_RED_DN_THRESHOLD:.0f}). "
                f"Dark konstanta {black:.0f} DN automaticky odectena. "
                f"NDVI je NEPLATNE - nocni snimek bez osvetleneho Red pasma.")
    elif is_night:
        note = (f"NOC (Red DN={red_mean:.1f}). NDVI je NEPLATNE - "
                f"nocni snimek bez osvetleneho Red pasma.")
    else:
        note = (f"DEN (Red DN={red_mean:.1f}). NDVI platne, "
                f"dark konstanta se pres den neaplikuje.")

    nir8 = np.clip(nir / 16.0, 0, 255).astype(np.uint8)
    red8 = np.clip(red / 16.0, 0, 255).astype(np.uint8)

    # BGR: B=Red, G=NIR (jen pro nahled), R=NIR
    bgr_half = np.dstack([red8, nir8, nir8])

    # obnova pomeru stran (sloupce byly pulene) -> zpet na nativni sirku
    bgr = cv2.resize(bgr_half, (width, height), interpolation=cv2.INTER_LINEAR)

    return RawLoad(
        carrier_bgr=bgr,
        is_night=is_night,
        nir_mean_dn=nir_mean,
        red_mean_dn=red_mean,
        black_level=black,
        dark_applied=dark_applied,
        note=note,
    )
