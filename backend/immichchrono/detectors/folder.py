"""Derive coarse dates from folder names such as /Urlaub 2014/ or /2014/07/."""

from __future__ import annotations

import re
from datetime import datetime

from ..model import Candidate, plausible

_MONTHS = {
    "jan": 1, "januar": 1, "january": 1, "feb": 2, "februar": 2, "february": 2, "mär": 3, "maerz": 3,
    "märz": 3, "mar": 3, "march": 3, "apr": 4, "april": 4, "mai": 5, "may": 5, "jun": 6, "juni": 6,
    "june": 6, "jul": 7, "juli": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "okt": 10, "oct": 10, "oktober": 10, "october": 10, "nov": 11, "november": 11,
    "dez": 12, "dec": 12, "dezember": 12, "december": 12,
}

_FULL = re.compile(r"(?:^|[^0-9])((?:19|20)\d\d)[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])(?:[^0-9]|$)")
_YM = re.compile(r"(?:^|[^0-9])((?:19|20)\d\d)[-_. ](0[1-9]|1[0-2])(?:[^0-9]|$)")
_YEAR = re.compile(r"(?:^|[^0-9])((?:19|20)\d\d)(?:[^0-9]|$)")
_MONTH_WORD = re.compile(r"(?i)\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b\.?\s*((?:19|20)\d\d)")

# Path segments Immich itself generates (upload/<user>/<aa>/<bb>/...) carry no meaning.
_IGNORED = re.compile(r"^(upload|library|thumbs|encoded-video|[0-9a-f]{2}|[0-9a-f-]{36})$", re.I)


def detect(original_path: str, now: datetime | None = None) -> Candidate | None:
    parts = [p for p in re.split(r"[\\/]", original_path or "")[:-1] if p and not _IGNORED.match(p)]
    if not parts:
        return None
    # Walk from the innermost folder outwards; the innermost meaningful hint wins,
    # but an outer year folder combined with an inner month folder is understood.
    year: int | None = None
    month: int | None = None
    for seg in reversed(parts):
        if m := _FULL.search(seg):
            when = datetime(int(m[1]), int(m[2]), int(m[3]), 12)
            if plausible(when, now):
                return _cand(when, "day", 0.75, seg)
        if m := _YM.search(seg):
            when = datetime(int(m[1]), int(m[2]), 15, 12)
            if plausible(when, now):
                return _cand(when, "month", 0.7, seg)
        if m := _MONTH_WORD.search(seg):
            when = datetime(int(m[2]), _MONTHS[m[1].lower()], 15, 12)
            if plausible(when, now):
                return _cand(when, "month", 0.7, seg)
        if month is None and (mm := re.fullmatch(r"(0[1-9]|1[0-2])(?:[ _.-].*)?", seg)):
            month = int(mm[1])
            continue
        if m := _YEAR.search(seg):
            year = int(m[1])
            if month:
                when = datetime(year, month, 15, 12)
                if plausible(when, now):
                    return _cand(when, "month", 0.7, "/".join(parts[-2:]))
            when = datetime(year, 7, 1, 12)
            if plausible(when, now):
                return _cand(when, "year", 0.6, seg)
    return None


def _cand(when: datetime, precision: str, confidence: float, seg: str) -> Candidate:
    return Candidate(
        source="folder", when=when, precision=precision, confidence=confidence,
        explanation=f"Ordnername „{seg}“",
    )
