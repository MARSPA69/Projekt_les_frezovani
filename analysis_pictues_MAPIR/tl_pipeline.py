"""
Spojeni celeho zpracovani casosberne sady MAPIR do jednoho volani.

Pouziva ho CLI (`tl_cli.py`) i Streamlit aplikace (`timelapse_app.py`), aby
obe cesty delaly totez.

VYSTUPY:
    <plocha>_casosber.mp4    zrychlene casosberne video z JPG nahledu
    <plocha>_ndvi_denni.csv  denni rada vegetacnich indexu
    MAPIR_biotop_report.pdf  report o biotopu (obraz + cidla + meteo)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import tl_nir_series
import tl_scan
import tl_sensors
import tl_video
from tl_report import BiotopeReport

# Cidla kolokovana s kamerou MAPIR (plocha Frezovany 2022) a srovnavaci
# nefrezovana plocha. NF2022 lezi v jine geologicke skupine ~2,5 km daleko -
# report tuto vyhradu vzdy tiskne.
PRIMARY_SENSORS = ("T10F22", "T48F22")
COMPARISON_SENSORS = ("T10NF22", "T48NF22")


@dataclass
class MapirJob:
    """Zadani zpracovani jedne obrazove sady."""
    plot_name: str
    photo_dir: Path
    sensor_dir: Path
    output_dir: Path
    # Nazev vysledneho mp4; None = odvodit z nazvu plochy.
    video_name: str | None = None


def process(job: MapirJob,
            fps: int = tl_video.DEFAULT_OUTPUT_FPS,
            make_video: bool = True,
            make_nir: bool = True,
            overlay_date: bool = True,
            max_shots: int | None = None,
            progress=None) -> BiotopeReport:
    """
    Zpracuje obrazovou sadu MAPIR a vrati podklady pro PDF report.

    `max_shots` omezi pocet zpracovanych zachytu (rovnomerne po cele sade) -
    slouzi pro rychly nahled, nez se pusti nekolikahodinovy plny beh.
    """
    def step(stage: str, done: int, total: int, detail: str = "") -> None:
        if progress:
            progress(stage, done, total, detail)

    step("nacitani", 0, 1, "hledám snímky")
    photo_set = tl_scan.scan_photo_set(job.photo_dir)
    if not photo_set.shots:
        raise ValueError(f"Ve složce {job.photo_dir} nejsou žádné snímky MAPIR.")

    shots = photo_set.shots
    if max_shots and len(shots) > max_shots:
        picks = np.linspace(0, len(shots) - 1, max_shots).astype(int)
        shots = [shots[i] for i in sorted(set(picks))]
    step("nacitani", len(shots), len(shots), f"{len(shots)} zachytů")

    job.output_dir.mkdir(parents=True, exist_ok=True)
    video_path = job.output_dir / (job.video_name or f"{job.plot_name}_casosber.mp4")
    if make_video:
        tl_video.render_video(
            shots, video_path, fps=fps, overlay_date=overlay_date,
            progress=lambda done, total, detail: step("video", done, total, detail))

    ndvi_daily = pd.DataFrame()
    night_count = 0
    if make_nir:
        samples = tl_nir_series.analyse_series(
            shots, progress=lambda done, total, detail: step("nir", done, total, detail))
        night_count = sum(1 for s in samples if s.is_night)
        ndvi_daily = tl_nir_series.daily_series(samples)
        if not ndvi_daily.empty:
            ndvi_daily.to_csv(job.output_dir / f"{job.plot_name}_ndvi_denni.csv",
                              sep=";", decimal=",", encoding="utf-8-sig")

    step("senzory", 0, 1, "načítám TOMST")
    primary_raw, primary_daily = _load_group(job.sensor_dir, PRIMARY_SENSORS)
    comparison_raw, comparison_daily = _load_group(job.sensor_dir, COMPARISON_SENSORS)

    period = photo_set.period
    return BiotopeReport(
        plot_name=job.plot_name,
        photo_dir=str(job.photo_dir),
        video_path=str(video_path) if make_video else "–",
        video_fps=fps,
        shots_total=len(shots),
        shots_day=len(shots) - night_count,
        shots_night=night_count,
        rejected_clock=len(photo_set.rejected_clock),
        interval_hours=tl_scan.median_interval_hours(shots),
        period_start=period[0],
        period_end=period[1],
        ndvi_daily=ndvi_daily,
        primary=primary_daily,
        comparison=comparison_daily,
        primary_raw=primary_raw,
        comparison_raw=comparison_raw,
    )


def _load_group(sensor_dir: Path, codes) -> tuple[dict, dict]:
    """Nacte skupinu cidel; vrati (15min rady, denni rady) podle kodu."""
    raw: dict[str, pd.DataFrame] = {}
    daily: dict[str, pd.DataFrame] = {}
    for code in codes:
        path = Path(sensor_dir) / f"{code}.csv"
        if not path.exists():
            continue
        frame = tl_sensors.load_sensor(sensor_dir, code)
        raw[code] = frame
        daily[code] = tl_sensors.daily_summary(frame)
    return raw, daily
