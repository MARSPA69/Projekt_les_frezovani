"""
Davkove zpracovani RGB casosberu z prikazove radky.

PRIKLAD - obe plochy najednou, vychozi nastaveni (nocni rez 22:00-05:00, 10 fps):

    python cli.py ^
        --plocha "Frézovaný 2022=C:\\...\\lokalita freza\\RGB" ^
        --plocha "Nefrézovaný 2022=C:\\...\\lokalita nefreza\\RGB" ^
        --vystup VYSTUP

Kdyz se zada vic ploch, PDF report je spolecny a obsahuje jejich srovnani.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import timelapse
from pipeline import PlotJob, process_plot
from report_rgb import build_report


def _parse_time(value: str) -> dt.time:
    try:
        hours, minutes = value.split(":")
        return dt.time(int(hours), int(minutes))
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError(f"Čas musí být ve tvaru HH:MM, dostal jsem '{value}'.")


def _parse_plot(value: str) -> PlotJob:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            f"Plocha se zadává jako 'Název=cesta', dostal jsem '{value}'.")
    name, _, path = value.partition("=")
    directory = Path(path.strip().strip('"'))
    if not directory.is_dir():
        raise argparse.ArgumentTypeError(f"Složka neexistuje: {directory}")
    return PlotJob(name=name.strip(), source_dir=directory, output_dir=Path("."))


def _force_utf8_console() -> None:
    """
    Windowsi konzole jede ve vychozim stavu v cp1252, ve kterem ceska diakritika
    spadne na UnicodeEncodeError. Prepnuti na UTF-8 je jednodussi nez zbavovat
    hlasky hacku a carek.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()
    parser = argparse.ArgumentParser(
        description="Časosběrné mp4 a PDF report z RGB záznamu kamery Brinno.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--plocha", action="append", required=True, type=_parse_plot,
                        metavar="NÁZEV=CESTA",
                        help="Plocha ke zpracování; lze uvést vícekrát.")
    parser.add_argument("--video", action="append", default=None, metavar="SOUBOR.mp4",
                        help="Název výstupního mp4; uvádí se ve stejném pořadí jako "
                             "--plocha. Bez něj se název odvodí z názvu plochy.")
    parser.add_argument("--vystup", type=Path, default=Path("VYSTUP"),
                        help="Složka pro mp4, CSV a PDF (výchozí: VYSTUP).")
    parser.add_argument("--fps", type=int, default=timelapse.DEFAULT_OUTPUT_FPS,
                        help="Snímků za sekundu ve výstupním videu (výchozí: 10).")
    parser.add_argument("--noc-od", type=_parse_time, default=timelapse.DEFAULT_NIGHT_START,
                        metavar="HH:MM", help="Začátek nočního řezu (výchozí: 22:00).")
    parser.add_argument("--noc-do", type=_parse_time, default=timelapse.DEFAULT_NIGHT_END,
                        metavar="HH:MM", help="Konec nočního řezu (výchozí: 05:00).")
    parser.add_argument("--kvalita", type=int, default=timelapse.DEFAULT_CRF,
                        metavar="CRF",
                        help="Kvalita videa H.264; nižší číslo = lepší obraz a větší "
                             "soubor (výchozí: 23, rozsah 14-35).")
    parser.add_argument("--bez-videa", action="store_true", help="Jen analýza a report.")
    parser.add_argument("--bez-fenologie", action="store_true", help="Jen video.")
    parser.add_argument("--bez-datumu", action="store_true",
                        help="Nevykreslovat české datum do snímku.")
    parser.add_argument("--report", type=str, default="RGB_report.pdf",
                        help="Název souboru PDF reportu.")
    arguments = parser.parse_args(argv)

    if not 1 <= arguments.fps <= 60:
        parser.error("--fps musí být mezi 1 a 60.")
    if not 14 <= arguments.kvalita <= 35:
        parser.error("--kvalita musí být mezi 14 a 35.")

    video_names = arguments.video or []
    if video_names and len(video_names) != len(arguments.plocha):
        parser.error(f"--video je uvedeno {len(video_names)}x, ale --plocha "
                     f"{len(arguments.plocha)}x; počty musí sedět.")

    output_dir: Path = arguments.vystup
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress(stage: str, done: int, total: int, detail: str) -> None:
        print(f"  [{stage}] {done}/{total} {detail}", flush=True)

    reports = []
    for index, job in enumerate(arguments.plocha):
        job.output_dir = output_dir
        if video_names:
            job.video_name = video_names[index]
        print(f"\n=== {job.name} ===\n  zdroj: {job.source_dir}", flush=True)
        report = process_plot(
            job, fps=arguments.fps, crf=arguments.kvalita,
            night_start=arguments.noc_od, night_end=arguments.noc_do,
            make_video=not arguments.bez_videa,
            make_phenology=not arguments.bez_fenologie,
            overlay_date=not arguments.bez_datumu,
            progress=progress,
        )
        reports.append(report)
        print(f"  zachytů {report.total_captures}, ponecháno {report.kept}, "
              f"vyřazeno nocí {report.dropped_night}, "
              f"video {report.kept / max(arguments.fps, 1):.0f} s", flush=True)

    report_path = output_dir / arguments.report
    build_report(reports, str(report_path))
    print(f"\nPDF report: {report_path}")
    for report in reports:
        if report.video_path != "–":
            size_mb = Path(report.video_path).stat().st_size / 1e6
            print(f"Video:      {report.video_path}  ({size_mb:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
