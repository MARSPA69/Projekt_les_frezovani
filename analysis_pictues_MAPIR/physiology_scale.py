"""
Davkova relativni fyziologicka skala pro RAW snimky lesni skolky.

Princip (relativni analytika, BEZ kalibracniho terciku):
    1) Kazdy denni RAW se prevede na NIR/Red nosic a spocita se robustni
       index vitality OSAVI (median pres vegetacni pixely). OSAVI je zvoleny,
       protoze je nejstabilnejsi vuci osvetleni (CV ~3 %) a NEsaturuje jako
       NDVI (median NDVI = 1.0 -> pro rozliseni kategorii nepouzitelne).
    2) Snimky se seradi a rozdeli do N kategorii (4-6) RELATIVNE v ramci davky
       - podle pozice v rozsahu [min..max] dane serie. Tim se rusi absolutni
       vliv osvetleni; skala rika "ktera skolka je na tom v teto serii lepe".

DULEZITE:
    - Focte celou serii najednou za stejneho (idealne difuzniho) svetla.
    - Nocni snimky (Red pasmo neosvetlene) se do skaly nezahrnuji.
    - Vysledek je RELATIVNI poradi, ne absolutni fyziologicka hodnota.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from calibration import default_fallback_calibration
from mapir_raw import load_mapir_raw
from ndvi_processor import process_image

# Vychozi index skaly + duvod viz docstring.
SCALE_INDEX = "OSAVI"

# Prah smysluplneho rozptylu (v jednotkach OSAVI). Zmereny sum osvetleni
# na stejne scene pres den je ~0.05 OSAVI. Pokud je rozptyl davky pod timto
# prahem, rozdily jsou v ramci sumu osvetleni a NELZE je fyziologicky
# kategorizovat - skala by binovala jen sum.
MEANINGFUL_SPREAD_OSAVI = 0.05

# Pojmenovani kategorii od nejhorsi po nejlepsi (podporujeme 4-6 kategorii).
CATEGORY_LABELS = {
    4: ["Kriticka", "Oslabena", "Dobra", "Vyborna"],
    5: ["Kriticka", "Oslabena", "Prumerna", "Dobra", "Vyborna"],
    6: ["Kriticka", "Slaba", "Podprumerna", "Prumerna", "Dobra", "Vyborna"],
}

# Barvy kategorii (od nejhorsi po nejlepsi) - cervena -> zelena.
CATEGORY_COLORS = {
    4: ["#c62828", "#ef6c00", "#9e9d24", "#2e7d32"],
    5: ["#c62828", "#ef6c00", "#f9a825", "#9e9d24", "#2e7d32"],
    6: ["#c62828", "#e64a19", "#ef6c00", "#f9a825", "#9e9d24", "#2e7d32"],
}


@dataclass
class BatchResult:
    """Vysledek davkove kategorizace + diagnostika rozptylu."""
    scores: list                # list[ImageScore]
    n_categories: int
    span: float                 # rozptyl OSAVI v davce (max - min)
    meaningful: bool            # je rozptyl nad prahem sumu osvetleni?
    n_day: int
    n_night: int
    message: str


@dataclass
class ImageScore:
    """Skore jednoho snimku pro fyziologickou skalu."""
    name: str
    is_night: bool
    scale_value: float          # median OSAVI pres vegetacni pixely
    veg_cover: float            # podil vegetacnich pixelu (0..1) = pokryvnost
    ndvi_mean: float            # doplnkove
    note: str = ""
    # doplneno pri kategorizaci:
    category_index: int = -1    # 0 = nejhorsi
    category_label: str = ""
    category_color: str = ""
    rel_position: float = 0.0   # 0..1 pozice v rozsahu davky


def score_carrier(name: str, carrier_bgr: np.ndarray, is_night: bool,
                  note: str = "") -> ImageScore:
    """Spocita fyziologicke skore z hotoveho NIR/Red nosice."""
    cal = default_fallback_calibration()
    res = process_image(carrier_bgr, cal)
    osavi = res.index_arrays[SCALE_INDEX]
    ndvi = res.ndvi
    valid = res.valid_mask
    # vegetacni pixely: NDVI > 0.2 a validni
    veg = valid & np.isfinite(ndvi) & (ndvi > 0.2)
    veg_vals = osavi[veg & np.isfinite(osavi)]
    scale_value = float(np.median(veg_vals)) if veg_vals.size else 0.0
    veg_cover = float(veg.sum()) / float(valid.sum()) if valid.sum() else 0.0
    return ImageScore(
        name=name, is_night=is_night, scale_value=scale_value,
        veg_cover=veg_cover, ndvi_mean=float(res.stats.mean), note=note,
    )


def score_raw_bytes(name: str, data: bytes) -> ImageScore:
    """Nacte RAW a spocita skore. Nocni snimky oznaci (do skaly nepatri)."""
    raw = load_mapir_raw(data)
    if raw.is_night:
        return ImageScore(name=name, is_night=True, scale_value=0.0,
                          veg_cover=0.0, ndvi_mean=0.0, note=raw.note)
    return score_carrier(name, raw.carrier_bgr, is_night=False, note=raw.note)


def assign_categories(scores: list[ImageScore], n_categories: int = 5,
                      mode: str = "interval") -> BatchResult:
    """
    Priradi kategorie RELATIVNE v ramci davky (jen dennim snimkum).

    mode:
        "interval" - linearni deleni rozsahu [min..max] na N stejnych pasem
                     (zachovava relativni rozestupy hodnot).
        "quantile" - stejny pocet snimku v kazde kategorii (podle poradi).

    POJISTKA: pokud je rozptyl davky pod prahem sumu osvetleni
    (MEANINGFUL_SPREAD_OSAVI), rozdily NEJSOU fyziologicke - vsechny denni
    snimky se zaradi do jedne (nejlepsi) kategorie a `meaningful=False`.
    """
    n = max(4, min(6, int(n_categories)))
    labels = CATEGORY_LABELS[n]
    colors = CATEGORY_COLORS[n]

    day = [s for s in scores if not s.is_night]
    n_night = len(scores) - len(day)

    if not day:
        return BatchResult(scores, n, 0.0, False, 0, n_night,
                           "Zadny denni snimek - skala se nesestavuje "
                           "(nocni snimky nemaji platny NDVI).")

    vals = np.array([s.scale_value for s in day], dtype=float)
    vmin, vmax = float(vals.min()), float(vals.max())
    span = vmax - vmin
    meaningful = span >= MEANINGFUL_SPREAD_OSAVI

    if not meaningful:
        # Rozdily jsou v ramci sumu osvetleni -> nekategorizuj, vse = jedna trida
        for s in day:
            s.category_index = n - 1
            s.rel_position = 1.0
            s.category_label = "Bez rozliseni"
            s.category_color = "#607d8b"
        msg = (f"Rozptyl davky ({span:.3f} OSAVI) je POD prahem sumu osvetleni "
               f"({MEANINGFUL_SPREAD_OSAVI:.2f}). Rozdily nejsou fyziologicke - "
               f"snimky jsou v ramci mereni shodne. Pro rozliseni potrebujes "
               f"snimky s vetsimi fyziologickymi rozdily nebo prisnejsi "
               f"standardizaci osvetleni.")
        return BatchResult(scores, n, span, False, len(day), n_night, msg)

    if mode == "quantile" and len(day) >= n:
        order = np.argsort(vals)
        for cat, idx_group in enumerate(np.array_split(order, n)):
            for i in idx_group:
                day[i].category_index = cat
    else:
        for i, s in enumerate(day):
            rel = (vals[i] - vmin) / span
            s.category_index = min(n - 1, int(rel * n))

    for s in day:
        s.rel_position = float((s.scale_value - vmin) / span)
        s.category_label = labels[s.category_index]
        s.category_color = colors[s.category_index]

    msg = (f"Skala sestavena z {len(day)} dennich snimku "
           f"(rozptyl {span:.3f} OSAVI). {n_night} nocnich vynechano.")
    return BatchResult(scores, n, span, True, len(day), n_night, msg)
