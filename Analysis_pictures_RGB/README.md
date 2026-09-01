# RGB časosběr — Brinno TLC2000

Aplikace pro projekt **„Vliv frézování půdy po těžbě dřeva na růst sazenic"**
(CRA s.r.o.). Ze záznamu časosběrné kamery Brinno vyrobí zrychlené `.mp4`
s vyřazenou nocí a PDF report s fenologickou analýzou zelenosti porostu.

## Spuštění

```
run_app.bat
```

Vytvoří `.venv`, doinstaluje závislosti a otevře aplikaci na
`http://localhost:8502`. Vyžaduje **ffmpeg** v `PATH`
(`winget install Gyan.FFmpeg`).

Dávkově z příkazové řádky:

```
.venv\Scripts\python cli.py ^
    --plocha "Frézovaný 2022=...\lokalita freza\RGB" ^
    --plocha "Nefrézovaný 2022=...\lokalita nefreza\RGB" ^
    --vystup VYSTUP
```

## Co je potřeba vědět o vstupních datech

Brinno **neukládá jednotlivé fotografie, ale rovnou hotové AVI** (MJPEG,
1920×1080, 30 fps), kde **jeden snímek = jeden zachyt v terénu**. Kamera dělí
záznam na více souborů `TLC000xx.AVI`; některé obsahují jediný snímek (restart
kamery) a do časosběru nevstupují.

Naměřená data projektu:

| | Frézovaný 2022 | Nefrézovaný 2022 |
|---|---|---|
| použitelných zachytů | 1113 | 1121 |
| interval | 2 h 0,5 min | přesně 2 h |
| období | 20. 5. – 21. 8. 2026 | 20. 5. – 21. 8. 2026 |

## Proč se rychlost neřídí násobičem

Zdrojové AVI má 30 fps, ale jeden snímek pokrývá zhruba **dvě hodiny reality**.
Násobič typu „×1,2" je proto bezpředmětný — celé léto by se přehrálo za 37 s
a ×1,2 by to zkrátilo na 31 s. Skutečný ovládací prvek je **výstupní fps**:

| fps | délka videa (~786 snímků) | 1 s videa ≈ |
|---|---|---|
| 6 | 131 s | 12 hodin |
| **10** (výchozí) | **79 s** | **20 hodin** |
| 15 | 52 s | 30 hodin |

## Noční řez

Vyřazují se snímky pořízené v zadaném intervalu, výchozí **22:00–05:00**
(interval smí přecházet přes půlnoc; stejný čas na obou koncích znamená, že se
nevyřazuje nic). Na datech projektu to vyřadí zhruba 30 % snímků.

Čas se čte **z časového razítka vypáleného kamerou do každého snímku**, ne
z pořadí snímku. Je to nutné: interval na ploše Frézovaný je 7230 s místo
7200 s, takže se čas záběru během sezony posune o celé hodiny a řez podle
pořadí by postupně vyřezával úplně jiné části dne.

Razítko čte modul `brinno_ocr.py` vlastním template matchingem (tesseract není
potřeba). Ověřeno na kompletní sadě **2238 snímků obou lokalit — 100 %
přečteno**, čas monotónně rostoucí.

## Fenologie GCC / ExG

**GCC** (green chromatic coordinate) = `G / (R + G + B)`. Protože jde o poměr,
změna osvětlení posune všechny tři kanály stejně a index zůstane stabilní —
popisuje tedy stav vegetace, ne počasí. Používá ho síť PhenoCam jako standardní
fenologický index. **ExG** (`2G − R − B` na normalizovaných kanálech) doplňuje
GCC silnější reakcí na přechod holá půda → vegetace.

- Analyzuje se jen výřez 35–97 % výšky snímku (bez oblohy a bez časového pruhu).
- Snímky s průměrným jasem mimo 25–245 se vyřazují.
- Denní hodnota je **90. percentil** z použitelných snímků dne (potlačí stín,
  mlhu a nízké slunce).

### Výsledek na datech projektu

Frézovaná plocha zelenost přes léto **drží a mírně roste** (+0,0112 GCC/měsíc,
vrchol 21. 7.), nefrézovaná od poloviny července **klesá** (−0,0219 GCC/měsíc).
To nezávisle odpovídá zjištění senzorové zprávy, že NF2022 má nejsilnější
červencové vysychání mělké vrstvy v celé sadě.

> **Výhrada:** absolutní hodnoty GCC ze dvou různých kamer nejsou přímo
> srovnatelné (jiný senzor, expozice, výřez). Srovnávat lze tvar a trend
> křivky. Srovnání F2022 vs. NF2022 navíc **není čistým efektem frézování** —
> plochy leží v odlišných geologických skupinách (Ca vs. Ka) 2,5 km od sebe.

## Výstupy

```
VYSTUP/
├── <plocha>_casosber.mp4      zrychlené časosběrné video
├── <plocha>_gcc_denni.csv     denní řada GCC/ExG (oddělovač ;, desetinná čárka)
└── RGB_report.pdf             report obou ploch včetně srovnání
```

Videa jsou velká (~200 MB na plochu při výchozí kvalitě). Časosběrný les se
komprimuje špatně — sousední snímky dělí dvě hodiny, scéna se změní úplně
a mezisnímková komprese nemá co ušetřit. Parametr `--kvalita` (CRF 14–35,
výchozí 23) velikost reguluje; `--kvalita 28` soubor zhruba půlí.

## Moduly

| soubor | co dělá |
|---|---|
| `brinno_ocr.py` | čtení vypáleného časového razítka (vlastní template matching) |
| `timelapse.py` | skenování AVI, noční řez, render mp4 |
| `phenology.py` | indexy zelenosti GCC/ExG a denní agregace |
| `report_rgb.py` | PDF report |
| `pipeline.py` | spojení kroků; sdílí ho CLI i Streamlit |
| `app.py` | Streamlit aplikace |
| `cli.py` | dávkové zpracování |
