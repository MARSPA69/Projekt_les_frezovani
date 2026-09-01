"""
Casosberne zpracovani sady MAPIR z prikazove radky.

PRIKLAD:

    python tl_cli.py ^
        --snimky "C:\\...\\lokalita freza\\Photo" ^
        --senzory "C:\\...\\senzory" ^
        --vystup VYSTUP

Vystupem je zrychlene mp4, denni CSV vegetacnich indexu a PDF report
o sledovanem biotopu.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tl_video
from tl_pipeline import MapirJob, process
from tl_report import build_report


def _force_utf8_console() -> None:
    """Windowsi konzole jede v cp1252, ve kterem ceska diakritika spadne."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()
    parser = argparse.ArgumentParser(
        description="Časosběrné mp4 a PDF report o biotopu ze snímků MAPIR Survey 3N.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--snimky", type=Path, required=True,
                        help="Složka se snímky MAPIR (dvojice RAW + JPG).")
    parser.add_argument("--senzory", type=Path, required=True,
                        help="Složka s CSV soubory čidel TOMST.")
    parser.add_argument("--vystup", type=Path, default=Path("VYSTUP"),
                        help="Složka pro mp4, CSV a PDF (výchozí: VYSTUP).")
    parser.add_argument("--video", type=str, default=None, metavar="SOUBOR.mp4",
                        help="Název výstupního mp4; bez něj se odvodí z názvu plochy.")
    parser.add_argument("--plocha", type=str, default="Frézovaný 2022",
                        help="Název monitorované plochy do reportu.")
    parser.add_argument("--fps", type=int, default=tl_video.DEFAULT_OUTPUT_FPS,
                        help="Snímků za sekundu ve výstupním videu (výchozí: 10).")
    parser.add_argument("--nahled", type=int, default=None, metavar="POČET",
                        help="Zpracovat jen POČET snímků rovnoměrně po sadě "
                             "(rychlý náhled místo plného běhu).")
    parser.add_argument("--bez-videa", action="store_true", help="Jen analýza a report.")
    parser.add_argument("--bez-nir", action="store_true", help="Jen video, bez NDVI.")
    parser.add_argument("--bez-datumu", action="store_true",
                        help="Nevykreslovat datum do snímku.")
    parser.add_argument("--report", type=str, default="MAPIR_biotop_report.pdf",
                        help="Název souboru PDF reportu.")
    arguments = parser.parse_args(argv)

    if not arguments.snimky.is_dir():
        parser.error(f"Složka se snímky neexistuje: {arguments.snimky}")
    if not arguments.senzory.is_dir():
        parser.error(f"Složka se senzory neexistuje: {arguments.senzory}")
    if not 1 <= arguments.fps <= 60:
        parser.error("--fps musí být mezi 1 a 60.")

    arguments.vystup.mkdir(parents=True, exist_ok=True)

    def progress(stage: str, done: int, total: int, detail: str) -> None:
        print(f"  [{stage}] {done}/{total} {detail}", flush=True)

    job = MapirJob(plot_name=arguments.plocha, photo_dir=arguments.snimky,
                   sensor_dir=arguments.senzory, output_dir=arguments.vystup,
                   video_name=arguments.video)
    print(f"=== {job.plot_name} ===\n  snímky:  {job.photo_dir}\n"
          f"  senzory: {job.sensor_dir}", flush=True)

    report = process(job, fps=arguments.fps,
                     make_video=not arguments.bez_videa,
                     make_nir=not arguments.bez_nir,
                     overlay_date=not arguments.bez_datumu,
                     max_shots=arguments.nahled,
                     progress=progress)

    report_path = arguments.vystup / arguments.report
    build_report(report, str(report_path))

    print(f"\nZachytů:    {report.shots_total} "
          f"({report.shots_day} denních, {report.shots_night} nočních)")
    print(f"PDF report: {report_path}")
    if report.video_path != "–":
        size_mb = Path(report.video_path).stat().st_size / 1e6
        print(f"Video:      {report.video_path}  ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
