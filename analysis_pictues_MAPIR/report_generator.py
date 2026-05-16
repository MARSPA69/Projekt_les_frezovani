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
from ndvi_processor import NDVIResult


def _img_to_b64(arr: np.ndarray) -> str:
    """Konverze numpy HxWx3 uint8 na base64 PNG."""
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
