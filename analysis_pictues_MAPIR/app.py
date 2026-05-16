"""
MAPIR Survey 3N NIR - aplikace pro vyhodnoceni fotosynteticke aktivity.

Streamlit aplikace - spustit prikazem:
    streamlit run app.py
nebo dvojklikem na run_app.bat.

Projekt: Alcedo Frezovani, CRA s.r.o., Rumburk.
"""

from __future__ import annotations

import io
from datetime import date, datetime, time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from calibration import (
    CalibrationBundle,
    MAPIR_TARGET_REFLECTANCE,
    PATCH_ORDER,
    TARGET_REFLECTANCE_PROFILE,
    calibrate_from_patches,
    default_fallback_calibration,
    detect_calibration_target,
)
from indices import INDICES
from interpretation import VEG_PROFILES, interpret, interpret_all_indices
from ndvi_processor import index_to_rgb, ndvi_to_rgb, process_image
from report_generator import build_csv_summary, build_html_report


# -------------------------------------------------------------------- konfigurace UI

st.set_page_config(
    page_title="MAPIR Survey 3N - NIR analyza",
    page_icon="🌲",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
  .main-header {
      background: linear-gradient(120deg, #1b5e20 0%, #2e7d32 50%, #388e3c 100%);
      color: white; padding: 24px 28px; border-radius: 14px;
      margin-bottom: 22px; box-shadow: 0 4px 14px rgba(0,0,0,0.08);
  }
  .main-header h1 { margin: 0; font-size: 28px; font-weight: 700; }
  .main-header p  { margin: 6px 0 0 0; opacity: 0.92; }
  .verdict-card {
      padding: 18px 24px; border-radius: 12px; color: white;
      font-size: 22px; font-weight: 700; text-align: center;
      margin: 12px 0 16px 0;
  }
  .metric-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
  .stat-card {
      background: #f1f8f4; padding: 14px; border-radius: 10px;
      border-left: 4px solid #2e7d32; text-align: center;
  }
  .stat-card .v { font-size: 26px; font-weight: 700; color: #1b5e20; }
  .stat-card .l { font-size: 12px; color: #5f6368; text-transform: uppercase; }
  .warning-box {
      background: #fff8e1; border-left: 4px solid #f9a825;
      padding: 12px 16px; border-radius: 8px; margin: 10px 0;
  }
  .error-box {
      background: #ffebee; border-left: 4px solid #c62828;
      padding: 12px 16px; border-radius: 8px; margin: 10px 0;
  }
  div[data-testid="stMetricValue"] { font-size: 22px; }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# -------------------------------------------------------------------- session state

def init_state() -> None:
    defaults = {
        "step": 1,
        "uploaded_image": None,        # np.ndarray BGR
        "uploaded_name": None,
        "metadata": {},
        "patch_points": [],            # [(x,y), ...] for manual calibration
        "calibration": None,           # CalibrationBundle
        "analysis": None,              # dict with NDVIResult + Interpretation
        "qr_detected": None,           # dict from detect_calibration_target
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# -------------------------------------------------------------------- helpers

def load_image(file) -> np.ndarray:
    """Nacte uploadovany soubor jako BGR np.uint8."""
    data = file.read()
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Nelze dekodovat obrazek.")
    return img


def bgr_to_rgb(img_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)


def reset_workflow() -> None:
    for k in ["uploaded_image", "uploaded_name", "metadata",
              "patch_points", "calibration", "analysis", "qr_detected"]:
        st.session_state[k] = None if k != "patch_points" else []
    st.session_state["metadata"] = {}
    st.session_state["step"] = 1


# -------------------------------------------------------------------- header

st.markdown(
    """<div class="main-header">
        <h1>🌲 MAPIR Survey 3N NIR — analyza fotosynteticke aktivity</h1>
        <p>Vyhodnoceni NDVI z NIR snimku lesniho biotopu | projekt Alcedo Frezovani</p>
    </div>""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------- sidebar nav

with st.sidebar:
    st.markdown("### Postup analyzy")
    steps = [
        "1. Nahrani snimku",
        "2. Metadata snimku",
        "3. Kalibrace tercku",
        "4. Vysledky NDVI",
        "5. Report & export",
    ]
    for idx, label in enumerate(steps, start=1):
        if idx == st.session_state.step:
            st.markdown(f"**▶ {label}**")
        elif idx < st.session_state.step:
            st.markdown(f"✅ {label}")
        else:
            st.markdown(f"<span style='color:#9aa0a6'>{label}</span>",
                        unsafe_allow_html=True)

    st.divider()
    if st.button("🔄 Nova analyza (reset)", use_container_width=True):
        reset_workflow()
        st.rerun()

    st.divider()
    st.caption(
        "Survey 3N mapping:\n"
        "- R kanal = NIR (850 nm)\n"
        "- B kanal = Red (660 nm)\n"
        "- NDVI = (NIR - Red) / (NIR + Red)"
    )


# ==================================================================== STEP 1

if st.session_state.step == 1:
    st.subheader("Krok 1 — Nahraj NIR snimek")

    col1, col2 = st.columns([2, 1])
    with col1:
        uploaded = st.file_uploader(
            "Vyber JPG/PNG/TIFF z MAPIR Survey 3N",
            type=["jpg", "jpeg", "png", "tif", "tiff"],
            help="Snimek po-export z MAPIR kamery. RAW JPG je idealni."
        )
        if uploaded is not None:
            try:
                img = load_image(uploaded)
                st.session_state.uploaded_image = img
                st.session_state.uploaded_name = uploaded.name

                # Auto-detekce QR tercku
                qr = detect_calibration_target(img)
                st.session_state.qr_detected = qr

                st.success(f"Nactenc: {uploaded.name}  "
                           f"({img.shape[1]} × {img.shape[0]} px)")
                if qr is not None:
                    st.info(
                        f"🎯 Kalibracni QR tercik detekovan automaticky "
                        f"(metoda: {qr['method']}). V dalsim kroku jen dolad patche."
                    )
                else:
                    st.warning(
                        "Tercik nedetekovan automaticky - v kroku 3 oznac manualne "
                        "nebo zvol fallback (bez kalibrace)."
                    )
            except Exception as e:
                st.error(f"Chyba pri nacitani: {e}")

    with col2:
        if st.session_state.uploaded_image is not None:
            st.image(bgr_to_rgb(st.session_state.uploaded_image),
                     caption="Nahled", use_container_width=True)

    if st.session_state.uploaded_image is not None:
        if st.button("Pokracovat na metadata →", type="primary"):
            st.session_state.step = 2
            st.rerun()


# ==================================================================== STEP 2

elif st.session_state.step == 2:
    st.subheader("Krok 2 — Metadata snimku a podminek")

    md = st.session_state.metadata

    with st.form("metadata_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Datum a cas snimku**")
            datum = st.date_input(
                "Datum poizeni", value=md.get("datum_obj", date.today())
            )
            cas = st.time_input(
                "Cas poizeni", value=md.get("cas_obj", time(12, 0))
            )

            st.markdown("**Vegetace v zaberu**")
            typ_porostu = st.selectbox(
                "Typ porostu",
                options=list(VEG_PROFILES.keys()),
                format_func=lambda k: VEG_PROFILES[k]["name"],
                index=list(VEG_PROFILES.keys()).index(md.get("typ_porostu", "mix")),
            )
            st.caption(VEG_PROFILES[typ_porostu]["notes"])

            st.markdown("**Meteorologicke podminky**")
            meteo = st.selectbox(
                "Aktualne pri snimani",
                options=["zatazeno", "oblacno", "polojasno", "jasno", "mlha", "dest"],
                index=["zatazeno", "oblacno", "polojasno", "jasno", "mlha", "dest"]
                      .index(md.get("meteo", "oblacno")),
                help="Pro kalibraci nejlepsi: zatazeno / oblacno (difuzni svetlo).",
            )

        with col2:
            st.markdown("**Kamera (stacionarni na strome)**")
            vyska_kamery = st.number_input(
                "Vyska umisteni kamery [m]",
                min_value=0.5, max_value=30.0,
                value=md.get("vyska_kamery_m", 2.5), step=0.5,
            )
            uhel_kamery = st.slider(
                "Uhel naklonu kamery od horizontu [°]",
                min_value=-45, max_value=45,
                value=md.get("uhel_kamery_deg", 0),
                help="0° = vodorovne; zaporne = dolu; kladne = nahoru.",
            )
            horizont = st.number_input(
                "Vzdalenost zorneho horizontu [m]",
                min_value=5.0, max_value=200.0,
                value=md.get("horizont_m", 27.0), step=1.0,
                help="Vzdalenost objektu kde kamera ostri (typ. 25-30 m dle metodiky).",
            )

            st.markdown("**Kalibracni tercik**")
            tercik_v_zaberu = st.radio(
                "Je tercik na snimku?",
                options=["ANO", "NE"],
                index=0 if md.get("tercik_pritomen", "ANO") == "ANO" else 1,
                horizontal=True,
                help="Bez tercku bude vyhodnoceni POUZE indikativni.",
            )
            vzdalenost_tercku = st.number_input(
                "Vzdalenost tercku od kamery [m]",
                min_value=0.5, max_value=50.0,
                value=md.get("vzdalenost_tercku_m", 5.0), step=0.5,
                disabled=(tercik_v_zaberu == "NE"),
                help="Doporuceno 3-8 m, kolmo na osu kamery.",
            )

        st.markdown("**Poznamky (volitelne)**")
        poznamky = st.text_area(
            "Stanoviste, ID plochy, jine pozorovani...",
            value=md.get("poznamky", ""),
            height=80,
        )

        submitted = st.form_submit_button("Ulozit metadata a pokracovat →",
                                          type="primary")

    if submitted:
        st.session_state.metadata = {
            "datum_obj":  datum,
            "cas_obj":    cas,
            "datum":      datum.strftime("%Y-%m-%d"),
            "cas":        cas.strftime("%H:%M"),
            "typ_porostu": typ_porostu,
            "meteo":       meteo,
            "vyska_kamery_m":      vyska_kamery,
            "uhel_kamery_deg":     uhel_kamery,
            "horizont_m":          horizont,
            "tercik_pritomen":     tercik_v_zaberu,
            "vzdalenost_tercku_m": vzdalenost_tercku if tercik_v_zaberu == "ANO" else None,
            "soubor":     st.session_state.uploaded_name,
            "poznamky":   poznamky,
        }
        st.session_state.step = 3
        st.rerun()

    if st.button("← Zpet na nahrani"):
        st.session_state.step = 1
        st.rerun()


# ==================================================================== STEP 3

elif st.session_state.step == 3:
    st.subheader("Krok 3 — Kalibrace (oznaceni patchu tercku)")

    md = st.session_state.metadata
    img_bgr = st.session_state.uploaded_image

    if md.get("tercik_pritomen") == "NE":
        st.markdown(
            "<div class='warning-box'>"
            "<strong>Tercik neni na snimku.</strong> Aplikace pouzije fallback "
            "(linear DN/255). NDVI bude pouze INDIKATIVNI, ne kvantitativni."
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("Pokracovat s fallback kalibraci →", type="primary"):
            st.session_state.calibration = default_fallback_calibration()
            st.session_state.step = 4
            st.rerun()
        if st.button("← Zpet na metadata"):
            st.session_state.step = 2
            st.rerun()

    else:
        st.markdown(
            "Zadej **stredy 4 patchu** v poradi:  "
            f"**{' → '.join(PATCH_ORDER)}**  (od nejsvetlejsiho k nejtmavsimu)."
        )
        # Tabulka aktivnich kalibracnich hodnot
        reflectance_lines = "  ".join(
            f"`{p}` = {MAPIR_TARGET_REFLECTANCE[p][0]:.2f} (Red) / "
            f"{MAPIR_TARGET_REFLECTANCE[p][1]:.2f} (NIR)"
            for p in PATCH_ORDER
        )
        st.caption(
            f"Aktivni profil: **{TARGET_REFLECTANCE_PROFILE.upper()}** — "
            f"{reflectance_lines}.  Profil zmenis v `calibration.py` "
            f"(promenna TARGET_REFLECTANCE_PROFILE: 'nominal' / 'chart')."
        )

        # Zobraz snimek s vyznacenymi body
        img_rgb = bgr_to_rgb(img_bgr).copy()
        h, w = img_rgb.shape[:2]

        # Nahled s overlay - barvy bunky pro 4 patche (white -> dark_gray)
        annotated = img_rgb.copy()
        for i, (x, y) in enumerate(st.session_state.patch_points):
            color = [(245, 245, 245), (180, 180, 180),
                     (90, 90, 90), (30, 30, 30)][i]
            cv2.rectangle(annotated, (x - 12, y - 12), (x + 12, y + 12),
                          color, 2)
            cv2.putText(annotated, PATCH_ORDER[i], (x - 30, y - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 220, 0), 2)

        # Pokud detekovan QR, vyznac
        qr = st.session_state.qr_detected
        if qr is not None:
            pts = np.array(qr["corners"], dtype=np.int32)
            cv2.polylines(annotated, [pts], True, (0, 255, 255), 3)

        col_img, col_form = st.columns([2, 1])

        with col_img:
            st.image(annotated, caption="Klikni na nahled pro odecet pixelu "
                     "(ručně zapis souradnice vpravo)", use_container_width=True)
            st.caption(f"Rozmer obrazku: {w} × {h} px")

        with col_form:
            st.markdown("**Pixel souradnice patchu**")
            new_pts: list[tuple[int, int]] = []
            for i, name in enumerate(PATCH_ORDER):
                default_x, default_y = 0, 0
                if i < len(st.session_state.patch_points):
                    default_x, default_y = st.session_state.patch_points[i]
                c1, c2 = st.columns(2)
                with c1:
                    x = st.number_input(f"{name} — X", min_value=0, max_value=w-1,
                                        value=default_x, key=f"x_{i}")
                with c2:
                    y = st.number_input(f"{name} — Y", min_value=0, max_value=h-1,
                                        value=default_y, key=f"y_{i}")
                new_pts.append((int(x), int(y)))
            st.session_state.patch_points = new_pts

            patch_half = st.slider("Polomer vzorkovani [px]",
                                   min_value=3, max_value=30, value=10,
                                   help="Velikost ROI kolem stredu patche.")

            if st.button("Spustit kalibraci", type="primary",
                         use_container_width=True):
                if any(x == 0 and y == 0 for (x, y) in new_pts):
                    st.error("Doplnte X/Y pro vsechny 4 patche (vse != 0).")
                else:
                    try:
                        cal = calibrate_from_patches(img_bgr, new_pts, patch_half)
                        st.session_state.calibration = cal
                        st.success("Kalibrace dokoncena.")
                        st.metric("R² NIR", f"{cal.nir.r_squared:.3f}")
                        st.metric("R² Red", f"{cal.red.r_squared:.3f}")
                        for w_msg in cal.warnings:
                            st.warning(w_msg)
                    except Exception as e:
                        st.error(f"Chyba kalibrace: {e}")

        if st.session_state.calibration is not None:
            cal = st.session_state.calibration
            st.markdown("---")
            colA, colB = st.columns(2)
            with colA:
                df_nir = pd.DataFrame({
                    "patch": PATCH_ORDER,
                    "DN": cal.nir.measured_dn,
                    "reflektance": cal.nir.known_reflectance,
                })
                fig = px.scatter(df_nir, x="DN", y="reflektance",
                                 text="patch", title="Kalibrace NIR")
                xs = np.linspace(0, 255, 50)
                ys = cal.nir.gain * xs + cal.nir.offset
                fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                         name="regresn primka"))
                fig.update_traces(textposition="top center")
                st.plotly_chart(fig, use_container_width=True)
            with colB:
                df_red = pd.DataFrame({
                    "patch": PATCH_ORDER,
                    "DN": cal.red.measured_dn,
                    "reflektance": cal.red.known_reflectance,
                })
                fig = px.scatter(df_red, x="DN", y="reflektance",
                                 text="patch", title="Kalibrace Red")
                xs = np.linspace(0, 255, 50)
                ys = cal.red.gain * xs + cal.red.offset
                fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines",
                                         name="regresni primka"))
                fig.update_traces(textposition="top center")
                st.plotly_chart(fig, use_container_width=True)

            if st.button("Pokracovat na vysledky →", type="primary"):
                st.session_state.step = 4
                st.rerun()

        if st.button("← Zpet na metadata"):
            st.session_state.step = 2
            st.rerun()


# ==================================================================== STEP 4

elif st.session_state.step == 4:
    st.subheader("Krok 4 — Vysledky NDVI a interpretace")

    md = st.session_state.metadata
    img_bgr = st.session_state.uploaded_image
    cal = st.session_state.calibration

    if cal is None:
        st.error("Kalibrace neni hotova. Vrat se na krok 3.")
        if st.button("← Zpet"):
            st.session_state.step = 3
            st.rerun()
        st.stop()

    # Pripadne vylouceni ROI tercku z vypoctu
    exclude_roi = None
    if cal.target_detected and cal.patch_centers_px:
        xs = [p[0] for p in cal.patch_centers_px]
        ys = [p[1] for p in cal.patch_centers_px]
        pad = cal.patch_size_px * 2
        x_min, x_max = max(0, min(xs) - pad), max(xs) + pad
        y_min, y_max = max(0, min(ys) - pad), max(ys) + pad
        exclude_roi = (x_min, y_min, x_max - x_min, y_max - y_min)

    with st.spinner("Pocitam NDVI a doplnkove indexy..."):
        result = process_image(img_bgr, cal, exclude_target_roi=exclude_roi)
        interp = interpret(
            stats=result.stats,
            vegetation_type=md["typ_porostu"],
            capture_date=md["datum_obj"],
            meteo=md["meteo"],
            calibration=cal,
            has_target=(md["tercik_pritomen"] == "ANO"),
            index_stats=result.index_stats,
        )
        index_interps = interpret_all_indices(
            index_stats=result.index_stats,
            vegetation_type=md["typ_porostu"],
            capture_date=md["datum_obj"],
        )

    st.session_state.analysis = {
        "result": result,
        "interpretation": interp,
        "index_interpretations": index_interps,
    }

    # Verdikt
    st.markdown(
        f"<div class='verdict-card' style='background:{interp.color_code}'>"
        f"{interp.overall_verdict}</div>",
        unsafe_allow_html=True,
    )

    # Statistiky
    s = result.stats
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mean NDVI", f"{s.mean:.3f}")
    c2.metric("Median NDVI", f"{s.median:.3f}")
    c3.metric("Zdrave (>0.5)", f"{s.fraction_healthy*100:.1f} %")
    c4.metric("Stres (0.2-0.4)", f"{s.fraction_stressed*100:.1f} %")

    st.info(interp.summary)
    st.markdown(f"**Sezonni kontext:** {interp.observed_vs_expected}")
    st.markdown(f"**Cross-validace indexu:** {interp.cross_validation}")
    st.markdown(f"**Kvalita:** {interp.quality_assessment}")

    if result.warnings:
        for w in result.warnings:
            st.warning(w)
    if cal.warnings:
        for w in cal.warnings:
            st.warning(w)

    # Vizualizace
    st.markdown("---")
    tab1, tab2, tab3, tab4 = st.tabs([
        "NDVI heatmapa", "Histogram",
        "Vegetacni indexy (6 metrik)", "Detaily"
    ])

    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Puvodni snimek**")
            st.image(bgr_to_rgb(img_bgr), use_container_width=True)
        with col2:
            st.markdown("**NDVI heatmapa (cervena = bare, zelena = vegetace)**")
            heat = ndvi_to_rgb(result.ndvi)
            st.image(heat, use_container_width=True)

    with tab2:
        flat = result.ndvi[result.valid_mask]
        flat = flat[np.isfinite(flat)]
        if len(flat) > 200_000:
            flat = np.random.choice(flat, size=200_000, replace=False)
        fig = px.histogram(
            x=flat, nbins=60, range_x=(-0.5, 1.0),
            labels={"x": "NDVI"}, title="Distribuce NDVI validnich pixelu",
        )
        fig.add_vline(x=s.mean, line_dash="dash", line_color="black",
                      annotation_text=f"mean={s.mean:.3f}")
        fig.add_vline(x=0.5, line_dash="dot", line_color="green",
                      annotation_text="zdrave")
        fig.add_vline(x=0.2, line_dash="dot", line_color="orange",
                      annotation_text="stres")
        st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.markdown(
            "Sestava 6 indexu pro Survey 3N (vyzaduji jen Red + NIR pasma). "
            "Kazdy index osvetluje jiny aspekt fyziologie a struktury porostu."
        )

        # Souhrnna tabulka vsech indexu
        rows = []
        for code, info in INDICES.items():
            st_i = result.index_stats[code]
            ii = index_interps[code]
            rows.append({
                "Index":       code,
                "Mean":        f"{st_i.mean:.3f}",
                "Median":      f"{st_i.median:.3f}",
                "σ":           f"{st_i.std:.3f}",
                "P10–P90":     f"{st_i.p10:.2f} – {st_i.p90:.2f}",
                "Zdrave (%)":  f"{st_i.fraction_healthy*100:.1f}",
                "Verdikt":     ii.verdict,
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     use_container_width=True)

        st.markdown("---")
        # Per-index detail s heatmapou a biologickou interpretaci
        for code, info in INDICES.items():
            st_i = result.index_stats[code]
            ii = index_interps[code]
            with st.expander(
                f"**{code}** — {info.name_cs}  (mean = {st_i.mean:.3f}, "
                f"verdikt: {ii.verdict})",
                expanded=(code == "NDVI"),
            ):
                colA, colB = st.columns([1, 1])
                with colA:
                    arr = result.index_arrays[code]
                    heat = index_to_rgb(arr, info)
                    st.image(heat, caption=f"{code} heatmapa",
                             use_container_width=True)
                    st.caption(f"**Formula:** `{info.formula}`")
                    st.caption(f"**Rozsah indexu:** "
                               f"{info.typical_range[0]:.2f} az "
                               f"{info.typical_range[1]:.2f}. "
                               f"Prah zdravi: {info.healthy_min:.2f}.")
                with colB:
                    st.markdown("**Biologicky vyznam**")
                    st.write(info.biology)
                    st.markdown("**Fyziologicky kontext**")
                    st.write(info.physiology)
                    st.markdown("**V lesnim biotopu**")
                    st.write(info.forest_context)

                st.markdown("---")
                st.markdown("**Interpretace tohoto snimku**")
                st.success(ii.biological_meaning) if ii.color == "#2e7d32" else (
                    st.warning(ii.biological_meaning) if ii.color == "#f9a825"
                    else st.error(ii.biological_meaning)
                )
                if info.caveats:
                    st.caption(f"**Omezeni:** {info.caveats}")
                if ii.flags:
                    st.caption("Flagy: " + ", ".join(ii.flags))

    with tab4:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Statistiky NDVI**")
            st.dataframe(pd.DataFrame({
                "metrika": ["mean", "median", "std", "p10", "p25", "p75", "p90",
                            "pixel_count"],
                "hodnota": [s.mean, s.median, s.std, s.p10, s.p25, s.p75, s.p90,
                            s.pixel_count],
            }), hide_index=True, use_container_width=True)
        with col2:
            st.markdown("**Frakce pixelu**")
            st.dataframe(pd.DataFrame({
                "tridka": ["vegetated (>0.2)", "healthy (>0.5)",
                          "stressed (0.2-0.4)", "bare/dead (<0.2)"],
                "%": [s.fraction_vegetated*100, s.fraction_healthy*100,
                      s.fraction_stressed*100, s.fraction_bare_or_dead*100],
            }), hide_index=True, use_container_width=True)

    st.markdown("### Doporuceni")
    if interp.recommendations:
        for r in interp.recommendations:
            st.markdown(f"- {r}")
    else:
        st.markdown("- Zadna doporuceni — vse v poradku.")

    st.markdown("---")
    col_back, col_fwd = st.columns(2)
    with col_back:
        if st.button("← Zpet na kalibraci"):
            st.session_state.step = 3
            st.rerun()
    with col_fwd:
        if st.button("Pokracovat na report →", type="primary"):
            st.session_state.step = 5
            st.rerun()


# ==================================================================== STEP 5

elif st.session_state.step == 5:
    st.subheader("Krok 5 — Report a export")

    if st.session_state.analysis is None:
        st.error("Chybi vysledky analyzy.")
        st.stop()

    md = st.session_state.metadata
    img_bgr = st.session_state.uploaded_image
    cal = st.session_state.calibration
    result = st.session_state.analysis["result"]
    interp = st.session_state.analysis["interpretation"]
    index_interps = st.session_state.analysis.get("index_interpretations", {})

    meta_for_report = {
        "soubor": md.get("soubor", ""),
        "datum": md.get("datum", ""),
        "cas": md.get("cas", ""),
        "typ_porostu": VEG_PROFILES[md["typ_porostu"]]["name"],
        "meteo": md.get("meteo", ""),
        "vyska_kamery_m": md.get("vyska_kamery_m", ""),
        "uhel_kamery_deg": md.get("uhel_kamery_deg", ""),
        "horizont_m": md.get("horizont_m", ""),
        "tercik_pritomen": md.get("tercik_pritomen", ""),
        "vzdalenost_tercku_m": md.get("vzdalenost_tercku_m", ""),
        "poznamky": md.get("poznamky", ""),
    }

    # Heatmapy vsech indexu pro report (vc. NDVI)
    index_heatmaps = {
        code: index_to_rgb(result.index_arrays[code], INDICES[code])
        for code in INDICES
    }

    html = build_html_report(
        metadata=meta_for_report,
        ndvi_result=result,
        interpretation=interp,
        calibration=cal,
        original_image_rgb=bgr_to_rgb(img_bgr),
        ndvi_heatmap_rgb=ndvi_to_rgb(result.ndvi),
        index_interpretations=index_interps,
        index_heatmaps=index_heatmaps,
    )
    csv = build_csv_summary(meta_for_report, result, interp)

    stem = Path(md.get("soubor", "snimek")).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            "⬇️ Stahnout HTML report",
            data=html.encode("utf-8"),
            file_name=f"NDVI_report_{stem}_{timestamp}.html",
            mime="text/html",
            use_container_width=True,
            type="primary",
        )
    with col2:
        st.download_button(
            "⬇️ Stahnout CSV souhrn",
            data=csv.encode("utf-8"),
            file_name=f"NDVI_summary_{stem}_{timestamp}.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col3:
        # NDVI raster jako 8-bit PNG (mapovany na 0-255 z [-1..+1])
        ndvi_norm = ((np.nan_to_num(result.ndvi, nan=-1.0) + 1) * 127.5).astype(np.uint8)
        pil_img = Image.fromarray(ndvi_norm)
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        st.download_button(
            "⬇️ NDVI raster (PNG)",
            data=buf.getvalue(),
            file_name=f"NDVI_raster_{stem}_{timestamp}.png",
            mime="image/png",
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown("### Nahled HTML reportu")
    st.components.v1.html(html, height=900, scrolling=True)

    if st.button("← Zpet na vysledky"):
        st.session_state.step = 4
        st.rerun()
