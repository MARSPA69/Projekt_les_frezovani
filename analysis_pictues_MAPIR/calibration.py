"""
Kalibrace MAPIR Survey 3N NIR snimku.

Princip:
    Survey 3N je dual-band kamera s filterem Red(660 nm) + NIR(850 nm).
    V RAW JPG/TIFF jsou kanaly mapovany takto:
        R kanal  -> NIR (850 nm)
        B kanal  -> Red (660 nm)
        G kanal  -> nepouzity pro NDVI (zachycuje smes)

    Kalibrace prevadi DN (digital number, 0-255) na fyzikalni reflektanci
    (0.0 - 1.0) pomoci linearni regrese mezi zname reflektance terciku
    a namerene DN hodnoty patchu na snimku.

        reflectance = gain * DN + offset

    Tato kalibrace se aplikuje samostatne pro NIR a Red kanal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


# =========================================================================
# Reflektancni hodnoty kalibracniho tercku MAPIR T4 (4 patche)
# =========================================================================
#
# Aplikace pouziva tercik MAPIR T4-R50 se 4 patchi: White, Light Gray,
# Silver Gray, Dark Gray. Existuji DVE moznosti, kterymi lze tercik
# kalibrovat - vyber pres TARGET_REFLECTANCE_PROFILE nize.
#
# (A) NOMINAL_T4  - bezne nominalni hodnoty pouzivane v MAPIR softwaru
#                   (idealizovana skala 95/45/15/5 %). Vhodne pro rychlou
#                   pracovni kalibraci a kompatibilitu s ostatnimi MAPIR
#                   nastroji.
#
# (B) CHART_T4    - hodnoty odecitane ze spektralnich krivek (Diffuse Refl.)
#                   v dodanem grafu "MAPIR Diffuse Reflectance Standard
#                   Calibration Target Data T4" na pasmech, ktera Survey 3N
#                   skutecne vidi: Red filter @ 661 nm, NIR2 filter @ 850 nm.
#                   Fyzikalne presnejsi - krivky T4 NEJSOU linearni!
#
# Pokud mate dodany konkretni kalibracni list pro vas kus tercku
# (vyrobni cislo), prepiste hodnoty zde primo.

NOMINAL_T4 = {
    # patch_name :   (red, nir) - idealizovana nominalni skala
    "white":         (0.95, 0.95),
    "light_gray":    (0.45, 0.45),
    "silver_gray":   (0.15, 0.15),
    "dark_gray":     (0.05, 0.05),
}

CHART_T4 = {
    # patch_name :   (red_661nm, nir_850nm) - odeceteno z MAPIR T4 grafu
    "white":         (0.82, 0.84),
    "light_gray":    (0.67, 0.72),
    "silver_gray":   (0.40, 0.43),
    "dark_gray":     (0.22, 0.25),
}

# Aktivni profil - prepni dle potreby ("nominal" / "chart")
TARGET_REFLECTANCE_PROFILE = "nominal"

MAPIR_TARGET_REFLECTANCE = (
    NOMINAL_T4 if TARGET_REFLECTANCE_PROFILE == "nominal" else CHART_T4
)

# Poradi patchu od nejsvetlejsiho k nejtmavsimu
PATCH_ORDER = ["white", "light_gray", "silver_gray", "dark_gray"]


@dataclass
class CalibrationResult:
    """Vysledek kalibrace pro jeden kanal (NIR nebo Red)."""
    gain: float
    offset: float
    r_squared: float
    measured_dn: list[float]
    known_reflectance: list[float]


@dataclass
class CalibrationBundle:
    """Kompletni kalibrace - oba kanaly + metadata."""
    nir: CalibrationResult
    red: CalibrationResult
    patch_centers_px: list[tuple[int, int]]
    patch_size_px: int
    target_detected: bool
    detection_method: str  # "qr", "manual", "fallback"
    warnings: list[str]


def detect_calibration_target(image_bgr: np.ndarray) -> Optional[dict]:
    """
    Pokusi se detekovat kalibracni QR tercik na snimku.

    Strategie:
        1) Zkus pyzbar (pokud nainstalovan) - dekoduje QR + vrati polygon
        2) Fallback: OpenCV QRCodeDetector

    Returns:
        dict se 'corners' (4 body), 'data' (string QR), 'center' nebo None.
    """
    try:
        from pyzbar.pyzbar import decode as zbar_decode

        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        results = zbar_decode(gray)
        for r in results:
            if r.type == "QRCODE":
                pts = [(p.x, p.y) for p in r.polygon]
                if len(pts) >= 4:
                    cx = int(sum(p[0] for p in pts) / len(pts))
                    cy = int(sum(p[1] for p in pts) / len(pts))
                    return {
                        "corners": pts[:4],
                        "data": r.data.decode("utf-8", errors="ignore"),
                        "center": (cx, cy),
                        "method": "pyzbar",
                    }
    except Exception:
        pass

    # Fallback - OpenCV
    try:
        qr = cv2.QRCodeDetector()
        data, points, _ = qr.detectAndDecode(image_bgr)
        if points is not None and len(points) > 0:
            pts = [tuple(map(int, p)) for p in points[0]]
            cx = int(sum(p[0] for p in pts) / len(pts))
            cy = int(sum(p[1] for p in pts) / len(pts))
            return {
                "corners": pts,
                "data": data,
                "center": (cx, cy),
                "method": "opencv",
            }
    except Exception:
        pass

    return None


def sample_patch(image_bgr: np.ndarray, cx: int, cy: int,
                 half: int = 10) -> tuple[float, float, float]:
    """Vrati prumerne (B, G, R) DN v okoli (cx, cy) o polomeru `half` px."""
    h, w = image_bgr.shape[:2]
    x1, x2 = max(0, cx - half), min(w, cx + half + 1)
    y1, y2 = max(0, cy - half), min(h, cy + half + 1)
    roi = image_bgr[y1:y2, x1:x2].astype(np.float32)
    b = float(roi[..., 0].mean())
    g = float(roi[..., 1].mean())
    r = float(roi[..., 2].mean())
    return b, g, r


def calibrate_channel(measured_dn: list[float],
                      known_reflectance: list[float]) -> CalibrationResult:
    """Linearni regrese DN -> reflektance pro jeden kanal."""
    x = np.asarray(measured_dn, dtype=np.float64)
    y = np.asarray(known_reflectance, dtype=np.float64)

    if len(x) < 2:
        return CalibrationResult(
            gain=1.0 / 255.0, offset=0.0, r_squared=0.0,
            measured_dn=measured_dn, known_reflectance=known_reflectance,
        )

    # y = gain * x + offset
    A = np.vstack([x, np.ones_like(x)]).T
    (gain, offset), *_ = np.linalg.lstsq(A, y, rcond=None)

    y_pred = gain * x + offset
    ss_res = float(((y - y_pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0

    return CalibrationResult(
        gain=float(gain), offset=float(offset), r_squared=float(r2),
        measured_dn=measured_dn, known_reflectance=known_reflectance,
    )


def calibrate_from_patches(image_bgr: np.ndarray,
                           patch_centers: list[tuple[int, int]],
                           patch_half_px: int = 10) -> CalibrationBundle:
    """
    Provede kalibraci na zaklade 4 zadanych stredu patchu
    v poradi: white, light_gray, silver_gray, dark_gray.
    """
    if len(patch_centers) != 4:
        raise ValueError(
            "Pro kalibraci je potreba 4 patche (white, light_gray, silver_gray, dark_gray)."
        )

    nir_dn: list[float] = []
    red_dn: list[float] = []
    for (cx, cy) in patch_centers:
        b, g, r = sample_patch(image_bgr, cx, cy, half=patch_half_px)
        # MAPIR Survey 3N: R = NIR, B = Red
        nir_dn.append(r)
        red_dn.append(b)

    nir_ref = [MAPIR_TARGET_REFLECTANCE[p][1] for p in PATCH_ORDER]
    red_ref = [MAPIR_TARGET_REFLECTANCE[p][0] for p in PATCH_ORDER]

    nir_cal = calibrate_channel(nir_dn, nir_ref)
    red_cal = calibrate_channel(red_dn, red_ref)

    warnings: list[str] = []
    if nir_cal.r_squared < 0.95:
        warnings.append(
            f"Nizka kvalita kalibrace NIR (R² = {nir_cal.r_squared:.3f}). "
            "Zkontroluj osvetleni tercku - mozna dappled light?"
        )
    if red_cal.r_squared < 0.95:
        warnings.append(
            f"Nizka kvalita kalibrace Red (R² = {red_cal.r_squared:.3f})."
        )
    # Saturace bileho patche
    if nir_cal.measured_dn[0] > 250:
        warnings.append(
            "Bily patch je saturovany (DN > 250). Snizit expozici / posunout do stinu."
        )

    return CalibrationBundle(
        nir=nir_cal, red=red_cal,
        patch_centers_px=patch_centers,
        patch_size_px=patch_half_px * 2 + 1,
        target_detected=True,
        detection_method="manual",
        warnings=warnings,
    )


def default_fallback_calibration() -> CalibrationBundle:
    """
    Pokud terck neni v zaberu, pouzij hruby fallback:
    linearni mapping DN [0..255] -> reflektance [0..1].

    POZOR: vysledne NDVI bude pouze indikativni, ne kvantitativni!
    """
    nir = CalibrationResult(
        gain=1.0 / 255.0, offset=0.0, r_squared=0.0,
        measured_dn=[], known_reflectance=[],
    )
    red = CalibrationResult(
        gain=1.0 / 255.0, offset=0.0, r_squared=0.0,
        measured_dn=[], known_reflectance=[],
    )
    return CalibrationBundle(
        nir=nir, red=red,
        patch_centers_px=[], patch_size_px=0,
        target_detected=False, detection_method="fallback",
        warnings=[
            "Kalibracni tercik NENI na snimku - pouzit fallback DN/255.",
            "Vysledny NDVI je INDIKATIVNI, ne kvantitativni.",
            "Pro vedecky pouzitelna data prid tercik do zorneho pole.",
        ],
    )
