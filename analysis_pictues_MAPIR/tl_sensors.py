"""
Nacteni dat z pudnich cidel TOMST TMS a meteorologicky ramec.

FORMAT CSV TOMST:
    Strednikem oddelene sloupce bez hlavicky:
        0  poradove cislo
        1  datum a cas (RRRR.MM.DD HH:MM), krok 15 minut
        2  casove pasmo
        3  T1  teplota pudniho profilu
        4  T2  teplota pudniho profilu
        5  T3  prizemni/vzduchovy kanal (mraziky a prehrivani u povrchu)
        6  raw vlhkost (surovy TMS count)
        7  shake
        8  chybovy priznak (0 = v poradku)
    Cast souboru pouziva desetinnou carku, cast tecku - nacita se proto jako
    text a prevadi rucne.

RAW VLHKOST NENI PROCENTO:
    Sloupec vlhkosti je surovy TMS count, ne objemova vlhkost pudy (VWC).
    Bez lokalni kalibrace nelze rikat "tato plocha ma o X % vice vody".
    Srovnavat lze TVAR krivky: reakci po srazce, rychlost vysychani a zmenu
    v ramci jednoho cidla. Absolutni uroven mezi dvema cidly ovlivnuje kontakt
    s pudou, dutiny, koreny, kamenitost a stárnuti kontaktu.

INTERPRETACNI KOREKCE:
    Prevzato ze zpravy "Analyza senzorickych dat z 21082026 - projekt LES".
    Prvni tyden po instalaci je kontaktni faze; nektera cidla maji navic
    vlastni pozdejsi zacatek nebo trvaly zlom, ktery se nesmi cist jako
    hydrologicky trend.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

COLUMN_NAMES = ["poradi", "cas", "pasmo", "T1", "T2", "T3", "vlhkost_raw",
                "shake", "chyba", "_prazdny"]

# Prahy pro pocty stresovych dnu podle prizemniho kanalu T3.
HEAT_THRESHOLDS = (30.0, 35.0, 40.0)


@dataclass(frozen=True)
class SensorInfo:
    """Popis jednoho cidla podle zpravy z 21. 8. 2026."""
    code: str
    plot: str
    treatment: str
    year: int
    depth_cm: int
    group: str
    latitude: float
    longitude: float
    interpret_from: dt.date
    note: str = ""


# Souradnice, skupiny a interpretacni zacatky prevzaty z tabulek 2 a 4/5
# zpravy "Analyza senzorickych dat z 21082026 - projekt LES".
SENSORS: dict[str, SensorInfo] = {
    "T10F22": SensorInfo("T10F22", "F2022", "fréza", 2022, 10, "Ca",
                         49.362581, 14.299215, dt.date(2026, 3, 17)),
    "T48F22": SensorInfo("T48F22", "F2022", "fréza", 2022, 48, "Ca",
                         49.362158, 14.299185, dt.date(2026, 3, 17),
                         "trvalý zlom raw vlhkosti 20. 5. – před a po se nesmí "
                         "spojovat do jedné absolutní řady"),
    "T10F26": SensorInfo("T10F26", "F2026", "fréza", 2026, 10, "Ca",
                         49.362491, 14.298674, dt.date(2026, 4, 3),
                         "prudký skok 2. 4., pravděpodobně kontaktní změna"),
    "T48F26": SensorInfo("T48F26", "F2026", "fréza", 2026, 48, "Ca",
                         49.362354, 14.298777, dt.date(2026, 3, 17)),
    "T10NF26": SensorInfo("T10NF26", "NF2026", "nefréza", 2026, 10, "Ca",
                          49.362533, 14.298873, dt.date(2026, 3, 17),
                          "jedna delší časová mezera"),
    "T48NF26": SensorInfo("T48NF26", "NF2026", "nefréza", 2026, 48, "Ca",
                          49.362357, 14.298919, dt.date(2026, 3, 17)),
    "T10NF22": SensorInfo("T10NF22", "NF2022", "nefréza", 2022, 10, "Ka",
                          49.356000, 14.330828, dt.date(2026, 3, 17)),
    "T48NF22": SensorInfo("T48NF22", "NF2022", "nefréza", 2022, 48, "Ka",
                          49.356236, 14.330911, dt.date(2026, 4, 15),
                          "do 14. 4. neinterpretovatelný raw signál"),
}

# Regionalni meteorologicky ramec pro Podoli I. / Milevsko, prevzaty z tabulky 3
# tehoz podkladu. Lokalni srazkomer na plochach neni, takze jde o RAMEC, ne
# o presny denni srazkovy zaznam u cidla.
METEO_FRAMEWORK = [
    ("březen 2026", "srážkově podnormální",
     "19 mm, 41 % normálu; 5. nejsušší březen od 1961", "suchý start sezony"),
    ("duben 2026", "srážkově silně podnormální",
     "13 mm, 33 % normálu", "prohloubení deficitu před aktivním růstem"),
    ("květen 2026", "srážkově normální, teplotně nadnormální",
     "57 mm, 81 % normálu; mělká podzemní voda mimořádně podnormální",
     "srážkové pulzy bez plného odstranění deficitu"),
    ("červen 2026", "teplotně silně nadnormální, srážkově normální",
     "71 mm, 87 % normálu; horká vlna 18.–30. 6.; lokální bouřky",
     "rychlý růst buřeně a vysoký evapotranspirační tlak"),
    ("červenec 2026", "srážkově podnormální",
     "51 mm, 57 % normálu", "silný červencový pokles mělké vlhkosti"),
    ("srpen do 21. 8.", "přetrvávající hydrologické sucho",
     "ČHMÚ 19. 8.: hydrologické sucho přetrvává na většině území",
     "stav při odečtu je už letní stresový stav"),
]

# Vlhkostni epizody identifikovane v teze zprave (kapitola 6.1).
MOISTURE_EVENTS = [
    (dt.date(2026, 5, 16), "květnový impuls"),
    (dt.date(2026, 6, 1), "silný nástup vlhkosti"),
    (dt.date(2026, 6, 13), "vlhkostní událost 13.–16. 6."),
    (dt.date(2026, 7, 1), "epizoda na přelomu 29. 6. – 1. 7."),
]


def load_tomst_csv(path: Path) -> pd.DataFrame:
    """
    Nacte jeden TOMST CSV a vrati DataFrame indexovany casem.

    Desetinny oddelovac se lisi soubor od souboru, proto se cisla nacitaji
    jako text a prevadeji az po nahrazeni carky teckou.
    """
    raw = pd.read_csv(path, sep=";", header=None, dtype=str, engine="python",
                      names=COLUMN_NAMES)
    frame = pd.DataFrame(index=pd.to_datetime(raw["cas"], format="%Y.%m.%d %H:%M"))
    for column in ("T1", "T2", "T3", "vlhkost_raw", "chyba"):
        frame[column] = pd.to_numeric(
            raw[column].str.replace(",", ".", regex=False).values, errors="coerce")
    frame.index.name = "cas"
    return frame.sort_index()


def load_sensor(directory: Path, code: str, apply_interpret_from: bool = True) -> pd.DataFrame:
    """
    Nacte cidlo podle kodu (napr. "T10F22") ze slozky se senzorickymi CSV.

    Pri `apply_interpret_from` se odrizne instalacni/kontaktni faze podle
    tabulky ve zprave, aby trend nezacinal na neplatnych hodnotach.
    """
    info = SENSORS.get(code)
    frame = load_tomst_csv(Path(directory) / f"{code}.csv")
    if apply_interpret_from and info is not None:
        frame = frame[frame.index.date >= info.interpret_from]
    return frame


def daily_summary(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Denni agregace: median raw vlhkosti, prumer T1/T2 a maximum/minimum T3.

    Vlhkost se agreguje medianem (odolny vuci ojedinelym vypadkum kontaktu),
    teploty prumerem a prizemni kanal extremy, protoze prave extremy nesou
    informaci o stresu.
    """
    if frame.empty:
        return pd.DataFrame()
    daily = frame.resample("D").agg(
        vlhkost_raw=("vlhkost_raw", "median"),
        T1=("T1", "mean"),
        T2=("T2", "mean"),
        T3_max=("T3", "max"),
        T3_min=("T3", "min"),
        T3_mean=("T3", "mean"),
    )
    return daily.dropna(how="all")


def heat_stress_days(frame: pd.DataFrame) -> dict[str, int]:
    """Pocty dnu s prekrocenim stresovych prahu prizemniho kanalu T3."""
    if frame.empty:
        return {}
    daily_max = frame["T3"].resample("D").max().dropna()
    daily_min = frame["T3"].resample("D").min().dropna()
    counts = {f"T3>{int(threshold)}": int((daily_max > threshold).sum())
              for threshold in HEAT_THRESHOLDS}
    counts["T3<0"] = int((daily_min < 0).sum())
    return counts


def moisture_change(daily: pd.DataFrame) -> tuple[float, float, float, float]:
    """
    Vrati (prvni, posledni, absolutni zmena, trend na den) raw vlhkosti.

    Trend je smernice linearni regrese pres denni mediany. U cidel s trvalym
    kontaktnim zlomem je nutne ho cist s vyhradou uvedenou v `SensorInfo.note`.
    """
    series = daily["vlhkost_raw"].dropna()
    if len(series) < 2:
        return (np.nan,) * 4
    days = (series.index - series.index[0]).days.to_numpy(dtype=float)
    slope = float(np.polyfit(days, series.to_numpy(), 1)[0])
    return (float(series.iloc[0]), float(series.iloc[-1]),
            float(series.iloc[-1] - series.iloc[0]), slope)


def align_to_dates(daily: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Prevzorkuje denni radu na zadane dny (pro spojeni s obrazovou radou)."""
    if daily.empty:
        return pd.DataFrame(index=index)
    return daily.reindex(daily.index.union(index)).interpolate(
        method="time", limit_direction="both").reindex(index)
