"""Decision log: why the user accepted, rejected or changed a suggestion.

Every decision is stored with a snapshot of the suggestion and the asset at that moment, so the
log can be analysed later (per source, camera, issue, file-name pattern …) without the live tables.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime

from . import __version__
from .db import Database, now_iso

log_ = logging.getLogger(__name__)

# code -> (label, actions where the reason is offered in the UI)
REASONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "correct": ("Vorschlag stimmt", ("applied",)),
    "close_enough": ("Passt ungefähr", ("applied", "manual")),
    "old_correct": ("Altes Datum war richtig", ("rejected", "reverted")),
    "wrong": ("Vorschlag falsch", ("rejected", "reverted", "manual")),
    "wrong_day": ("Richtiges Jahr, falscher Tag", ("rejected", "reverted", "manual")),
    "bad_source": ("Quelle passt nicht (z. B. Album/Nachbar)", ("rejected", "reverted", "manual")),
    "timezone": ("Zeitzone", ("applied", "rejected", "reverted", "manual")),
    "not_capture": ("Datum ist Scan-/Download-/Weiterleitungsdatum, nicht Aufnahme", ("applied", "manual")),
    "dont_care": ("Bild ist mir egal (Meme, Screenshot, fremd)", ("applied", "rejected")),
    "unsure": ("Unsicher – später", ("applied", "rejected", "reverted")),
}
# Set by the system, never chosen in the UI.
SYSTEM_REASONS = {"auto": "Automatisch übernommen", "unbekannt": "Unbekannt (vor 0.1.1)"}
_LABELS = {c: label for c, (label, _) in REASONS.items()} | SYSTEM_REASONS
ACTIONS = ("applied", "auto_applied", "rejected", "reverted", "manual", "camera_shift")
NOTE_MAX = 500


def reason_labels() -> list[dict]:
    return [{"code": c, "label": label, "actions": list(acts)} for c, (label, acts) in REASONS.items()]


def name_pattern(name: str | None) -> str | None:
    """`IMG-20190301-WA0004.jpg` -> `IMG-########-WA####.jpg` – groups files by naming scheme."""
    return re.sub(r"\d", "#", name) if name else None


def _days(a: str | None, b: str | None) -> float | None:
    try:
        return round((datetime.fromisoformat(a[:19]) - datetime.fromisoformat(b[:19])).total_seconds() / 86400, 3)
    except (TypeError, ValueError):
        return None


def snapshot(db: Database, user_id: str, s: dict) -> dict:
    """Features of a suggestion row (and its asset) worth learning from. Never raises."""
    try:
        return _snapshot(db, user_id, s)
    except Exception:  # noqa: BLE001 - a broken asset row must not block the decision itself
        log_.exception("Snapshot für Vorschlag %s fehlgeschlagen", s.get("id"))
        return {"source": s.get("source"), "confidence": s.get("confidence"), "proposed": s.get("proposed"),
                "previous_date": s.get("previous_date"), "app_version": __version__, "snapshot_error": True}


def _snapshot(db: Database, user_id: str, s: dict) -> dict:
    a = db.one("SELECT file_name, path, type, make, model, issues, category, data FROM assets "
               "WHERE user_id=? AND id=?", (user_id, s["asset_id"])) or {}
    data = json.loads(a["data"]) if a.get("data") else {}
    exif = data.get("exifInfo") or {}
    features = {
        "source": s["source"],
        "confidence": s["confidence"],
        "proposed": s["proposed"],
        "previous_date": s["previous_date"],
        "precision": s["precision"],
        "range_start": s.get("range_start"),
        "range_end": s.get("range_end"),
        "delta_days": _days(s["proposed"], s["previous_date"]),
        "explanation": s["explanation"],
        "suggested_at": s.get("created_at"),
        "file_name": a.get("file_name"),
        "name_pattern": name_pattern(a.get("file_name")),
        "folder": os.path.basename(os.path.dirname(a["path"])) if a.get("path") else None,
        "type": a.get("type"),
        "make": a.get("make"),
        "model": a.get("model"),
        "issues": json.loads(a["issues"]) if a.get("issues") else [],
        "category": a.get("category"),
        "has_gps": exif.get("latitude") is not None,
        "uploaded_at": data.get("createdAt"),
        "app_version": __version__,
    }
    if s["source"] == "claude":
        features["claude_model"] = db.scalar(
            "SELECT model FROM claude_usage WHERE user_id=? AND asset_id=? AND created_at<=? "
            "ORDER BY id DESC LIMIT 1", (user_id, s["asset_id"], s.get("created_at") or now_iso()))
    return features


def log(db: Database, user_id: str, s: dict, action: str, reason: str | None = None, note: str | None = None,
        features: dict | None = None, ts: str | None = None) -> None:
    db.execute(
        "INSERT INTO decisions(ts, user_id, suggestion_id, asset_id, action, reason, note, features) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (ts or now_iso(), user_id, s["id"], s["asset_id"], action, reason,
         (note or "").strip()[:NOTE_MAX] or None,
         json.dumps(features if features is not None else snapshot(db, user_id, s), ensure_ascii=False)),
    )


def backfill(db: Database) -> int:
    """Log decisions made before the log existed (reason `unbekannt`). Idempotent."""
    total = 0
    while True:
        rows = db.all(
            "SELECT * FROM suggestions s WHERE status IN ('applied','auto_applied','rejected','reverted') "
            "AND NOT EXISTS (SELECT 1 FROM decisions d WHERE d.suggestion_id=s.id) ORDER BY id LIMIT 1000")
        if not rows:
            return total
        with db.tx():
            for s in rows:
                action = s["status"]
                if action == "applied" and s["source"] in ("manual", "camera_shift"):
                    action = s["source"]
                features = snapshot(db, s["user_id"], s) | {"backfilled": True}
                if action != "rejected":
                    # The asset row already shows the corrected state – its issues say nothing about before.
                    features |= {"issues": None, "category": None}
                log(db, s["user_id"], s, action, "auto" if action == "auto_applied" else "unbekannt",
                    features=features, ts=s["applied_at"] or s["created_at"])
        total += len(rows)


def export(db: Database, user_id: str | None = None) -> Iterator[str]:
    """JSON lines, oldest first – one decision per line, features inlined."""
    where, params = ("WHERE user_id=?", (user_id,)) if user_id else ("", ())
    last = 0
    while True:  # paged so a large log never sits in memory at once
        rows = db.all(f"SELECT * FROM decisions {where} {'AND' if where else 'WHERE'} id>? ORDER BY id LIMIT 1000",
                      (*params, last))
        if not rows:
            return
        for r in rows:
            r["reason_label"] = _LABELS.get(r["reason"]) if r["reason"] else None
            r["features"] = json.loads(r["features"])
            yield json.dumps(r, ensure_ascii=False) + "\n"
        last = rows[-1]["id"]


def stats(db: Database, user_id: str) -> dict:
    """Acceptance per source, camera and issue, based on the latest decision per suggestion."""
    rows = db.all(
        "SELECT d.action, d.reason, d.features FROM decisions d JOIN ("
        "  SELECT MAX(id) id FROM decisions WHERE user_id=? GROUP BY COALESCE(suggestion_id, -id)"
        ") last ON last.id=d.id", (user_id,))
    groups: dict[str, dict[str, dict[str, int]]] = {k: defaultdict(lambda: defaultdict(int))
                                                     for k in ("source", "camera", "issue", "pattern")}
    reasons: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        f = json.loads(r["features"])
        outcome = {"applied": "accepted", "auto_applied": "auto", "rejected": "rejected",
                   "reverted": "rejected"}.get(r["action"], "manual")
        camera = " ".join(x for x in (f.get("make"), f.get("model")) if x) or "ohne Kamera"
        issues = f.get("issues")
        keys = {"source": [f.get("source") or "?"], "camera": [camera],
                "issue": [] if issues is None else issues or ["keins"],  # None = unknown (backfilled)
                "pattern": [f.get("name_pattern") or "?"]}
        for dim, values in keys.items():
            for v in values:
                groups[dim][v][outcome] += 1
        reasons[(r["action"], r["reason"] or "keiner")] += 1

    def table(dim: str) -> list[dict]:
        out = []
        for key, c in groups[dim].items():
            decided = c["accepted"] + c["rejected"]
            out.append({"key": key, "accepted": c["accepted"], "rejected": c["rejected"], "auto": c["auto"],
                        "manual": c["manual"], "rate": round(c["accepted"] / decided, 3) if decided else None})
        return sorted(out, key=lambda x: -(x["accepted"] + x["rejected"] + x["auto"] + x["manual"]))[:50]

    labels = _LABELS | {"keiner": "Ohne Grund"}
    return {
        "total": len(rows),
        "bySource": table("source"), "byCamera": table("camera"), "byIssue": table("issue"),
        "byPattern": table("pattern"),
        "reasons": sorted(({"action": a, "reason": r, "label": labels.get(r, r), "count": n}
                           for (a, r), n in reasons.items()), key=lambda x: -x["count"]),
    }
