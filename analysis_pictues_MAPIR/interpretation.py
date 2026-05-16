"""
Biologicka interpretace NDVI a doplnkovych vegetacnich indexu.

Hlavni funkce:
    interpret()             - celkovy verdikt + souhrn (primarni NDVI)
    interpret_index()       - per-index kontextova interpretace
    interpret_all_indices() - dict per-index interpretaci pro report

Veskera interpretace je citliva na:
    - typ porostu (jehlicnan / listnac / mix)
    - mesic snimku (fenofaze)
    - meteo podminky
    - kvalitu kalibrace
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from calibration import CalibrationBundle
from indices import INDICES, IndexInfo, IndexStats
from ndvi_processor import NDVIStats


# =========================================================================
# Sezonni profily lesnich biotopu (NDVI baseline + stress prahy)
# =========================================================================

VEG_PROFILES: dict[str, dict] = {
    "jehlicnany": {
        "name": "Jehlicnaty les",
        "ndvi_healthy_min": 0.55,
        "ndvi_healthy_max": 0.80,
        "monthly_baseline": {
            1: 0.55, 2: 0.55, 3: 0.58, 4: 0.62, 5: 0.70, 6: 0.75,
            7: 0.75, 8: 0.72, 9: 0.68, 10: 0.62, 11: 0.58, 12: 0.55,
        },
        "stress_threshold": 0.45,
        "notes": (
            "Jehlicnany udrzuji zelenou biomasu cely rok - NDVI < 0.45 "
            "v letni sezone indikuje vazny stres (kurovec, sucho, defoliace)."
        ),
        "physiology": (
            "Smrk a borovice maji vyssi obsah voskoviteho kutikularniho voska "
            "a niksi specifickou listovou plochu nez listnace, coz se projevuje "
            "nizsi maximalni NDVI (typicky 0.70-0.80 v lete) i pri zdravem stavu. "
            "Letni pokles pod 0.55 je kriticky - smrk obvykle reaguje pomaleji "
            "nez listnace, takze projevy stresu jsou poslem dlouhodobeho problemu."
        ),
    },
    "listnace": {
        "name": "Listnaty les",
        "ndvi_healthy_min": 0.60,
        "ndvi_healthy_max": 0.85,
        "monthly_baseline": {
            1: 0.20, 2: 0.20, 3: 0.25, 4: 0.45, 5: 0.70, 6: 0.80,
            7: 0.82, 8: 0.78, 9: 0.65, 10: 0.40, 11: 0.25, 12: 0.20,
        },
        "stress_threshold": 0.50,
        "notes": (
            "Listnace maji silne sezonni cyklus - mimo vegetacni sezonu "
            "(listopad-brezen) je nizke NDVI normalni jev."
        ),
        "physiology": (
            "Buk, dub, brizy a daln listnace projevuji silnou fenologickou "
            "amplitudu: zima NDVI < 0.25 (jen kura+vetve), oliсteni v dubnu "
            "/ kvetnu zvedne NDVI o 0.4-0.5 za 3-4 tydny. Vrchol fotosyntezy "
            "v cervenci (LAI 4-6, NDVI 0.78-0.85). Senescence v zari-rijnu - "
            "anthokyany pohlcuji vice cerveneho svetla, ale NIR klesa rychleji "
            "= NDVI klesa o 0.3-0.4 behem 4 tydnu."
        ),
    },
    "mix": {
        "name": "Smiseny porost",
        "ndvi_healthy_min": 0.55,
        "ndvi_healthy_max": 0.82,
        "monthly_baseline": {
            1: 0.40, 2: 0.40, 3: 0.45, 4: 0.55, 5: 0.70, 6: 0.78,
            7: 0.78, 8: 0.75, 9: 0.65, 10: 0.50, 11: 0.42, 12: 0.40,
        },
        "stress_threshold": 0.45,
        "notes": (
            "Smiseny porost ma stredni sezonni amplitudu - "
            "zima cca 0.40, vrchol leta 0.75-0.80."
        ),
        "physiology": (
            "Smes jehlicnanu a listnacu = tlumeny sezonni cyklus. Jehlicnata "
            "slozka drzi NDVI nad 0.40 i v zime, listnata slozka pridava "
            "+0.30-0.40 v lete. Heterogenni porost ma typicky vysoke smerodatne "
            "odchylky NDVI (sigma > 0.15) - to neni anomalie, ale charakteristika."
        ),
    },
}


METEO_QUALITY = {
    "jasno":     ("STREDNI", "Prime slunecni svetlo zvysuje riziko dappled light na tercku."),
    "polojasno": ("DOBRE",   "Prijatelne podminky, sleduj stiny na tercku."),
    "oblacno":   ("VYBORNE", "Difuzni svetlo - optimalni podminky pro kalibraci."),
    "zatazeno":  ("VYBORNE", "Difuzni svetlo - optimalni podminky pro kalibraci."),
    "mlha":      ("SPATNE",  "Mlha snizuje kontrast NIR, vyhodnoceni je nejisty."),
    "dest":      ("SPATNE",  "Mokra vegetace meni NIR reflektanci, kalibrace nepouzitelna."),
}


# =========================================================================
# Per-index interpretace (kontextualni)
# =========================================================================

@dataclass
class IndexInterpretation:
    """Kontextualni interpretace JEDNOHO indexu."""
    code: str
    value: float
    healthy_min: float
    verdict: str               # "ZDRAVA" / "STREDNI STRES" / "VAZNY STRES" / "MIMO ROZSAH"
    color: str                 # hex
    biological_meaning: str    # co tato hodnota biologicky znamena
    forest_specific: str       # kontext lesni biotop + porost
    flags: list[str] = field(default_factory=list)


def _classify_value(value: float, info: IndexInfo) -> tuple[str, str]:
    """Vrati (verdict, color) podle hodnoty indexu."""
    h_min = info.healthy_min
    # u FCI2 je vyssi = mene les (opacna logika), takze hranice nizsi
    if info.code == "FCI2":
        if value < 0.15:
            return "ZAPOJENY LES", "#2e7d32"
        if value < 0.30:
            return "MOZAIKA / MLAZINY", "#f9a825"
        return "OTEVRENA VEGETACE", "#c62828"
    # ostatni indexy - vyssi = lepsi
    if value >= h_min:
        return "ZDRAVA", "#2e7d32"
    if value >= h_min - 0.15:
        return "STREDNI STRES", "#f9a825"
    return "VAZNY STRES", "#c62828"


def _ndvi_biology(value: float, veg_profile: dict, month: int) -> str:
    baseline = veg_profile["monthly_baseline"][month]
    healthy_min = veg_profile["ndvi_healthy_min"]
    if value >= veg_profile["ndvi_healthy_max"]:
        return (
            f"NDVI {value:.2f} je nad ocekavanym maximem pro {veg_profile['name']} "
            f"({veg_profile['ndvi_healthy_max']:.2f}) - velmi husta a zdrava "
            "biomasa s vysokym obsahem chlorofylu a plnym LAI. Kontrola: "
            "neni saturovany cely zaber? V tom pripade sleduj WDRVI."
        )
    if value >= healthy_min:
        return (
            f"NDVI {value:.2f} odpovida zdravemu stavu fotosyntetickeho aparatu "
            f"{veg_profile['name'].lower()} ({healthy_min:.2f} az "
            f"{veg_profile['ndvi_healthy_max']:.2f}). Vysoka aktivni listova "
            "plocha s plnou koncentraci chlorofylu."
        )
    if value >= veg_profile["stress_threshold"]:
        delta = baseline - value
        return (
            f"NDVI {value:.2f} je pod prahem zdravi ({healthy_min:.2f}) o "
            f"{healthy_min - value:.2f} a pod sezonni baseline ({baseline:.2f}) "
            f"o {delta:.2f}. Indikuje STREDNI STRES: prvni znamky zmen "
            "fotosynteticke kapacity - mozne priciny: pocatecni vodni stres, "
            "rana faze napadeni kurovcem, dehiscence po napadu housenkami, "
            "ranouny mraz."
        )
    return (
        f"NDVI {value:.2f} pod kritickou hranici "
        f"({veg_profile['stress_threshold']:.2f}). VAZNY STRES nebo holy povrch: "
        "pokrocila kurovcova kalamita / hluboke sucho s odlistenim / mechanicke "
        "poskozeni / nevegetacni pokryv v ROI (cesta, holosec). Doporucena "
        "rucni inspekce ploochy."
    )


def _wdrvi_biology(value: float, veg_profile: dict, ndvi_value: float) -> str:
    if ndvi_value >= 0.75:
        return (
            f"WDRVI {value:.3f} v saturovanem NDVI rezimu - klicovy ukazatel "
            "ZMEN v zapojene korunkove vrstve. Pro absolutni posouzeni neni "
            "vhodny, ale pri opakovanem snimkani sleduj jeho trend. Pokles "
            "WDRVI v case ukaze ztenceni koruny DRIVE nez NDVI."
        )
    return (
        f"WDRVI {value:.3f}. Index je nejcitlivejsi v hustem porostu (LAI > 3); "
        f"pri stavu {veg_profile['name'].lower()} mimo plne zapojeni "
        "(LAI < 3) doplnuje NDVI jen okrajove. Sledujte spis vyvoj v case."
    )


def _msavi2_biology(value: float, veg_profile: dict, ndvi_value: float) -> str:
    diff = abs(value - ndvi_value)
    if diff < 0.05:
        return (
            f"MSAVI2 {value:.2f} prakticky shodny s NDVI ({ndvi_value:.2f}) - "
            "zaber je homogenni vegetace bez znacne expozice pudy. Soil-correction "
            "tedy nepridava informaci, ale potvrzuje NDVI."
        )
    if value < ndvi_value:
        return (
            f"MSAVI2 {value:.2f} nizsi nez NDVI ({ndvi_value:.2f}) o "
            f"{ndvi_value - value:.2f} - puvodni NDVI byl NADHODNOCEN "
            "podlozim. Skutecny stav vegetace odpovida MSAVI2."
        )
    return (
        f"MSAVI2 {value:.2f}, NDVI {ndvi_value:.2f}. Po korekci pudniho signalu "
        "vegetace vychazi mirne lepsi - typicke pri tmavem podlozi nebo stinech."
    )


def _osavi_biology(value: float, veg_profile: dict, ndvi_value: float) -> str:
    if ndvi_value > 0.7:
        return (
            f"OSAVI {value:.2f} v plne zapojenem porostu - prakticky shodne "
            "s NDVI. Hlavni hodnota OSAVI je pro RIDKE pokryvy (mladsi sazenice, "
            "obnova po tezbe) - tady prinasi informaci jen v okrajovych zonach."
        )
    if value < 0.4 and ndvi_value < 0.4:
        return (
            f"OSAVI {value:.2f} v ridke vegetaci - nizke pokryti vegetaci, "
            "vetsina povrchu je puda nebo holiny. Pro projekt Alcedo to muze "
            "byt: paseka, holosec, plocha pred vysadbou, podzimni stav po opadu."
        )
    return (
        f"OSAVI {value:.2f} - vyssi citlivost nez NDVI pri pokrytich pod 50 %. "
        "Vhodne ke kvantifikaci ujeti sazenic v prvnich letech po vysadbe."
    )


def _fci2_biology(value: float) -> str:
    if value < 0.15:
        return (
            f"FCI2 {value:.3f} - nizka hodnota indikuje ZAPOJENY LES "
            "(strukturne clenitou vegetaci se znacnym stinovanim v korunkach). "
            "Typicke pro dospely sklenuty porost."
        )
    if value < 0.30:
        return (
            f"FCI2 {value:.3f} - stredni hodnota indikuje MOZAIKOVY POKRYV: "
            "smes mladi vegetace, mlazin, paseky se zarustanim, "
            "popripade rozvolneny porost s otevrenymi cestami v korune."
        )
    return (
        f"FCI2 {value:.3f} - vysoka hodnota indikuje OTEVRENOU VEGETACI: "
        "trava, mlaziny pred zapojenim, agrarni vegetace. V projektu Alcedo "
        "muze odpovidat predvysadbove plose nebo cerstve holosec."
    )


def _rdvi_biology(value: float, veg_profile: dict) -> str:
    return (
        f"RDVI {value:.2f} - geometricky robustni ukazatel, idealni pro "
        "pripoji do casove rady (stacionarni kamera + ruzne casy dne). "
        "Pri opakovanem snimkani te same plochy bude RDVI nejstabilnejsi z "
        "indexu - vyrovnava vliv menici se slunecni geometrie."
    )


INDEX_BIOLOGY_FN = {
    "NDVI":   lambda v, p, m, n: _ndvi_biology(v, p, m),
    "WDRVI":  lambda v, p, m, n: _wdrvi_biology(v, p, n),
    "MSAVI2": lambda v, p, m, n: _msavi2_biology(v, p, n),
    "OSAVI":  lambda v, p, m, n: _osavi_biology(v, p, n),
    "FCI2":   lambda v, p, m, n: _fci2_biology(v),
    "RDVI":   lambda v, p, m, n: _rdvi_biology(v, p),
}


def interpret_index(code: str, stats: IndexStats,
                    vegetation_type: str, capture_date: date,
                    ndvi_value: float) -> IndexInterpretation:
    """Vrati kontextualni interpretaci jednoho indexu."""
    info = INDICES[code]
    veg_profile = VEG_PROFILES.get(vegetation_type, VEG_PROFILES["mix"])
    month = capture_date.month
    value = stats.mean

    verdict, color = _classify_value(value, info)

    bio_fn = INDEX_BIOLOGY_FN.get(code)
    bio = bio_fn(value, veg_profile, month, ndvi_value) if bio_fn else ""

    flags: list[str] = []
    if value > info.saturation_warning and code != "FCI2":
        flags.append(f"{code}_SATURATED")
    if stats.std > 0.25 and code in ("NDVI", "MSAVI2", "OSAVI"):
        flags.append(f"{code}_HETEROGENEOUS")

    # Forest-specific kontext - cely vysledek do jedne uceleny vety
    forest_specific = (
        f"{info.forest_context}  |  Pro {veg_profile['name'].lower()} v "
        f"mesici {month}: ocekavana hodnota se pohybuje kolem sezonni baseline "
        f"({veg_profile['monthly_baseline'][month]:.2f} NDVI)."
    )

    return IndexInterpretation(
        code=code, value=value,
        healthy_min=info.healthy_min,
        verdict=verdict, color=color,
        biological_meaning=bio,
        forest_specific=forest_specific,
        flags=flags,
    )


def interpret_all_indices(index_stats: dict[str, IndexStats],
                          vegetation_type: str, capture_date: date,
                          ) -> dict[str, IndexInterpretation]:
    """Interpretace vsech 6 indexu - vstup pro report."""
    ndvi_val = index_stats["NDVI"].mean if "NDVI" in index_stats else 0.0
    return {
        code: interpret_index(code, stats, vegetation_type, capture_date, ndvi_val)
        for code, stats in index_stats.items()
    }


# =========================================================================
# Celkova interpretace (primarni NDVI + sekundarni cross-validation)
# =========================================================================

@dataclass
class Interpretation:
    overall_verdict: str
    color_code: str
    summary: str
    expected_ndvi_range: tuple[float, float]
    observed_vs_expected: str
    quality_assessment: str
    cross_validation: str                # co rikaji ostatni indexy
    recommendations: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def _cross_validation_text(idx_stats: dict[str, IndexStats],
                           ndvi_value: float) -> str:
    """Sjednoceny komentar k souladu indexu."""
    lines: list[str] = []
    # WDRVI - dynamic range check
    if "WDRVI" in idx_stats and ndvi_value > 0.75:
        wdrvi_v = idx_stats["WDRVI"].mean
        lines.append(
            f"NDVI saturuje ({ndvi_value:.2f}), WDRVI = {wdrvi_v:.3f} je vodicim "
            "ukazatelem pro trend v case."
        )
    # MSAVI2 vs NDVI - puda v zaberu?
    if "MSAVI2" in idx_stats and "NDVI" in idx_stats:
        diff = idx_stats["NDVI"].mean - idx_stats["MSAVI2"].mean
        if diff > 0.08:
            lines.append(
                f"NDVI je o {diff:.2f} vyssi nez MSAVI2 - v ROI je vyssi expozice "
                "pudy, prava hodnota vegetace odpovida MSAVI2."
            )
        elif diff < -0.05:
            lines.append(
                f"MSAVI2 vyssi nez NDVI o {-diff:.2f} - tmave podlozi nebo stiny "
                "stahuji NDVI dolu, fyzicky stav vegetace lepsi nez NDVI naznacuje."
            )
    # FCI2 typ pokryvu
    if "FCI2" in idx_stats:
        fci = idx_stats["FCI2"].mean
        if fci < 0.15:
            lines.append(f"FCI2 = {fci:.3f}: scena je zapojeny les.")
        elif fci < 0.30:
            lines.append(f"FCI2 = {fci:.3f}: mozaikova krajina (les + holiny).")
        else:
            lines.append(f"FCI2 = {fci:.3f}: dominantne otevrena vegetace nebo holina.")
    # OSAVI vs NDVI - rude vegetace
    if "OSAVI" in idx_stats and ndvi_value < 0.5:
        osavi_v = idx_stats["OSAVI"].mean
        if osavi_v > ndvi_value + 0.05:
            lines.append(
                f"OSAVI = {osavi_v:.2f} (vyssi nez NDVI) potvrzuje ridke pokryti "
                "vegetaci - typicke pro pasecnou/mlazinovou fazi."
            )
    if not lines:
        return "Cross-validace: vsechny indexy konzistentni s NDVI."
    return " ".join(lines)


def interpret(stats: NDVIStats,
              vegetation_type: str,
              capture_date: date,
              meteo: str,
              calibration: CalibrationBundle,
              has_target: bool,
              index_stats: dict[str, IndexStats] | None = None,
              ) -> Interpretation:
    """Sjednoceni NDVI + multi-index interpretace do citelneho verdiktu."""

    profile = VEG_PROFILES.get(vegetation_type, VEG_PROFILES["mix"])
    month = capture_date.month
    expected_baseline = profile["monthly_baseline"][month]
    healthy_min = profile["ndvi_healthy_min"]
    stress_thr = profile["stress_threshold"]

    expected_low = max(-0.1, expected_baseline - 0.12)
    expected_high = min(1.0, expected_baseline + 0.12)

    observed = stats.mean
    delta = observed - expected_baseline

    # Verdikt
    if vegetation_type == "listnace" and month in (11, 12, 1, 2, 3):
        if observed < 0.30:
            verdict = "MIMO SEZONU"
            color = "#9aa0a6"
        else:
            verdict = "ZDRAVA (predcasna fenofaze)"
            color = "#2e7d32"
    elif observed >= healthy_min:
        verdict = "ZDRAVA"
        color = "#2e7d32"
    elif observed >= stress_thr:
        verdict = "STREDNI STRES"
        color = "#f9a825"
    else:
        verdict = "VAZNY STRES"
        color = "#c62828"

    # Sezonni kontext
    if abs(delta) < 0.07:
        obs_vs_exp = (
            f"V mezich ocekavani pro {profile['name'].lower()} v mesici {month} "
            f"(ocekavani ~{expected_baseline:.2f}, namereno {observed:.2f})."
        )
    elif delta < 0:
        obs_vs_exp = (
            f"NDVI o {abs(delta):.2f} NIZSI nez sezonni baseline "
            f"({expected_baseline:.2f}) - indikator stresu."
        )
    else:
        obs_vs_exp = (
            f"NDVI o {delta:.2f} VYSSI nez sezonni baseline "
            f"({expected_baseline:.2f}) - vyborny stav nebo prepalena obloha v ROI."
        )

    # Kvalita
    meteo_grade, meteo_note = METEO_QUALITY.get(
        meteo.lower(), ("NEZNAME", "Meteo data neuvedena.")
    )
    quality_lines = [f"Meteo: {meteo_grade} - {meteo_note}"]
    if not has_target:
        quality_lines.append(
            "Kalibracni tercik NENI ve snimku - NDVI je INDIKATIVNI."
        )
    else:
        nir_r2 = calibration.nir.r_squared
        red_r2 = calibration.red.r_squared
        if nir_r2 > 0.95 and red_r2 > 0.95:
            quality_lines.append(
                f"Kalibrace OK (R² NIR={nir_r2:.3f}, R² Red={red_r2:.3f})."
            )
        else:
            quality_lines.append(
                f"Kalibrace s vyhradou (R² NIR={nir_r2:.3f}, R² Red={red_r2:.3f})."
            )
    quality = " | ".join(quality_lines)

    # Cross-validation s ostatnimi indexy
    cross = (
        _cross_validation_text(index_stats, observed) if index_stats
        else "Cross-validace nedostupna (multi-index nespocten)."
    )

    # Souhrn
    summary = (
        f"Vegetacni typ: {profile['name']}. "
        f"Mean NDVI = {observed:.3f} (median {stats.median:.3f}, σ={stats.std:.3f}). "
        f"Zdrave pixely (>0.5): {stats.fraction_healthy*100:.1f} %. "
        f"Stresovane (0.2-0.4): {stats.fraction_stressed*100:.1f} %. "
        f"Bez vegetace (<0.2): {stats.fraction_bare_or_dead*100:.1f} %.  "
        f"Fyziologie: {profile['physiology']}"
    )

    # Doporuceni
    recs: list[str] = []
    flags: list[str] = []

    if not has_target:
        recs.append(
            "Pri pristim snimku pridej kalibracni tercik (3-8 m od kamery, "
            "kolmo, difuzni svetlo)."
        )
        flags.append("NO_TARGET")

    if meteo.lower() in ("jasno", "mlha", "dest"):
        flags.append("BAD_METEO")
        recs.append(
            "Pro kvantitativni vyhodnoceni preferuj zatazeno/oblacno (difuzni svetlo)."
        )

    if verdict == "VAZNY STRES" and vegetation_type == "jehlicnany":
        recs.append(
            "Doporuceno: rucni inspekce ROI - kontrola kurovce, suska, defoliace."
        )
        flags.append("CONIFER_STRESS")

    if stats.fraction_bare_or_dead > 0.4 and verdict != "MIMO SEZONU":
        recs.append(
            f"{stats.fraction_bare_or_dead*100:.0f} % plochy bez vegetace - "
            "zkontroluj zda ROI nezahrnuje cestu, palouk nebo holosec."
        )

    if calibration.warnings:
        recs.extend(calibration.warnings)

    if stats.std > 0.25:
        flags.append("HIGH_VARIANCE")
        recs.append(
            f"Vysoka variabilita NDVI (σ={stats.std:.3f}) - heterogenni porost "
            "nebo smes vegetace + holiny v ROI."
        )

    # Saturace - doporucit WDRVI/MSAVI2
    if stats.p90 > 0.85 and index_stats is not None:
        recs.append(
            "NDVI saturuje (>0.85) - pro citlivy monitoring sleduj WDRVI a MSAVI2."
        )

    return Interpretation(
        overall_verdict=verdict,
        color_code=color,
        summary=summary,
        expected_ndvi_range=(expected_low, expected_high),
        observed_vs_expected=obs_vs_exp,
        quality_assessment=quality,
        cross_validation=cross,
        recommendations=recs,
        flags=flags,
    )
