"""
Fenologicke indexy zelenosti z RGB casosberu (phenocam metodika).

PROC GCC A NE PROSTE "ZELENY KANAL":
    Absolutni jas se u venkovni kamery meni s oblacnosti, uhlem slunce a
    automatickou expozici - syrovy zeleny kanal proto mnohem vic vypovida
    o pocasi nez o rostlinach. GCC (green chromatic coordinate) je podil
        G / (R + G + B)
    tedy pomer, ktery se scitanim jasu KRATI. Zmena osvetleni posune vsechny
    tri kanaly stejne a GCC zustane temer konstantni. Presne proto ho pouziva
    sit PhenoCam jako standardni fenologicky index.

DOPLNKOVY INDEX ExG:
    ExG = 2G - R - B (na normalizovanych kanalech) reaguje silneji na
    prechod puda -> vegetace, takze dobre doplnuje GCC pri zapoji porostu.

DENNI AGREGACE JE NUTNA:
    Jednotlive snimky kolisaji podle okamzite oblacnosti. Standardni postup
    phenocam site je brat denni horni percentil (tzv. 90th percentile
    compositing), ktery potlaci snimky se stinem, mlhou a nizkym sluncem.
    Pouzivame denni 90. percentil z DENNICH snimku.

ROI:
    Analyzuje se jen vyrez obrazu, ne cely snimek. Ve vychozim nastaveni
    vynechavame oblohu (horni cast) a vypaleny casovy pruh (spodni cast),
    protoze obloha do indexu zelenosti vnasi jen sum.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from timelapse import Capture

# Vychozi ROI jako podil vysky snimku: od 35 % (pod obzorem) do 97 %
# (nad vypalenym razitkem). Sirka se bere cela.
DEFAULT_ROI_TOP = 0.35
DEFAULT_ROI_BOTTOM = 0.97

# Snimky s prumernym jasem mimo tento rozsah jsou pro fenologii nepouzitelne
# (soumrak, presvicena scena) a do denniho kompozitu nevstupuji.
MIN_USABLE_BRIGHTNESS = 25.0
MAX_USABLE_BRIGHTNESS = 245.0

DAILY_PERCENTILE = 90


@dataclass
class GreennessSample:
    """Indexy zelenosti jednoho snimku."""
    timestamp: dt.datetime
    gcc: float
    exg: float
    brightness: float
    usable: bool


def region_of_interest(frame: np.ndarray,
                       top: float = DEFAULT_ROI_TOP,
                       bottom: float = DEFAULT_ROI_BOTTOM) -> np.ndarray:
    """Vyrez snimku, ze ktereho se pocitaji indexy."""
    height = frame.shape[0]
    return frame[int(height * top):int(height * bottom)]


def greenness(frame_bgr: np.ndarray) -> tuple[float, float, float]:
    """
    Vrati (GCC, ExG, prumerny jas) pro dany vyrez.

    Kanaly se prevadi na float az po souctu, aby se u uint8 neprepnul rozsah.
    Deleni je jistene proti nulovemu souctu u zcela cernych snimku.
    """
    blue, green, red = (frame_bgr[:, :, i].astype(np.float32) for i in range(3))
    total = red + green + blue
    brightness = float(total.mean() / 3.0)

    safe_total = np.maximum(total, 1e-6)
    gcc = float((green / safe_total).mean())

    red_n, green_n, blue_n = red / safe_total, green / safe_total, blue / safe_total
    exg = float((2.0 * green_n - red_n - blue_n).mean())
    return gcc, exg, brightness


def analyse_captures(captures: list[Capture],
                     roi_top: float = DEFAULT_ROI_TOP,
                     roi_bottom: float = DEFAULT_ROI_BOTTOM,
                     progress=None) -> list[GreennessSample]:
    """
    Spocita indexy zelenosti pro kazdy zachyt. Cte sekvencne, snimek po snimku,
    stejnou strategii jako render (viz timelapse.render_video).
    """
    samples: list[GreennessSample] = []
    reader: cv2.VideoCapture | None = None
    open_source: Path | None = None
    next_index = 0

    try:
        for done, item in enumerate(captures, start=1):
            if item.source != open_source:
                if reader is not None:
                    reader.release()
                reader = cv2.VideoCapture(str(item.source))
                open_source = item.source
                next_index = 0
            if item.frame_index < next_index:
                reader.set(cv2.CAP_PROP_POS_FRAMES, item.frame_index)
                next_index = item.frame_index
            while next_index < item.frame_index:
                if not reader.grab():
                    break
                next_index += 1

            ok, frame = reader.read()
            next_index += 1
            if not ok or frame is None:
                continue

            gcc, exg, brightness = greenness(region_of_interest(frame, roi_top, roi_bottom))
            samples.append(GreennessSample(
                timestamp=item.timestamp,
                gcc=gcc,
                exg=exg,
                brightness=brightness,
                usable=MIN_USABLE_BRIGHTNESS <= brightness <= MAX_USABLE_BRIGHTNESS,
            ))
            if progress and done % 25 == 0:
                progress(done, len(captures), "fenologie")
    finally:
        if reader is not None:
            reader.release()
    return samples


def daily_series(samples: list[GreennessSample]) -> pd.DataFrame:
    """
    Denni kompozit indexu: 90. percentil z pouzitelnych snimku daneho dne.

    Vraci DataFrame s indexem `date` a sloupci gcc, exg, n_snimku.
    """
    usable = [s for s in samples if s.usable]
    if not usable:
        return pd.DataFrame(columns=["gcc", "exg", "n_snimku"])

    frame = pd.DataFrame({
        "date": [s.timestamp.date() for s in usable],
        "gcc": [s.gcc for s in usable],
        "exg": [s.exg for s in usable],
    })
    grouped = frame.groupby("date").agg(
        gcc=("gcc", lambda v: float(np.percentile(v, DAILY_PERCENTILE))),
        exg=("exg", lambda v: float(np.percentile(v, DAILY_PERCENTILE))),
        n_snimku=("gcc", "size"),
    )
    grouped.index = pd.to_datetime(grouped.index)
    return grouped.sort_index()


def smooth(series: pd.Series, window: int = 7) -> pd.Series:
    """Klouzavy median pro potlaceni zbytkoveho sumu pocasi."""
    return series.rolling(window=window, center=True, min_periods=1).median()


@dataclass
class SeasonMetrics:
    """Souhrnne fenologicke ukazatele jedne plochy."""
    start: dt.date
    end: dt.date
    gcc_min: float
    gcc_max: float
    gcc_mean: float
    peak_date: dt.date | None
    amplitude: float
    trend_per_month: float


def season_metrics(daily: pd.DataFrame) -> SeasonMetrics | None:
    """
    Zakladni popis sezonni krivky GCC.

    `trend_per_month` je smernice linearni regrese vyhlazene krivky prepoctena
    na 30 dni - u letniho useku ukazuje, zda porost jeste zeleni nebo uz
    stagnuje/zaziva stres.
    """
    if daily.empty:
        return None
    smoothed = smooth(daily["gcc"])
    days = (daily.index - daily.index[0]).days.to_numpy(dtype=float)
    if len(days) >= 2:
        slope = float(np.polyfit(days, smoothed.to_numpy(), 1)[0]) * 30.0
    else:
        slope = 0.0
    return SeasonMetrics(
        start=daily.index[0].date(),
        end=daily.index[-1].date(),
        gcc_min=float(daily["gcc"].min()),
        gcc_max=float(daily["gcc"].max()),
        gcc_mean=float(daily["gcc"].mean()),
        peak_date=smoothed.idxmax().date() if len(smoothed) else None,
        amplitude=float(daily["gcc"].max() - daily["gcc"].min()),
        trend_per_month=slope,
    )
