# Vývojářské shrnutí — MAPIR časosběr a report o biotopu

Doprovodný dokument k [README_CASOSBER.md](README_CASOSBER.md). README popisuje
*jak aplikaci používat*; tenhle dokument popisuje *jak je postavená, proč tak
a kde je slabá*.

Týká se **jen modulů `tl_*.py` a `timelapse_app.py`**. Původní aplikace
(`app.py`, analýza jednoho snímku) zůstala nedotčená.

Stav: **funkční, ověřeno na kompletní sadě** (809 zachytů, 17 GB, červenec–srpen
2026). Bez automatických testů.

---

## 1. Proč to leží ve stejné složce jako původní aplikace

Zvažoval jsem samostatnou složku vedle `Analysis_pictures_RGB`. Rozhodl jsem se
pro společnou složku ze dvou důvodů:

1. **Sdílení `mapir_raw.py` a `indices.py`.** Časosběrná analýza počítá NDVI
   stejným kódem jako jednosnímková. Kdyby to byly dva projekty, výpočet indexů
   by se dřív nebo později rozešel a čísla ze dvou částí projektu by si
   přestala odpovídat.
2. **Sdílení `.venv`.** Závislosti jsou identické, druhé prostředí nemá smysl.

Cenou je, že složka teď obsahuje dvě aplikace. Rozlišuje je prefix `tl_`
a vlastní launcher `run_timelapse.bat` (port 8503 vs. 8501).

---

## 2. Architektura

```
tl_cli.py ─────┐
               ├─► tl_pipeline.process ─► tl_scan.scan_photo_set
timelapse_app ─┘          │               tl_video.render_video    ─► ffmpeg
                          │               tl_nir_series.analyse_series ─► mapir_raw + indices
                          │               tl_sensors.load_sensor
                          └────────────► tl_report.build_report    ─► reportlab
```

Stejný vzorec jako u RGB aplikace: `tl_pipeline.py` je jediné místo, které zná
celý postup, CLI i Streamlit ho jen volají.

---

## 3. Klíčová rozhodnutí

### 3.1 JPG na video, RAW na analýzu

Není to optimalizace, ale nutnost. MAPIR do JPG aplikuje vyvážení bílé, které
slije pásma Red a NIR (korelace ≈ 0,998) — NDVI z JPG vyjde kolem nuly bez
ohledu na skutečný stav porostu. To je zdokumentované už v hlavičce
`mapir_raw.py` a časosběrná část to jen respektuje.

### 3.2 Normalizace na odrazivost 0–1

**Tohle jsem napoprvé udělal špatně** a stojí za to, aby to bylo zapsané.
Původně jsem indexy počítal přímo ze surových DN (0–4095). Výsledek:

| index | ze surových DN | správně (0–1) |
|---|---|---|
| NDVI | 0,7815 | 0,7815 |
| OSAVI | 0,781**4** | 0,619 |
| RDVI | **40,2** | 0,628 |

NDVI je poměrový, takže měřítko vykrátí a vyšlo správně. OSAVI ale má
v jmenovateli konstantu `L = 0,16`, která je proti DN v tisících zanedbatelná —
index **zkolaboval přesně na NDVI** a tvářil se jako nezávislá informace.
RDVI dělí odmocninou součtu, takže roste s měřítkem.

Poučení: index, který se od NDVI liší jen o konstantu, je potřeba kontrolovat
proti NDVI. Rozdíl 0,0001 byl signál, ne shoda.

Vzorce se teď berou z `indices.py` hlavní aplikace, ne z vlastní implementace.

### 3.3 Podvzorkování 1:16

Statistiky se počítají z každého 4. pixelu v obou osách. NDVI je prostorový
průměr přes miliony pixelů, takže se to projeví až na třetím desetinném místě,
ale zrychlí to běh řádově. Plná sada: **~4 minuty** místo hodin.

### 3.4 Zadává se cesta, ne upload

811 dvojic = 17 GB. Streamlit drží uploady v paměti, takže upload je vyloučený.
Jediná odchylka od původního zadání.

---

## 4. Ověření správnosti

To, co považuju za nejsilnější doklad, že modul čidel čte data správně:
`tl_sensors.py` **nezávisle reprodukuje tabulky 5 a 7** projektové zprávy
z 21. 8. 2026, aniž by z ní přebíral čísla — jen mapování kanálů a interpretační
začátky.

| čidlo | vlhkost první → poslední | trend/den | dny T3>30 / >35 / >40 / <0 |
|---|---|---|---|
| T10F22 | 1226 → 1170 | −1,10 | 82 / 46 / 21 / 32 |
| T48F22 | 1434 → 1022 | −4,02 | 83 / 44 / 19 / 42 |
| T10NF22 | 1586 → 995 | −4,85 | 56 / 36 / 19 / 27 |
| T48NF22 | 2154 → 1449 | −3,20 | 86 / 54 / 25 / 17 |

Všechny hodnoty sedí na desetinu.

---

## 5. Slabá místa

### 5.1 NDVI se počítá z celého snímku, bez ROI

**Nejvážnější slabina.** RGB aplikace analyzuje jen výřez pod obzorem; tady se
NDVI počítá z **celého** snímku 4000×3000 — včetně oblohy, kmenů v pozadí
a okraje s vinětací. Obloha má NDVI blízko nuly nebo záporné, kmeny taky.
Absolutní úroveň je tím posunutá dolů a podíl oblohy ve scéně se navíc mění
s ročním obdobím, jak porost roste.

Pro *relativní* časovou řadu je to snesitelné, dokud se poměr obloha/porost
mění pomalu. Ale je to systematická chyba, kterou by stálo za to odstranit —
ideálně stejným mechanismem jako v RGB aplikaci.

### 5.2 Kalibrace se nepoužívá — a v této sadě ani použít nejde

Ve složce je hotový `calibration.py` s detekcí QR terčíku a výpočtem
gain/offset. Časosběrná větev ho **vůbec nevolá** — analýza je čistě relativní.

Terčík v sadě **je**, na snímcích ze dne instalace (15. 7. 2026, viz
`2026_0715_111014_002_MARK.JPG`). Prověřil jsem, jestli by se z něj dala odvodit
kalibrace. **Nedá.** Důvody v pořadí závažnosti:

1. **Pásmo Red je na terčíku na úrovni šumu.** Naměřeno v RAW: světlý pruh má
   `Red = 6,8 ± 1,5 DN` při black levelu `4,0 DN` — tedy zhruba **3 DN užitečného
   signálu** z rozsahu 4095. Pro srovnání, osluněná vegetace v témže snímku má
   `Red = 273 DN`. Kalibrovat červený kanál z 3 DN nelze.
2. **Světlo pod porostem je spektrálně zkreslené.** Terčík leží ve stínu pod
   vegetací, takže na něj dopadá světlo prošlé listovím — a to listí červenou
   pohlcuje a NIR propouští. Světlý pruh terčíku proto vychází na `NDVI ≈ 0,99`,
   ačkoli jde o šedou plochu, která má být spektrálně plochá. Terčík tedy není
   jen slabý, ale zkreslený **přesně tím směrem, který by NDVI rozbil nejvíc**.
3. **Je jen na 11 denních snímcích z 809.** I kdyby kalibrace vyšla, platila by
   pro 1,4 % řady. Kamera má automatickou expozici, takže koeficienty nelze
   přenést na zbytek sezony.
4. **Je moc malý a šikmo.** Celá sestava má ~100 × 80 px ve 12 MPx snímku,
   jednotlivé plošky kolem 500 px, na zemi pod ostrým úhlem.
5. Viditelná je jedna, nanejvýš dvě plošky — ne celý čtyřstupňový žebříček
   (bílá → světle šedá → stříbrně šedá → tmavě šedá), který `calibration.py`
   očekává.

**Co by z toho udělalo použitelnou kalibraci příště:** terčík držet zhruba metr
od objektivu tak, aby vyplnil podstatnou část snímku, **na stejném světle jako
porost** (tedy na slunci, ne ve stínu pod vegetací), kolmo ke slunci, a nasnímat
ho na začátku i na konci každé návštěvy lokality. Pak by šlo nejen převést NDVI
na skutečnou odrazivost, ale i sledovat drift kamery mezi návštěvami.

### 5.3 Den/noc je jeden pevný práh

`classify_daynight` porovnává průměr pásma Red s prahem 20 DN. U snímků za
soumraku, které leží těsně kolem prahu, je zařazení nahodilé — a přitom právě
ty mají nejšumovější NDVI. Report by mohl vykazovat vyšší rozptyl v okrajových
hodinách. Neměřil jsem, jak moc se to projevuje.

### 5.4 Krátká a čistě letní řada

Obrazová sada pokrývá **39 dní**, jen červenec–srpen. Korelace v kapitole 6
reportu (NDVI × vlhkost = +0,30, NDVI × max T3 = −0,41) jsou proto slabý důkaz:
v letním úseku sdílejí NDVI, teplota i vlhkost společný sezónní trend, takže
korelace měří hlavně ten. Report to říká, ale je to zásadní omezení, ne
formalita.

### 5.5 Obrazová data jsou jen z jedné plochy

Druhá kamera nefungovala. Srovnávací plocha vstupuje do reportu **jen přes
čidla**. Jakýkoli závěr o rozdílu *porostů* mezi plochami by potřeboval obraz
z obou. Navíc F2022 vs. NF2022 není čisté srovnání (Ca vs. Ka, 2,5 km).

### 5.6 Mrtvý kód a duplicita

- `tl_sensors.align_to_dates()` je **definovaná, ale nikde nevolaná**. Psal jsem
  ji pro spojení senzorové a obrazové řady, nakonec to report řeší přes
  `DataFrame.join`. Buď smazat, nebo použít.
- `smooth()` je implementovaná dvakrát — tady a v `phenology.py` RGB aplikace.

### 5.7 Chybějící čidla se přejdou tichem

`tl_pipeline._load_group` přeskočí CSV, které neexistuje. Streamlit na to
upozorní, ale **CLI ne** — dávkový běh s překlepem v cestě vyrobí report
s prázdnými senzorovými grafy a nic neřekne.

### 5.8 Report neuvádí přeskočené snímky

Poškozený JPG (`2026_0731_011337_002.JPG`, 0 bajtů) se ve videu tiše přeskočí.
`render_video` sice spadne, když se ztratí víc než polovina snímků, ale
jednotlivé ztráty se do reportu nedostanou. Snímky s resetovanými hodinami
report naopak uvádí správně.

### 5.9 Žádné testy

Nejcennější by byl test `tl_scan.scan_photo_set` na umělé složce s hraničními
případy: osamocený RAW bez JPG, resetované hodiny, dvojice s posunem přes 60 s.
Párovací logika je nejvíc netriviální část a je snadné ji rozbít.

---

## 6. Co by bylo dobré udělat příště

1. **ROI pro NDVI** (§5.1) — největší dopad na věcnou správnost.
2. Prověřit, zda sada obsahuje snímky s kalibračním terčíkem (§5.2).
3. Test párování v `tl_scan` (§5.9).
4. Nechat CLI hlásit chybějící čidla (§5.7).
5. Uklidit `align_to_dates` a sjednotit `smooth()` (§5.6).
6. Až budou data z F2026/NF2026 s obrazem, přesunout těžiště reportu na ně —
   je to podle projektové zprávy jediný čistý experimentální pár.

---

## 7. Prostředí a pasti

- **`cv2.imread` tiše vrací `None` u cest s diakritikou.** Na Windows používá
  ANSI souborové API, takže na `Sběr data 21082026_LES` selže bez výjimky.
  První běh kvůli tomu vyrobil mp4 o **261 bajtech**. Řeší to
  `tl_video.imread_unicode()` (čtení přes `pathlib` + `cv2.imdecode`) a pojistka,
  která vyhodí chybu, když se zapíše méně než polovina snímků.
  `cv2.VideoCapture` tímhle netrpí — proto RGB aplikace fungovala hned.
- **pip potřebuje `--trusted-host`** (PyPI za SSL inspekcí). V `run_timelapse.bat`.
- **Konzole cp1252** → `tl_cli.py` přepíná stdout na UTF-8, `.bat` volá `chcp 65001`.
- **ffmpeg** musí být v `PATH`.
