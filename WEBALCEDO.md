# Projekt_les_frezovani – Webové stránky EU lesnického projektu

## Popis projektu
Webová prezentace výzkumného projektu **"Vliv frézování půdy po těžbě dřeva na růst sazenic"** (2026–2027).
Monitoring fyzikálně-mechanických a biologických vlastností lesní půdy, dekompozice dřevních zbytků a vitality výsadby na 9 lokalitách (27 ploch).

## Hosting
- **Primární**: Vercel Hobby (free tier) – statický deployment z git repozitáře
- **Záloha**: NAS Synology (`volume1/web/lesnicky_projekt`) – volitelné ruční nahrání

## Struktura projektu

```
Projekt_les_frezovani/
├── index.html                          # Hlavní stránka (self-contained, ~3700 řádků)
├── vercel.json                         # Konfigurace Vercel (caching, clean URLs)
├── .gitignore                          # Git ignorace (.vercel, node_modules, Thumbs.db)
├── WEBALCEDO.md                        # Tento soubor – dokumentace
└── assets/
    ├── images/                         # Multispektrální snímky z kamer
    │   ├── nir_comparison.jpg          # NIR porovnání – Plocha 1
    │   ├── nir_comparison_plot2.jpg    # NIR porovnání – Plocha 2
    │   ├── nir_comparison_plot3.jpg    # NIR porovnání – Plocha 3
    │   ├── ndvi_vegetation.jpg         # NDVI vegetační analýza
    │   ├── ndvi_plot2.jpg              # NDVI – Plocha 2
    │   ├── cir_false_color.jpg         # CIR nepravé barvy – Plocha 1
    │   ├── cir_plot2.jpg               # CIR nepravé barvy – Plocha 2
    │   └── camera_coverage_analysis.png # Analýza pokrytí kamerami
    └── docs/
        └── OBEC_PODOLI_I_POR_MAP_10.pdf # Mapový podklad obce Podolí
```

## Co bylo vytvořeno

### 1. index.html
Základ převzat z referenčního souboru `Frezovani_v3.html` (ALCEDO_frezovani složka).
Self-contained HTML s inline CSS a JS, bez build procesu.

**Sekce stránky (11 původních + 1 nová):**

| # | Sekce | ID | Popis |
|---|-------|----|-------|
| 01 | Cíle projektu | `#cile` | 6 výzkumných cílů (ujímání sazenic, fyzikální vlastnosti, biologie, požární riziko, časosběr, kauzální analýza) |
| 02 | Experimentální design | `#design` | Tabulka 9 lokalit (L1–L9), fréza/nefréza/nová, rozměry, replikace |
| 02b | Satelitní mapa | `#mapa` | Leaflet.js + ESRI Maxar, polygon pokusných ploch (49.36°N, 14.30°E), semi-3D pohled |
| 02c | Monitoring | `#monitoring` | Třívrstvá architektura (RGB Brinno TLC 2020, NIR MAPIR Survey3W OCN, půdní senzory), vegetační indexy (GCC, ExG, VARI, NDVI, SAVI, GDD), hloubkový profil půdy, Early Warning System |
| 03 | Parametry | `#parametry` | 3 záložky: Půda (14 parametrů), Dřevní zbytky (7), Sazenice (5) |
| 04 | Kauzality | `#kauzality` | Kauzální diagram (frézování → půdní procesy → růst/přežívání/požární riziko), korelační karty |
| 05 | Harmonogram | `#harmonogram` | Timeline leden 2026 – prosinec 2027 (9 milníků) |
| 06 | Protokoly | `#protokoly` | 12 měřicích protokolů (půda, penetrace, infiltrace, pF, BET, chemie, mikrobiologie, mykorhiza, dekompozice, požár, sazenice, kamery) |
| 07 | Rizika | `#rizika` | 6 rizik (vysoké: počasí, kamery; střední: heterogenita, kontaminace, škůdci; nízké: personál) |
| 08 | Technologie | `#technologie` | 3 kategorie: terénní přístroje, laboratorní vybavení, monitorovací senzory/kamery |
| 09 | Algoritmy | `#algoritmy` | 6 analytických metod (ANOVA, LMM, korelace, SEM/path, požární index, časové řady) |
| **10** | **Galerie** | `#galerie` | **NOVÁ SEKCE** – 8 multispektrálních snímků s lightbox zvětšením |

### 2. Galerie snímků (nová sekce)
- 8 karet s obrázky z `assets/images/`
- Lightbox pro zvětšení na celou obrazovku (klik na obrázek)
- Zavření: klik na overlay nebo klávesa ESC
- Barevné tagy: NIR (fialová), NDVI (zelená), CIR (modrá), Pokrytí (hnědá)
- Responsivní grid (2 sloupce desktop, 1 sloupec mobil)

### 3. vercel.json
- `cleanUrls: true` – bez .html v URL
- Cache hlavičky:
  - Obrázky: `max-age=31536000, immutable` (1 rok)
  - Dokumenty: `max-age=86400` (1 den)

### 4. Assets
Zkopírovány z `adminlte/dist/ALCEDO_frezovani/`:
- 7× JPG (NIR, NDVI, CIR snímky z experimentálních ploch)
- 1× PNG (analýza pokrytí kamerami)
- 1× PDF (mapový podklad)

## Externí závislosti (CDN)
- Google Fonts: Playfair Display, Source Sans 3, JetBrains Mono
- Leaflet.js 1.9.4 (mapa + CSS)
- ESRI World Imagery tile server (satelitní podklad)

## Design
- Lesní/přírodní barevné schéma (CSS custom properties)
- Klíčové barvy: `--forest-dark: #1a2f1a`, `--moss: #4a6741`, `--leaf-light: #8cb369`, `--cream: #f5f1e8`, `--amber: #d4a574`
- Fonty: Playfair Display (nadpisy), Source Sans 3 (text), JetBrains Mono (kód/data)
- Scroll animace (IntersectionObserver)
- Plně responsivní (mobile-first breakpoint 768px)

## Deployment na Vercel

```bash
# 1. Vytvořit GitHub repozitář
gh repo create Projekt_les_frezovani --public --source=. --push

# 2. Na vercel.com: Import Project → vybrat repozitář → Deploy
# Vercel automaticky detekuje statický web, žádná konfigurace build není potřeba

# 3. Alternativně přes Vercel CLI:
npm i -g vercel
cd C:\Users\mspan\Desktop\Projekt_les_frezovani
vercel
```

## Git
- Repozitář inicializován v `C:\Users\mspan\Desktop\Projekt_les_frezovani\`
- Branch: `master`
- Initial commit: `de0b52f` (12 souborů, 3688 insertions)
