"""
Casova rada vegetacnich indexu z RAW snimku MAPIR Survey 3N.

RELATIVNI ANALYZA:
    Sada nema pri kazdem zachytu kalibracni tercik, takze prevod na absolutni
    odrazivost neni mozny. NDVI je ale pomerovy index - konstantni multiplikativni
    zisk se v citateli i jmenovateli krati, takze RELATIVNI vyvoj v case je
    platny i bez kalibrace. Absolutni uroven se proto v reportu neinterpretuje
    jako presna hodnota odrazivosti a hodnoty se nesrovnavaji s jinou kamerou.

NOCNI SNIMKY:
    MAPIR fotografuje i v noci. Bez osvetleneho Red pasma je NDVI nesmysl,
    proto se nocni snimky poznaji podle prumeru Red pasma (mapir_raw.
    classify_daynight) a z casove rady se vyradi.

VYKON:
    Jeden RAW ma 18 MB a rozbaleni 12-bit packed pole neni zadarmo. Aby se
    sada 811 snimku zpracovala v rozumnem case, pocitaji se statistiky na
    PODVZORKOVANEM poli (kazdy n-ty pixel). NDVI je prostorovy prumer pres
    miliony pixelu, takze podvzorkovani 1:16 zmeni vysledek az na tretim
    desetinnem miste, ale zrychli beh radove.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np
import pandas as pd

import indices
import mapir_raw
from tl_scan import Shot

# Plny rozsah 12-bit senzoru. Pasma se pred vypoctem indexu deli timto cislem,
# aby byla v rozsahu 0..1 jako odrazivost.
#
# PROC TO NELZE VYNECHAT:
#   NDVI je pomerovy, takze meritko krati a na skale nezalezi. OSAVI a RDVI ale
#   NE: OSAVI ma v citateli konstantu L=0.16, ktera je proti DN v tisicich
#   zanedbatelna, takze OSAVI zkolabuje presne na NDVI. RDVI deli odmocninou
#   souctu, takze jeho hodnota primo roste s meritkem (na syrovych DN vychazelo
#   kolem 40 misto radu desetin). Oba indexy jsou definovane pro odrazivost 0..1.
FULL_SCALE_DN = 4095.0

# Kazdy 4. pixel v obou osach = 1/16 dat. Pro prostorovy prumer bohate staci.
SUBSAMPLE = 4

# Minimalni podil platnych pixelu, aby se snimek pustil do rady.
MIN_VALID_FRACTION = 0.5

DAILY_PERCENTILE = 75


@dataclass
class NirSample:
    """Indexy jednoho RAW snimku."""
    timestamp: dt.datetime
    ndvi: float
    ndvi_p25: float
    ndvi_p75: float
    osavi: float
    rdvi: float
    nir_dn: float
    red_dn: float
    is_night: bool


def _indices_from_bands(nir_dn: np.ndarray, red_dn: np.ndarray) -> tuple[float, float, float, float, float]:
    """
    NDVI (prumer, p25, p75), OSAVI a RDVI ze dvou pasem.

    Pasma prichazeji v DN a prevadeji se na relativni odrazivost 0..1; teprve
    v ni davaji OSAVI a RDVI smysl. Vlastni vzorce se berou z modulu `indices`
    hlavni aplikace, aby se obe cesty nemohly rozejit.
    """
    nir = nir_dn / FULL_SCALE_DN
    red = red_dn / FULL_SCALE_DN

    valid = (nir + red) > 1e-6
    if valid.mean() < MIN_VALID_FRACTION:
        return (np.nan,) * 5

    ndvi = np.where(valid, indices.ndvi(nir, red), np.nan)
    osavi = np.where(valid, indices.osavi(nir, red), np.nan)
    rdvi = np.where(valid, indices.rdvi(nir, red), np.nan)

    return (float(np.nanmean(ndvi)),
            float(np.nanpercentile(ndvi, 25)),
            float(np.nanpercentile(ndvi, 75)),
            float(np.nanmean(osavi)),
            float(np.nanmean(rdvi)))


def analyse_raw(shot: Shot) -> NirSample | None:
    """
    Spocita indexy jednoho RAW snimku. Vraci None, pokud soubor nelze precist.

    Pracuje primo se syrovymi pasmy (DN 0..4095) misto s 8-bit nosicem
    z `load_mapir_raw`, aby se u tmavsich snimku neztratilo rozliseni
    kvantizaci na 256 urovni.
    """
    if shot.raw_path is None:
        return None
    try:
        data = shot.raw_path.read_bytes()
        bayer = mapir_raw._unpack_raw12(data, mapir_raw.RAW_WIDTH, mapir_raw.RAW_HEIGHT)
    except (OSError, ValueError):
        return None

    nir_full, red_full = mapir_raw.split_nir_red(bayer)
    nir_mean = float(nir_full.mean())
    red_mean = float(red_full.mean())
    is_night = mapir_raw.classify_daynight(red_mean)

    nir = nir_full[::SUBSAMPLE, ::SUBSAMPLE]
    red = red_full[::SUBSAMPLE, ::SUBSAMPLE]
    if is_night:
        # V noci je signal jen sum nad dark urovni; NDVI se stejne zahodi,
        # ale odecet dark konstanty brani nesmyslnym extremum v grafu.
        black = mapir_raw.estimate_black_level(bayer)
        nir = np.clip(nir - black, 0.0, None)
        red = np.clip(red - black, 0.0, None)

    ndvi, p25, p75, osavi, rdvi = _indices_from_bands(nir, red)
    return NirSample(
        timestamp=shot.timestamp,
        ndvi=ndvi, ndvi_p25=p25, ndvi_p75=p75,
        osavi=osavi, rdvi=rdvi,
        nir_dn=nir_mean, red_dn=red_mean,
        is_night=is_night,
    )


def analyse_series(shots: list[Shot], progress=None) -> list[NirSample]:
    """Spocita indexy pro vsechny RAW snimky sady."""
    with_raw = [s for s in shots if s.raw_path is not None]
    samples: list[NirSample] = []
    for done, shot in enumerate(with_raw, start=1):
        sample = analyse_raw(shot)
        if sample is not None:
            samples.append(sample)
        if progress and done % 10 == 0:
            progress(done, len(with_raw), "NIR analýza")
    if progress:
        progress(len(with_raw), len(with_raw), "hotovo")
    return samples


def daily_series(samples: list[NirSample]) -> pd.DataFrame:
    """
    Denni agregace indexu z DENNICH snimku.

    Bere 75. percentil - vyssi percentil potlaci snimky se stinem a nizkym
    sluncem, ale na rozdil od 90. percentilu neni tak citlivy na jednotlive
    presvicene snimky, kterych je u NIR vic.
    """
    daytime = [s for s in samples if not s.is_night and np.isfinite(s.ndvi)]
    if not daytime:
        return pd.DataFrame(columns=["ndvi", "osavi", "rdvi", "nir_dn", "red_dn", "n_snimku"])

    frame = pd.DataFrame({
        "date": [s.timestamp.date() for s in daytime],
        "ndvi": [s.ndvi for s in daytime],
        "osavi": [s.osavi for s in daytime],
        "rdvi": [s.rdvi for s in daytime],
        "nir_dn": [s.nir_dn for s in daytime],
        "red_dn": [s.red_dn for s in daytime],
    })
    grouped = frame.groupby("date").agg(
        ndvi=("ndvi", lambda v: float(np.percentile(v, DAILY_PERCENTILE))),
        osavi=("osavi", lambda v: float(np.percentile(v, DAILY_PERCENTILE))),
        rdvi=("rdvi", lambda v: float(np.percentile(v, DAILY_PERCENTILE))),
        nir_dn=("nir_dn", "median"),
        red_dn=("red_dn", "median"),
        n_snimku=("ndvi", "size"),
    )
    grouped.index = pd.to_datetime(grouped.index)
    return grouped.sort_index()


def smooth(series: pd.Series, window: int = 7) -> pd.Series:
    """Klouzavy median pro potlaceni denniho sumu."""
    return series.rolling(window=window, center=True, min_periods=1).median()
