"""Find dates in text Immich's OCR recognised in the image (date stamps, screenshots, documents)."""

from __future__ import annotations

import re
from datetime import datetime

from ..model import Candidate, plausible

_MONTHS = {
    "januar": 1, "jänner": 1, "january": 1, "jan": 1, "februar": 2, "february": 2, "feb": 2,
    "märz": 3, "maerz": 3, "march": 3, "mär": 3, "mar": 3, "april": 4, "apr": 4, "mai": 5, "may": 5,
    "juni": 6, "june": 6, "jun": 6, "juli": 7, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "oktober": 10, "october": 10, "okt": 10, "oct": 10,
    "november": 11, "nov": 11, "dezember": 12, "december": 12, "dez": 12, "dec": 12,
}
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))

# Analog camera date imprints: '98 7 14 / 7 14 '98 / 14 7 '98
_STAMP_YMD = re.compile(r"[’'`´]\s?(\d\d)\s+(\d{1,2})\s+(\d{1,2})(?!\d)")
_STAMP_DMY = re.compile(r"(?<!\d)(\d{1,2})\s+(\d{1,2})\s+[’'`´]\s?(\d\d)(?!\d)")
_DMY = re.compile(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d\d|\d\d)(?![\d./])")
_YMD = re.compile(r"(?<!\d)((?:19|20)\d\d)-(\d\d)-(\d\d)(?!\d)")
_D_MON_Y = re.compile(rf"(?i)(?<!\d)(\d{{1,2}})\.?\s+({_MON})\.?\s+((?:19|20)\d\d)")
_MON_D_Y = re.compile(rf"(?i)\b({_MON})\.?\s+(\d{{1,2}}),?\s+((?:19|20)\d\d)")
_MON_Y = re.compile(rf"(?i)\b({_MON})\.?\s+((?:19|20)\d\d)\b")


def _year(two_or_four: str) -> int:
    y = int(two_or_four)
    if y >= 100:
        return y
    return 1900 + y if y > 30 else 2000 + y


def _mk(y: int, m: int, d: int) -> datetime | None:
    try:
        return datetime(y, m, d, 12)
    except ValueError:
        return None


def find_dates(text: str, now: datetime | None = None) -> list[tuple[datetime, str, str, float]]:
    """Return (date, precision, matched text, confidence) tuples."""
    found: list[tuple[datetime, str, str, float]] = []

    def add(when: datetime | None, precision: str, raw: str, conf: float) -> None:
        if when and plausible(when, now) and when.year >= 1900:
            found.append((when, precision, raw, conf))

    for m in _STAMP_YMD.finditer(text):
        add(_mk(_year(m[1]), int(m[2]), int(m[3])), "day", m[0], 0.7)
    for m in _STAMP_DMY.finditer(text):
        a, b, y = int(m[1]), int(m[2]), _year(m[3])
        add(_mk(y, a, b) if a <= 12 else _mk(y, b, a), "day", m[0], 0.65)
    for m in _YMD.finditer(text):
        add(_mk(int(m[1]), int(m[2]), int(m[3])), "day", m[0], 0.6)
    for m in _DMY.finditer(text):
        add(_mk(_year(m[3]), int(m[2]), int(m[1])), "day", m[0], 0.55)
    for m in _D_MON_Y.finditer(text):
        add(_mk(int(m[3]), _MONTHS[m[2].lower()], int(m[1])), "day", m[0], 0.55)
    for m in _MON_D_Y.finditer(text):
        add(_mk(int(m[3]), _MONTHS[m[1].lower()], int(m[2])), "day", m[0], 0.55)
    if not found:
        for m in _MON_Y.finditer(text):
            add(_mk(int(m[2]), _MONTHS[m[1].lower()], 15), "month", m[0], 0.45)
    return found


def detect(ocr_rows: list[dict], now: datetime | None = None) -> Candidate | None:
    text = "\n".join(r.get("text", "") for r in ocr_rows if (r.get("textScore") or 1) >= 0.5)
    if not text.strip():
        return None
    dates = find_dates(text, now)
    if not dates:
        return None
    # Prefer analog stamps / highest confidence; with several different dates, the
    # latest one is the most likely "photo date" (documents often mention older dates).
    dates.sort(key=lambda t: (t[3], t[0]), reverse=True)
    when, precision, raw, conf = dates[0]
    distinct = {d[0].date() for d in dates}
    if len(distinct) > 1:
        conf -= 0.1
    return Candidate(
        source="ocr", when=when, precision=precision, confidence=round(conf, 2),
        explanation=f"Im Bild erkannter Text „{raw.strip()}“",
    )
