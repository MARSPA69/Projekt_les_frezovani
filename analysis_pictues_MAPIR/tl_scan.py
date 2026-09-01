"""
Nacteni casosberne sady snimku z MAPIR Survey 3N.

STRUKTURA SADY:
    Kamera uklada ke kazdemu zachytu dvojici souboru:
        2026_0715_110447_001.RAW   12-bit packed Bayer, 4000x3000, 18 000 000 B
        2026_0715_110449_002.JPG   white-balancovany nahled, 4000x3000
    Cas je primo v nazvu (RRRR_MMDD_HHMMSS). JPG je o par sekund pozdeji nez
    RAW, protoze kamera uklada postupne - parovani proto probiha podle
    poradi, ne podle presne shody casu.

KTERY SOUBOR K CEMU:
    JPG  -> casosberne video. Je to hotovy barevny nahled, presne to, co ma
            byt videt.
    RAW  -> NDVI a vegetacni indexy. Z JPG je NDVI nepouzitelne: MAPIR do nej
            aplikuje white balance, ktery kanaly R a B slije dohromady
            (korelace ~0.998), takze NDVI vyjde kolem nuly bez ohledu na stav
            porostu. Viz dokumentace v mapir_raw.py.

SPATNE HODINY KAMERY:
    Kdyz kamera ztrati napajeni, resetuje hodiny na 2024_0101. Takove snimky
    maji nesmyslny cas a do casove rady nepatri - filtruji se podle toho, ze
    jejich datum lezi mimo skutecne obdobi mereni.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

FILENAME_PATTERN = re.compile(r"^(\d{4})_(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(\d{3})$")

# Snimky s datem mimo tento rozsah pochazeji z resetovanych hodin kamery.
PLAUSIBLE_FROM = dt.datetime(2025, 1, 1)
PLAUSIBLE_TO = dt.datetime(2100, 1, 1)


@dataclass
class Shot:
    """Jeden zachyt: dvojice RAW + JPG se spolecnym casem."""
    timestamp: dt.datetime
    raw_path: Path | None
    jpg_path: Path | None

    @property
    def has_pair(self) -> bool:
        return self.raw_path is not None and self.jpg_path is not None


@dataclass
class PhotoSet:
    """Nactena casosberna sada."""
    shots: list[Shot]
    rejected_clock: list[Path]
    unmatched: list[Path]

    @property
    def period(self) -> tuple[dt.datetime, dt.datetime] | None:
        if not self.shots:
            return None
        return self.shots[0].timestamp, self.shots[-1].timestamp

    def with_jpg(self) -> list[Shot]:
        return [s for s in self.shots if s.jpg_path is not None]

    def with_raw(self) -> list[Shot]:
        return [s for s in self.shots if s.raw_path is not None]


def _timestamp_from_name(path: Path) -> dt.datetime | None:
    match = FILENAME_PATTERN.match(path.stem)
    if not match:
        return None
    year, month, day, hour, minute, second, _ = (int(g) for g in match.groups())
    try:
        return dt.datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def scan_photo_set(directory: Path) -> PhotoSet:
    """
    Nacte slozku se snimky MAPIR a spari RAW s JPG.

    Parovani: obe skupiny se seradi podle casu a spoji se po poradi, pokud si
    odpovidajici cas nelezi dal nez 60 s. Presna shoda casu nefunguje, protoze
    kamera zapisuje RAW a JPG s nekolikasekundovym odstupem.
    """
    directory = Path(directory)
    raws: list[tuple[dt.datetime, Path]] = []
    jpgs: list[tuple[dt.datetime, Path]] = []
    rejected: list[Path] = []

    for path in sorted(directory.iterdir()):
        suffix = path.suffix.lower()
        if suffix not in (".raw", ".jpg", ".jpeg"):
            continue
        stamp = _timestamp_from_name(path)
        if stamp is None or not (PLAUSIBLE_FROM <= stamp <= PLAUSIBLE_TO):
            rejected.append(path)
            continue
        (raws if suffix == ".raw" else jpgs).append((stamp, path))

    raws.sort()
    jpgs.sort()

    shots: list[Shot] = []
    unmatched: list[Path] = []
    raw_index = jpg_index = 0
    while raw_index < len(raws) or jpg_index < len(jpgs):
        if raw_index >= len(raws):
            stamp, path = jpgs[jpg_index]
            shots.append(Shot(stamp, None, path))
            unmatched.append(path)
            jpg_index += 1
            continue
        if jpg_index >= len(jpgs):
            stamp, path = raws[raw_index]
            shots.append(Shot(stamp, path, None))
            unmatched.append(path)
            raw_index += 1
            continue

        raw_stamp, raw_path = raws[raw_index]
        jpg_stamp, jpg_path = jpgs[jpg_index]
        delta = abs((jpg_stamp - raw_stamp).total_seconds())
        if delta <= 60:
            shots.append(Shot(raw_stamp, raw_path, jpg_path))
            raw_index += 1
            jpg_index += 1
        elif raw_stamp < jpg_stamp:
            shots.append(Shot(raw_stamp, raw_path, None))
            unmatched.append(raw_path)
            raw_index += 1
        else:
            shots.append(Shot(jpg_stamp, None, jpg_path))
            unmatched.append(jpg_path)
            jpg_index += 1

    shots.sort(key=lambda s: s.timestamp)
    return PhotoSet(shots=shots, rejected_clock=rejected, unmatched=unmatched)


def median_interval_hours(shots: list[Shot]) -> float:
    """Medianovy odstup mezi zachyty v hodinach."""
    if len(shots) < 2:
        return 0.0
    import numpy as np
    deltas = np.diff([s.timestamp.timestamp() for s in shots])
    return float(np.median(deltas)) / 3600.0
