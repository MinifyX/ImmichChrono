"""Read metadata Immich does not expose (GPS time, XMP/IPTC/QuickTime dates) via exiftool."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..model import Candidate, plausible, to_aware
from .suspects import is_phone

_DATE = re.compile(
    r"^(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?$"
)

EMBEDDED_TAGS = (
    ("EXIF:DateTimeOriginal", 0.96),
    ("XMP:DateTimeOriginal", 0.95),
    ("QuickTime:CreationDate", 0.95),
    ("Composite:SubSecDateTimeOriginal", 0.96),
    ("EXIF:CreateDate", 0.94),
    ("XMP:DateCreated", 0.93),
    ("Composite:DateTimeCreated", 0.92),
    ("XMP:CreateDate", 0.9),
    ("QuickTime:CreateDate", 0.85),
)


@dataclass
class DeepInfo:
    candidates: list[Candidate] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    serial: str | None = None
    file_number: int | None = None
    raw: dict = field(default_factory=dict)


def parse_exif_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    m = _DATE.match(value.strip())
    if not m:
        return None
    y, mo, d, h, mi, s, off = m.groups()
    try:
        when = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None
    if when.year < 1900:
        return None
    if off == "Z":
        return when.replace(tzinfo=UTC)
    if off:
        sign = -1 if off[0] == "-" else 1
        hh, mm = int(off[1:3]), int(off[-2:])
        return when.replace(tzinfo=timezone(sign * timedelta(hours=hh, minutes=mm)))
    return when


def _offset(value: object) -> timezone | None:
    if isinstance(value, str) and re.fullmatch(r"[+-]\d\d:\d\d", value):
        sign = -1 if value[0] == "-" else 1
        return timezone(sign * timedelta(hours=int(value[1:3]), minutes=int(value[4:6])))
    return None


def analyze(tags: dict, *, make: str | None, tz: ZoneInfo | None, now: datetime | None = None) -> DeepInfo:
    info = DeepInfo(raw={k: v for k, v in tags.items() if "Date" in k or "Time" in k or "Number" in k})
    info.serial = next(
        (str(tags[k]) for k in ("EXIF:SerialNumber", "MakerNotes:SerialNumber", "MakerNotes:InternalSerialNumber")
         if tags.get(k)), None,
    )
    fn = tags.get("MakerNotes:FileNumber") or tags.get("MakerNotes:ImageNumber") or tags.get("EXIF:ImageNumber")
    if isinstance(fn, int | str) and str(fn).replace("-", "").isdigit():
        info.file_number = int(str(fn).replace("-", ""))

    dto = parse_exif_date(tags.get("EXIF:DateTimeOriginal"))
    if dto is not None and dto.tzinfo is None:
        off = _offset(tags.get("EXIF:OffsetTimeOriginal"))
        if off:
            dto = dto.replace(tzinfo=off)

    # Embedded dates (used when Immich itself found no camera date).
    for tag, conf in EMBEDDED_TAGS:
        when = parse_exif_date(tags.get(tag))
        if when is None or not plausible(when, now):
            continue
        if tag == "QuickTime:CreateDate" and when.tzinfo is None:
            when = when.replace(tzinfo=UTC)  # QuickTime stores UTC by spec
        info.candidates.append(Candidate(
            source="exif_deep", when=when, precision="second", confidence=conf,
            explanation=f"Eingebettetes Datum {tag} = {tags.get(tag)}",
        ))
        break

    # GPS time comes from satellites and is therefore independent of the camera clock.
    gps = parse_exif_date(tags.get("Composite:GPSDateTime"))
    if gps is not None and gps.tzinfo is None:
        gps = gps.replace(tzinfo=UTC)
    if gps is not None and plausible(gps, now) and dto is not None and not is_phone(make):
        if dto.tzinfo is not None or tz is not None:
            diff = to_aware(dto, tz) - gps
            tz_explained = False
        else:
            diff = dto.replace(tzinfo=UTC) - gps
            quarter = round(diff / timedelta(minutes=15)) * timedelta(minutes=15)
            tz_explained = abs(diff) <= timedelta(hours=14) and abs(diff - quarter) < timedelta(minutes=3)
        if not tz_explained and abs(diff) > timedelta(minutes=5):
            info.issues.append("camera_clock")
            info.candidates.insert(0, Candidate(
                source="gps", when=gps, precision="second",
                confidence=0.96 if abs(diff) > timedelta(hours=1) else 0.9,
                explanation=f"GPS-Zeitstempel {gps:%d.%m.%Y %H:%M} UTC; Kamera-Uhr lag {_fmt(diff)} daneben",
            ))
    return info


def _fmt(diff: timedelta) -> str:
    secs = int(abs(diff.total_seconds()))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    parts = [f"{days} T"] if days else []
    parts.append(f"{hours} h {rem // 60} min")
    return ("+" if diff.total_seconds() > 0 else "−") + " ".join(parts)


async def run_exiftool(path: Path) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "exiftool", "-j", "-G", "-n", "-fast", "-api", "LargeFileSupport=1",
        "-time:all", "-GPSDateTime", "-GPSDateStamp", "-GPSTimeStamp", "-SerialNumber",
        "-InternalSerialNumber", "-FileNumber", "-ImageNumber", "-OffsetTime*", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
    try:
        data = json.loads(out or b"[]")
    except json.JSONDecodeError:
        return {}
    return data[0] if data else {}
