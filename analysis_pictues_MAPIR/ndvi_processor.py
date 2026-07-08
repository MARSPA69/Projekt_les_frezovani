"""
Zpracovani snimku MAPIR Survey 3N - kalibrace, multi-index analyza, statistiky.

Pro Survey 3N je R-kanal raw JPG = NIR (850 nm), B-kanal = Red (661 nm).
Po aplikaci kalibrace (gain, offset) ziskame reflektance v [0..1],
ze kterych pocitame 6 vegetacnich indexu z `indices.py`.

NDVI zustava primarnim indexem (zpetna kompatibilita pro UI a reporting),
ostatni indexy doplnuji biologickou interpretaci.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from calibration import CalibrationBundle
from indices import (
    INDICES,
    IndexInfo,
    IndexStats,
    compute_all_indices,
    compute_index_stats,
)


# =========================================================================
# Statistiky NDVI (zachovany typ pro zpetnou kompatibilitu)
# =========================================================================

@dataclass
class NDVIStats:
    """Statistiky pro PRIMARNI NDVI - pouzite UI / reportingem."""
    mean: float
    median: float
    std: float
    p10: float
    p25: float
    p75: float
    p90: float
    fraction_vegetated: float        # NDVI > 0.2
    fraction_healthy: float          # NDVI > 0.5
    fraction_stressed: float         # 0.2 < NDVI < 0.4
    fraction_bare_or_dead: float     # NDVI < 0.2
    pixel_count: int


@dataclass
class NDVIResult:
    """Vysledek analyzy - obsahuje primarni NDVI i vsechny dalsi indexy."""
    nir_reflectance: np.ndarray
    red_reflectance: np.ndarray
    ndvi: np.ndarray
    valid_mask: np.ndarray
    stats: NDVIStats                              # primarni NDVI statistiky
    # Multi-index vystupy:
    index_arrays: dict[str, np.ndarray] = field(default_factory=dict)
    index_stats: dict[str, IndexStats] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# =========================================================================
# Reflektance: kanalove mapovani Survey 3N
# =========================================================================

def extract_channels(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Vrati (nir_dn, red_dn) jako float32 pole [0..255].
    Pro Survey 3N: NIR = R kanal, Red = B kanal.
    """
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ValueError("Ocekavan BGR obrazek 3 kanaly.")
    nir = image_bgr[..., 2].astype(np.float32)  # R kanal v BGR
    red = image_bgr[..., 0].astype(np.float32)  # B kanal v BGR
    return nir, red


def apply_calibration(dn: np.ndarray, gain: float, offset: float) -> np.ndarray:
    """Aplikuje linearni kalibraci DN -> reflektance."""
    return dn * gain + offset


# =========================================================================
# Masky a primarni NDVI statistiky
# =========================================================================

def build_valid_mask(nir_refl: np.ndarray, red_refl: np.ndarray,
                     mask_overexposed: bool = True,
                     mask_underexposed: bool = True) -> np.ndarray:
    """Maska pro vyloouceni prepalu a podexpozice."""
    mask = np.ones_like(nir_refl, dtype=bool)
    if mask_overexposed:
        mask &= ~((nir_refl > 0.98) & (red_refl > 0.98))
    if mask_underexposed:
        mask &= ~((nir_refl < 0.02) & (red_refl < 0.02))
    return mask


def _ndvi_class_stats(ndvi_arr: np.ndarray, valid_mask: np.ndarray) -> NDVIStats:
    """Spocita primarni NDVI statistiky vcetne klasifikacnich frakci."""
    flat = ndvi_arr[valid_mask]
    flat = flat[np.isfinite(flat)]
    n = int(flat.size)
    if n == 0:
        return NDVIStats(
            mean=0, median=0, std=0,
            p10=0, p25=0, p75=0, p90=0,
            fraction_vegetated=0, fraction_healthy=0,
            fraction_stressed=0, fraction_bare_or_dead=0,
            pixel_count=0,
        )
    return NDVIStats(
        mean=float(flat.mean()),
        median=float(np.median(flat)),
        std=float(flat.std()),
        p10=float(np.percentile(flat, 10)),
        p25=float(np.percentile(flat, 25)),
        p75=float(np.percentile(flat, 75)),
        p90=float(np.percentile(flat, 90)),
        fraction_vegetated=float((flat > 0.2).mean()),
        fraction_healthy=float((flat > 0.5).mean()),
        fraction_stressed=float(((flat > 0.2) & (flat < 0.4)).mean()),
        fraction_bare_or_dead=float((flat < 0.2).mean()),
        pixel_count=n,
    )


# =========================================================================
# Hlavni vstup
# =========================================================================

def process_image(image_bgr: np.ndarray,
                  calibration: CalibrationBundle,
                  exclude_target_roi: Optional[tuple[int, int, int, int]] = None,
                  ) -> NDVIResult:
    """
    Plne zpracovani snimku:
        1) Extrakce a kalibrace kanalu (NIR=R, Red=B)
        2) Maska validnich pixelu (vyloouceni saturace/podexp/ROI tercku)
        3) Vypocet 6 vegetacnich indexu z indices.INDICES
        4) Statistiky primarniho NDVI + vsech indexu

    Returns:
        NDVIResult s `ndvi` jako primarni metrikou a `index_arrays`/
        `index_stats` se vsemi 6 indexy.
    """
    nir_dn, red_dn = extract_channels(image_bgr)
    nir_refl = apply_calibration(nir_dn, calibration.nir.gain,
                                  calibration.nir.offset)
    red_refl = apply_calibration(red_dn, calibration.red.gain,
                                  calibration.red.offset)

    nir_refl = np.clip(nir_refl, 0.0, 1.5)
    red_refl = np.clip(red_refl, 0.0, 1.5)

    valid = build_valid_mask(nir_refl, red_refl)
    if exclude_target_roi is not None:
        x, y, w, h = exclude_target_roi
        h_img, w_img = valid.shape
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(w_img, x + w), min(h_img, y + h)
        valid[y1:y2, x1:x2] = False

    # Multi-index vypocet
    idx_arrays = compute_all_indices(nir_refl, red_refl, valid)
    idx_stats = {
        code: compute_index_stats(arr, valid, INDICES[code])
        for code, arr in idx_arrays.items()
    }

    # Primarni NDVI
    ndvi_arr = idx_arrays["NDVI"]
    stats = _ndvi_class_stats(ndvi_arr, valid)

    # Varovani
    warnings: list[str] = []
    if stats.pixel_count < 1000:
        warnings.append(
            f"Pouze {stats.pixel_count} validnich pixelu - snimek je "
            "vetsinou maskovany (prepal/podexpozice/ROI tercku)."
        )
    if stats.fraction_bare_or_dead > 0.7:
        warnings.append(
            "Vetsina sceny ma NDVI < 0.2. Kontrola: spravna sezona? "
            "Holy les v zime? Obraceny kanalovy mapping?"
        )
    # Saturace primarniho indexu
    ndvi_info = INDICES["NDVI"]
    if stats.p90 > ndvi_info.saturation_warning:
        warnings.append(
            f"NDVI p90 = {stats.p90:.2f} - vegetace je saturovana. "
            "Pro citlivy monitoring koruny sleduj WDRVI nebo MSAVI2."
        )

    return NDVIResult(
        nir_reflectance=nir_refl,
        red_reflectance=red_refl,
        ndvi=ndvi_arr,
        valid_mask=valid,
        stats=stats,
        index_arrays=idx_arrays,
        index_stats=idx_stats,
        warnings=warnings,
    )


# =========================================================================
# Vizualizace
# =========================================================================

def index_to_rgb(arr: np.ndarray, info: IndexInfo,
                 cmap_name: str = "RdYlGn") -> np.ndarray:
    """
    Vykresli libovolny index jako RGB heatmapu.
    Skalovani podle `typical_range` daneho indexu.
    """
    import matplotlib.cm as cm
    valid = np.isfinite(arr)
    lo, hi = info.typical_range
    norm = (np.where(valid, arr, lo) - lo) / max(hi - lo, 1e-6)
    norm = np.clip(norm, 0.0, 1.0)
    # FCI2 ma opacnou logiku (nizsi = lesnatejsi) -> obratit barevnou skalu
    if info.code == "FCI2":
        norm = 1.0 - norm
    cmap = cm.get_cmap(cmap_name)
    rgba = cmap(norm)
    rgba[..., :3] = np.where(valid[..., None], rgba[..., :3], 0.2)
    return (rgba[..., :3] * 255).astype(np.uint8)


def ndvi_to_rgb(ndvi: np.ndarray) -> np.ndarray:
    """Zachovano pro zpetnou kompatibilitu - delegujeme na index_to_rgb."""
    return index_to_rgb(ndvi, INDICES["NDVI"])


# Legenda barev NDVI heatmapy (RdYlGn, rozsah -0.2 az 0.9).
# Kazda polozka: (hex barva, popis rozsahu NDVI, biologicky vyznam).
# Hex barvy jsou reprezentativni vzorky z colormapy RdYlGn.
NDVI_COLOR_LEGEND = [
    ("#006837", "0,8 – 1,0",  "Velmi vitalni, husta vegetace. U nekalibrovanych "
                              "dat casto saturuje (NDVI se blizi 1,0)."),
    ("#4cae4c", "0,55 – 0,8", "Zdrava, fotosynteticky aktivni vegetace."),
    ("#c7e77f", "0,4 – 0,55", "Slabsi / mlada / ridsi vegetace (pod prahem zdravi)."),
    ("#fef1a7", "0,3 – 0,4",  "Ridka nebo stresovana vegetace."),
    ("#fa9a58", "0,15 – 0,3", "Prechod: prosychajici, velmi ridka vegetace, "
                              "nebo travni suchopar."),
    ("#ee613d", "0,0 – 0,15", "Bez vegetace: hola puda, cesty, mulc, konstrukce."),
    ("#a50026", "< 0,0",      "Voda, hluboky stin, umele/lesle povrchy."),
    ("#333333", "—",          "Prazdna (seda) mista = NEPLATNY pixel: prepal, "
                              "podexpozice, nebo vylouceny kalibracni tercik. "
                              "Bez hodnoty NDVI."),
]
