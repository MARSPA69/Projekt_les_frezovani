# MAPIR Survey 3N — časosběr a report o biotopu

Druhá aplikace v této složce. Zatímco `app.py` analyzuje **jeden snímek**,
tato zpracuje **celou časosběrnou sadu**: vyrobí zrychlené `.mp4` a PDF report
o sledovaném biotopu, který spojuje obrazovou analýzu NIR s daty z půdních
čidel TOMST a meteorologickým rámcem.

Sdílí s původní aplikací moduly `mapir_raw.py`, `indices.py` i `.venv` —
proto leží tady a ne ve vlastní složce.

## Spuštění

```
run_timelapse.bat
```

Otevře aplikaci na `http://localhost:8503` (původní `run_app.bat` běží na
8501, takže mohou běžet obě zároveň). Vyžaduje **ffmpeg** v `PATH`.

Dávkově:

```
.venv\Scripts\python tl_cli.py ^
    --snimky  "...\lokalita freza\Photo" ^
    --senzory "...\senzory" ^
    --vystup  VYSTUP_TIMELAPSE
```

Přepínač `--nahled 100` zpracuje jen 100 snímků rovnoměrně po sadě — hodí se
na rychlou kontrolu nastavení, než se pustí plný běh (~10 minut).

## Zadává se cesta, ne upload

Sada má 811 dvojic RAW+JPG, dohromady **17 GB**. Nahrávat ji přes prohlížeč
nelze — Streamlit drží uploady v paměti. Aplikace proto čte složku přímo
z disku. To je jediná odchylka od původního zadání a jde o technickou nutnost.

## Které soubory k čemu

| | použití | proč |
|---|---|---|
| **JPG** | časosběrné video | hotový barevný náhled kamery |
| **RAW** | NDVI a vegetační indexy | jediný zdroj spektrální informace |

Z JPG **nelze počítat NDVI**. MAPIR do něj aplikuje vyvážení bílé, které pásma
Red a NIR slije dohromady (korelace R↔B ≈ 0,998), takže NDVI vychází kolem nuly
bez ohledu na skutečný stav porostu. Podrobně v hlavičce `mapir_raw.py`.

## Co se v datech projektu našlo

| | |
|---|---|
| zachytů | 809 (410 denních, 399 nočních) |
| období | 14. 7. – 21. 8. 2026 |
| interval | 1,1 h |
| dnů s NDVI | 39 |
| NDVI průměr | 0,771 (rozsah 0,622–0,902) |

Vyřazeno automaticky: **4 snímky** s resetovanými hodinami kamery (datum 2024)
a **1 poškozený JPG** o nulové velikosti (`2026_0731_011337_002.JPG`).

Noční snímky se z NDVI vyřazují — bez osvětleného pásma Red je index neplatný.
Ve videu naopak zůstávají, protože dokládají denní rytmus stanoviště.

## Vegetační indexy

Počítají se funkcemi z `indices.py` hlavní aplikace, aby se obě cesty nemohly
rozejít. Pásma se před výpočtem převádějí z DN na relativní odrazivost 0–1
(dělení plnou škálou 4095).

> **Proč to nelze vynechat:** NDVI je poměrový, takže na měřítku nezáleží.
> OSAVI a RDVI ale ano — OSAVI má v čitateli konstantu `L = 0,16`, která je
> proti DN v tisících zanedbatelná, takže OSAVI zkolabuje přesně na NDVI;
> RDVI dělí odmocninou součtu, takže jeho hodnota přímo roste s měřítkem
> (na surových DN vycházelo ~40 místo řádu desetin).

> **Výhrada:** sada nemá u každého zachytu kalibrační terčík, takže jde
> o **relativní** analýzu. Platný je vývoj v čase, ne absolutní úroveň
> odrazivosti; hodnoty se nesrovnávají s jinou kamerou ani jinou sezonou.

## Půdní čidla TOMST

Název souboru kóduje hloubku, zásah a rok: `T10` = 10 cm, `T48` = 48 cm,
`F`/`NF` = fréza/nefréza, `22`/`26` = rok. Kanály: **T1, T2** teplota půdního
profilu, **T3** přízemní stresový kanál (mrazíky a přehřívání u povrchu),
plus **raw vlhkost**.

Report používá `T10F22` + `T48F22` (kolokované s kamerou) jako hlavní a
`T10NF22` + `T48NF22` jako srovnávací. Modul `tl_sensors.py` nese i
interpretační korekce z projektové zprávy — sensor-specifické začátky
(např. `T48NF22` až od 15. 4.) a příznaky kontaktních zlomů.

> **Raw vlhkost není procento.** Je to surový TMS count. Bez lokální kalibrace
> nelze tvrdit „tato plocha má o X % více vody“ — srovnatelný je tvar křivky.

## Meteorologický rámec

Na plochách není srážkoměr, takže report používá **regionální měsíční rámec**
ČHMÚ pro Podolí I. / Milevsko (březen–srpen 2026) převzatý z tabulky 3 zprávy
„Analýza senzorických dat z 21082026 – projekt LES“. Je to rámec, ne denní
srážkový záznam u čidla.

## Zásadní výhrada k designu pokusu

Srovnání **F2022 vs. NF2022 není čistým efektem frézování**: F2022 leží
v geologické skupině Ca, NF2022 ve skupině Ka zhruba 2,5 km daleko s odlišným,
drenážnějším podložím. Nejčistším experimentálním párem je podle projektové
zprávy dvojice **F2026 vs. NF2026** — tu ale obrazová sada MAPIR nepokrývá,
protože druhá kamera nefungovala.

## Výstupy

```
VYSTUP_TIMELAPSE/
├── <plocha>_casosber.mp4       zrychlené video (1600×1200)
├── <plocha>_ndvi_denni.csv     denní řada indexů
└── MAPIR_biotop_report.pdf     report o biotopu
```

## Moduly

| soubor | co dělá |
|---|---|
| `tl_scan.py` | načtení sady, párování RAW+JPG, filtr resetovaných hodin |
| `tl_video.py` | render mp4 z JPG (včetně čtení cest s diakritikou) |
| `tl_nir_series.py` | časová řada NDVI/OSAVI/RDVI z RAW |
| `tl_sensors.py` | čidla TOMST, interpretační korekce, meteo rámec |
| `tl_report.py` | PDF report o biotopu |
| `tl_pipeline.py` | spojení kroků; sdílí ho CLI i Streamlit |
| `timelapse_app.py` | Streamlit aplikace |
| `tl_cli.py` | dávkové zpracování |
