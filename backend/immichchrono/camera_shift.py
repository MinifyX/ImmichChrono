"""Shift all dates of one camera in a time window by a fixed offset (wrong camera clock)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from .dates import current_local
from .db import Database


def affected(db: Database, user_id: str, make: str | None, model: str | None,
             start: datetime | None, end: datetime | None) -> list[dict]:
    rows = db.all(
        "SELECT data FROM assets WHERE user_id=? AND IFNULL(make,'')=? AND IFNULL(model,'')=? ORDER BY local_dt",
        (user_id, make or "", model or ""),
    )
    out = []
    for r in rows:
        a = json.loads(r["data"])
        cur = current_local(a)
        if cur is None or (start and cur < start) or (end and cur > end):
            continue
        out.append(a)
    return out


def offset_from_reference(reference: dict, true_local: datetime) -> timedelta:
    cur = current_local(reference)
    if cur is None:
        raise ValueError("Referenzbild hat kein Datum")
    return true_local - cur
