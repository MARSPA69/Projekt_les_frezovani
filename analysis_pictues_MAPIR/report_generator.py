"""
Generator HTML reportu z analyzy NDVI snimku MAPIR Survey 3N.

Vystup: jeden self-contained HTML soubor s vlozenymi obrazky (base64).
"""

from __future__ import annotations

import base64
import io
from dataclasses import asdict
from datetime import datetime
from html import escape
from typing import Any

import numpy as np
from PIL import Image

from calibration import CalibrationBundle
from indices import INDICES
from interpretation import IndexInterpretation, Interpretation
from ndvi_processor import NDVI_COLOR_LEGEND, NDVIResult


def _downscale(arr: np.ndarray, max_w: int = 1600) -> np.ndarray:
    """Zmensi obrazek na max sirku (kvuli velikosti reportu). Print kvalita
    ~1600 px bohate staci; plne 4000 px by nafouklo report na desitky MB."""
    from PIL import Image as _PImage
    h, w = arr.shape[:2]
    if w <= max_w:
        return arr
    new_h = int(round(h * max_w / w))
    img = _PImage.fromarray(arr.astype(np.uint8)).resize(
        (max_w, new_h), _PImage.LANCZOS)
    return np.asarray(img)


def _img_to_b64(arr: np.ndarray) -> str:
    """Konverze numpy HxWx3 uint8 na base64 PNG (zmenseno kvuli velikosti)."""
    arr = _downscale(arr)
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _pil_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _build_indices_section(ndvi_result: NDVIResult,
                            index_interpretations: dict[str, IndexInterpretation],
                            index_heatmaps: dict[str, np.ndarray]) -> str:
    """HTML sekce s tabulkou indexu a per-index biologickou interpretaci."""
    if not index_interpretations:
        return ""

    # Souhrnna tabulka
    table_rows = []
    for code in INDICES:
        if code not in ndvi_result.index_stats:
            continue
        info = INDICES[code]
        st_i = ndvi_result.index_stats[code]
        ii = index_interpretations[code]
        table_rows.append(
            f"<tr>"
            f"<td><strong>{escape(code)}</strong><br>"
            f"<small style='color:#5f6368'>{escape(info.name_cs)}</small></td>"
            f"<td>{st_i.mean:.3f}</td>"
            f"<td>{st_i.median:.3f}</td>"
            f"<td>{st_i.std:.3f}</td>"
            f"<td>{st_i.fraction_healthy*100:.1f} %</td>"
            f"<td><span class='verdict-pill' style='background:{ii.color}'>"
            f"{escape(ii.verdict)}</span></td>"
            f"</tr>"
        )
    table_html = "\n".join(table_rows)

    # Per-index detailed bloky
    detail_blocks = []
    for code in INDICES:
        if code not in ndvi_result.index_stats:
            continue
        info = INDICES[code]
        st_i = ndvi_result.index_stats[code]
        ii = index_interpretations[code]
        heat_b64 = _img_to_b64(index_heatmaps[code]) if code in index_heatmaps else ""

        flags_html = " ".join(
            f"<span class='flag'>{escape(f)}</span>" for f in ii.flags
        )

        detail_blocks.append(f"""
        <div class="index-block">
          <div class="index-header" style="border-left-color:{ii.color}">
            <div>
              <h3>{escape(code)} — {escape(info.name_cs)}</h3>
              <div class="formula"><code>{escape(info.formula)}</code></div>
            </div>
            <div class="index-verdict">
              <div class="value">{st_i.mean:.3f}</div>
              <div class="verdict-pill" style="background:{ii.color}">
                {escape(ii.verdict)}
              </div>
            </div>
          </div>
          <div class="index-body">
            <div class="index-image">
              {f'<img src="data:image/png;base64,{heat_b64}" alt="{code}">'
               if heat_b64 else ''}
            </div>
            <div class="index-text">
              <h4>Biologicky vyznam</h4>
              <p>{escape(info.biology)}</p>
              <h4>Fyziologicky kontext</h4>
              <p>{escape(info.physiology)}</p>
              <h4>V lesnim biotopu</h4>
              <p>{escape(info.forest_context)}</p>
              <h4>Interpretace tohoto snimku</h4>
              <p class="interpretation" style="border-left-color:{ii.color}">
                {escape(ii.biological_meaning)}
              </p>
              <p class="forest-specific">{escape(ii.forest_specific)}</p>
              <p class="caveats"><strong>Omezeni indexu:</strong>
                 {escape(info.caveats)}</p>
              <p class="higher-means"><strong>Vyssi hodnota znamena:</strong>
                 {escape(info.higher_means)}</p>
              {f'<div class="flags-row">{flags_html}</div>' if flags_html else ''}
            </div>
          </div>
        </div>
        """)

    return f"""
    <h2>Vegetacni indexy — souhrnna tabulka</h2>
    <table class="indices-table">
      <thead>
        <tr><th>Index</th><th>Mean</th><th>Median</th><th>σ</th>
            <th>Zdrave %</th><th>Verdikt</th></tr>
      </thead>
      <tbody>{table_html}</tbody>
    </table>

    <h2>Per-index biologicka a fyziologicka interpretace</h2>
    {"".join(detail_blocks)}
    """


def build_html_report(metadata: dict[str, Any],
                      ndvi_result: NDVIResult,
                      interpretation: Interpretation,
                      calibration: CalibrationBundle,
                      original_image_rgb: np.ndarray,
                      ndvi_heatmap_rgb: np.ndarray,
                      index_interpretations: dict[str, IndexInterpretation] | None = None,
                      index_heatmaps: dict[str, np.ndarray] | None = None,
                      ) -> str:
    """Vrati kompletni HTML report jako string."""
    stats = ndvi_result.stats
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    img_orig_b64 = _img_to_b64(original_image_rgb)
    img_ndvi_b64 = _img_to_b64(ndvi_heatmap_rgb)

    indices_section = _build_indices_section(
        ndvi_result,
        index_interpretations or {},
        index_heatmaps or {},
    )

    # Metadata tabulka
    meta_rows = "\n".join(
        f"<tr><td>{escape(str(k))}</td><td>{escape(str(v))}</td></tr>"
        for k, v in metadata.items()
    )

    # Kalibrace
    cal_rows = ""
    if calibration.target_detected:
        cal_rows = f"""
        <tr><td>NIR gain</td><td>{calibration.nir.gain:.6f}</td></tr>
        <tr><td>NIR offset</td><td>{calibration.nir.offset:.4f}</td></tr>
        <tr><td>NIR R²</td><td>{calibration.nir.r_squared:.4f}</td></tr>
        <tr><td>Red gain</td><td>{calibration.red.gain:.6f}</td></tr>
        <tr><td>Red offset</td><td>{calibration.red.offset:.4f}</td></tr>
        <tr><td>Red R²</td><td>{calibration.red.r_squared:.4f}</td></tr>
        """
    else:
        cal_rows = (
            "<tr><td colspan='2'><em>Tercik nedetekovan - fallback DN/255</em></td></tr>"
        )

    # Doporuceni
    recs_html = "".join(
        f"<li>{escape(r)}</li>" for r in interpretation.recommendations
    ) or "<li><em>Zadna doporuceni - vse v poradku.</em></li>"

    warnings_html = "".join(
        f"<li>{escape(w)}</li>"
        for w in (ndvi_result.warnings + calibration.warnings)
    )
    warnings_block = (
        f"<div class='warnings'><h3>Upozorneni</h3><ul>{warnings_html}</ul></div>"
        if warnings_html else ""
    )

    flags_html = " ".join(
        f"<span class='flag'>{escape(f)}</span>"
        for f in interpretation.flags
    )

    html = f"""<!doctype html>
<html lang="cs">
<head>
<meta charset="utf-8">
<title>MAPIR NIR analyza - {escape(metadata.get('datum', timestamp))}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
         margin: 0; padding: 32px; background: #f5f7fa; color: #1a1a1a; }}
  .container {{ max-width: 1080px; margin: 0 auto; background: #fff;
                padding: 32px; border-radius: 12px;
                box-shadow: 0 2px 12px rgba(0,0,0,0.06); }}
  h1 {{ margin: 0 0 4px 0; font-size: 28px; }}
  .subtitle {{ color: #5f6368; margin-bottom: 24px; }}
  .verdict {{ display: inline-block; padding: 12px 24px;
              border-radius: 8px; color: #fff; font-weight: 600;
              font-size: 20px; background: {interpretation.color_code};
              margin: 12px 0 24px 0; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
  .card {{ background: #fafbfc; border: 1px solid #e8eaed;
           border-radius: 8px; padding: 16px; }}
  .card h3 {{ margin-top: 0; color: #202124; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #ecedef; }}
  td:first-child {{ color: #5f6368; width: 40%; }}
  img {{ width: 100%; border-radius: 6px; }}
  ul {{ padding-left: 20px; }}
  .flag {{ display: inline-block; padding: 2px 10px; margin: 2px;
           background: #fff3cd; color: #7d6608; border-radius: 12px;
           font-size: 12px; font-weight: 600; }}
  .warnings {{ background: #fdf2e9; border-left: 4px solid #e67e22;
               padding: 12px 18px; border-radius: 6px; margin: 16px 0; }}
  .stat-big {{ font-size: 32px; font-weight: 700; color: #202124; }}
  .stat-label {{ color: #5f6368; font-size: 13px; text-transform: uppercase; }}
  .stats-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
                margin: 16px 0; }}
  .stat-box {{ background: #f1f3f4; padding: 14px; border-radius: 8px; text-align: center; }}
  h2 {{ margin-top: 40px; color: #1b5e20; border-bottom: 2px solid #c8e6c9;
        padding-bottom: 6px; }}
  .indices-table {{ width: 100%; border-collapse: collapse; margin: 16px 0; }}
  .indices-table th {{ background: #f1f8f4; padding: 10px; text-align: left;
                       border-bottom: 2px solid #2e7d32; }}
  .indices-table td {{ padding: 10px; border-bottom: 1px solid #ecedef; }}
  .verdict-pill {{ display: inline-block; padding: 4px 10px; border-radius: 12px;
                   color: white; font-weight: 600; font-size: 12px; }}
  .index-block {{ background: #fafbfc; border-radius: 10px; padding: 18px;
                  margin: 20px 0; border: 1px solid #e8eaed; }}
  .index-header {{ display: flex; justify-content: space-between;
                   align-items: flex-start; border-left: 5px solid #2e7d32;
                   padding-left: 14px; margin-bottom: 14px; }}
  .index-header h3 {{ margin: 0; color: #1b5e20; }}
  .index-header .formula {{ font-family: monospace; color: #5f6368;
                            font-size: 13px; margin-top: 4px; }}
  .index-verdict .value {{ font-size: 28px; font-weight: 700; color: #202124;
                           text-align: right; }}
  .index-body {{ display: grid; grid-template-columns: 1fr 2fr; gap: 18px; }}
  .index-body h4 {{ margin: 12px 0 6px 0; color: #2e7d32; font-size: 14px;
                    text-transform: uppercase; letter-spacing: 0.4px; }}
  .index-body p {{ margin: 0 0 8px 0; font-size: 14px; line-height: 1.5; }}
  .interpretation {{ padding: 10px 14px; background: #fff;
                     border-left: 4px solid; border-radius: 4px; }}
  .forest-specific {{ font-style: italic; color: #444; }}
  .caveats {{ font-size: 13px; color: #7d6608; background: #fff8e1;
              padding: 8px 12px; border-radius: 4px; }}
  .higher-means {{ font-size: 13px; color: #1b5e20; background: #e8f5e9;
                   padding: 8px 12px; border-radius: 4px; }}
  .flags-row {{ margin-top: 8px; }}
  .cross-val {{ background: #e3f2fd; border-left: 4px solid #1976d2;
                padding: 12px 16px; border-radius: 6px; margin: 12px 0; }}
  footer {{ margin-top: 32px; color: #80868b; font-size: 12px; text-align: center; }}
</style>
</head>
<body>
<div class="container">
  <h1>MAPIR Survey 3N - Analyza fotosynteticke aktivity</h1>
  <div class="subtitle">Vygenerovano: {timestamp} | Projekt Alcedo Frezovani</div>

  <div class="verdict">{escape(interpretation.overall_verdict)}</div>
  {f'<div>{flags_html}</div>' if flags_html else ''}

  <div class="stats-row">
    <div class="stat-box">
      <div class="stat-big">{stats.mean:.3f}</div>
      <div class="stat-label">Mean NDVI</div>
    </div>
    <div class="stat-box">
      <div class="stat-big">{stats.median:.3f}</div>
      <div class="stat-label">Median</div>
    </div>
    <div class="stat-box">
      <div class="stat-big">{stats.fraction_healthy*100:.0f}%</div>
      <div class="stat-label">Zdrave (&gt;0.5)</div>
    </div>
    <div class="stat-box">
      <div class="stat-big">{stats.fraction_stressed*100:.0f}%</div>
      <div class="stat-label">Stres (0.2-0.4)</div>
    </div>
  </div>

  <h3>Souhrn</h3>
  <p>{escape(interpretation.summary)}</p>
  <p><strong>Sezonni kontext:</strong> {escape(interpretation.observed_vs_expected)}</p>
  <div class="cross-val">
    <strong>Cross-validace vegetacnich indexu:</strong>
    {escape(interpretation.cross_validation)}
  </div>
  <p><strong>Kvalita:</strong> {escape(interpretation.quality_assessment)}</p>

  {warnings_block}

  <div class="grid">
    <div class="card">
      <h3>Puvodni snimek (RGB pseudobarvy)</h3>
      <img src="data:image/png;base64,{img_orig_b64}" alt="original">
    </div>
    <div class="card">
      <h3>NDVI heatmapa (RdYlGn)</h3>
      <img src="data:image/png;base64,{img_ndvi_b64}" alt="ndvi">
    </div>
  </div>

  <div class="grid" style="margin-top: 24px;">
    <div class="card">
      <h3>Metadata snimku</h3>
      <table>{meta_rows}</table>
    </div>
    <div class="card">
      <h3>Kalibrace</h3>
      <table>{cal_rows}</table>
    </div>
  </div>

  {indices_section}

  <h3>Doporuceni</h3>
  <ul>{recs_html}</ul>

  <footer>
    MAPIR Survey 3N NIR Analyser | CRA s.r.o. - Alcedo Frezovani | Rumburk<br>
    Survey 3N mapping: R kanal = NIR (850 nm), B kanal = Red (661 nm)<br>
    Vegetacni indexy podle MAPIR documentation a referenci uvedenych v
    Multispectral Index Formulas.
  </footer>
</div>
</body>
</html>"""
    return html


# =========================================================================
# PDF report (reportlab) - sjednoceny vystup vc. vizualizace RAW -> PNG
# =========================================================================

def _register_pdf_font() -> tuple[str, str]:
    """
    Zaregistruje Unicode font (DejaVuSans z matplotlibu) pro spravne
    zobrazeni ceskych znaku v PDF. Vraci (regular, bold) nazvy fontu.
    Fallback na Helvetica, pokud DejaVu neni k dispozici.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    try:
        import os
        import matplotlib
        base = os.path.join(os.path.dirname(matplotlib.__file__),
                            "mpl-data", "fonts", "ttf")
        reg = os.path.join(base, "DejaVuSans.ttf")
        bold = os.path.join(base, "DejaVuSans-Bold.ttf")
        if os.path.exists(reg) and "DejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVu", reg))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
        if os.path.exists(reg):
            return "DejaVu", "DejaVu-Bold"
    except Exception:
        pass
    return "Helvetica", "Helvetica-Bold"


def _np_to_rl_image(arr: np.ndarray, width_mm: float):
    """Konvertuje numpy RGB uint8 na reportlab Image o dane sirce (mm),
    vyska dopoctena podle pomeru stran."""
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage

    arr = _downscale(arr, max_w=1400)
    if arr.dtype != np.uint8:
        arr = arr.astype(np.uint8)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    h, w = arr.shape[:2]
    width = width_mm * mm
    height = width * (h / w)
    return RLImage(buf, width=width, height=height)


def build_pdf_report(metadata: dict[str, Any],
                     ndvi_result: NDVIResult,
                     interpretation: Interpretation,
                     calibration: CalibrationBundle,
                     raw_png_rgb: np.ndarray,
                     ndvi_heatmap_rgb: np.ndarray,
                     index_interpretations: dict[str, IndexInterpretation] | None = None,
                     index_heatmaps: dict[str, np.ndarray] | None = None,
                     raw_meta: Any = None,
                     ) -> bytes:
    """
    Sestavi sjednoceny PDF report a vrati ho jako bytes.

    Obsahuje:
        - hlavicku, den/noc + platnost NDVI, verdikt, souhrnne statistiky,
        - VIZUALIZACNI SEKCI: RAW prevedeny do PNG (false-color NIR) vedle
          NDVI heatmapy - jasne kontrasty a barevne odchylky,
        - souhrn + sezonni kontext + cross-validaci + kvalitu,
        - tabulku 6 vegetacnich indexu vc. jejich heatmap,
        - metadata + kalibraci, doporuceni a upozorneni.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )

    font, font_b = _register_pdf_font()
    stats = ndvi_result.stats
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def hx(c: str):
        return colors.HexColor(c) if c and c.startswith("#") else colors.HexColor("#2e7d32")

    # --- styly ---
    body = ParagraphStyle("body", fontName=font, fontSize=9.5, leading=13)
    small = ParagraphStyle("small", fontName=font, fontSize=8, leading=11,
                           textColor=colors.HexColor("#5f6368"))
    h1 = ParagraphStyle("h1", fontName=font_b, fontSize=18, leading=22,
                        textColor=colors.HexColor("#1b5e20"), spaceAfter=2)
    h2 = ParagraphStyle("h2", fontName=font_b, fontSize=13, leading=17,
                        textColor=colors.HexColor("#1b5e20"), spaceBefore=14,
                        spaceAfter=6)
    label = ParagraphStyle("label", fontName=font, fontSize=7.5, leading=9,
                           textColor=colors.HexColor("#5f6368"),
                           alignment=1)
    bignum = ParagraphStyle("bignum", fontName=font_b, fontSize=17, leading=19,
                            alignment=1, textColor=colors.HexColor("#202124"))

    story: list = []

    # --- hlavicka ---
    story.append(Paragraph("MAPIR Survey 3N — analyza fotosynteticke aktivity", h1))
    story.append(Paragraph(
        f"Vygenerovano: {timestamp} &nbsp;|&nbsp; Projekt Alcedo Frezovani", small))
    story.append(Spacer(1, 6))

    # --- den/noc + platnost NDVI ---
    is_night = bool(getattr(raw_meta, "is_night", False))
    if is_night:
        banner_bg, banner_txt = "#5c3d99", "NOCNI SNIMEK — NDVI NEPLATNE"
    else:
        banner_bg, banner_txt = "#2e7d32", "DENNI SNIMEK — NDVI platne"
    note = getattr(raw_meta, "note", "")
    banner = Table([[Paragraph(f"<b>{banner_txt}</b>", ParagraphStyle(
        "bn", fontName=font_b, fontSize=11, textColor=colors.white))],
        [Paragraph(escape(note), ParagraphStyle(
            "bn2", fontName=font, fontSize=8.5, textColor=colors.white))]]
        if note else [[Paragraph(f"<b>{banner_txt}</b>", ParagraphStyle(
            "bn", fontName=font_b, fontSize=11, textColor=colors.white))]],
        colWidths=[174 * mm])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(banner_bg)),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(banner)
    story.append(Spacer(1, 8))

    # --- verdikt ---
    # U nocniho snimku je NDVI neplatne, takze nezobrazujeme zavadejici
    # verdikt "ZDRAVA" - prepiseme na jasne NEPLATNE.
    if is_night:
        verdict_text = "NDVI NEPLATNE — nocni snimek (bez osvetleneho Red pasma)"
        verdict_bg = colors.HexColor("#5c3d99")
    else:
        verdict_text = interpretation.overall_verdict
        verdict_bg = hx(interpretation.color_code)
    verdict = Table([[Paragraph(
        f"<b>{escape(verdict_text)}</b>",
        ParagraphStyle("v", fontName=font_b, fontSize=13, textColor=colors.white))]],
        colWidths=[174 * mm])
    verdict.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), verdict_bg),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(verdict)
    story.append(Spacer(1, 8))

    # --- statistiky ---
    def stat_cell(val, lab):
        return [Paragraph(val, bignum), Paragraph(lab, label)]
    stat_tbl = Table([[
        stat_cell(f"{stats.mean:.3f}", "Mean NDVI"),
        stat_cell(f"{stats.median:.3f}", "Median"),
        stat_cell(f"{stats.fraction_healthy*100:.0f}%", "Zdrave (>0.5)"),
        stat_cell(f"{stats.fraction_stressed*100:.0f}%", "Stres (0.2-0.4)"),
    ]], colWidths=[43.5 * mm] * 4)
    stat_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f3f4")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(stat_tbl)
    if is_night:
        story.append(Spacer(1, 3))
        story.append(Paragraph(
            "Pozor: hodnoty vyse jsou u nocniho snimku NEPLATNE "
            "(Red pasmo neni osvetleno, NDVI se falesne blizi 1.0).",
            ParagraphStyle("nightnote", fontName=font, fontSize=8,
                           textColor=colors.HexColor("#5c3d99"))))

    # --- VIZUALIZACE: RAW->PNG + NDVI heatmapa ---
    story.append(Paragraph("Vizualizace — RAW snimek a NDVI", h2))
    story.append(Paragraph(
        "Vlevo: RAW prevedeny do PNG (false-color NIR, R=NIR kanal) — "
        "kontrasty vegetace vs. konstrukce. Vpravo: NDVI heatmapa "
        "(cervena = bez vegetace, zelena = zdrava vegetace).", small))
    story.append(Spacer(1, 4))
    viz = Table([[
        _np_to_rl_image(raw_png_rgb, 85),
        _np_to_rl_image(ndvi_heatmap_rgb, 85),
    ]], colWidths=[87 * mm, 87 * mm])
    viz.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 4),
    ]))
    story.append(viz)

    # --- legenda barev NDVI heatmapy ---
    story.append(Spacer(1, 6))
    story.append(Paragraph("Legenda barev NDVI heatmapy", ParagraphStyle(
        "legh", fontName=font_b, fontSize=10,
        textColor=colors.HexColor("#1b5e20"), spaceAfter=3)))
    leg_meaning_style = ParagraphStyle(
        "legm", fontName=font, fontSize=8, leading=10)
    leg_data = []
    for hexc, rng, meaning in NDVI_COLOR_LEGEND:
        leg_data.append(["", f"NDVI {rng}",
                         Paragraph(escape(meaning), leg_meaning_style)])
    leg_tbl = Table(leg_data, colWidths=[8 * mm, 24 * mm, 140 * mm])
    leg_style = [
        ("FONTNAME", (1, 0), (-1, -1), font),
        ("FONTNAME", (1, 0), (1, -1), font_b),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (2, 0), (2, -1), 8),
        ("LINEBELOW", (1, 0), (-1, -1), 0.3, colors.HexColor("#ecedef")),
    ]
    # barevny ctverecek v prvnim sloupci
    for i, (hexc, _rng, _m) in enumerate(NDVI_COLOR_LEGEND):
        leg_style.append(("BACKGROUND", (0, i), (0, i), colors.HexColor(hexc)))
    leg_tbl.setStyle(TableStyle(leg_style))
    story.append(leg_tbl)

    # --- souhrn ---
    story.append(Paragraph("Souhrn a interpretace", h2))
    story.append(Paragraph(escape(interpretation.summary), body))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"<b>Sezonni kontext:</b> {escape(interpretation.observed_vs_expected)}", body))
    story.append(Paragraph(
        f"<b>Cross-validace indexu:</b> {escape(interpretation.cross_validation)}", body))
    story.append(Paragraph(
        f"<b>Kvalita:</b> {escape(interpretation.quality_assessment)}", body))

    # --- upozorneni ---
    warns = list(ndvi_result.warnings) + list(calibration.warnings)
    if warns:
        story.append(Paragraph("Upozorneni", h2))
        for w in warns:
            story.append(Paragraph(f"• {escape(w)}", body))

    # --- tabulka indexu ---
    if index_interpretations:
        story.append(Paragraph("Vegetacni indexy — souhrn", h2))
        head = ["Index", "Mean", "Median", "σ", "Zdrave %", "Verdikt"]
        data = [head]
        for code in INDICES:
            if code not in ndvi_result.index_stats:
                continue
            st_i = ndvi_result.index_stats[code]
            ii = index_interpretations.get(code)
            data.append([
                code, f"{st_i.mean:.3f}", f"{st_i.median:.3f}",
                f"{st_i.std:.3f}", f"{st_i.fraction_healthy*100:.1f}",
                ii.verdict if ii else "",
            ])
        idx_tbl = Table(data, colWidths=[24*mm, 24*mm, 24*mm, 24*mm, 26*mm, 52*mm])
        idx_tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTNAME", (0, 0), (-1, 0), font_b),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f5e9")),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#2e7d32")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#ecedef")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(idx_tbl)

    # --- metadata + kalibrace ---
    story.append(Paragraph("Metadata a kalibrace", h2))
    meta_pairs = [[escape(str(k)), escape(str(v))] for k, v in metadata.items()]
    if calibration.target_detected:
        cal_info = (f"tercik detekovan ({calibration.detection_method}); "
                    f"NIR gain={calibration.nir.gain:.5f}, "
                    f"Red gain={calibration.red.gain:.5f}")
    else:
        cal_info = "tercik nedetekovan — fallback DN/255 (NDVI indikativni)"
    meta_pairs.append(["kalibrace", escape(cal_info)])
    meta_tbl = Table(meta_pairs, colWidths=[52 * mm, 122 * mm])
    meta_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#5f6368")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#ecedef")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta_tbl)

    # --- doporuceni ---
    story.append(Paragraph("Doporuceni", h2))
    recs = interpretation.recommendations or ["Zadna doporuceni — vse v poradku."]
    for r in recs:
        story.append(Paragraph(f"• {escape(r)}", body))

    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=0.5,
                            color=colors.HexColor("#c8e6c9")))
    story.append(Paragraph(
        "MAPIR Survey 3N NIR Analyser | CRA s.r.o. — Alcedo Frezovani | Rumburk<br/>"
        "Zdroj dat: RAW (sude sloupce = NIR 850 nm, liche = Red 660 nm). "
        "JPG z MAPIRu ma slite kanaly a pro NDVI je nepouzitelny.", small))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="MAPIR NIR analyza",
    )
    doc.build(story)
    return buf.getvalue()


def build_csv_summary(metadata: dict[str, Any],
                      ndvi_result: NDVIResult,
                      interpretation: Interpretation) -> str:
    """One-row CSV pro pripadne pridani do archivu casovych rad."""
    s = ndvi_result.stats
    cols = [
        ("datum",                metadata.get("datum", "")),
        ("cas",                  metadata.get("cas", "")),
        ("typ_porostu",          metadata.get("typ_porostu", "")),
        ("meteo",                metadata.get("meteo", "")),
        ("vyska_kamery_m",       metadata.get("vyska_kamery_m", "")),
        ("uhel_kamery_deg",      metadata.get("uhel_kamery_deg", "")),
        ("horizont_m",           metadata.get("horizont_m", "")),
        ("vzdalenost_tercku_m",  metadata.get("vzdalenost_tercku_m", "")),
        ("tercik_pritomen",      metadata.get("tercik_pritomen", "")),
        ("ndvi_mean",            f"{s.mean:.4f}"),
        ("ndvi_median",          f"{s.median:.4f}"),
        ("ndvi_std",             f"{s.std:.4f}"),
        ("ndvi_p10",             f"{s.p10:.4f}"),
        ("ndvi_p90",             f"{s.p90:.4f}"),
        ("frac_healthy",         f"{s.fraction_healthy:.4f}"),
        ("frac_stressed",        f"{s.fraction_stressed:.4f}"),
        ("frac_bare",            f"{s.fraction_bare_or_dead:.4f}"),
        ("verdikt",              interpretation.overall_verdict),
        ("flags",                "|".join(interpretation.flags)),
    ]
    # Pridej mean hodnoty vsech dalsich indexu (NDVI uz zahrnuto vyse)
    for code, st_i in ndvi_result.index_stats.items():
        if code == "NDVI":
            continue
        cols.append((f"{code.lower()}_mean",   f"{st_i.mean:.4f}"))
        cols.append((f"{code.lower()}_median", f"{st_i.median:.4f}"))
        cols.append((f"{code.lower()}_std",    f"{st_i.std:.4f}"))
    header = ",".join(c[0] for c in cols)
    row = ",".join(f'"{c[1]}"' for c in cols)
    return f"{header}\n{row}\n"
