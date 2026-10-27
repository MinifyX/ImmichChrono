"""Pick the best candidate per asset and decide whether a change is needed at all."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from ..model import PRECISIONS, Candidate, to_local, tolerance, window

# Base trust per source, used to break ties between equally confident candidates.
SOURCE_RANK = {
    "manual": 10, "gps": 9, "exif_deep": 8, "duplicate": 8, "filename": 7, "claude": 6, "sequence": 5,
    "ollama": 4, "ocr": 4, "folder": 3, "similar": 2,
}


def agrees(a: Candidate, b: Candidate, tz: ZoneInfo | None) -> bool:
    coarse = max(a.precision, b.precision, key=PRECISIONS.index)
    la, lb = to_local(a.when, tz), to_local(b.when, tz)
    if coarse in ("month", "year", "decade", "day"):
        sa, ea = window(la, coarse)
        return sa <= lb <= ea or window(lb, coarse)[0] <= la <= window(lb, coarse)[1]
    return abs(la - lb) <= tolerance(coarse)


def matches_current(c: Candidate, current_local: datetime | None, tz: ZoneInfo | None) -> bool:
    if current_local is None:
        return False
    local = to_local(c.when, tz)
    if c.precision in ("day", "month", "year", "decade"):
        start, end = window(local, c.precision)
        if c.range_start and c.range_end:
            start, end = min(start, c.range_start), max(end, c.range_end)
        return start <= current_local <= end
    return abs(local - current_local) <= tolerance(c.precision)


def best(candidates: list[Candidate], tz: ZoneInfo | None) -> Candidate | None:
    if not candidates:
        return None
    for c in candidates:
        c.agreeing = [o.source for o in candidates if o is not c and o.source != c.source and agrees(c, o, tz)]
    def score(c: Candidate) -> tuple[float, int, int]:
        boosted = min(0.99, c.confidence + 0.04 * len(set(c.agreeing)))
        return boosted, -PRECISIONS.index(c.precision), SOURCE_RANK.get(c.source, 0)
    top = max(candidates, key=score)
    if top.agreeing:
        top.confidence = round(min(0.99, top.confidence + 0.04 * len(set(top.agreeing))), 2)
        top.explanation += f" (bestätigt durch: {', '.join(sorted(set(top.agreeing)))})"
    return top
