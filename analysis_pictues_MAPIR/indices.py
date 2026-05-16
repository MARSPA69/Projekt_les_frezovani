"""
Multispektralni vegetacni indexy pro MAPIR Survey 3N.

Survey 3N ma POUZE dve pasma: Red (661 nm) a NIR2 (850 nm), takze
implementujeme jen indexy, ktere vyzaduji vyhradne tyto dva kanaly.

Vybrana sestava 6 indexu pokryva ruzne aspekty stavu lesniho biotopu:

    NDVI    - standard, primarni metrika fotosynteticke aktivity
    WDRVI   - linearizovany NDVI pro husty zapojeny porost (LAI > 3)
    MSAVI2  - auto-adaptivni soil correction (mozaika, holiny)
    OSAVI   - optimalizovany pro ridkou vegetaci (mlaziny, paseky)
    FCI2    - Forest Cover Index, klasifikace lesni vs. otevrena vegetace
    RDVI    - geometricky robustni, srovnatelny pres ruzne uhly slunce

Pro kazdy index drzime:
    - formulaci (textovou i jako Python funkci nad reflektancemi)
    - hranice "zdrave" hodnoty pro lesni biotopy
    - biologicky vyznam (chlorofyl, LAI, voda)
    - fyziologicky kontext (kdy/proc se index meni)
    - upozorneni na limity (saturace, expozice, pudni signal)

Reference: viz "Multispectral Index Formulas.docx" (MAPIR documentation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


# =========================================================================
# Formularecepty indexu (vstup: NIR i Red reflektance v rozsahu [0..~1])
# =========================================================================

def _safe_div(num: np.ndarray, denom: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        out = num / denom
    return np.where(np.abs(denom) < 1e-6, np.nan, out)


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - Red) / (NIR + Red), rozsah [-1, +1]."""
    v = _safe_div(nir - red, nir + red)
    return np.clip(v, -1.0, 1.0).astype(np.float32)


def wdrvi(nir: np.ndarray, red: np.ndarray, alpha: float = 0.2) -> np.ndarray:
    """
    Wide Dynamic Range VI: (alpha*NIR - Red) / (alpha*NIR + Red).
    Doporuceno alpha = 0.1-0.2 (Henebry et al. 2004).
    """
    v = _safe_div(alpha * nir - red, alpha * nir + red)
    return np.clip(v, -1.0, 1.0).astype(np.float32)


def msavi2(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """
    Modified Soil Adjusted VI v2:
        (2*NIR + 1 - sqrt((2*NIR + 1)^2 - 8*(NIR - Red))) / 2.
    Auto-adaptivni soil correction (bez parametru L).
    """
    inner = (2.0 * nir + 1.0) ** 2 - 8.0 * (nir - red)
    inner = np.maximum(inner, 0.0)
    v = (2.0 * nir + 1.0 - np.sqrt(inner)) / 2.0
    return np.clip(v, -1.0, 1.0).astype(np.float32)


def osavi(nir: np.ndarray, red: np.ndarray, L: float = 0.16) -> np.ndarray:
    """
    Optimized Soil Adjusted VI: (NIR - Red) / (NIR + Red + 0.16).
    Lepsi nez NDVI pro vegetaci s cover < 50% (Rondeaux 1996).
    """
    v = _safe_div(nir - red, nir + red + L)
    return np.clip(v, -1.0, 1.0).astype(np.float32)


def fci2(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """
    Forest Cover Index 2: Red * NIR (Becker et al. 2018).
    Lesy maji NIZSI FCI2 nez otevrena vegetace (stinovani v korune).
    """
    v = nir * red
    return np.clip(v, 0.0, 1.5).astype(np.float32)


def rdvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """
    Renormalized Difference VI: (NIR - Red) / sqrt(NIR + Red).
    Robustni vuci pudnimu pozadi a slunecni geometrii (Roujean 1995).
    """
    denom = np.sqrt(np.maximum(nir + red, 0.0))
    v = _safe_div(nir - red, denom)
    return np.clip(v, -1.5, 1.5).astype(np.float32)


# =========================================================================
# Metadata jednotlivych indexu (popis, vyznam, prahove hodnoty)
# =========================================================================

@dataclass(frozen=True)
class IndexInfo:
    code: str
    name_cs: str
    name_en: str
    formula: str
    fn: Callable[[np.ndarray, np.ndarray], np.ndarray]
    typical_range: tuple[float, float]     # rozumny rozsah pro vizualizaci
    healthy_min: float                     # prah "zdrave vegetace"
    saturation_warning: float              # nad touto hodnotou index saturuje
    biology: str                           # co fyzicky meri
    physiology: str                        # kdy a proc se meni
    forest_context: str                    # specificky pro lesni biotopy
    caveats: str                           # limity a varovani
    higher_means: str                      # "vyssi hodnota = vyssi cara biomasy"


INDICES: dict[str, IndexInfo] = {
    "NDVI": IndexInfo(
        code="NDVI",
        name_cs="Normalizovany rozdilovy vegetacni index",
        name_en="Normalized Difference Vegetation Index",
        formula="(NIR - Red) / (NIR + Red)",
        fn=ndvi,
        typical_range=(-0.2, 0.9),
        healthy_min=0.55,
        saturation_warning=0.85,
        biology=(
            "Mira zelene biomasy = chlorofyll x listova plocha (LAI). "
            "Chlorofyl silne absorbuje cervene svetlo (660 nm) pro fotosyntezu, "
            "zatimco mezofyl listu silne odrazi blizke infracervene (850 nm) - "
            "rozdil techto reflektanci je primy proxy pro mnozstvi aktivni "
            "fotosynteticke tkane v zaberu."
        ),
        physiology=(
            "NDVI klesa pri jakemkoliv stresu, ktery snizuje obsah chlorofylu "
            "nebo plochu fotosynteticky aktivni tkane: vodni stres (zaviranim "
            "prudchu klesa fotosynteza), napadeni kurovcem (rozpad jehlic), "
            "defoliace housenkami, mraz, choroby (sypavka, padli). "
            "Nejcitlivejsi je ve fazich olisteni (brezen-kveten) a senescence "
            "(zari-rijen) - tam kde se LAI meni nejrychleji."
        ),
        forest_context=(
            "Pro jehlicnaty les v plne vegetaci ocekavame NDVI 0.65-0.80; "
            "pro listnaty 0.70-0.85. POZOR na saturaci: pri LAI > 3 (typicke "
            "v zapojenem dospelem porostu) NDVI dosahne plato a uz spatne "
            "rozlisuje rozdily v hustote koruny. Pro citlive sledovani "
            "dospelych porostu pouzij WDRVI nebo MSAVI2."
        ),
        caveats=(
            "Saturuje v hustem porostu (LAI > 3). Citlivy na puda v zaberu "
            "(podhodnocuje vegetaci pri vysoke expozici pudy). Citlivy na "
            "uhel slunce - rano/vecer jine hodnoty nez v poledne. "
            "Mokra vegetace ma docasne snizene NDVI."
        ),
        higher_means="vyssi koncentrace chlorofylu / vetsi LAI / aktivnejsi fotosyntéza",
    ),

    "WDRVI": IndexInfo(
        code="WDRVI",
        name_cs="Vegetacni index sirokeho dynamickeho rozsahu",
        name_en="Wide Dynamic Range Vegetation Index",
        formula="(0.2*NIR - Red) / (0.2*NIR + Red)",
        fn=wdrvi,
        typical_range=(-0.8, 0.3),
        healthy_min=-0.3,
        saturation_warning=0.2,
        biology=(
            "Linearizuje vztah mezi indexem a LAI v hustych porostech. "
            "Vahuje NIR koeficientem alpha (zde 0.2) - tim se prekonava "
            "saturace, kterou trpi klasicky NDVI pri LAI > 3."
        ),
        physiology=(
            "Citlivy na zmeny LAI v rozsahu, kde NDVI je necitlivy (LAI 3-6). "
            "Dokaze tedy detekovat ZMENY ve sklenutich korunkach drive a "
            "vyrazneji nez NDVI. Pro detekci rane faze kurovcoveho napadeni "
            "u smrku nebo praskove faze zaschnuti listu klicovy."
        ),
        forest_context=(
            "POZOR: WDRVI ma jiny ciselny rozsah nez NDVI - typicky -0.5 az +0.3 "
            "pro zdravou vegetaci. Nehodi se k absolutnimu posouzeni, ale k "
            "monitoringu TRENDU. Pokles WDRVI v case ukazuje rozpad korunkove "
            "vrstvy DRIVE nez NDVI."
        ),
        caveats=(
            "Hodnoty nejsou primo srovnatelne s NDVI. Hodnota -0.4 muze byt "
            "zcela zdrava vegetace - rozhoduje TREND a srovnani s baseline pro "
            "danou plochu."
        ),
        higher_means="vyssi LAI v rozsahu, kde NDVI saturuje (dospely zapojeny porost)",
    ),

    "MSAVI2": IndexInfo(
        code="MSAVI2",
        name_cs="Modifikovany puda-adjustovany vegetacni index v2",
        name_en="Modified Soil Adjusted Vegetation Index 2",
        formula="(2*NIR+1 - sqrt((2*NIR+1)^2 - 8*(NIR-Red))) / 2",
        fn=msavi2,
        typical_range=(-0.2, 0.9),
        healthy_min=0.45,
        saturation_warning=0.80,
        biology=(
            "Stejny biologicky vyznam jako NDVI (chlorofyl x LAI), ale s "
            "matematickou korekci na signal z odhalene pudy. Korekcni faktor "
            "se vypocita ze samotneho snimku, nepotrebuje znat hustotu vegetace "
            "predem (na rozdil od SAVI)."
        ),
        physiology=(
            "V heterogennich porostech s viditelnou pudou (paseky, holosec, "
            "mlaziny, mezery v korunkove vrstve) odstranuje matouci signal z "
            "podloznich vrstev. Citlivejsi nez NDVI na aktualni stav vegetace "
            "nez na podlozi."
        ),
        forest_context=(
            "Idealni pro pokusne plochy projektu Alcedo Frezovani - vetsina "
            "ploch ma mozaikovou strukturu (sazenice + holiny po-tezbe + "
            "nalety). MSAVI2 izoluje signal sazenic od podloznich zbytku "
            "tlejiciho dreva, suti, suti svahu."
        ),
        caveats=(
            "V plne zapojenem porostu prakticky shodny s NDVI - dodatecna "
            "informace minimalni. Vypocet je narocnejsi (odmocnina), ale to "
            "v praxi nevadi."
        ),
        higher_means="vyssi fotosynteticka aktivita s vylouenim signalu pudy",
    ),

    "OSAVI": IndexInfo(
        code="OSAVI",
        name_cs="Optimalizovany puda-adjustovany vegetacni index",
        name_en="Optimized Soil Adjusted Vegetation Index",
        formula="(NIR - Red) / (NIR + Red + 0.16)",
        fn=osavi,
        typical_range=(-0.2, 0.9),
        healthy_min=0.40,
        saturation_warning=0.78,
        biology=(
            "Modifikace NDVI s pevnym soil adjustment faktorem L = 0.16, "
            "ktery Rondeaux (1996) urcil jako optimum pro vegetace pokryvajici "
            "< 50 % povrchu - typicke pro mladsi vyssadby a paseky."
        ),
        physiology=(
            "Vyssi citlivost nez NDVI v sub-50% pokryvech - kazdy procentni "
            "narust pokryvu vegetace se projevi vyraznejsi zmenou OSAVI. "
            "Pro mlade sazenice (1-3 roky po vysadbe) je to nejcitlivejsi "
            "ukazatel ujeti a rustu."
        ),
        forest_context=(
            "KLICOVY index pro monitoring obnovy lesa po tezbe. Sleduje "
            "kvantifikaci zarustani holosec, ujeti sazenic, vyvoj mlazin. "
            "V plne zapojenem porostu prakticky shodny s NDVI."
        ),
        caveats=(
            "Vyssi citlivost na pudu znamena i vyssi citlivost na suchou "
            "vyprahlost pudy - po dlouhem suchu muze klesat i bez stresu "
            "vegetace samotne."
        ),
        higher_means="vyssi vegetacni pokryv v ridke nebo obnovujici se vegetaci",
    ),

    "FCI2": IndexInfo(
        code="FCI2",
        name_cs="Index lesni pokryvy 2",
        name_en="Forest Cover Index 2",
        formula="Red * NIR",
        fn=fci2,
        typical_range=(0.0, 0.7),
        healthy_min=0.05,
        saturation_warning=0.50,
        biology=(
            "Soucin red a NIR reflektance - intuiticne by mela byt vyssi pro "
            "vegetaci. Becker et al. (2018) vsak ukazuji, ze pro STRUKTURNE "
            "CLENITOU vegetaci (les s pomesnou patrovitosti, stiny v korunkach) "
            "je FCI2 NIZSI nez pro jednolite povrchy (travnik, kukurice, "
            "raselina) - diky vyssi celkove absorpci a stinovani."
        ),
        physiology=(
            "Pomalu reaguje na akutni stres - meri spis strukturni "
            "vlastnosti porostu nez okamzity fyziologicky stav. Klesa s "
            "rustem hustoty a vysky porostu (zvysuje se stinovani)."
        ),
        forest_context=(
            "Ukazatel TYPU pokryvu v zaberu. NIZKE FCI2 (< 0.15) = "
            "zapojeny les. STREDNI (0.15-0.30) = mlaziny / smiseny pokryv "
            "/ vyssi travy. VYSOKE (> 0.30) = otevrena agrarni vegetace nebo "
            "holina. Sledovanim trendu FCI2 lze detekovat zarustani paseky "
            "(klesa) nebo proredeni porostu (roste)."
        ),
        caveats=(
            "OPACNA logika nez NDVI - vyssi cislo neznamena lepsi zdravi! "
            "Index je vhodny ke klasifikaci typu pokryvu, NE k posouzeni "
            "fyziologickeho stavu vegetace."
        ),
        higher_means="vetsi podil otevrene vegetace nebo holiny (a tedy MENE zapojeny les)",
    ),

    "RDVI": IndexInfo(
        code="RDVI",
        name_cs="Renormalizovany rozdilovy vegetacni index",
        name_en="Renormalized Difference Vegetation Index",
        formula="(NIR - Red) / sqrt(NIR + Red)",
        fn=rdvi,
        typical_range=(-0.2, 0.7),
        healthy_min=0.30,
        saturation_warning=0.60,
        biology=(
            "Geometricky 'kompromis' mezi NDVI a DVI - prinasi do indexu "
            "fyzicky rozmer (neni bezrozmerny). Roujean & Breon (1995) ho "
            "navrhli pro vegetaci s ruznym pomerem listu a stinu, kde NDVI "
            "selhava kvuli vlivu uhlu pozorovani."
        ),
        physiology=(
            "Nejstabilnejsi z indexu pri promenlivem uhlu slunce, vetru "
            "(naklon listu) a stinovani. Pro stacionarni kameru pozorujici "
            "stejnou plochu z ruzneho denniho casu da RDVI nejkonzistentnejsi "
            "data v case."
        ),
        forest_context=(
            "Pro instalaci Alcedo (stacionarni kamera na strome, multiple "
            "snimky v ruzny cas dne) je RDVI nejvhodnejsi pro tvorbu "
            "casove rady - nemate-li striktni kontrolu na hodinu poizeni. "
            "Pro porovnani plocha-vs-plocha v jeden okamzik pouzij NDVI."
        ),
        caveats=(
            "Nizsi citlivost nez NDVI pri detekci akutnich zmen biomasy. "
            "Pro detekci rychlych jevu (uvolneni listoveho aparatu mrazem) "
            "pouzij NDVI nebo WDRVI."
        ),
        higher_means="stabilnejsi mira biomasy nezavisla na uhlu slunce",
    ),
}


# =========================================================================
# Statistiky a multi-index vypocet
# =========================================================================

@dataclass
class IndexStats:
    code: str
    mean: float
    median: float
    std: float
    p10: float
    p90: float
    fraction_healthy: float       # podil pixelu nad healthy_min
    pixel_count: int


def compute_index_stats(arr: np.ndarray, valid_mask: np.ndarray,
                        info: IndexInfo) -> IndexStats:
    """Spocita statistiky pro jeden index."""
    flat = arr[valid_mask]
    flat = flat[np.isfinite(flat)]
    n = int(flat.size)
    if n == 0:
        return IndexStats(
            code=info.code, mean=0.0, median=0.0, std=0.0,
            p10=0.0, p90=0.0, fraction_healthy=0.0, pixel_count=0,
        )
    return IndexStats(
        code=info.code,
        mean=float(flat.mean()),
        median=float(np.median(flat)),
        std=float(flat.std()),
        p10=float(np.percentile(flat, 10)),
        p90=float(np.percentile(flat, 90)),
        fraction_healthy=float((flat > info.healthy_min).mean()),
        pixel_count=n,
    )


def compute_all_indices(nir_refl: np.ndarray, red_refl: np.ndarray,
                        valid_mask: np.ndarray) -> dict[str, np.ndarray]:
    """Vypocita vsechny indexy z `INDICES`. Mimo valid_mask = NaN."""
    out: dict[str, np.ndarray] = {}
    for code, info in INDICES.items():
        arr = info.fn(nir_refl, red_refl)
        arr = np.where(valid_mask, arr, np.nan)
        out[code] = arr
    return out
