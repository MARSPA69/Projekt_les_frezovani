"""
Streamlit aplikace: casosberne mp4 a PDF report z RGB zaznamu Brinno.

ZADAVA SE CESTA KE SLOZCE, NE UPLOAD:
    Zdrojova AVI maji stovky MB a vysledne video take. Nahravani pres prohlizec
    by data zbytecne kopirovalo a u vetsich sad naraze na limity Streamlitu.
    Aplikace proto pracuje primo se slozkou na disku.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import streamlit as st

import timelapse
from pipeline import PlotJob, process_plot
from report_rgb import build_report

st.set_page_config(page_title="RGB časosběr – projekt LES", page_icon="🌲", layout="wide")

st.title("🌲 RGB časosběr – Brinno TLC2000")
st.caption("Projekt „Vliv frézování půdy po těžbě dřeva na růst sazenic“ · CRA s.r.o.")

DEFAULT_PLOTS = [
    ("Frézovaný 2022", r"C:\Users\mspan\Desktop\Sběr data 21082026_LES\kamery\lokalita freza\RGB"),
    ("Nefrézovaný 2022", r"C:\Users\mspan\Desktop\Sběr data 21082026_LES\kamery\lokalita nefreza\RGB"),
]

with st.sidebar:
    st.header("Nastavení")

    st.subheader("Noční řez")
    night_start = st.time_input("Vyřadit od", dt.time(22, 0), step=1800)
    night_end = st.time_input("Vyřadit do", dt.time(5, 0), step=1800)
    st.caption("Interval smí přecházet přes půlnoc. Stejný čas na obou polích "
               "znamená, že se nevyřazuje nic.")

    st.subheader("Video")
    fps = st.slider("Snímků za sekundu", 4, 30, timelapse.DEFAULT_OUTPUT_FPS)
    st.caption(f"Jeden snímek videa = jeden zachyt (~2 h reality). "
               f"Při {fps} fps odpovídá 1 s videa zhruba {2 * fps} hodinám.")
    crf = st.slider("Kvalita (nižší = lepší obraz, větší soubor)", 14, 35,
                    timelapse.DEFAULT_CRF)
    overlay_date = st.checkbox("Vykreslit datum do snímku", value=True)

    st.subheader("Co spočítat")
    make_video = st.checkbox("Časosběrné mp4", value=True)
    make_phenology = st.checkbox("Fenologie GCC/ExG + PDF report", value=True)

    output_dir = Path(st.text_input(
        "Výstupní složka",
        str(Path(__file__).parent / "VYSTUP")))

st.subheader("Plochy ke zpracování")
count = st.number_input("Počet ploch", 1, 4, 2)

jobs: list[PlotJob] = []
for index in range(int(count)):
    default_name, default_path = (DEFAULT_PLOTS[index] if index < len(DEFAULT_PLOTS)
                                  else (f"Plocha {index + 1}", ""))
    left, right = st.columns([1, 3])
    name = left.text_input("Název", default_name, key=f"name{index}")
    path = right.text_input("Složka s AVI", default_path, key=f"path{index}")
    directory = Path(path) if path else None
    if directory and not directory.is_dir():
        st.warning(f"Složka neexistuje: {directory}")
    elif directory:
        avi_count = len(list(directory.glob("*.AVI"))) + len(list(directory.glob("*.avi")))
        st.caption(f"Nalezeno {avi_count} souborů AVI.")
        jobs.append(PlotJob(name=name, source_dir=directory, output_dir=output_dir))

if st.button("Zpracovat", type="primary", disabled=not jobs):
    status = st.status("Zpracovávám…", expanded=True)
    bar = st.progress(0.0)

    def progress(stage: str, done: int, total: int, detail: str) -> None:
        bar.progress(min(done / max(total, 1), 1.0))
        status.write(f"**{stage}** {done}/{total} {detail}")

    reports = []
    try:
        for job in jobs:
            status.write(f"### {job.name}")
            reports.append(process_plot(
                job, fps=fps, crf=crf, night_start=night_start, night_end=night_end,
                make_video=make_video, make_phenology=make_phenology,
                overlay_date=overlay_date, progress=progress))
        report_path = output_dir / "RGB_report.pdf"
        build_report(reports, str(report_path))
        status.update(label="Hotovo", state="complete")
    except Exception as error:                       # noqa: BLE001 - hlaska patri uzivateli
        status.update(label="Chyba", state="error")
        st.error(str(error))
        st.stop()

    st.success(f"PDF report: {report_path}")
    with open(report_path, "rb") as handle:
        st.download_button("Stáhnout PDF report", handle, file_name="RGB_report.pdf",
                           mime="application/pdf")

    for report in reports:
        st.subheader(report.name)
        columns = st.columns(4)
        columns[0].metric("Zachytů", report.total_captures)
        columns[1].metric("Ponecháno", report.kept)
        columns[2].metric("Vyřazeno nocí", report.dropped_night)
        columns[3].metric("Délka videa", f"{report.kept / max(fps, 1):.0f} s")

        if report.gaps:
            st.warning("Výpadky záznamu: " + "; ".join(
                f"{a:%d.%m. %H:%M} → {b:%d.%m. %H:%M} ({hours:.0f} h)"
                for a, b, hours in report.gaps))

        if not report.daily.empty:
            st.line_chart(report.daily[["gcc", "exg"]])

        video = Path(report.video_path)
        if video.exists():
            size_mb = video.stat().st_size / 1e6
            st.caption(f"{video}  ({size_mb:.0f} MB)")
            if size_mb < 200:
                st.video(str(video))
            else:
                st.info("Video je pro náhled v prohlížeči příliš velké – "
                        "otevři ho prosím přímo ze složky.")
