"""
Skenovani casosbernych AVI Brinno, nocni rez a render zrychleneho mp4.

VSTUPNI DATA:
    Brinno TLC2000 nezaznamenava jednotlive fotky, ale rovnou hotove AVI
    (MJPEG, 1920x1080, 30 fps), kde JEDEN SNIMEK = jeden zachyt v terenu.
    Kamera zaznam deli na vice souboru TLC000xx.AVI; nektere obsahuji jediny
    snimek (restart kamery po vymene karty) - ty se do casosberu neberou.

CO ZNAMENA "RYCHLOST":
    Zdrojove AVI ma 30 fps, ale jeden snimek pokryva 2 hodiny reality. Nasobic
    rychlosti (x1.2) je proto bezpredmetny - cele leto by se prehralo za 37 s.
    Skutecny ovladaci prvek je VYSTUPNI fps: kolik zachytu za sekundu se ma
    prehrat. Pri 10 fps odpovida 1 s videa zhruba 20 hodinam reality.

NOCNI REZ:
    Vyrazuji se snimky, jejichz cas padne do nocniho intervalu (vychozi
    22:00-05:00). Interval prechazi pres pulnoc, takze test je "cas >= zacatek
    NEBO cas < konec". Pri zacatku == konci se nevyrazuje nic.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from brinno_ocr import read_stamp

DEFAULT_NIGHT_START = dt.time(22, 0)
DEFAULT_NIGHT_END = dt.time(5, 0)
DEFAULT_OUTPUT_FPS = 10

# Kvalita H.264 (nizsi cislo = lepsi obraz a vetsi soubor). Casosberny les se
# komprimuje spatne - sousedni snimky deli dve hodiny, takze se scena zmeni
# uplne a mezisnimkova komprese nema co usetrit. Pri 786 snimcich v 1080p
# vychazi crf 20 na ~270 MB, crf 23 na ~200 MB a crf 28 zhruba na polovinu
# crf 20. Vychozich 23 je kompromis mezi ctelnosti jehlici a velikosti.
DEFAULT_CRF = 23

# Mezera mezi po sobe jdoucimi zachyty, ktera uz znamena vypadek zaznamu
# (kamera stala, plna karta, vybita baterie). Nasobek medianoveho intervalu.
GAP_FACTOR = 2.5


@dataclass
class Capture:
    """Jeden zachyt v terenu = jeden snimek zdrojoveho AVI."""
    source: Path
    frame_index: int
    timestamp: dt.datetime


@dataclass
class ScanResult:
    """Vysledek nacteni vsech AVI jedne lokality."""
    captures: list[Capture] = field(default_factory=list)
    unreadable: list[tuple[Path, int, str]] = field(default_factory=list)
    skipped_files: list[tuple[Path, str]] = field(default_factory=list)

    @property
    def interval_seconds(self) -> float:
        """Medianovy odstup mezi zachyty. 0 pokud jsou mene nez dva."""
        if len(self.captures) < 2:
            return 0.0
        deltas = np.diff([c.timestamp.timestamp() for c in self.captures])
        return float(np.median(deltas))

    def gaps(self) -> list[tuple[dt.datetime, dt.datetime, float]]:
        """Vypadky zaznamu jako (od, do, delka v hodinach)."""
        interval = self.interval_seconds
        if interval <= 0:
            return []
        limit = interval * GAP_FACTOR
        found = []
        for previous, current in zip(self.captures, self.captures[1:]):
            delta = (current.timestamp - previous.timestamp).total_seconds()
            if delta > limit:
                found.append((previous.timestamp, current.timestamp, delta / 3600.0))
        return found


def is_night(moment: dt.time, start: dt.time, end: dt.time) -> bool:
    """True pokud cas padne do nocniho intervalu (muze prechazet pres pulnoc)."""
    if start == end:
        return False
    if start < end:
        return start <= moment < end
    return moment >= start or moment < end


def scan_directory(directory: Path, progress=None) -> ScanResult:
    """
    Nacte vsechna AVI ve slozce, precte razitko kazdeho snimku a vrati
    zachyty serazene podle casu.

    `progress` je volitelny callback (hotovo, celkem, popis) pro UI.
    """
    files = sorted(p for p in Path(directory).iterdir() if p.suffix.lower() == ".avi")
    result = ScanResult()

    for file_number, path in enumerate(files, start=1):
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            result.skipped_files.append((path, "soubor nelze otevrit"))
            continue
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 1:
            # Jednosnimkove soubory vznikaji pri restartu kamery.
            result.skipped_files.append((path, f"jen {total} snimek - restart kamery"))
            capture.release()
            continue

        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            stamp = read_stamp(frame)
            if stamp.timestamp is None:
                result.unreadable.append((path, index, stamp.reason))
            else:
                result.captures.append(Capture(path, index, stamp.timestamp))
            index += 1
        capture.release()

        if progress:
            progress(file_number, len(files), f"{path.name}: {index} snimku")

    result.captures.sort(key=lambda c: c.timestamp)
    return result


def filter_daytime(captures: list[Capture],
                   night_start: dt.time = DEFAULT_NIGHT_START,
                   night_end: dt.time = DEFAULT_NIGHT_END) -> tuple[list[Capture], list[Capture]]:
    """Rozdeli zachyty na denni (ponechane) a nocni (vyrazene)."""
    kept, dropped = [], []
    for item in captures:
        (dropped if is_night(item.timestamp.time(), night_start, night_end) else kept).append(item)
    return kept, dropped


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def render_video(captures: list[Capture],
                 output_path: Path,
                 fps: int = DEFAULT_OUTPUT_FPS,
                 overlay_date: bool = True,
                 crf: int = DEFAULT_CRF,
                 progress=None) -> Path:
    """
    Vyrenderuje mp4 z vybranych zachytu.

    Snimky se streamuji po jednom rovnou do ffmpegu - drzet je v pameti nelze,
    740 snimku v 1080p je pres 4 GB. Cte se sekvencne (v MJPEG je nahodne
    skakani radove pomalejsi) a prehravac se preotevre jen pri zmene souboru
    nebo pri skoku zpet. Zapisuje se do H.264, ktery se na rozdil od OpenCV
    mp4v prehraje vsude vcetne PowerPointu a webu.
    """
    if not captures:
        raise ValueError("Zadne snimky k renderovani - zkontroluj nocni rez.")
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg neni dostupny v PATH; bez nej nelze zapsat mp4.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    height, width = 1080, 1920
    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    reader: cv2.VideoCapture | None = None
    open_source: Path | None = None
    next_index = 0          # index snimku, ktery vrati priste reader.read()
    written = 0

    try:
        for item in captures:
            if item.source != open_source:
                if reader is not None:
                    reader.release()
                reader = cv2.VideoCapture(str(item.source))
                open_source = item.source
                next_index = 0
            if item.frame_index < next_index:
                reader.set(cv2.CAP_PROP_POS_FRAMES, item.frame_index)
                next_index = item.frame_index
            while next_index < item.frame_index:
                if not reader.grab():
                    break
                next_index += 1

            ok, frame = reader.read()
            next_index += 1
            if not ok or frame is None:
                continue

            if frame.shape[0] != height or frame.shape[1] != width:
                frame = cv2.resize(frame, (width, height))
            if overlay_date:
                frame = _draw_date_badge(frame, item.timestamp)
            process.stdin.write(frame.tobytes())
            written += 1
            if progress and written % 25 == 0:
                progress(written, len(captures), "render")
    finally:
        if reader is not None:
            reader.release()
        if process.stdin:
            process.stdin.close()
        stderr = process.stderr.read() if process.stderr else b""
        code = process.wait()

    if code != 0:
        raise RuntimeError(f"ffmpeg selhal (kod {code}): {stderr.decode(errors='replace')[:500]}")
    if progress:
        progress(written, len(captures), "hotovo")
    return output_path


_CZECH_MONTHS = ["", "ledna", "unora", "brezna", "dubna", "kvetna", "cervna",
                 "cervence", "srpna", "zari", "rijna", "listopadu", "prosince"]


def _draw_date_badge(frame: np.ndarray, moment: dt.datetime) -> np.ndarray:
    """
    Prekryje puvodni Brinno razitko citelnym ceskym datem.

    Puvodni razitko je male a v case posunute o sekundy; pro report je
    citelnejsi velky datum v levem dolnim rohu.
    """
    frame = frame.copy()
    label = f"{moment.day}. {_CZECH_MONTHS[moment.month]} {moment.year}   {moment:%H:%M}"
    cv2.rectangle(frame, (0, 1048), (1920, 1080), (0, 0, 0), -1)
    cv2.putText(frame, label, (24, 1072), cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return frame
