"""
Render casosberneho mp4 z JPG snimku MAPIR Survey 3N.

PROC JPG A NE RAW:
    JPG je hotovy barevny nahled kamery - presne to, co ma divak videt.
    RAW se pouziva jen pro NDVI (viz tl_nir_series.py), protoze je v nem
    zachovana spektralni informace, kterou JPG slucuje.

ROZLISENI:
    Nativni snimek ma 4000x3000 (4:3, 12 MPx). Pro video se skaluje na
    1600x1200; vyssi rozliseni nema smysl - vysledek by mel stovky MB a
    detail casosberu stejne nese pohyb, ne pocet pixelu. Rozmery musi byt
    sude kvuli yuv420p.

CAS VE SNIMKU:
    Do spodniho okraje se vykresluje datum. cv2.putText umi jen ASCII
    (Hershey fonty), takze nazvy mesicu jsou zamerne bez diakritiky.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import cv2
import numpy as np

from tl_scan import Shot

DEFAULT_OUTPUT_FPS = 10
VIDEO_WIDTH = 1600
VIDEO_HEIGHT = 1200

_CZECH_MONTHS = ["", "ledna", "unora", "brezna", "dubna", "kvetna", "cervna",
                 "cervence", "srpna", "zari", "rijna", "listopadu", "prosince"]


def imread_unicode(path: Path) -> np.ndarray | None:
    """
    Nacte obrazek z cesty, ktera muze obsahovat diakritiku.

    cv2.imread na Windows pouziva ANSI souborove API, takze na ceste jako
    "Sběr data 21082026_LES" TISE vrati None. Data projektu takove cesty maji,
    proto se soubor nacte pres pathlib a dekoduje z pameti.

    Vraci None i u prazdneho nebo poskozeneho souboru - v sade se takovy
    najde (napr. 2026_0731_011337_002.JPG ma nula bajtu) a cv2.imdecode by
    na prazdnem bufferu spadl na assertion misto aby vratil None.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if not data:
        return None
    try:
        return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        return None


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _draw_date_badge(frame: np.ndarray, moment: dt.datetime) -> np.ndarray:
    """Vykresli datum a cas do cerneho pruhu u spodniho okraje."""
    height = frame.shape[0]
    band = 44
    cv2.rectangle(frame, (0, height - band), (frame.shape[1], height), (0, 0, 0), -1)
    label = f"{moment.day}. {_CZECH_MONTHS[moment.month]} {moment.year}   {moment:%H:%M}"
    cv2.putText(frame, label, (20, height - 14), cv2.FONT_HERSHEY_SIMPLEX,
                0.9, (255, 255, 255), 2, cv2.LINE_AA)
    return frame


def render_video(shots: list[Shot],
                 output_path: Path,
                 fps: int = DEFAULT_OUTPUT_FPS,
                 overlay_date: bool = True,
                 progress=None) -> Path:
    """
    Slozi mp4 z JPG snimku. Snimky se streamuji po jednom do ffmpegu, aby se
    17GB sada nikdy nemusela vejit do pameti.
    """
    usable = [s for s in shots if s.jpg_path is not None]
    if not usable:
        raise ValueError("Sada neobsahuje žádné JPG snímky k renderování.")
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg není dostupný v PATH; bez něj nelze zapsat mp4.")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}", "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    written = 0
    skipped: list[Path] = []
    try:
        for shot in usable:
            frame = imread_unicode(shot.jpg_path)
            if frame is None:
                skipped.append(shot.jpg_path)
                continue
            frame = cv2.resize(frame, (VIDEO_WIDTH, VIDEO_HEIGHT),
                               interpolation=cv2.INTER_AREA)
            if overlay_date:
                frame = _draw_date_badge(frame, shot.timestamp)
            process.stdin.write(frame.tobytes())
            written += 1
            if progress and written % 20 == 0:
                progress(written, len(usable), "video")
    finally:
        if process.stdin:
            process.stdin.close()
        stderr = process.stderr.read() if process.stderr else b""
        code = process.wait()

    if code != 0:
        raise RuntimeError(f"ffmpeg selhal (kód {code}): {stderr.decode(errors='replace')[:500]}")
    # Bez teto kontroly by se necitelna sada projevila az jako nekolikasetbajtove
    # mp4 bez jedineho snimku, coz uz nikdo v davce nepozna.
    if written < len(usable) * 0.5:
        raise RuntimeError(
            f"Do videa se zapsalo jen {written} z {len(usable)} snímků – "
            f"zbytek se nepodařilo načíst (např. {skipped[0].name if skipped else '?'}).")
    if progress:
        progress(written, len(usable), "hotovo")
    return output_path
