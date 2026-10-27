"""Persisting, applying and undoing date suggestions."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from . import decisions
from .config import settings
from .dates import asset_zone, current_iso, to_write_iso
from .db import Database, now_iso
from .immich import Immich, ImmichError
from .model import Candidate, to_local

OPEN = ("pending",)


def store(db: Database, user_id: str, asset: dict, cand: Candidate) -> int | None:
    """Insert a suggestion unless an equivalent one exists or was rejected before."""
    tz = asset_zone(asset, settings.default_tz)
    proposed = to_write_iso(cand.when, tz)
    existing = db.all(
        "SELECT id, proposed, status, source FROM suggestions WHERE user_id=? AND asset_id=? "
        "AND status IN ('pending','rejected')",
        (user_id, asset["id"]),
    )
    for row in existing:
        if row["proposed"] == proposed:
            return None if row["status"] == "rejected" else row["id"]
    for row in existing:
        if row["status"] == "pending" and row["source"] not in ("manual", "claude"):
            db.execute("UPDATE suggestions SET status='superseded' WHERE id=?", (row["id"],))
    cur = db.execute(
        "INSERT INTO suggestions(user_id, asset_id, source, proposed, precision, range_start, range_end, "
        "confidence, explanation, status, previous_date, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            user_id, asset["id"], cand.source, proposed, cand.precision,
            to_local(cand.range_start, tz).isoformat() if cand.range_start else None,
            to_local(cand.range_end, tz).isoformat() if cand.range_end else None,
            round(cand.confidence, 3), cand.explanation, "pending",
            current_iso(asset, settings.default_tz), now_iso(),
        ),
    )
    return cur.lastrowid


async def apply(db: Database, immich: Immich, user_id: str, ids: list[int], *, auto: bool = False,
                reason: str | None = None, note: str | None = None) -> dict:
    rows = db.all(
        f"SELECT * FROM suggestions WHERE user_id=? AND status='pending' AND id IN ({','.join('?' * len(ids))})",
        (user_id, *ids),
    ) if ids else []
    sem = asyncio.Semaphore(4)
    ok, failed = 0, []

    async def one(row: dict) -> None:
        nonlocal ok
        features = decisions.snapshot(db, user_id, row)  # before the asset is marked as fixed
        async with sem:
            try:
                updated = await immich.update_date(row["asset_id"], row["proposed"])
            except ImmichError as e:
                failed.append({"id": row["id"], "error": str(e)})
                return
        db.execute(
            "UPDATE suggestions SET status=?, applied_at=? WHERE id=?",
            ("auto_applied" if auto else "applied", now_iso(), row["id"]),
        )
        # Other open suggestions for this asset are obsolete now.
        db.execute(
            "UPDATE suggestions SET status='superseded' WHERE user_id=? AND asset_id=? AND status='pending'",
            (user_id, row["asset_id"]),
        )
        _refresh_asset(db, user_id, row["asset_id"], updated, row["proposed"])
        action = "auto_applied" if auto else row["source"] if row["source"] in ("manual", "camera_shift") else "applied"
        decisions.log(db, user_id, row, action, "auto" if auto else reason, note, features)
        ok += 1

    await asyncio.gather(*(one(r) for r in rows))
    return {"applied": ok, "failed": failed}


def reject(db: Database, user_id: str, ids: list[int], reason: str | None = None, note: str | None = None) -> int:
    rows = db.all(
        f"SELECT * FROM suggestions WHERE user_id=? AND status='pending' AND id IN ({','.join('?' * len(ids))})",
        (user_id, *ids),
    ) if ids else []
    done = 0
    with db.tx():
        for row in rows:
            # Status check again inside the transaction: a parallel apply may have won meanwhile.
            if db.execute("UPDATE suggestions SET status='rejected' WHERE id=? AND status='pending'",
                          (row["id"],)).rowcount:
                decisions.log(db, user_id, row, "rejected", reason, note)
                done += 1
    return done


async def undo(db: Database, immich: Immich, user_id: str, suggestion_id: int, reason: str | None = None,
               note: str | None = None) -> None:
    row = db.one("SELECT * FROM suggestions WHERE user_id=? AND id=?", (user_id, suggestion_id))
    if not row or row["status"] not in ("applied", "auto_applied") or not row["previous_date"]:
        raise ValueError("Diese Änderung kann nicht rückgängig gemacht werden")
    updated = await immich.update_date(row["asset_id"], row["previous_date"])
    db.execute("UPDATE suggestions SET status='reverted' WHERE id=?", (suggestion_id,))
    # Same features as when it was applied – the asset row now looks "fixed".
    prev = db.scalar("SELECT features FROM decisions WHERE suggestion_id=? ORDER BY id DESC LIMIT 1", (suggestion_id,))
    decisions.log(db, user_id, row, "reverted", reason, note, json.loads(prev) if prev else None)
    _refresh_asset(db, user_id, row["asset_id"], updated, row["previous_date"])


def create_manual(db: Database, user_id: str, asset: dict, when: datetime, note: str, source: str = "manual") -> int:
    cand = Candidate(source=source, when=when, precision="second", confidence=1.0, explanation=note)
    sid = store(db, user_id, asset, cand)
    if sid is None:  # previously rejected identical date – the user now explicitly wants it
        db.execute(
            "UPDATE suggestions SET status='pending', source=? WHERE user_id=? AND asset_id=? AND proposed=?",
            (source, user_id, asset["id"], to_write_iso(when, asset_zone(asset, settings.default_tz))),
        )
        sid = db.scalar(
            "SELECT id FROM suggestions WHERE user_id=? AND asset_id=? AND status='pending' ORDER BY id DESC",
            (user_id, asset["id"]),
        )
    return int(sid)


def _refresh_asset(db: Database, user_id: str, asset_id: str, updated: dict | None, iso: str) -> None:
    row = db.one("SELECT data FROM assets WHERE user_id=? AND id=?", (user_id, asset_id))
    if not row:
        return
    data = json.loads(row["data"])
    local = iso[:19]
    # Immich re-extracts metadata asynchronously, so the response may still carry the old value.
    data["localDateTime"] = f"{local}.000Z"
    data.setdefault("exifInfo", {})["dateTimeOriginal"] = iso
    db.execute(
        "UPDATE assets SET data=?, local_dt=?, date_original=?, category='fixed' WHERE user_id=? AND id=?",
        (json.dumps(data), data["localDateTime"], iso, user_id, asset_id),
    )
