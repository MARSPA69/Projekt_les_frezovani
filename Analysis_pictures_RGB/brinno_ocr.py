"""
Cteni vypaleneho casoveho razitka z casosbernych AVI kamery Brinno TLC2000.

PROC VLASTNI OCR A NE TESSERACT:
    Brinno vypaluje razitko do cerneho pruhu pod obrazem ve tvaru
        "TLC2000 2026/07/15 12:11:17"
    pevnym monospace fontem, vzdy na stejnem miste a vzdy bile na cerne.
    Tesseract v systemu neni a jeho instalace je zbytecna - pro pevny font
    staci template matching, ktery je navic deterministicky a rychlejsi.
    Sablony 11 glyfu (0-9 a '/') jsou zabalene primo v tomto souboru, takze
    modul nema zadnou externi zavislost krome numpy/opencv.

PROC NESTACI DOPOCITAT CAS Z INDEXU SNIMKU:
    Interval mezi snimky NENI presne 2 h - na lokalite "freza" je 7230 s,
    takze cas snimku se behem sezony posune o cele hodiny. Kdyby se nocni
    rez pocital z indexu, vyriznul by postupne uplne jine casti dne.
    Proto se cas cte z KAZDEHO snimku zvlast.

OVERENO:
    Na kompletni sade 2238 snimku obou lokalit (freza + nefreza, kveten az
    srpen 2026) precteno 100 % razitek, cas monotonne rostouci.

GEOMETRIE (Brinno TLC2000, 1920x1080):
    Cerny pruh zacina na radku 1048; text ma vysku ~20 px.
    Radek je "TLC2000 " + datum + cas = 25 souvislych bloku pixelu:
    7 znaku modelu (preskakuji se), 10 znaku data (vc. dvou '/'),
    8 znaku casu (dvojtecky jsou uzke bloky sirky ~3 px).
"""

from __future__ import annotations

import base64
import datetime as dt
import zlib
from dataclasses import dataclass

import cv2
import numpy as np

# --- geometrie razitka ------------------------------------------------------

BAND_TOP = 1048           # prvni radek cerneho pruhu s razitkem
BAND_BOTTOM = 1080        # konec snimku
BINARY_THRESHOLD = 128    # bile pismo na cerne -> pevny prah je bezpecny
MODEL_PREFIX_GLYPHS = 7   # "TLC2000" - preskakuje se
EXPECTED_GLYPH_RUNS = 25  # "TLC2000" + "2026/07/15" + "12:11:17"
COLON_MAX_WIDTH = 6       # dvojtecka je vyrazne uzsi nez cislice (3 vs 11 px)
MAX_TEMPLATE_DISTANCE = 25.0  # prumerna abs. odchylka; typicka shoda je < 5

# --- sablony glyfu ----------------------------------------------------------

GLYPH_LABELS = "0123456789/"
GLYPH_HEIGHT = 16
GLYPH_WIDTH = 12

# 11 sablon 16x12 uint8, zlib+base64. Ziskano shlukovanim glyfu z realnych
# snimku obou lokalit a rucnim oznacenim shluku.
_GLYPH_BLOB = (
    "eNrFlbFrIkEUxucfSK4UZGHLcI1NRGJjdYYjYHNBCELqNAERLE11pSDCNQd2chJYUh1JYbnNyJFwsCmWAzkQlgMRRCOIYPPuvZ15OyPxTrnmXp"
    "H5ZXfm7TdvvjcKkfIBw08JIbJDGEqJf7JCjMEvCFHwYSxqCyjiW1GERQ2g6RK7TVqVEXFkXnM7itrbePt8k9P+lq1hQ5ul2XG+EB7TGoCf8lmz"
    "570Tx5op/jdLDNT2TCNY4UzUSHsBCOi1DHGPnueq8vTnZc5FtdrFucBwESaOooPqqq8fup+AMff1h9dQ+OHRL+mn9VEvq7Ez++hqlGsIpQ5bv0"
    "g76iycNHpG66fz6vyr/mkeh16EMQnTQvMUFFO8l2rOzpzem5gKHmqAx1jaEFBbUnOHczpgVoJMuAyCuQathGnU7EE54XhQHIGz+SAe8iCt9eU4"
    "aLTrWdNBlCgyu3rNY145JtZndE9cTCb+mX0PoyFMnlmXuOhgVGH9PZlaGO8+O5uPuqb+Plj1R2/bnsdedu7on/h8A+pxKQPcS2lEvY9+7Wxobi"
    "2brtl/Rlxr/chtSjvDvWMtVlXcQAVrglxg/X+7r5hri+4R69f3D/YReljdP8rbfP+gf+yz4/4IYS1ND44Z3342fAm/rgwHjJXhtwxzPelT0YRl"
    "z3BXmP69Zu5Ck/EqNNyHbsZwPcFV9UDjRv8q/9Aey/N+hvt3n7rlp0Eu6d90OEn612J7zj45AVgD5WdtlN/SzJwSrD/2WHkeeyb+7QDgM6Xfr3"
    "2+azyDOSvUCyvieznDl5O28nkDrXdte95tLlsb567uwII/KvHdOIzPOh3SR+6clOnlw4v1E/Op8cnJQ3S5xSepm5fbLT45HwzOtvjE8sbZYHC+"
    "xQ+3LzeJlgDMF6OHE3NXnDI+rS8OmX8DLzIQxA=="
)

_TEMPLATES: np.ndarray | None = None


def _templates() -> np.ndarray:
    """Vrati sablony glyfu jako int16 pole (11, 16, 12). Cachovano."""
    global _TEMPLATES
    if _TEMPLATES is None:
        raw = zlib.decompress(base64.b64decode(_GLYPH_BLOB))
        arr = np.frombuffer(raw, dtype=np.uint8)
        _TEMPLATES = arr.reshape(len(GLYPH_LABELS), GLYPH_HEIGHT, GLYPH_WIDTH).astype(np.int16)
    return _TEMPLATES


# --- vlastni cteni ----------------------------------------------------------


@dataclass
class StampResult:
    """Vysledek cteni jednoho razitka."""
    timestamp: dt.datetime | None   # None = nepodarilo se precist
    text: str                       # co se precetlo (i kdyz to neni platne datum)
    reason: str                     # proc se nepodarilo (prazdne pri uspechu)


def _normalise_glyph(patch: np.ndarray) -> np.ndarray | None:
    """Orizne glyf na bounding box a natahne na jednotnou velikost sablony."""
    rows = np.where(patch.sum(axis=1) > 0)[0]
    cols = np.where(patch.sum(axis=0) > 0)[0]
    if rows.size == 0 or cols.size == 0:
        return None
    cropped = patch[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
    return cv2.resize(
        cropped.astype(np.uint8) * 255,
        (GLYPH_WIDTH, GLYPH_HEIGHT),
        interpolation=cv2.INTER_AREA,
    )


def _segment_runs(binary: np.ndarray) -> list[tuple[int, int]]:
    """Rozdeli binarni pruh na svisle bloky (jeden blok = jeden znak)."""
    occupied = binary.sum(axis=0) > 0
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for x, on in enumerate(occupied):
        if on and start is None:
            start = x
        elif not on and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(occupied)))
    return runs


def read_stamp(frame: np.ndarray) -> StampResult:
    """
    Precte casove razitko z jednoho snimku Brinno.

    `frame` je BGR snimek v nativnim rozliseni 1920x1080. Vraci `StampResult`;
    pri neuspechu je `timestamp` None a `reason` popisuje proc, aby volajici
    mohl chybne snimky vypsat misto tichého preskoceni.
    """
    if frame is None or frame.shape[0] < BAND_BOTTOM:
        return StampResult(None, "", "snimek nema ocekavanou vysku 1080 px")

    band = frame[BAND_TOP:BAND_BOTTOM]
    grey = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    binary = (grey > BINARY_THRESHOLD).astype(np.uint8)

    runs = _segment_runs(binary)
    if len(runs) != EXPECTED_GLYPH_RUNS:
        return StampResult(None, "", f"nalezeno {len(runs)} znaku misto {EXPECTED_GLYPH_RUNS}")

    templates = _templates()
    chars: list[str] = []
    for position, (left, right) in enumerate(runs):
        if position < MODEL_PREFIX_GLYPHS:
            continue                       # "TLC2000"
        if right - left <= COLON_MAX_WIDTH:
            chars.append(":")              # uzky blok = dvojtecka v case
            continue
        glyph = _normalise_glyph(binary[:, left:right])
        if glyph is None:
            return StampResult(None, "".join(chars), f"prazdny glyf na pozici {position}")
        distances = np.mean(np.abs(templates - glyph.astype(np.int16)), axis=(1, 2))
        best = int(distances.argmin())
        if distances[best] > MAX_TEMPLATE_DISTANCE:
            return StampResult(
                None, "".join(chars),
                f"glyf na pozici {position} neodpovida zadne sablone "
                f"(odchylka {distances[best]:.1f})",
            )
        chars.append(GLYPH_LABELS[best])

    text = "".join(chars)
    try:
        stamp = dt.datetime.strptime(text, "%Y/%m/%d%H:%M:%S")
    except ValueError:
        return StampResult(None, text, f"'{text}' neni platne datum a cas")
    return StampResult(stamp, text, "")
