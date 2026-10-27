"""Detectors that infer a date from *other* assets: duplicates, camera sequences, similar images."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..model import Candidate

_SEQ = re.compile(
    r"(?i)^(?:img|dsc|dscf|dscn|dsc_|_dsc|imgp|p\d{3}|pict|cimg|sam|gopr|gp\d\d|dji|mvi|_mg|_igp)_?(\d{3,5})"
)


@dataclass
class Ref:
    """A reference asset with a trusted date (naive local)."""

    id: str
    when: datetime
    file_name: str = ""
    camera: str = ""


def sequence_number(file_name: str) -> int | None:
    m = _SEQ.match(file_name)
    return int(m[1]) if m else None


def from_duplicates(asset_id: str, group: list[Ref]) -> Candidate | None:
    others = [r for r in group if r.id != asset_id]
    if not others:
        return None
    best = others[0]
    return Candidate(
        source="duplicate", when=best.when, precision="second", confidence=0.95,
        explanation=f"Duplikat „{best.file_name}“ hat ein verlässliches Aufnahmedatum",
    )


def from_sequence(number: int, camera_refs: list[tuple[int, Ref]], max_gap: int = 40) -> Candidate | None:
    """Interpolate between the nearest trusted frames of the same camera by file number.

    ``camera_refs`` must be sorted by sequence number.
    """
    before = [(n, r) for n, r in camera_refs if n < number and number - n <= max_gap]
    after = [(n, r) for n, r in camera_refs if n > number and n - number <= max_gap]
    if not before or not after:
        return None
    (n1, r1), (n2, r2) = before[-1], after[0]
    span = r2.when - r1.when
    if span < timedelta(0) or span > timedelta(days=4):
        return None
    when = r1.when + span * ((number - n1) / (n2 - n1))
    precision = "hour" if span <= timedelta(hours=6) else "day"
    return Candidate(
        source="sequence", when=when.replace(microsecond=0), precision=precision,
        confidence=0.85 if span <= timedelta(hours=6) else 0.75,
        explanation=f"Liegt in der Bildnummernfolge zwischen „{r1.file_name}“ und „{r2.file_name}“",
        range_start=r1.when, range_end=r2.when,
    )


def from_similar(refs: list[Ref]) -> Candidate | None:
    """Cluster the dates of visually similar trusted images (from Immich's CLIP search)."""
    if len(refs) < 3:
        return None
    dates = sorted(r.when for r in refs)
    med = dates[len(dates) // 2]
    for span, precision, conf in ((timedelta(days=2), "day", 0.65), (timedelta(days=45), "month", 0.5),
                                  (timedelta(days=400), "year", 0.4)):
        close = [d for d in dates if abs(d - med) <= span]
        if len(close) >= max(3, len(dates) * 0.6):
            ts = statistics.median(d.timestamp() for d in close)
            return Candidate(
                source="similar", when=datetime.fromtimestamp(ts).replace(microsecond=0),
                precision=precision, confidence=conf,
                explanation=f"{len(close)} von {len(dates)} ähnlichen Bildern stammen aus diesem Zeitraum",
                range_start=close[0], range_end=close[-1],
            )
    return None
