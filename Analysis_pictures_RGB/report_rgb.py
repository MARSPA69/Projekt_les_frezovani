"""
PDF report k RGB casosberu: technicky protokol + fenologicka krivka GCC/ExG.

STRUKTURA REPORTU:
    1. Prehled zpracovani (obdobi, pocty snimku, nocni rez, vypadky)
    2. Fenologicka krivka GCC + ExG s vyhlazenim
    3. Sezonni ukazatele (min/max/vrchol/trend)
    4. Srovnani lokalit, pokud jsou zpracovane obe
    5. Metodicka poznamka a vyhrady

VYHRADY, KTERE REPORT VZDY NESE:
    Srovnani ploch F2022 a NF2022 neni cisty efekt frezovani - plochy lezi
    v odlisnych geologickych skupinach (Ca vs. Ka) a jsou od sebe ~2,5 km.
    Prevzato ze zpravy "Analyza senzorickych dat z 21082026 - projekt LES".
    Krome toho jsou GCC hodnoty dvou RUZNYCH kamer srovnatelne jen v TRENDU,
    ne v absolutni urovni (jiny senzor, jine nastaveni expozice, jina scena).
"""

from __future__ import annotations

import datetime as dt
import io
import os
from dataclasses import dataclass

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from phenology import SeasonMetrics, smooth

ACCENT = colors.HexColor("#2E6B4F")
GRID = colors.HexColor("#D8D8D8")

GEOLOGY_CAVEAT = (
    "Srovnání ploch Frézovaný 2022 a Nefrézovaný 2022 <b>není čistým efektem "
    "frézování</b>. Podle zprávy „Analýza senzorických dat z 21082026 – projekt LES“ "
    "leží F2022 v geologické skupině Ca, zatímco NF2022 ve skupině Ka zhruba 2,5 km "
    "daleko, s odlišným (grusovějším a drenážnějším) podložím. Rozdíl mezi plochami "
    "proto spojuje vliv zásahu s vlivem stanoviště."
)

CAMERA_CAVEAT = (
    "Absolutní hodnoty GCC ze dvou různých kamer nejsou přímo srovnatelné – liší se "
    "senzor, automatická expozice, výřez a podíl oblohy ve scéně. Srovnávat lze "
    "<b>tvar a trend</b> křivky, nikoli absolutní úroveň."
)


def _register_font() -> tuple[str, str]:
    """Unicode font pro ceskou diakritiku; stejny postup jako v MAPIR aplikaci."""
    try:
        base = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf")
        regular = os.path.join(base, "DejaVuSans.ttf")
        bold = os.path.join(base, "DejaVuSans-Bold.ttf")
        if os.path.exists(regular) and "DejaVu" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("DejaVu", regular))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold))
        if os.path.exists(regular):
            return "DejaVu", "DejaVu-Bold"
    except Exception:
        pass
    return "Helvetica", "Helvetica-Bold"


@dataclass
class PlotReport:
    """Vsechna data jedne plochy potrebna pro report."""
    name: str
    source_dir: str
    total_captures: int
    kept: int
    dropped_night: int
    unreadable: int
    skipped_files: list[tuple[str, str]]
    interval_hours: float
    period_start: dt.datetime
    period_end: dt.datetime
    gaps: list[tuple[dt.datetime, dt.datetime, float]]
    daily: pd.DataFrame
    metrics: SeasonMetrics | None
    video_path: str
    video_fps: int
    night_start: dt.time
    night_end: dt.time


def _chart(figure) -> RLImage:
    """Vykresli matplotlib figuru do reportlab obrazku."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(figure)
    buffer.seek(0)
    return RLImage(buffer, width=165 * mm, height=165 * mm * figure.get_figheight()
                   / figure.get_figwidth())


def _greenness_chart(reports: list[PlotReport]):
    """Fenologicka krivka GCC a ExG pro vsechny plochy."""
    figure, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    palette = ["#2E6B4F", "#B4632A", "#3C6E9E"]

    for position, key, label in ((0, "gcc", "GCC (green chromatic coordinate)"),
                                 (1, "exg", "ExG (excess green)")):
        axis = axes[position]
        for index, report in enumerate(reports):
            if report.daily.empty:
                continue
            colour = palette[index % len(palette)]
            axis.plot(report.daily.index, report.daily[key], linewidth=0.7,
                      alpha=0.35, color=colour)
            axis.plot(report.daily.index, smooth(report.daily[key]), linewidth=2.0,
                      color=colour, label=report.name)
        axis.set_ylabel(label, fontsize=9)
        axis.grid(True, alpha=0.3, linestyle=":")
        axis.tick_params(labelsize=8)

    axes[0].legend(fontsize=8, loc="best")
    axes[0].set_title("Sezónní vývoj zelenosti porostu (denní 90. percentil, "
                      "tučně klouzavý medián 7 dní)", fontsize=10)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    axes[1].set_xlabel("2026", fontsize=9)
    figure.tight_layout()
    return figure


def _coverage_chart(report: PlotReport):
    """Mapa pokryti: kolik pouzitelnych snimku pripada na kazdy den."""
    figure, axis = plt.subplots(figsize=(9, 2.2))
    if not report.daily.empty:
        axis.bar(report.daily.index, report.daily["n_snimku"], width=1.0, color="#2E6B4F")
    axis.set_ylabel("snímků/den", fontsize=9)
    axis.set_title(f"Pokrytí záznamu – {report.name}", fontsize=10)
    axis.grid(True, alpha=0.3, axis="y", linestyle=":")
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    axis.tick_params(labelsize=8)
    figure.tight_layout()
    return figure


def _table(rows: list[list[str]], font: str, bold: str, widths=None) -> Table:
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, 1), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0EC")),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def build_report(reports: list[PlotReport], output_path: str) -> str:
    """Sestavi PDF report pro jednu nebo vice ploch a ulozi ho na `output_path`."""
    font, bold = _register_font()
    sheet = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=sheet["Normal"], fontName=font,
                          fontSize=9.5, leading=13.5, spaceAfter=5)
    heading = ParagraphStyle("heading", parent=sheet["Heading2"], fontName=bold,
                             fontSize=13, textColor=ACCENT, spaceBefore=12, spaceAfter=6)
    title = ParagraphStyle("title", parent=sheet["Title"], fontName=bold,
                           fontSize=18, textColor=ACCENT, spaceAfter=4)
    note = ParagraphStyle("note", parent=body, fontSize=8.5, leading=12,
                          textColor=colors.HexColor("#555555"))

    document = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="RGB časosběr – projekt LES", author="CRA s.r.o.",
    )

    story: list = [
        Paragraph("RGB časosběr – analýza porostu", title),
        Paragraph("Projekt „Vliv frézování půdy po těžbě dřeva na růst sazenic“ · "
                  "kamera Brinno TLC2000", note),
        Paragraph(f"Zpracováno {dt.date.today():%d. %m. %Y}", note),
        Spacer(1, 8),
    ]

    # --- 1. prehled zpracovani ---------------------------------------------
    story.append(Paragraph("1. Přehled zpracování", heading))
    rows = [["Plocha", "Období", "Zachytů", "Ponecháno", "Vyřazeno nocí",
             "Interval", "Délka videa"]]
    for report in reports:
        rows.append([
            report.name,
            f"{report.period_start:%d.%m.} – {report.period_end:%d.%m.%Y}",
            str(report.total_captures),
            str(report.kept),
            f"{report.dropped_night} ({report.dropped_night / max(report.total_captures, 1):.0%})",
            f"{report.interval_hours:.2f} h",
            f"{report.kept / max(report.video_fps, 1):.0f} s @ {report.video_fps} fps",
        ])
    story.append(_table(rows, font, bold))
    story.append(Spacer(1, 6))

    first = reports[0]
    story.append(Paragraph(
        f"Noční řez vyřazuje snímky pořízené mezi <b>{first.night_start:%H:%M}</b> a "
        f"<b>{first.night_end:%H:%M}</b>. Čas se čte z časového razítka vypáleného "
        "kamerou do každého snímku, nikoli z pořadí snímku – interval mezi zachyty "
        "totiž není přesně dvouhodinový a čas záběru se během sezony posouvá.", body))

    for report in reports:
        if report.unreadable:
            story.append(Paragraph(
                f"{report.name}: u {report.unreadable} snímků se nepodařilo přečíst "
                "časové razítko; tyto snímky do videa ani do analýzy nevstupují.", note))
        if report.skipped_files:
            skipped = ", ".join(f"{name} ({reason})" for name, reason in report.skipped_files)
            story.append(Paragraph(f"{report.name}: přeskočené soubory – {skipped}.", note))
        if report.gaps:
            gaps = "; ".join(f"{a:%d.%m. %H:%M} → {b:%d.%m. %H:%M} ({hours:.0f} h)"
                             for a, b, hours in report.gaps)
            story.append(Paragraph(f"{report.name}: výpadky záznamu – {gaps}.", note))

    # --- 2. fenologie -------------------------------------------------------
    story.append(Paragraph("2. Fenologický vývoj zelenosti", heading))
    story.append(Paragraph(
        "GCC (green chromatic coordinate) je podíl zeleného kanálu na součtu všech tří "
        "kanálů. Tím se krátí vliv okamžitého osvětlení, takže index popisuje stav "
        "vegetace, ne počasí. ExG (excess green) reaguje silněji na přechod mezi "
        "holou půdou a vegetací. Obě řady jsou agregované jako denní 90. percentil "
        "z denních snímků, což je standardní postup sítě PhenoCam pro potlačení "
        "snímků se stínem, mlhou a nízkým sluncem.", body))
    story.append(_chart(_greenness_chart(reports)))
    story.append(Spacer(1, 4))
    story.append(Paragraph(CAMERA_CAVEAT, note))

    # --- 3. sezonni ukazatele ----------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("3. Sezónní ukazatele", heading))
    rows = [["Plocha", "GCC min", "GCC max", "GCC průměr", "Amplituda",
             "Vrchol zelenosti", "Trend GCC / měsíc"]]
    for report in reports:
        if report.metrics is None:
            rows.append([report.name, "–", "–", "–", "–", "–", "–"])
            continue
        metrics = report.metrics
        rows.append([
            report.name,
            f"{metrics.gcc_min:.4f}",
            f"{metrics.gcc_max:.4f}",
            f"{metrics.gcc_mean:.4f}",
            f"{metrics.amplitude:.4f}",
            f"{metrics.peak_date:%d. %m. %Y}" if metrics.peak_date else "–",
            f"{metrics.trend_per_month:+.4f}",
        ])
    story.append(_table(rows, font, bold))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Záporný trend GCC v letním úseku neznamená automaticky poškození porostu – "
        "u jehličnatých kultur jde běžně o kombinaci dozrávání jehličí, zasychání "
        "bylinného patra a rostoucího podílu suchých zbytků ve scéně. Interpretovat "
        "je proto nutné společně s daty o půdní vlhkosti a teplotě.", body))

    for report in reports:
        story.append(Paragraph(f"Pokrytí záznamu – {report.name}", heading))
        story.append(_chart(_coverage_chart(report)))

    # --- 4. metodika --------------------------------------------------------
    story.append(Paragraph("4. Metodika a výhrady", heading))
    story.append(Paragraph(GEOLOGY_CAVEAT, body))
    story.append(Paragraph(
        "Analyzuje se pouze výřez snímku pod obzorem a nad vypáleným časovým pruhem; "
        "obloha do indexu zelenosti vnáší pouze šum. Snímky s průměrným jasem mimo "
        "rozsah 25–245 (soumrak, přesvícená scéna) jsou z denního kompozitu vyloučeny.", body))
    story.append(Paragraph(
        "Video: 1 snímek videa = 1 zachyt v terénu. Zdrojové AVI má 30 fps, ale jeden "
        "snímek pokrývá zhruba dvě hodiny reality – násobič rychlosti proto nemá "
        "smysl a rychlost se řídí výstupním fps. Při 10 fps odpovídá 1 sekunda videa "
        "přibližně 20 hodinám reality.", body))

    rows = [["Plocha", "Zdrojová složka", "Výstupní video"]]
    for report in reports:
        rows.append([report.name, report.source_dir, report.video_path])
    story.append(Spacer(1, 4))
    story.append(_table(rows, font, bold, widths=[30 * mm, 75 * mm, 60 * mm]))

    document.build(story)
    return output_path
