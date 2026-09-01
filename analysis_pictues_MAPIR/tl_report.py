"""
PDF report o sledovanem biotopu: NIR obrazova analyza + pudni cidla + meteo.

CO REPORT TVRDI A CO NE:
    NDVI se pocita z nekalibrovanych RAW snimku, takze se interpretuje jako
    RELATIVNI rada - platny je jeji tvar a zmena v case, ne absolutni uroven.
    Raw vlhkost TOMST je surovy count, ne objemova vlhkost pudy; mezi cidly se
    proto neporovnavaji absolutni hodnoty, ale prubeh krivky.
    Srovnani F2022 vs. NF2022 neni cisty efekt frezovani, protoze plochy lezi
    v ruznych geologickych skupinach ~2,5 km od sebe.

Vsechny tri vyhrady jsou v reportu vytistene, aby se z nej nedaly vytrhnout
zaveery, ktere data neunesou.
"""

from __future__ import annotations

import datetime as dt
import io
import os
from dataclasses import dataclass, field

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image as RLImage, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

import tl_sensors as sensors
from tl_nir_series import smooth

ACCENT = colors.HexColor("#2E6B4F")
GRID = colors.HexColor("#D8D8D8")

NDVI_CAVEAT = (
    "NDVI je počítáno z <b>nekalibrovaných</b> RAW snímků – v sadě není u každého "
    "zachytu kalibrační terčík. NDVI je poměrový index, takže konstantní zisk se "
    "v čitateli i jmenovateli krátí a <b>relativní vývoj v čase je platný</b>. "
    "Absolutní hodnotu ale nelze číst jako přesnou odrazivost ani ji srovnávat "
    "s měřením z jiné kamery či jiné sezony."
)

MOISTURE_CAVEAT = (
    "Vlhkostní kanál TOMST je <b>surový TMS count, nikoli % objemové vlhkosti</b>. "
    "Bez lokální kalibrace nelze tvrdit „tato plocha má o X % více vody“. "
    "Srovnatelný je tvar křivky: reakce po srážce, rychlost vysychání a změna "
    "v rámci jednoho čidla. Absolutní úroveň mezi čidly ovlivňuje kontakt s půdou, "
    "dutiny, kořeny, kamenitost a stárnutí kontaktu."
)

GEOLOGY_CAVEAT = (
    "Srovnání F2022 vs. NF2022 <b>není čistým efektem frézování</b>. F2022 leží "
    "v geologické skupině Ca (moldanubikum, pararula/migmatit), NF2022 ve skupině "
    "Ka (granodiorit/durbachit, grusové zvětrávání) zhruba 2,5 km daleko. Rozdíl "
    "mezi plochami tedy spojuje vliv zásahu s vlivem odlišného stanoviště. "
    "Nejčistším experimentálním párem je podle zprávy z 21. 8. 2026 dvojice "
    "F2026 vs. NF2026, kterou ale obrazová sada MAPIR nepokrývá."
)


def _register_font() -> tuple[str, str]:
    """Unicode font pro ceskou diakritiku; stejny postup jako v hlavni aplikaci."""
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
class BiotopeReport:
    """Vstupy pro report o biotopu."""
    plot_name: str
    photo_dir: str
    video_path: str
    video_fps: int
    shots_total: int
    shots_day: int
    shots_night: int
    rejected_clock: int
    interval_hours: float
    period_start: dt.datetime
    period_end: dt.datetime
    ndvi_daily: pd.DataFrame
    primary: dict[str, pd.DataFrame] = field(default_factory=dict)    # kod -> denni rada
    comparison: dict[str, pd.DataFrame] = field(default_factory=dict)
    primary_raw: dict[str, pd.DataFrame] = field(default_factory=dict)  # kod -> 15min rada
    comparison_raw: dict[str, pd.DataFrame] = field(default_factory=dict)


def _chart(figure) -> RLImage:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    plt.close(figure)
    buffer.seek(0)
    ratio = figure.get_figheight() / figure.get_figwidth()
    return RLImage(buffer, width=165 * mm, height=165 * mm * ratio)


def _table(rows, font, bold, widths=None) -> Table:
    table = Table(rows, colWidths=widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), bold),
        ("FONTNAME", (0, 1), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 7.6),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0EC")),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("GRID", (0, 0), (-1, -1), 0.4, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _mark_events(axis) -> None:
    """Vyznaci vlhkostni epizody popsane ve zprave z 21. 8. 2026."""
    for date, _label in sensors.MOISTURE_EVENTS:
        axis.axvline(pd.Timestamp(date), color="#3C6E9E", alpha=0.35,
                     linestyle="--", linewidth=1.0)


def _ndvi_chart(report: BiotopeReport):
    figure, axis = plt.subplots(figsize=(9, 3.4))
    daily = report.ndvi_daily
    if not daily.empty:
        axis.plot(daily.index, daily["ndvi"], linewidth=0.7, alpha=0.35,
                  color="#2E6B4F", label="denní hodnota")
        axis.plot(daily.index, smooth(daily["ndvi"]), linewidth=2.2,
                  color="#2E6B4F", label="klouzavý medián 7 dní")
        _mark_events(axis)
    axis.set_ylabel("NDVI (relativní)", fontsize=9)
    axis.set_title(f"Vývoj NDVI – {report.plot_name} (denní 75. percentil z denních snímků)",
                   fontsize=10)
    axis.grid(True, alpha=0.3, linestyle=":")
    axis.legend(fontsize=8)
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    axis.tick_params(labelsize=8)
    figure.tight_layout()
    return figure


def _ndvi_vs_moisture_chart(report: BiotopeReport):
    """NDVI proti raw vlhkosti hlavni plochy - hleda se casova souvislost."""
    figure, axis = plt.subplots(figsize=(9, 3.4))
    daily = report.ndvi_daily
    if not daily.empty:
        axis.plot(daily.index, smooth(daily["ndvi"]), linewidth=2.2,
                  color="#2E6B4F", label="NDVI (vyhlazené)")
    axis.set_ylabel("NDVI (relativní)", fontsize=9, color="#2E6B4F")
    axis.tick_params(axis="y", labelcolor="#2E6B4F", labelsize=8)

    twin = axis.twinx()
    palette = ["#3C6E9E", "#7A4FA3"]
    for index, (code, frame) in enumerate(report.primary.items()):
        if frame.empty:
            continue
        twin.plot(frame.index, frame["vlhkost_raw"], linewidth=1.4, alpha=0.85,
                  color=palette[index % len(palette)], label=f"{code} raw vlhkost")
    twin.set_ylabel("raw vlhkost TOMST (count)", fontsize=9)
    twin.tick_params(axis="y", labelsize=8)

    handles = axis.get_legend_handles_labels()[0] + twin.get_legend_handles_labels()[0]
    labels = axis.get_legend_handles_labels()[1] + twin.get_legend_handles_labels()[1]
    axis.legend(handles, labels, fontsize=8, loc="best")
    axis.set_title("NDVI a půdní vlhkost na monitorované ploše", fontsize=10)
    axis.grid(True, alpha=0.3, linestyle=":")
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    axis.tick_params(axis="x", labelsize=8)
    figure.tight_layout()
    return figure


def _moisture_comparison_chart(report: BiotopeReport):
    """Raw vlhkost hlavni a srovnavaci plochy."""
    figure, axes = plt.subplots(2, 1, figsize=(9, 5.2), sharex=True)
    for axis, depth in zip(axes, (10, 48)):
        for group, style, prefix in ((report.primary, "-", ""), (report.comparison, "--", "")):
            for code, frame in group.items():
                info = sensors.SENSORS.get(code)
                if info is None or info.depth_cm != depth or frame.empty:
                    continue
                colour = "#2E6B4F" if info.treatment == "fréza" else "#B4632A"
                axis.plot(frame.index, frame["vlhkost_raw"], style, linewidth=1.6,
                          color=colour, label=f"{code} ({info.plot}, {info.group})")
        _mark_events(axis)
        axis.set_ylabel(f"raw count, {depth} cm", fontsize=9)
        axis.grid(True, alpha=0.3, linestyle=":")
        axis.legend(fontsize=7.5, loc="best")
        axis.tick_params(labelsize=8)
    axes[0].set_title("Raw půdní vlhkost – mělká (10 cm) a hlubší (48 cm) vrstva\n"
                      "(svislé čáry = vlhkostní epizody dle zprávy z 21. 8. 2026)",
                      fontsize=10)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    figure.tight_layout()
    return figure


def _temperature_chart(report: BiotopeReport):
    """Prizemni kanal T3 se stresovymi prahy a pudni profil T1."""
    figure, axes = plt.subplots(2, 1, figsize=(9, 5.0), sharex=True)
    for code, frame in {**report.primary, **report.comparison}.items():
        info = sensors.SENSORS.get(code)
        if frame.empty or info is None:
            continue
        colour = "#2E6B4F" if info.treatment == "fréza" else "#B4632A"
        style = "-" if info.depth_cm == 10 else "--"
        axes[0].plot(frame.index, frame["T3_max"], style, linewidth=1.1,
                     alpha=0.9, color=colour, label=code)
        axes[1].plot(frame.index, frame["T1"], style, linewidth=1.4,
                     color=colour, label=code)
    for threshold, colour in ((30, "#E0A030"), (35, "#C04040")):
        axes[0].axhline(threshold, color=colour, linestyle=":", linewidth=1.2)
        axes[0].text(0.005, threshold, f" {threshold} °C", transform=axes[0].get_yaxis_transform(),
                     fontsize=7, color=colour, va="bottom")
    axes[0].set_ylabel("denní max T3 (°C)", fontsize=9)
    axes[0].set_title("Přízemní stresový kanál T3 a teplota půdního profilu T1", fontsize=10)
    axes[1].set_ylabel("denní průměr T1 (°C)", fontsize=9)
    for axis in axes:
        axis.grid(True, alpha=0.3, linestyle=":")
        axis.legend(fontsize=7.5, ncol=2, loc="best")
        axis.tick_params(labelsize=8)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
    figure.tight_layout()
    return figure


def _correlate(ndvi: pd.DataFrame, sensor_daily: pd.DataFrame, column: str) -> float:
    """Spearmanova korelace NDVI a senzoroveho kanalu na spolecnych dnech."""
    if ndvi.empty or sensor_daily.empty:
        return float("nan")
    joined = pd.DataFrame({"ndvi": ndvi["ndvi"]}).join(sensor_daily[[column]], how="inner")
    joined = joined.dropna()
    if len(joined) < 5:
        return float("nan")
    return float(joined["ndvi"].corr(joined[column], method="spearman"))


def build_report(report: BiotopeReport, output_path: str) -> str:
    """Sestavi PDF report o biotopu a ulozi ho."""
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
        title=f"Biotop {report.plot_name} – MAPIR NIR", author="CRA s.r.o.")

    daily = report.ndvi_daily
    story: list = [
        Paragraph("Sledovaný biotop – NIR analýza a mikroklima", title),
        Paragraph(f"Plocha {report.plot_name} · kamera MAPIR Survey 3N · "
                  f"půdní čidla TOMST TMS", note),
        Paragraph("Projekt „Vliv frézování půdy po těžbě dřeva na růst sazenic“ · "
                  f"zpracováno {dt.date.today():%d. %m. %Y}", note),
        Spacer(1, 10),
    ]

    # --- 1. shrnuti ---------------------------------------------------------
    story.append(Paragraph("1. Shrnutí", heading))
    if not daily.empty:
        first_ndvi = float(smooth(daily["ndvi"]).iloc[0])
        last_ndvi = float(smooth(daily["ndvi"]).iloc[-1])
        peak_date = smooth(daily["ndvi"]).idxmax()
        direction = ("mírně rostoucí" if last_ndvi - first_ndvi > 0.01 else
                     "klesající" if last_ndvi - first_ndvi < -0.01 else "stabilní")
        story.append(Paragraph(
            f"Obrazová sada pokrývá období <b>{report.period_start:%d. %m.} – "
            f"{report.period_end:%d. %m. %Y}</b> ({report.shots_total} zachytů, "
            f"medián intervalu {report.interval_hours:.1f} h). Z toho "
            f"{report.shots_day} denních snímků vstoupilo do NIR analýzy a "
            f"{report.shots_night} nočních bylo vyřazeno – bez osvětleného pásma "
            f"Red je NDVI neplatné.", body))
        story.append(Paragraph(
            f"Relativní NDVI je v celém období <b>{direction}</b>: z {first_ndvi:.3f} "
            f"na {last_ndvi:.3f}, s maximem {peak_date:%d. %m. %Y}. Porost je po celou "
            f"dobu v pásmu husté zapojené vegetace, takže NDVI je blízko saturace a "
            f"reaguje spíš na strukturu a osvětlení scény než na drobné změny vitality.", body))
    else:
        story.append(Paragraph("Obrazová sada neobsahuje použitelné denní snímky.", body))

    if report.rejected_clock:
        story.append(Paragraph(
            f"{report.rejected_clock} snímků mělo resetované hodiny kamery (datum 2024) "
            "a do časové řady nevstupuje.", note))

    # --- 2. casosberne video ------------------------------------------------
    story.append(Paragraph("2. Časosběrné video", heading))
    story.append(Paragraph(
        f"Video vzniklo z JPG náhledů celé sady bez časového řezu, tedy včetně nočních "
        f"snímků – ty ve videu dokládají denní rytmus stanoviště, i když pro NDVI "
        f"použitelné nejsou. Při {report.video_fps} fps trvá zhruba "
        f"{report.shots_total / max(report.video_fps, 1):.0f} sekund.", body))
    story.append(_table([["Zdrojová složka", report.photo_dir],
                         ["Výstupní video", report.video_path],
                         ["Snímků ve videu", str(report.shots_total)],
                         ["Rychlost", f"{report.video_fps} fps"]],
                        font, bold, widths=[38 * mm, 127 * mm]))

    # --- 3. NIR analyza -----------------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("3. Vegetační indexy z NIR snímků", heading))
    story.append(Paragraph(NDVI_CAVEAT, body))
    story.append(Paragraph(
        "NDVI se počítá přímo ze surových pásem RAW souboru. Z JPG náhledu by NDVI "
        "vyjít nemohlo – MAPIR do něj aplikuje vyvážení bílé, které pásma Red a NIR "
        "slije dohromady a index by vycházel kolem nuly bez ohledu na stav porostu.", body))
    story.append(_chart(_ndvi_chart(report)))

    if not daily.empty:
        rows = [["Ukazatel", "Hodnota"]]
        smoothed = smooth(daily["ndvi"])
        rows += [
            ["Dnů s použitelnými snímky", str(len(daily))],
            ["NDVI minimum / maximum", f"{daily['ndvi'].min():.3f} / {daily['ndvi'].max():.3f}"],
            ["NDVI průměr", f"{daily['ndvi'].mean():.3f}"],
            ["NDVI na začátku / na konci", f"{smoothed.iloc[0]:.3f} / {smoothed.iloc[-1]:.3f}"],
            ["OSAVI průměr", f"{daily['osavi'].mean():.3f}"],
            ["RDVI průměr", f"{daily['rdvi'].mean():.3f}"],
        ]
        story.append(Spacer(1, 4))
        story.append(_table(rows, font, bold, widths=[70 * mm, 60 * mm]))

    # --- 4. pudni cidla -----------------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("4. Půdní vlhkost a teplota", heading))
    story.append(Paragraph(MOISTURE_CAVEAT, body))

    rows = [["Čidlo", "Plocha", "Zásah", "Hloubka", "Skupina", "Interpretovat od",
             "Vlhkost první", "poslední", "změna", "trend/den"]]
    for code, frame in {**report.primary, **report.comparison}.items():
        info = sensors.SENSORS.get(code)
        first, last, change, slope = sensors.moisture_change(frame)
        rows.append([
            code, info.plot if info else "–", info.treatment if info else "–",
            f"{info.depth_cm} cm" if info else "–", info.group if info else "–",
            f"{info.interpret_from:%d. %m.}" if info else "–",
            f"{first:.0f}", f"{last:.0f}", f"{change:+.0f}", f"{slope:+.2f}",
        ])
    story.append(_table(rows, font, bold))

    flagged = [(code, sensors.SENSORS[code].note)
               for code in {**report.primary, **report.comparison}
               if code in sensors.SENSORS and sensors.SENSORS[code].note]
    if flagged:
        story.append(Spacer(1, 4))
        for code, text in flagged:
            story.append(Paragraph(f"<b>{code}:</b> {text}.", note))

    story.append(Spacer(1, 6))
    story.append(_chart(_moisture_comparison_chart(report)))
    story.append(PageBreak())
    story.append(_chart(_temperature_chart(report)))

    rows = [["Čidlo", "T3 min", "T3 max", "Dnů T3>30", "Dnů T3>35", "Dnů T3>40", "Dnů T3<0"]]
    for code, frame in {**report.primary_raw, **report.comparison_raw}.items():
        if frame.empty:
            continue
        counts = sensors.heat_stress_days(frame)
        rows.append([code, f"{frame['T3'].min():.1f}", f"{frame['T3'].max():.1f}",
                     str(counts.get("T3>30", 0)), str(counts.get("T3>35", 0)),
                     str(counts.get("T3>40", 0)), str(counts.get("T3<0", 0))])
    story.append(Spacer(1, 6))
    story.append(_table(rows, font, bold))
    story.append(Paragraph(
        "Přízemní kanál T3 není půdní teplota v hloubce – zachycuje přízemní mrazíky "
        "a denní přehřívání u povrchu. Právě proto je rozhodující pro čerstvou výsadbu: "
        "opakované překročení 35 °C se časově překrývá s poklesem mělké vlhkosti.", body))

    # --- 5. meteo -----------------------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("5. Meteorologický rámec", heading))
    story.append(Paragraph(
        "Na plochách není lokální srážkoměr, takže meteorologická data slouží jako "
        "<b>regionální rámec</b> (Podolí I. / Milevsko), nikoli jako přesný denní "
        "srážkový záznam u čidla. U lokálních bouřek může být rozdíl mezi stanicí "
        "a pozemkem zásadní; vlastní vlhkostní pulzy TOMST proto slouží zároveň jako "
        "indikátor skutečné lokální infiltrační události.", body))
    rows = [["Období", "Charakter", "Údaj ČHMÚ", "Dopad na interpretaci"]]
    rows += [list(entry) for entry in sensors.METEO_FRAMEWORK]
    story.append(_table(rows, font, bold, widths=[24 * mm, 38 * mm, 52 * mm, 51 * mm]))
    story.append(Spacer(1, 4))
    story.append(Paragraph("Zdroj: zpráva „Analýza senzorických dat z 21082026 – projekt LES“, "
                           "tabulka 3.", note))

    # --- 6. souvislosti -----------------------------------------------------
    story.append(Paragraph("6. Souvislost obrazu, vláhy a teploty", heading))
    rows = [["Čidlo", "NDVI × raw vlhkost", "NDVI × T1", "NDVI × denní max T3"]]
    for code, frame in report.primary.items():
        rows.append([
            code,
            f"{_correlate(daily, frame, 'vlhkost_raw'):+.2f}",
            f"{_correlate(daily, frame, 'T1'):+.2f}",
            f"{_correlate(daily, frame, 'T3_max'):+.2f}",
        ])
    story.append(_table(rows, font, bold, widths=[30 * mm, 45 * mm, 40 * mm, 45 * mm]))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Uvedeny jsou Spearmanovy korelace na společných dnech. Jde o <b>souběh, "
        "nikoli o důkaz příčiny</b>: obrazová sada pokrývá jen letní úsek, kdy "
        "NDVI, půdní teplota i vlhkost sdílejí společný sezónní trend. Krátká "
        "společná řada navíc znamená, že jednotlivá epizoda může korelaci výrazně "
        "posunout.", body))
    story.append(_chart(_ndvi_vs_moisture_chart(report)))

    # --- 7. zavery ----------------------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("7. Závěry a výhrady", heading))
    story.append(Paragraph(GEOLOGY_CAVEAT, body))
    story.append(Paragraph(
        "Obrazová sada MAPIR existuje pouze pro plochu Frézovaný 2022 – druhá kamera "
        "nefungovala. Srovnávací plocha proto vstupuje do reportu <b>jen přes data "
        "z půdních čidel</b>, nikoli obrazem. Jakýkoli závěr o rozdílu porostů mezi "
        "plochami by potřeboval obrazovou sadu z obou.", body))
    story.append(Paragraph(
        "Pro plné hodnocení efektu frézování doporučuji navázat na dvojici F2026 vs. "
        "NF2026, která leží ve stejné geologické skupině těsně vedle sebe a je podle "
        "zprávy z 21. 8. 2026 nejsilnějším experimentálním párem v projektu.", body))

    document.build(story)
    return output_path
