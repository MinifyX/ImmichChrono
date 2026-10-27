"""Derive capture dates from file names such as IMG_20190714_153000.jpg."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from ..model import Candidate, plausible

_Y = r"(?P<y>(?:19|20)\d\d)"
_M = r"(?P<m>0[1-9]|1[0-2])"
_D = r"(?P<d>0[1-9]|[12]\d|3[01])"
_HMS = r"(?P<H>[01]\d|2[0-3])(?P<sep>[.:\-_]?)(?P<Mi>[0-5]\d)(?P=sep)(?P<S>[0-5]\d)"

# (pattern, confidence, label). Ordered from most to least specific.
_PATTERNS: list[tuple[re.Pattern[str], float, str]] = [
    (
        re.compile(rf"(?:screenshot|bildschirmfoto|screen shot)[ _\-]*{_Y}-{_M}-{_D}"
                   rf"(?: um| at|[ _\-])+(?P<H>\d{{1,2}})[.:\-](?P<Mi>[0-5]\d)[.:\-](?P<S>[0-5]\d)"
                   r"(?:\s*(?P<ampm>[ap]\.?m\.?))?", re.I),
        0.97, "Screenshot-Dateiname",
    ),
    (
        re.compile(rf"screenshot[_\-]{_Y}{_M}{_D}[_\-]{_HMS}", re.I),
        0.97, "Screenshot-Dateiname",
    ),
    (
        re.compile(rf"whatsapp (?:image|video|bild|audio) {_Y}-{_M}-{_D} (?:at|um) "
                   r"(?P<H>\d{1,2})\.(?P<Mi>[0-5]\d)\.(?P<S>[0-5]\d)(?:\s*(?P<ampm>[ap]m))?", re.I),
        0.85, "WhatsApp-Empfangszeit",
    ),
    (
        re.compile(rf"signal-{_Y}-{_M}-{_D}-(?P<H>[01]\d|2[0-3])-?(?P<Mi>[0-5]\d)-?(?P<S>[0-5]\d)", re.I),
        0.85, "Signal-Empfangszeit",
    ),
    (
        re.compile(rf"photo_{_Y}-{_M}-{_D}_(?P<H>[01]\d|2[0-3])-(?P<Mi>[0-5]\d)-(?P<S>[0-5]\d)", re.I),
        0.85, "Telegram-Empfangszeit",
    ),
    (
        re.compile(rf"(?:^|[^0-9])(?:img|vid|pxl|pano|mvimg|burst|dji|mov|photo|video|rec|trim)?"
                   rf"[_\-]?{_Y}{_M}{_D}[_\-]?{_HMS}", re.I),
        0.95, "Kamera-Dateiname",
    ),
    (
        re.compile(rf"(?:^|[^0-9]){_Y}-{_M}-{_D}[ _T]{_HMS}", re.I),
        0.93, "Datum und Uhrzeit im Dateinamen",
    ),
    (
        re.compile(rf"(?:img|vid|aud|ptt|doc)-{_Y}{_M}{_D}-wa\d+", re.I),
        0.85, "WhatsApp-Empfangstag",
    ),
    (
        re.compile(rf"(?:^|[^0-9]){_Y}[-_.]?{_M}[-_.]?{_D}(?:[^0-9]|$)"),
        0.7, "Datum im Dateinamen",
    ),
    (
        re.compile(r"(?:^|[^0-9])(?P<ts>1[2-9]\d{8}(?:\d{3})?)(?:[^0-9]|$)"),
        0.6, "Unix-Zeitstempel im Dateinamen",
    ),
]


def detect(file_name: str, now: datetime | None = None) -> Candidate | None:
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    for pattern, confidence, label in _PATTERNS:
        m = pattern.search(stem)
        if not m:
            continue
        g = m.groupdict()
        try:
            if g.get("ts"):
                ts = int(g["ts"])
                when = datetime.fromtimestamp(ts / 1000 if ts > 10**11 else ts, UTC)
                precision = "second"
            else:
                hour = int(g["H"]) if g.get("H") else 0
                ampm = (g.get("ampm") or "").lower().replace(".", "")
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                when = datetime(
                    int(g["y"]), int(g["m"]), int(g["d"]),
                    hour, int(g.get("Mi") or 0), int(g.get("S") or 0),
                )
                precision = "second" if g.get("H") else "day"
                if precision == "day":
                    when = when.replace(hour=12)
        except (ValueError, OverflowError):
            continue
        if not plausible(when, now) or when.year < 1990:
            continue
        if precision == "second" and stem.upper().startswith("PXL_") and when.tzinfo is None:
            when = when.replace(tzinfo=UTC)  # Pixel phones name files in UTC
        return Candidate(
            source="filename",
            when=when,
            precision=precision,
            confidence=confidence,
            explanation=f"{label}: „{m.group(0).strip(' _-')}“",
        )
    return None
