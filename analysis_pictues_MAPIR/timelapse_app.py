"""
Streamlit aplikace: casosberne mp4 a report o biotopu ze snimku MAPIR Survey 3N.

Bezi vedle puvodni aplikace `app.py` (analyza jednotliveho snimku) a sdili
s ni moduly `mapir_raw`, `indices` i virtualni prostredi.

ZADAVA SE CESTA KE SLOZCE, NE UPLOAD:
    Sada ma 811 dvojic RAW+JPG, dohromady zhruba 17 GB. Nahravat ji pres
    prohlizec nelze - Streamlit drzi uploady v pameti. Aplikace proto cte
    slozku primo z disku.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

import tl_scan
import tl_video
from tl_pipeline import COMPARISON_SENSORS, PRIMARY_SENSORS, MapirJob, process
from tl_report import build_report

st.set_page_config(page_title="MAPIR časosběr – projekt LES", page_icon="🛰️", layout="wide")

st.title("🛰️ MAPIR Survey 3N – časosběr a report o biotopu")
st.caption("Projekt „Vliv frézování půdy po těžbě dřeva na růst sazenic“ · CRA s.r.o.")

DEFAULT_PHOTOS = r"C:\Users\mspan\Desktop\Sběr data 21082026_LES\kamery\lokalita freza\Photo"
DEFAULT_SENSORS = r"C:\Users\mspan\Desktop\Sběr data 21082026_LES\senzory"

with st.sidebar:
    st.header("Nastavení")
    plot_name = st.text_input("Monitorovaná plocha", "Frézovaný 2022")

    st.subheader("Video")
    fps = st.slider("Snímků za sekundu", 4, 30, tl_video.DEFAULT_OUTPUT_FPS)
    overlay_date = st.checkbox("Vykreslit datum do snímku", value=True)
    st.caption("U MAPIR sady se noční řez nedělá – video ukazuje celý denní rytmus. "
               "Z NDVI se noční snímky vyřazují automaticky.")

    st.subheader("Co spočítat")
    make_video = st.checkbox("Časosběrné mp4", value=True)
    make_nir = st.checkbox("NIR analýza (NDVI) + report", value=True)

    preview = st.number_input(
        "Náhled – zpracovat jen N snímků (0 = vše)", 0, 2000, 0, step=50,
        help="Rychlá kontrola nastavení. Snímky se vyberou rovnoměrně po celé sadě.")

    output_dir = Path(st.text_input(
        "Výstupní složka", str(Path(__file__).parent / "VYSTUP_TIMELAPSE")))

photo_dir = Path(st.text_input("Složka se snímky MAPIR (RAW + JPG)", DEFAULT_PHOTOS))
sensor_dir = Path(st.text_input("Složka s CSV čidel TOMST", DEFAULT_SENSORS))

ready = True
if not photo_dir.is_dir():
    st.warning(f"Složka se snímky neexistuje: {photo_dir}")
    ready = False
else:
    with st.spinner("Prohlížím sadu…"):
        photo_set = tl_scan.scan_photo_set(photo_dir)
    if not photo_set.shots:
        st.error("Ve složce nejsou žádné snímky MAPIR.")
        ready = False
    else:
        period = photo_set.period
        columns = st.columns(4)
        columns[0].metric("Zachytů", len(photo_set.shots))
        columns[1].metric("Dvojic RAW+JPG", sum(1 for s in photo_set.shots if s.has_pair))
        columns[2].metric("Interval",
                          f"{tl_scan.median_interval_hours(photo_set.shots):.1f} h")
        columns[3].metric("Období", f"{period[0]:%d.%m.} – {period[1]:%d.%m.}")
        if photo_set.rejected_clock:
            st.info(f"{len(photo_set.rejected_clock)} snímků má resetované hodiny kamery "
                    "(datum 2024) a do časové řady nevstupuje.")

if not sensor_dir.is_dir():
    st.warning(f"Složka se senzory neexistuje: {sensor_dir}")
    ready = False
else:
    missing = [code for code in PRIMARY_SENSORS + COMPARISON_SENSORS
               if not (sensor_dir / f"{code}.csv").exists()]
    if missing:
        st.warning("Chybí CSV čidel: " + ", ".join(missing))
    st.caption(f"Hlavní čidla: {', '.join(PRIMARY_SENSORS)} · "
               f"srovnávací: {', '.join(COMPARISON_SENSORS)}")

if st.button("Zpracovat", type="primary", disabled=not ready):
    status = st.status("Zpracovávám…", expanded=True)
    bar = st.progress(0.0)

    def progress(stage: str, done: int, total: int, detail: str) -> None:
        bar.progress(min(done / max(total, 1), 1.0))
        status.write(f"**{stage}** {done}/{total} {detail}")

    job = MapirJob(plot_name=plot_name, photo_dir=photo_dir,
                   sensor_dir=sensor_dir, output_dir=output_dir)
    try:
        report = process(job, fps=fps, make_video=make_video, make_nir=make_nir,
                         overlay_date=overlay_date,
                         max_shots=int(preview) or None, progress=progress)
        report_path = output_dir / "MAPIR_biotop_report.pdf"
        build_report(report, str(report_path))
        status.update(label="Hotovo", state="complete")
    except Exception as error:                       # noqa: BLE001 - hlaska patri uzivateli
        status.update(label="Chyba", state="error")
        st.error(str(error))
        st.stop()

    st.success(f"PDF report: {report_path}")
    with open(report_path, "rb") as handle:
        st.download_button("Stáhnout PDF report", handle,
                           file_name="MAPIR_biotop_report.pdf", mime="application/pdf")

    columns = st.columns(3)
    columns[0].metric("Denních snímků", report.shots_day)
    columns[1].metric("Nočních (mimo NDVI)", report.shots_night)
    columns[2].metric("Délka videa", f"{report.shots_total / max(fps, 1):.0f} s")

    if not report.ndvi_daily.empty:
        st.subheader("Vývoj vegetačních indexů")
        st.line_chart(report.ndvi_daily[["ndvi", "osavi", "rdvi"]])
        st.caption("NDVI z nekalibrovaných RAW snímků – platný je relativní vývoj "
                   "v čase, nikoli absolutní úroveň.")

    video = Path(report.video_path)
    if video.exists():
        size_mb = video.stat().st_size / 1e6
        st.caption(f"{video}  ({size_mb:.0f} MB)")
        if size_mb < 200:
            st.video(str(video))
        else:
            st.info("Video je pro náhled v prohlížeči příliš velké – "
                    "otevři ho prosím přímo ze složky.")
