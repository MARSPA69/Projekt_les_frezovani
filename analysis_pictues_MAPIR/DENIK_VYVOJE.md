# Deník vývoje — MAPIR Survey 3N NIR analyzátor

Projekt: Alcedo Frézování / CRA s.r.o. Rumburk
Aplikace: Streamlit analyzátor NDVI z NIR snímků MAPIR Survey 3N
Datum záznamu: 2026-07-08

Tento deník shrnuje jednu vývojovou seanci, ve které se z původně nefunkční
aplikace (padala a hlásila fyzikálně nemožné výsledky) stal funkční nástroj
pro relativní fyziologickou analýzu lesní školky. Záznamy jsou chronologické;
u každého kroku je uvedeno **co**, **proč** a **jak ověřeno**.

---

## 1. Oprava pádu aplikace (SyntaxError)

**Příznak:** Aplikace padala na `app.py:640` s `SyntaxError: '(' was never closed`.

**Příčina:** Ternární výraz použitý jako samostatný příkaz:
```python
st.success(ii.biological_meaning) if ii.color == "#2e7d32" else ( ... )
```
Streamlit „magic" bere poslední bare výraz na řádku a snaží se ho zobrazit —
přitom parsoval jen řádek 640 s neuzavřenou závorkou a spadl.

**Řešení:** Přepsáno na čitelné `if/elif/else`, které magic vůbec nespouští.

**Ověření:** `python -m py_compile app.py` prošel; kontrola, že stejný vzor
(bare ternár s `st.` voláním) není jinde v souboru.

---

## 2. Kořenová příčina falešného „vážného stresu"

**Příznak:** Na zahradě plné zeleně v červenci aplikace hlásila
Mean NDVI = −0.049, 100 % bez vegetace, „VÁŽNÝ STRES".

**Diagnóza (empiricky):** Aplikace počítala NDVI z **JPG**. Změřeno na
`2026_0707_150954_002.JPG`:

| Veličina | Hodnota |
|---|---|
| Korelace kanálů R↔B | **0.998** |
| NDVI (NIR=R, Red=B) | −0.046 |
| Vegetace > 0.2 | 0.0 % |

MAPIR ukládá JPG jako **white-balancovaný fialový náhled**, kde jsou všechny
tři kanály téměř identické. Spektrální rozdíl NIR vs Red je v něm nenávratně
slitý → (NIR − Red) ≈ 0 → falešný „stres". **Žádné přemapování kanálů JPG to
nespraví.**

**Klíčové zjištění:** Použitelná spektrální data jsou pouze v `.RAW` souboru.

---

## 3. Dekódování RAW formátu

**Formát:** `.RAW` = 18 000 000 B = 4000 × 3000 px, **12-bit packed** Bayer
(2 pixely ve 3 bajtech, RAW12).

**Spektrální rozložení (empiricky ověřeno):** Senzor je **sloupcově
prokládaný** na dvě pásma:
- sudé sloupce = **NIR** (850 nm), mean DN ~ 1500 (vegetace silně odráží)
- liché sloupce = **Red** (660 nm), mean DN ~ 100 (chlorofyl pohlcuje)

Testováno všech 6 párování Bayer sub-kanálů; správné (NIR vysoký / Red nízký)
dalo NDVI mean **+0.83 až +0.87**, 95 % vegetace — přesně to, co se čeká od
svěží červencové zahrady.

**Prostorové ověření:** Vyrenderovaná NDVI heatmapa z RAW ukázala reálnou
scénu (strom, listí, lehátko) zeleně = vegetace. Sedí na JPG.

---

## 4. Zapojení RAW do aplikace

**Návrh (minimálně invazivní):** Z RAW se staví **syntetický co-registrovaný
BGR nosič**, kde R kanál = NIR a B kanal = Red. Tím celý existující pipeline
(`extract_channels` čte NIR=R, Red=B; kalibrace; ROI; indexy) funguje **beze
změny** — jen dostane skutečně oddělená pásma.

**Implementace:** Nový modul `mapir_raw.py`:
- `_unpack_raw12()` — rozbalí 12-bit packed buffer
- `split_nir_red()` — rozdělí Bayer podle parity sloupců, NIR/Red auto podle jasu
- `load_mapir_raw()` — vrátí `RawLoad` (nosič + metadata)
- 12-bit DN škálováno na 8-bit (/16); NDVI je scale-invariantní

**Zapojení do `app.py`:** uploader přijímá `.raw`, směrování podle typu,
varování u JPG, aktualizované popisky.

**Ověření end-to-end (reálné moduly):** NDVI mean +0.867, zdravé 91.3 %,
bez vegetace 3.4 %. Verdikt „ZDRAVÁ" místo „VÁŽNÝ STRES".

---

## 5. Detekce den/noc + dark konstanta

**Motivace (zadání):** Používat jen denní snímky; noční mají mít automaticky
zabudovanou dark konstantu.

**Měření (celý 17snímkový timelapse):**

| Fáze | čas | NIR mean | Red mean |
|---|---|---|---|
| Den | 15:09–17:43 | 1500–1670 | 60–170 |
| Soumrak | 18:49 | 1085 | 4.9 |
| Noc | 19:56–04:37 | 200–350 | ~0.5 |

**Klasifikace:** Čistý separátor je **průměr Red pásma** (práh 20 DN) — den má
Red osvětlený, noc kolabuje k nule. Bez osvětleného Red pásma NDVI fyzikálně
neplatí (falešně se přisaje k 1.0).

**Dark konstanta:** Aplikuje se **jen na noční** snímky. Změřeno, že
black-level subtrakce denní NDVI naopak **zhoršuje** (0.836 → 0.858, protože
Red vegetace je reálně nízký). U tohoto senzoru vychází black-level ≈ 0
(tmavé pixely dosahují 0), takže odečet je fakticky nulový — mechanismus je
připravený, ale hlavní ochranou je **detekce a označení noci jako neplatné**.

**Ověření:** DEN Red=100 → platné; NOC Red=0.5 → neplatné, verdikt přepsán na
„NDVI NEPLATNÉ".

---

## 6. Sjednocený PDF report s vizualizací

**Zadání:** PDF report vč. vizualizace — RAW převedený do PNG, aby byly vidět
kontrasty a barevné odchylky.

**Implementace:** `build_pdf_report()` v `report_generator.py` (reportlab,
Unicode font DejaVuSans z matplotlibu kvůli českým znakům). Obsah: hlavička,
banner den/noc, verdikt, statistiky, **vizualizační sekce (RAW→PNG false-color
NIR vedle NDVI heatmapy)**, souhrn, 6 indexů, metadata, doporučení.

**Optimalizace:** Obrázky zmenšeny na ~1600 px → PDF ~5 MB místo 26 MB.

**Noční poctivost:** U nočního snímku se verdikt přepíše na fialové „NDVI
NEPLATNÉ" (žádná zavádějící zelená „ZDRAVÁ") + poznámka pod statistikami.

**Ověření:** Vyrenderované PDF (den i noc) vizuálně zkontrolováno; app boot
HTTP 200. Do requirements přidán `reportlab`.

---

## 7. Prošetření kalibračního terčíku

**Dotaz uživatele:** Terčík je na RAW vidět, ale auto-detekce ho nenašla.

**Zjištění:**
1. Detekce hledá **QR kód**; terčík uživatele žádný QR nemá — je to
   **černo-bílý ArUco marker** (potvrzeno: DICT_4X4_50, id=9). Auto-detekce
   „nenašla" korektně, protože hledala špatnou věc.
2. ArUco lze detekovat i rozostřený, ale detekce je **kolísavá** (2 ze 6
   denních snímků, kamera ostří na horizont ~27 m, terčík na ~5 m).
3. **Zásadní fyzikální problém:** černo-bílý terčík **nedokáže nakalibrovat
   NDVI**:
   - V NIR je nejjasnější **vegetace** (~1160+ DN), ne bílá karta (~80–180 DN).
     Bílá karta v NIR není světlé maximum — listy odrážejí 850 nm víc než papír.
   - Red kanál je na terčíku ≈ 0 (bílá i černá) → dvěma body na DN=0 nejde
     proložit kalibrační přímku.

**Rozhodnutí uživatele:** Fallback bez terčíku (indikativní NDVI). Žádná změna
kódu — aplikace tuto cestu už umí. Pro kvantitativní NDVI by byl nutný MAPIR
reflektanční terčík se 4 šedými patchi a známou reflektancí na 660/850 nm.

---

## 8. Dávková relativní fyziologická škála

**Zadání:** Relativní/kvalitativní analytika bez terčíku; škála fyziologie
lesní školky do 4–6 kategorií, do nich přiřazovat RAW snímky.

**Ověření vhodnosti metriky (denní snímky, stejná scéna):**

| Index | rozsah | CV (šum osvětlení) | závěr |
|---|---|---|---|
| NDVI mean | 0.82–0.91 | 4.0 % | median=1.0 → saturuje, NE |
| **OSAVI** | 0.56–0.61 | **3.2 %** | nejstabilnější → ANO |
| RDVI | 0.52–0.57 | 3.4 % | dobrý |
| MSAVI2 | 0.54–0.62 | 4.1 % | dobrý |
| WDRVI | 0.56–0.77 | 12.5 % | moc citlivý na světlo |

**Volba:** Škála stavěná na **OSAVI** (nesaturuje, nejstabilnější).

**Implementace:** Modul `physiology_scale.py` + dávkový režim v `app.py`
(přepínač v sidebaru). Skóre = medián OSAVI přes vegetační pixely; kategorizace
**relativní v rámci dávky** (interval min-max nebo kvantily); noční vynechány.

**Klíčová pojistka (kritická pro poctivost):** Změřený šum osvětlení v OSAVI je
~0.05. Pokud je **rozptyl dávky pod prahem** `MEANINGFUL_SPREAD_OSAVI = 0.05`,
aplikace kategorie **nevytvoří** a nahlásí „Bez rozlišení" — nefabrikuje škálu
ze světelného šumu.

**Ověření:**
- 7 denních snímků stejné zahrady (rozptyl 0.047 < 0.05) → správně „Bez
  rozlišení" místo vymyšlených kategorií.
- Syntetická dávka s reálným rozptylem (OSAVI 0.20–0.62) → korektně rozdělena
  do 5 kategorií (Kritická → Výborná).

---

## Přidané závislosti

- `reportlab>=4.0` — generování PDF (přidáno do requirements.txt)
- `python-docx` — generování metodické příručky DOCX

## Nové / změněné soubory

| Soubor | Změna |
|---|---|
| `app.py` | oprava pádu, RAW load, den/noc UI, PDF export, dávkový režim |
| `mapir_raw.py` | **nový** — RAW12 unpack, NIR/Red split, den/noc, dark konstanta |
| `physiology_scale.py` | **nový** — dávková relativní škála + pojistka na šum |
| `report_generator.py` | `build_pdf_report()`, downscaling obrázků |
| `requirements.txt` | + reportlab |

## Otevřená rizika / doporučení do budoucna

- **Šum osvětlení ~3–5 %** je pro nekalibrovaná data zásadní. Standardizovat
  focení (difuzní světlo, stejná série) je nutnost, ne volba.
- **ArUco detekce** není zapojena (uživatel zvolil fallback). Kdyby se v
  budoucnu chtěla, je nutné filtrovat falešné pozitivy (velikost markeru, ID).
- **OSAVI práh 0.05** je odvozen z jednoho dne / jedné scény. Při jiných
  podmínkách focení ověřit znovu.
- **Black-level ≈ 0** platí pro tento kus senzoru; u jiného kusu ověřit.
