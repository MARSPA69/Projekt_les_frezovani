# Vývojářské shrnutí — RGB časosběr (Brinno)

Doprovodný dokument k [README.md](README.md). README popisuje *jak aplikaci
používat*; tenhle dokument popisuje *jak je postavená, proč tak a kde je slabá*.

Stav: **funkční, ověřeno na kompletních datech projektu** (2234 snímků obou
lokalit, květen–srpen 2026). Bez automatických testů.

---

## 1. Jak se měnilo zadání proti původní představě

Původní zadání znělo „vezmi záznam, vyhoď noc, udělej časosběr ×1,2". Tři věci
se při průzkumu dat ukázaly jinak:

| Předpoklad | Skutečnost | Důsledek |
|---|---|---|
| ve složkách jsou snímky | jsou tam hotová **AVI** (MJPEG 1080p), 1 snímek = 1 zachyt | nečte se adresář obrázků, ale dekódují se videa |
| rychlost = násobič | zdroj má 30 fps, ale 1 snímek = 2 h reality → ×1,2 zkrátí léto z 37 s na 31 s | ovládá se **výstupní fps**, ne násobič |
| čas lze dopočítat z pořadí | interval na *freza* je 7230 s, ne 7200 s | čas se **čte z každého snímku zvlášť** |

Ten třetí bod je nejdůležitější a je důvodem, proč v projektu vůbec je OCR.
Při 7230 s se čas záběru za 443 snímků posune o **3,7 hodiny**. Řez podle
pořadí snímku by tedy během sezony postupně vyřezával úplně jiné části dne —
zpočátku noc, ke konci odpoledne.

---

## 2. Architektura

```
cli.py ─┐
        ├─► pipeline.process_plot ─► timelapse.scan_directory ─► brinno_ocr.read_stamp
app.py ─┘            │                timelapse.filter_daytime
                     │                timelapse.render_video      ─► ffmpeg
                     │                phenology.analyse_captures
                     └─────────────► report_rgb.build_report      ─► reportlab
```

`pipeline.py` existuje proto, aby CLI a Streamlit dělaly prokazatelně totéž.
Obě cesty volají jednu funkci; UI se liší jen sběrem parametrů a zobrazením.

Průběh se hlásí callbackem `progress(stage, done, total, detail)` — CLI ho
tiskne, Streamlit z něj plní progress bar. Žádná vrstva netiskne sama.

---

## 3. OCR časového razítka — proč vlastní řešení

Tesseract v systému není a pro tenhle případ by byl zbytečný: font je pevný,
pozice pevná, kontrast bílá-na-černé. Template matching je deterministický,
rychlejší a bez externí závislosti.

**Jak vznikly šablony.** Z reálných snímků obou lokalit se vyřízl pruh
`y = 1048..1080`, prahoval na 128, rozsegmentoval na svislé bloky a bloky se
shlukly podle pixelové podobnosti. Vyšlo přesně **11 shluků** = 10 číslic + `/`.
Ty jsem vizuálně odečetl a označil. Výsledek je zabalený jako zlib+base64
konstanta `_GLYPH_BLOB` přímo v `brinno_ocr.py`, takže modul nemá externí asset.

**Ověření.** Kompletní sada 2238 snímků (včetně jednosnímkových souborů):
**0 nečitelných razítek, čas monotónně rostoucí**, interval konzistentní
(7230 s na *freza*, 7200 s na *nefreza*).

**Kde se to zlomí.** Modul je pevně svázaný s Brinno TLC2000 v 1080p:

- `BAND_TOP = 1048` — jiné rozlišení = jiná pozice pruhu.
- `EXPECTED_GLYPH_RUNS = 25` a `MODEL_PREFIX_GLYPHS = 7` — počítá s prefixem
  `TLC2000`. Model s jiným počtem znaků v názvu (např. `TLC200`) rozbije
  segmentaci a **selžou všechny snímky naráz**, ne jen některé.
- Šablony jsou z jednoho firmwaru. Jiný font = nic nesedí.

Selhání je naštěstí hlasité a diagnostikovatelné: `StampResult.reason` nese
konkrétní důvod (`nalezeno N znaků místo 25`, `glyf na pozici N neodpovídá
žádné šabloně (odchylka X)`), takže se pozná, jestli jde o posun pruhu nebo
o jiný font.

---

## 4. Fenologie GCC/ExG

Volba GCC místo syrového zeleného kanálu je podstatná: venkovní kamera mění
expozici podle oblačnosti, takže absolutní jas vypovídá spíš o počasí než
o rostlinách. GCC = `G/(R+G+B)` je poměr, ve kterém se změna osvětlení vykrátí.
Je to standardní index sítě PhenoCam.

Denní hodnota = **90. percentil** z použitelných snímků dne. Potlačí snímky se
stínem, mlhou a nízkým sluncem. Snímky s průměrným jasem mimo 25–245 se
vyřazují úplně.

**Výsledek** (viz README): frézovaná +0,0112 GCC/měsíc, nefrézovaná −0,0219,
křivky se protínají kolem 20. června. Odpovídá to nezávisle senzorovému nálezu
o nejsilnějším červencovém vysychání na NF2022.

---

## 5. Slabá místa

Seřazeno podle toho, jak moc by mě trápila při dalším kole prací.

### 5.1 ROI se nedá nastavit jinak než v kódu

`phenology.analyse_captures()` parametry `roi_top`/`roi_bottom` přijímá, ale
`pipeline.process_plot()` je nepředává dál a UI ani CLI je nevystavují. Výřez
je tedy natvrdo 35–97 % výšky.

Pro současné dva záběry to sedí (obloha je nad 35 %), ale při přemístění kamery
nebo jiném sklonu by se do indexu dostala obloha. **Toto bych opravil první** —
je to pár řádků a jinak hrozí tiše zkreslený výsledek.

### 5.2 Srovnání dvou kamer je jen trendové, ale graf svádí k víc

Report obě křivky GCC vykresluje do jednoho grafu se společnou osou. Výhrada,
že absolutní úrovně dvou kamer nejsou srovnatelné, je v textu pod grafem —
ale grafu se čtenář dívá dřív než textu. Poctivější by bylo buď každou plochu
na vlastní ose, nebo vykreslovat odchylku od vlastního startu.

### 5.3 Trojí dekódování

Snímky se dekódují **třikrát**: jednou při `scan_directory` (kvůli OCR), podruhé
při renderu, potřetí při fenologii. Na lokalitu to je ~75 s navíc.

Řešení by bylo počítat GCC už při skenu, kdy je snímek stejně v paměti. Neudělal
jsem to, protože by to svázalo sken s fenologií a znemožnilo pustit jen video.
Za čistotu rozhraní se platí minutou strojového času — vědomé rozhodnutí, ale
při větších sadách by se to mělo přehodnotit.

### 5.4 Noční řez je pevný čas, ne poloha slunce

22:00–05:00 je od května do srpna dost odlišná část dne — v květnu je v 5:00
už dávno světlo, v srpnu ještě šero. Astronomický režim (východ/západ slunce
pro 49,36 N / 14,30 E) by byl věcně správnější a data pro něj jsou (souřadnice
jsou v `tl_sensors.SENSORS` sousední aplikace). Neimplementováno.

### 5.5 Datum přepisuje původní razítko

`_draw_date_badge` překreslí černý pruh včetně původního Brinno razítka. Kdyby
se OCR spletlo, ve videu už to nikdo nepozná. Bezpečnější by bylo kreslit
badge jinam a razítko nechat jako doklad.

### 5.6 Detail o nečitelných snímcích se zahazuje

`ScanResult.unreadable` nese trojici (soubor, index, důvod), ale
`PlotReport.unreadable` je **jen počet**. Kdyby OCR začalo selhávat, report
řekne „u 37 snímků se nepodařilo přečíst razítko" a neřekne u kterých ani proč.

### 5.7 Velikost videa

216–229 MB na plochu. Časosběrný les se komprimuje špatně — sousední snímky
dělí dvě hodiny, scéna se změní úplně a mezisnímková komprese nemá co ušetřit.
`--kvalita 28` soubor zhruba půlí. Není to chyba, ale je to nepohodlné.

### 5.8 Žádné testy

Nic z toho nemá test. Nejcennější by byl regresní test OCR na hrstce uložených
pruhů se známým výsledkem — právě tam je nejvíc netriviální logiky a zároveň
nejtišší způsob, jak by se to mohlo rozbít.

### 5.9 Drobnosti

- Soubory s jediným snímkem se přeskakují jako „restart kamery"; dvousnímkový
  soubor by prošel, i když je to nejspíš taky restart.
- `smooth()` je implementovaná dvakrát — tady v `phenology.py` a v sousední
  MAPIR aplikaci v `tl_nir_series.py`. Stejný kód na dvou místech.
- Výchozí cesty v `app.py` jsou natvrdo na konkrétní stroj.

---

## 6. Co by bylo dobré udělat příště

1. Vystavit ROI do UI/CLI (§5.1) — nejrychlejší poměr přínos/práce.
2. Regresní test OCR (§5.8).
3. Graf GCC jako odchylka od vlastního startu (§5.2).
4. Astronomický noční řez (§5.4).
5. Sjednotit `smooth()` do sdíleného modulu s MAPIR aplikací (§5.9).

---

## 7. Prostředí

- **ffmpeg** musí být v `PATH`; `.bat` to kontroluje a hlásí čitelně.
- **pip potřebuje `--trusted-host`** — PyPI je za SSL inspekcí, jinak instalace
  spadne na `CERTIFICATE_VERIFY_FAILED`. Zabudováno v `run_app.bat`.
- **Konzole jede v cp1252** → `cli.py` si přepíná stdout na UTF-8, `.bat` volá
  `chcp 65001`. Bez toho `print` s češtinou spadne.
