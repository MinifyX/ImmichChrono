"""Core value types shared by all detectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

# Precision levels, finest first. A candidate with a coarse precision only says
# "the photo was taken somewhere in this window".
PRECISIONS = ("second", "minute", "hour", "day", "month", "year", "decade")

# Sources whose results are trustworthy enough for automatic application.
AUTO_SOURCES = frozenset({"gps", "exif_deep", "filename", "duplicate"})
AUTO_MIN_CONFIDENCE = 0.93


@dataclass
class Candidate:
    """A guess for the real capture date of one asset.

    ``when`` is either timezone-aware (an absolute instant, e.g. from GPS) or naive,
    meaning local wall-clock time at the place the photo was taken.
    """

    source: str
    when: datetime
    precision: str
    confidence: float
    explanation: str
    range_start: datetime | None = None
    range_end: datetime | None = None
    agreeing: list[str] = field(default_factory=list)

    @property
    def auto_safe(self) -> bool:
        return (
            self.source in AUTO_SOURCES
            and self.precision in ("second", "minute")
            and self.confidence >= AUTO_MIN_CONFIDENCE
        )


def tolerance(precision: str) -> timedelta:
    return {
        "second": timedelta(minutes=2),
        "minute": timedelta(minutes=3),
        "hour": timedelta(hours=1, minutes=5),
        "day": timedelta(days=1),
        "month": timedelta(days=31),
        "year": timedelta(days=366),
        "decade": timedelta(days=3660),
    }[precision]


def window(when: datetime, precision: str) -> tuple[datetime, datetime]:
    """Calendar window covered by a coarse date (naive local)."""
    w = when.replace(tzinfo=None)
    if precision == "decade":
        start = datetime(w.year - w.year % 10, 1, 1)
        return start, datetime(start.year + 10, 1, 1) - timedelta(seconds=1)
    if precision == "year":
        return datetime(w.year, 1, 1), datetime(w.year + 1, 1, 1) - timedelta(seconds=1)
    if precision == "month":
        start = datetime(w.year, w.month, 1)
        nxt = datetime(w.year + (w.month == 12), w.month % 12 + 1, 1)
        return start, nxt - timedelta(seconds=1)
    if precision == "day":
        start = datetime(w.year, w.month, w.day)
        return start, start + timedelta(days=1) - timedelta(seconds=1)
    tol = tolerance(precision)
    return w - tol, w + tol


def zone(name: str | None, fallback: str) -> ZoneInfo | None:
    """Resolve Immich's timeZone strings ("Europe/Berlin", "UTC+2", "UTC-05:30")."""
    for candidate in (name, fallback):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except (KeyError, ValueError):
            pass
        if candidate.upper().startswith("UTC") and len(candidate) > 3:
            try:
                sign = -1 if candidate[3] == "-" else 1
                hh, _, mm = candidate[4:].partition(":")
                minutes = sign * (int(hh) * 60 + int(mm or 0))
                # Etc/GMT zones have inverted signs and only whole hours.
                if minutes % 60 == 0:
                    return ZoneInfo(f"Etc/GMT{'+' if minutes < 0 else '-'}{abs(minutes) // 60}")
            except (ValueError, KeyError):
                pass
    return None


def to_local(when: datetime, tz: ZoneInfo | None) -> datetime:
    """Convert to naive local wall-clock time."""
    if when.tzinfo is None:
        return when
    return (when.astimezone(tz) if tz else when.astimezone(UTC)).replace(tzinfo=None)


def to_aware(when: datetime, tz: ZoneInfo | None) -> datetime:
    if when.tzinfo is not None:
        return when.astimezone(tz) if tz else when
    return when.replace(tzinfo=tz or UTC)


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def plausible(when: datetime, now: datetime | None = None) -> bool:
    now = now or datetime.now()
    return datetime(1826, 1, 1) <= when.replace(tzinfo=None) <= now + timedelta(days=2)
