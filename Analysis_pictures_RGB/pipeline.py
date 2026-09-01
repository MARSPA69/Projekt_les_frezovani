"""
Spojeni celeho zpracovani jedne plochy do jednoho volani.

Pouzivaji ho jak CLI (`cli.py`), tak Streamlit aplikace (`app.py`), aby obe
cesty delaly presne totez a nemohly se rozejit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

import phenology
import timelapse
from report_rgb import PlotReport


@dataclass
class PlotJob:
    """Zadani pro jednu plochu."""
    name: str
    source_dir: Path
    output_dir: Path
    # Nazev vysledneho mp4. None = odvodit z nazvu plochy. Slouzi k tomu, aby
    # se dal vystup pojmenovat podle konvence odevzdani, aniz by se tim menil
    # nazev plochy, ktery jde do reportu.
    video_name: str | None = None


def process_plot(job: PlotJob,
                 fps: int = timelapse.DEFAULT_OUTPUT_FPS,
                 night_start: dt.time = timelapse.DEFAULT_NIGHT_START,
                 night_end: dt.time = timelapse.DEFAULT_NIGHT_END,
                 crf: int = timelapse.DEFAULT_CRF,
                 make_video: bool = True,
                 make_phenology: bool = True,
                 overlay_date: bool = True,
                 progress=None) -> PlotReport:
    """
    Zpracuje jednu plochu: nacte AVI, provede nocni rez, vyrenderuje mp4
    a spocita fenologickou radu. Vraci `PlotReport` pro PDF.
    """
    def step(stage: str, done: int, total: int, detail: str = "") -> None:
        if progress:
            progress(stage, done, total, detail)

    scan = timelapse.scan_directory(
        job.source_dir,
        progress=lambda done, total, detail: step("nacitani", done, total, detail),
    )
    if not scan.captures:
        raise ValueError(f"Ve složce {job.source_dir} nejsou žádné čitelné snímky.")

    kept, dropped = timelapse.filter_daytime(scan.captures, night_start, night_end)
    if not kept:
        raise ValueError("Noční řez vyřadil všechny snímky – zkontroluj zadaný interval.")

    job.output_dir.mkdir(parents=True, exist_ok=True)
    video_path = job.output_dir / (job.video_name or f"{job.name}_casosber.mp4")
    if make_video:
        timelapse.render_video(
            kept, video_path, fps=fps, overlay_date=overlay_date, crf=crf,
            progress=lambda done, total, detail: step("video", done, total, detail),
        )

    daily = pd.DataFrame()
    metrics = None
    if make_phenology:
        samples = phenology.analyse_captures(
            kept, progress=lambda done, total, detail: step("fenologie", done, total, detail),
        )
        daily = phenology.daily_series(samples)
        metrics = phenology.season_metrics(daily)
        if not daily.empty:
            daily.to_csv(job.output_dir / f"{job.name}_gcc_denni.csv",
                         sep=";", decimal=",", encoding="utf-8-sig")

    return PlotReport(
        name=job.name,
        source_dir=str(job.source_dir),
        total_captures=len(scan.captures),
        kept=len(kept),
        dropped_night=len(dropped),
        unreadable=len(scan.unreadable),
        skipped_files=[(path.name, reason) for path, reason in scan.skipped_files],
        interval_hours=scan.interval_seconds / 3600.0,
        period_start=scan.captures[0].timestamp,
        period_end=scan.captures[-1].timestamp,
        gaps=scan.gaps(),
        daily=daily,
        metrics=metrics,
        video_path=str(video_path) if make_video else "–",
        video_fps=fps,
        night_start=night_start,
        night_end=night_end,
    )
