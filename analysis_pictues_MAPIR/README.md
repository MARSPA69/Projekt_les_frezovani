# MAPIR Survey 3N — analyza fotosynteticke aktivity

Streamlit aplikace pro vyhodnoceni **NDVI** ze snimku kamery MAPIR Survey 3N
umistene stacionarne na strome v lesnim biotopu. Soucast projektu **Alcedo
Frezovani** (CRA s.r.o., Rumburk).

## Co aplikace dela

1. Nacte NIR snimek (JPG/PNG/TIFF) z kamery Survey 3N.
2. Sebere metadata snimku: datum/cas, typ porostu (jehlicnan/listnac/mix),
   meteo, vysku a uhel kamery, vzdalenost horizontu, pritomnost a vzdalenost
   kalibracniho terciku.
3. Detekuje kalibracni QR tercik (pyzbar / OpenCV); pripadne dovoli rucni
   oznaceni 4 patchu (white → light gray → silver gray → dark gray).
4. Spocita kalibrachni gain/offset pro **NIR (R kanal)** i **Red (B kanal)**.
5. Vypocita **6 vegetacnich indexu** (NDVI, WDRVI, MSAVI2, OSAVI, FCI2, RDVI)
   s heatmapou, histogramem a statistikami per index.
6. Sezonni a fyziologicka interpretace per index dle typu porostu, mesice
   a meteo podminek + cross-validace mezi indexy.
7. Export: self-contained **HTML report** s biologickou interpretaci kazdeho
   indexu, **CSV** radek pro casovou radu (vsechny indexy), NDVI raster PNG.

## Vegetacni indexy

Survey 3N ma jen dve pasma (Red 661 nm + NIR 850 nm), takze pouzivame
indexy vyzadujici pouze tato dve pasma. Sestava 6 indexu pokryva ruzne
aspekty stavu lesniho biotopu:

| Index  | Vzorec                                   | Pro co je nejlepsi                          |
|--------|------------------------------------------|---------------------------------------------|
| NDVI   | (NIR-Red)/(NIR+Red)                      | Standardni mira fotosynteticke aktivity     |
| WDRVI  | (0.2·NIR-Red)/(0.2·NIR+Red)              | Husty zapojeny porost (kde NDVI saturuje)   |
| MSAVI2 | (2·NIR+1 - √((2·NIR+1)²-8(NIR-Red))) / 2 | Mozaikova krajina s expozici pudy           |
| OSAVI  | (NIR-Red)/(NIR+Red+0.16)                 | Mlade vyssadby, paseky, sukcese             |
| FCI2   | Red · NIR                                | Klasifikace typu pokryvu (les vs. otevreny) |
| RDVI   | (NIR-Red)/√(NIR+Red)                     | Casove rady pres ruzny denni cas            |

Detailni biologicka, fyziologicka a forestry-specificka interpretace kazdeho
indexu je v `indices.py` (modul `INDICES`).

## Rychly start (Windows)

Dvojklik na `run_app.bat` — pri prvnim spusteni:

- vytvori virtualni prostredi `.venv`
- doinstaluje zavislosti z `requirements.txt`
- spusti Streamlit na `http://localhost:8501`

## Rucni spusteni

```cmd
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Struktura projektu

```text
analysis_pictues_MAPIR/
├── app.py                          # Streamlit UI - hlavni vstupni bod
├── calibration.py                  # detekce tercku + linearni regrese
├── ndvi_processor.py               # vypocet NDVI + statistiky
├── interpretation.py               # biologicka interpretace
├── report_generator.py             # HTML / CSV export
├── requirements.txt
├── run_app.bat                     # Windows launcher
├── Calibration_targets1.png        # ukazka MAPIR kalibracniho tercku
└── MAPIR_NIR_Monitoring_Alcedo.docx # zdrojova metodika
```

## Mapovani kanalu MAPIR Survey 3N

Survey 3N je dual-band kamera s filtrem Red(660 nm) + NIR(850 nm). V raw JPG
jsou kanaly mapovany:

| RGB kanal | Fyzikalni pasmo  |
|-----------|------------------|
| R         | NIR 850 nm       |
| G         | smes / nepouzity |
| B         | Red 660 nm       |

NDVI se pocita:
`NDVI = (R_kalibr - B_kalibr) / (R_kalibr + B_kalibr)`

## Kalibracni hodnoty MAPIR Target T4 (4 patche)

V `calibration.py` jsou pripraveny **dva profily** — prepinatelne promennou
`TARGET_REFLECTANCE_PROFILE` (`"nominal"` nebo `"chart"`).

### Profil A — `NOMINAL_T4` (vychozi)

Bezne nominalni hodnoty pouzivane v MAPIR softwaru. Idealizovana linearni
skala — dobre pro rychlou pracovni kalibraci a kompatibilitu s ostatnimi
MAPIR nastroji.

| Patch        | Red (661 nm) | NIR (850 nm) |
|--------------|--------------|--------------|
| white        | 0.95         | 0.95         |
| light_gray   | 0.45         | 0.45         |
| silver_gray  | 0.15         | 0.15         |
| dark_gray    | 0.05         | 0.05         |

### Profil B — `CHART_T4`

Hodnoty odecitane ze spektralnich krivek (Diffuse Reflectance) v grafu
`MAPIR diffuse reflectance standard calibration Target Data T4.avif`
na pasmech, ktera Survey 3N skutecne vidi:
**Red filter @ 661 nm** a **NIR2 filter @ 850 nm**.
Fyzikalne presnejsi — krivky T4 NEJSOU linearni.

| Patch        | Red (661 nm) | NIR (850 nm) |
|--------------|--------------|--------------|
| white        | 0.82         | 0.84         |
| light_gray   | 0.67         | 0.72         |
| silver_gray  | 0.40         | 0.43         |
| dark_gray    | 0.22         | 0.25         |

Pokud mate dodany konkretni kalibracni list pro vas kus tercku (s vyrobnim
cislem), prepiste hodnoty primo v `calibration.py`.

> **Tip:** Profil `nominal` davame jako vychozi (kompatibilita s MAPIR
> softwarem), ale pro publikovatelna data preferuj `chart` profile —
> odpovida fyzikalne mereny spektrum T4.

## Podminky kvalitniho mereni (dle metodiky)

- **Osvetleni:** difuzni denni svetlo (zatazeno / oblacno) — ne prime slunce,
  ne plny stin.
- **Orientace tercku:** kolmo k ose pohledu kamery.
- **Velikost tercku v zaberu:** min. 50 × 50 px.
- **Kriticke:** zadne dappled light (skvrny slunce) na tercku.
- **Casove okno:** 1–2 h po vychodu az 1–2 h pred zapadem slunce.
- **Vzdalenost tercku:** 3–8 m od kamery, scena 25–30 m za nim.

## Verdikty aplikace

| Barva | Verdikt       | Vyznam                                           |
|-------|---------------|--------------------------------------------------|
| 🟢    | ZDRAVA        | Mean NDVI v ocekavanem rozsahu pro typ a sezonu  |
| 🟡    | STREDNI STRES | NDVI pod baseline, ale nad prahem vazneho stresu |
| 🔴    | VAZNY STRES   | NDVI vyrazne pod baseline — doporucena inspekce  |
| ⚪    | MIMO SEZONU   | Listnac mimo vegetacni okno (listopad–brezen)    |

## Nasledne kroky (mimo tuto aplikaci)

Tato aplikace zpracovava **jeden snimek**. Pro tvorbu **casove rady NDVI** a
**detekci anomalii** (sezonni baseline + 2σ alert) napojit vystupni CSV na
pipeline doporucenou v metodice: `pandas` + `scipy` baseline fit (polynomicky
nebo spline) nad mesicnimi NDVI prumery z archivu.
