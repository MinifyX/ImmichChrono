from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import __version__, camera_shift, claude, decisions, ollama, scanner, suggestions
from .auth import COOKIE, User, create_session, current_user, get_db
from .config import settings
from .dates import asset_zone, current_local
from .db import Database, now_iso
from .detectors import combine
from .detectors.suspects import ISSUE_LABELS
from .immich import Immich, ImmichError

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Immich asset ids are UUIDs; restricting the alphabet keeps them from steering Immich request paths.
AssetId = Annotated[str, Path(pattern=r"^[0-9A-Za-z-]{1,64}$")]


def _has_session(request: Request, db: Database) -> bool:
    sid = request.cookies.get(COOKIE)
    return bool(sid and db.one("SELECT 1 FROM sessions WHERE id=? AND expires_at > ?", (sid, now_iso())))

# A reason code from decisions.REASONS (validated in the endpoints) plus optional free text.
ReasonCode = Annotated[str | None, Field(max_length=32, pattern=r"^[a-z_]+$")]
NoteText = Annotated[str | None, Field(max_length=decisions.NOTE_MAX)]


def _reason(code: str | None) -> str | None:
    if code is not None and code not in decisions.REASONS:
        raise HTTPException(422, "Unbekannter Grund")
    return code


DEFAULT_SETTINGS = {
    "auto_apply": True,
    "claude_model": None,
    "claude_budget_usd": 1.0,
    "ollama_enabled": True,
    "ollama_max_per_scan": 200,
}


def immich_for(user: User) -> Immich:
    return Immich(settings.immich_url, user.token)


def _asset(db: Database, user: User, asset_id: str) -> dict:
    row = db.one("SELECT data, issues, category FROM assets WHERE user_id=? AND id=?", (user.id, asset_id))
    if not row:
        raise HTTPException(404, "Unbekanntes Asset – bitte zuerst scannen")
    data = json.loads(row["data"])
    data["_issues"], data["_category"] = json.loads(row["issues"]), row["category"]
    return data


def _asset_view(a: dict) -> dict:
    exif = a.get("exifInfo") or {}
    return {
        "id": a["id"], "fileName": a.get("originalFileName"), "path": a.get("originalPath"), "type": a.get("type"),
        "localDateTime": (a.get("localDateTime") or "")[:19] or None, "timeZone": exif.get("timeZone"),
        "make": exif.get("make"), "model": exif.get("model"), "city": exif.get("city"),
        "country": exif.get("country"), "issues": a.get("_issues", []), "category": a.get("_category"),
    }


# --- auth ----------------------------------------------------------------
class LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response, db: Database = Depends(get_db)) -> dict:
    async with Immich(settings.immich_url) as immich:
        try:
            data = await immich.login(body.email, body.password)
        except ImmichError as e:
            raise HTTPException(401 if e.status in (400, 401) else 502, "Anmeldung fehlgeschlagen: " + str(e)) from e
    create_session(db, request, response, data)
    return {"id": data["userId"], "name": data.get("name"), "email": data.get("userEmail"),
            "isAdmin": data.get("isAdmin", False)}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db: Database = Depends(get_db)) -> dict:
    sid = request.cookies.get(COOKIE)
    if sid and (row := db.one("SELECT token FROM sessions WHERE id=?", (sid,))):
        async with Immich(settings.immich_url, row["token"]) as immich:
            await immich.logout()
        db.execute("DELETE FROM sessions WHERE id=?", (sid,))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/auth/me")
async def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "isAdmin": user.is_admin}


@router.get("/server")
async def server(request: Request, db: Database = Depends(get_db)) -> dict:
    version = None
    try:
        async with Immich(settings.immich_url) as immich:
            v = await immich.version()
            version = f"{v['major']}.{v['minor']}.{v['patch']}"
    except Exception:  # noqa: BLE001 - only informational
        pass
    return {
        "version": __version__, "immichVersion": version, "immichUrl": settings.public_url,
        "defaultTimeZone": settings.default_tz,
        "claude": {"configured": bool(settings.anthropic_api_key), "models": list(claude.MODELS),
                   "defaultModel": claude.model_name(None), "prices": claude.PRICES},
        # Ollama errors can contain internal addresses: details only for signed-in users.
        "ollama": await ollama.available() if _has_session(request, db) else {"configured": bool(settings.ollama_url)},
        "issueLabels": ISSUE_LABELS,
        "decisionReasons": decisions.reason_labels(),
    }


# --- settings --------------------------------------------------------------
@router.get("/settings")
def get_settings(user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    return {k: db.get_setting(user.id, k, v) for k, v in DEFAULT_SETTINGS.items()}


class SettingsBody(BaseModel):
    auto_apply: bool | None = None
    claude_model: str | None = None
    claude_budget_usd: float | None = Field(None, ge=0, le=100)
    ollama_enabled: bool | None = None
    ollama_max_per_scan: int | None = Field(None, ge=0, le=20000)


@router.put("/settings")
def put_settings(body: SettingsBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "claude_model" and v not in claude.MODELS:
            raise HTTPException(400, "Unbekanntes Modell")
        db.set_setting(user.id, k, v)
    return get_settings(user, db)


# --- summary / report ------------------------------------------------------
@router.get("/summary")
def summary(user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    cats = {r["category"] or "unscanned": r["n"] for r in db.all(
        "SELECT category, COUNT(*) n FROM assets WHERE user_id=? GROUP BY category", (user.id,))}
    issues: dict[str, int] = {}
    for r in db.all("SELECT issues FROM assets WHERE user_id=? AND issues != '[]'", (user.id,)):
        for i in json.loads(r["issues"]):
            issues[i] = issues.get(i, 0) + 1
    statuses = {r["status"]: r["n"] for r in db.all(
        "SELECT status, COUNT(*) n FROM suggestions WHERE user_id=? GROUP BY status", (user.id,))}
    sources = {r["source"]: r["n"] for r in db.all(
        "SELECT source, COUNT(*) n FROM suggestions WHERE user_id=? AND status='pending' GROUP BY source", (user.id,))}
    unresolved = db.scalar(
        "SELECT COUNT(*) FROM assets a WHERE a.user_id=? AND a.category NOT IN ('ok','fixed') AND NOT EXISTS "
        "(SELECT 1 FROM suggestions s WHERE s.user_id=a.user_id AND s.asset_id=a.id AND s.status='pending')",
        (user.id,),
    )
    last = db.one("SELECT * FROM jobs WHERE user_id=? AND kind LIKE '%scan' ORDER BY started_at DESC LIMIT 1",
                  (user.id,))
    spent = db.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM claude_usage WHERE user_id=?", (user.id,))
    return {
        "total": sum(cats.values()), "categories": cats, "issues": issues, "suggestions": statuses,
        "pendingBySource": sources, "unresolved": unresolved, "lastScan": _job_view(last) if last else None,
        "claudeSpentUsd": round(spent or 0, 4),
    }


# --- scans -----------------------------------------------------------------
def _job_view(row: dict) -> dict:
    return {**row, "stats": json.loads(row["stats"] or "{}")}


class ScanBody(BaseModel):
    full: bool = False


@router.post("/scans")
async def start_scan(body: ScanBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    job = scanner.start_scan(db, user.id, user.token, full=body.full)
    return _job_view(db.one("SELECT * FROM jobs WHERE id=?", (job.id,)))


@router.get("/scans")
def list_scans(user: User = Depends(current_user), db: Database = Depends(get_db)) -> list[dict]:
    return [_job_view(r) for r in db.all(
        "SELECT * FROM jobs WHERE user_id=? ORDER BY started_at DESC LIMIT 30", (user.id,))]


@router.get("/jobs/{job_id}")
def get_job(job_id: str, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    row = db.one("SELECT * FROM jobs WHERE id=? AND user_id=?", (job_id, user.id))
    if not row:
        raise HTTPException(404, "Job nicht gefunden")
    return _job_view(row)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    row = db.one("SELECT kind FROM jobs WHERE id=? AND user_id=?", (job_id, user.id))
    if not row:
        raise HTTPException(404, "Job nicht gefunden")
    ok = _cancel_claude(user.id, job_id) if row["kind"] == "claude" else scanner.cancel(user.id)
    return {"cancelled": ok}


# --- suggestions -------------------------------------------------------------
def _filter_sql(user_id: str, status: str, source: str | None, category: str | None, min_conf: float | None,
                max_conf: float | None, q: str | None) -> tuple[str, list]:
    where, params = ["s.user_id=?"], [user_id]
    if status == "history":
        where.append("s.status IN ('applied','auto_applied','reverted')")
    else:
        where.append("s.status=?")
        params.append(status)
    if source:
        where.append("s.source=?")
        params.append(source)
    if category:
        where.append("a.category=?")
        params.append(category)
    if min_conf is not None:
        where.append("s.confidence>=?")
        params.append(min_conf)
    if max_conf is not None:
        where.append("s.confidence<?")
        params.append(max_conf)
    if q:
        where.append("(a.file_name LIKE ? OR a.path LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    return " AND ".join(where), params


@router.get("/suggestions")
def list_suggestions(
    status: str = "pending", source: str | None = None, category: str | None = None,
    min_conf: float | None = None, max_conf: float | None = None, q: str | None = None,
    page: int = Query(1, ge=1), size: int = Query(60, ge=1, le=500),
    user: User = Depends(current_user), db: Database = Depends(get_db),
) -> dict:
    where, params = _filter_sql(user.id, status, source, category, min_conf, max_conf, q)
    base = f"FROM suggestions s JOIN assets a ON a.user_id=s.user_id AND a.id=s.asset_id WHERE {where}"
    total = db.scalar(f"SELECT COUNT(*) {base}", params)
    order = "s.applied_at DESC, s.id DESC" if status == "history" else "s.confidence DESC, s.id"
    rows = db.all(
        f"SELECT s.*, a.data, a.issues, a.category {base} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, size, (page - 1) * size],
    )
    items = []
    for r in rows:
        a = json.loads(r.pop("data"))
        a["_issues"], a["_category"] = json.loads(r.pop("issues")), r.pop("category")
        items.append({**r, "asset": _asset_view(a)})
    return {"items": items, "total": total, "page": page, "size": size}


class ReasonBody(BaseModel):
    reason: ReasonCode = None
    note: NoteText = None


class IdsBody(ReasonBody):
    ids: list[int] = Field(default_factory=list, max_length=20000)


class FilterBody(ReasonBody):
    source: str | None = None
    category: str | None = None
    min_conf: float | None = None
    max_conf: float | None = None
    q: str | None = None


@router.post("/suggestions/apply")
async def apply_suggestions(body: IdsBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    async with immich_for(user) as immich:
        return await suggestions.apply(db, immich, user.id, body.ids, reason=_reason(body.reason), note=body.note)


@router.post("/suggestions/apply-filter")
async def apply_filter(body: FilterBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    where, params = _filter_sql(user.id, "pending", body.source, body.category, body.min_conf, body.max_conf, body.q)
    ids = [r["id"] for r in db.all(
        f"SELECT s.id FROM suggestions s JOIN assets a ON a.user_id=s.user_id AND a.id=s.asset_id WHERE {where}",
        params)]
    reason = _reason(body.reason)
    async with immich_for(user) as immich:
        return await suggestions.apply(db, immich, user.id, ids, reason=reason, note=body.note)


@router.post("/suggestions/reject")
def reject(body: IdsBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    return {"rejected": suggestions.reject(db, user.id, body.ids, _reason(body.reason), body.note)}


@router.post("/suggestions/{suggestion_id}/undo")
async def undo(suggestion_id: int, body: ReasonBody | None = None, user: User = Depends(current_user),
               db: Database = Depends(get_db)) -> dict:
    body = body or ReasonBody()
    reason = _reason(body.reason)
    async with immich_for(user) as immich:
        try:
            await suggestions.undo(db, immich, user.id, suggestion_id, reason, body.note)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        except ImmichError as e:
            raise HTTPException(502, str(e)) from e
    return {"ok": True}


# --- assets ----------------------------------------------------------------
@router.get("/assets")
def list_assets(
    category: str | None = None, issue: str | None = None, unresolved: bool = False, q: str | None = None,
    page: int = Query(1, ge=1), size: int = Query(60, ge=1, le=500),
    user: User = Depends(current_user), db: Database = Depends(get_db),
) -> dict:
    where, params = ["a.user_id=?"], [user.id]
    if category:
        where.append("a.category=?")
        params.append(category)
    else:
        where.append("a.category NOT IN ('ok','fixed')")
    if issue:
        where.append("a.issues LIKE ?")
        params.append(f'%"{issue}"%')
    if unresolved:
        where.append("NOT EXISTS (SELECT 1 FROM suggestions s WHERE s.user_id=a.user_id AND s.asset_id=a.id "
                     "AND s.status='pending')")
    if q:
        where.append("(a.file_name LIKE ? OR a.path LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM assets a WHERE {w}", params)
    rows = db.all(f"SELECT data, issues, category FROM assets a WHERE {w} ORDER BY local_dt LIMIT ? OFFSET ?",
                  [*params, size, (page - 1) * size])
    items = []
    for r in rows:
        a = json.loads(r["data"])
        a["_issues"], a["_category"] = json.loads(r["issues"]), r["category"]
        items.append(_asset_view(a))
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/assets/{asset_id}")
def get_asset(asset_id: AssetId, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    a = _asset(db, user, asset_id)
    history = db.all("SELECT * FROM suggestions WHERE user_id=? AND asset_id=? ORDER BY id DESC", (user.id, asset_id))
    return {**_asset_view(a), "people": a.get("people", []), "fileCreatedAt": a.get("fileCreatedAt"),
            "uploadedAt": a.get("createdAt"), "suggestions": history,
            "immichLink": f"{settings.public_url}/photos/{asset_id}"}


@router.get("/assets/{asset_id}/thumbnail")
async def thumbnail(asset_id: AssetId, size: Literal["thumbnail", "preview"] = "thumbnail",
                    user: User = Depends(current_user)) -> Response:
    async with immich_for(user) as immich:
        try:
            r = await immich.thumbnail(asset_id, size)
        except ImmichError as e:
            raise HTTPException(e.status if e.status < 500 else 502, str(e)) from e
    return Response(r.content, media_type=r.headers.get("content-type", "image/jpeg"),
                    headers={"Cache-Control": "private, max-age=86400"})


class ManualBody(ReasonBody):
    date: datetime  # local wall-clock time
    apply: bool = True


@router.post("/assets/{asset_id}/manual")
async def manual(asset_id: AssetId, body: ManualBody, user: User = Depends(current_user),
                 db: Database = Depends(get_db)) -> dict:
    a = _asset(db, user, asset_id)
    reason = _reason(body.reason)
    sid = suggestions.create_manual(db, user.id, a, body.date.replace(tzinfo=None),
                                    body.note or "Manuell gesetzt")
    if not body.apply:
        return {"id": sid}
    async with immich_for(user) as immich:
        return {"id": sid, **await suggestions.apply(db, immich, user.id, [sid], reason=reason, note=body.note)}


# --- decision log -----------------------------------------------------------
@router.get("/decisions/stats")
def decision_stats(user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    return decisions.stats(db, user.id)


@router.get("/decisions/export")
def decision_export(user: User = Depends(current_user), db: Database = Depends(get_db)) -> StreamingResponse:
    return StreamingResponse(
        decisions.export(db, user.id), media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="immichchrono-entscheidungen.jsonl"'})


# --- camera clock tool ------------------------------------------------------
@router.get("/cameras")
def cameras(user: User = Depends(current_user), db: Database = Depends(get_db)) -> list[dict]:
    return db.all(
        "SELECT make, model, COUNT(*) count, MIN(local_dt) first, MAX(local_dt) last FROM assets "
        "WHERE user_id=? AND (make IS NOT NULL OR model IS NOT NULL) GROUP BY make, model ORDER BY count DESC",
        (user.id,),
    )


class ShiftBody(ReasonBody):
    make: str | None = None
    model: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    offset_seconds: int | None = None
    reference_asset_id: str | None = None
    reference_true_date: datetime | None = None


def _shift_plan(body: ShiftBody, user: User, db: Database) -> tuple[timedelta, list[dict]]:
    if body.reference_asset_id and body.reference_true_date:
        ref = _asset(db, user, body.reference_asset_id)
        offset = camera_shift.offset_from_reference(ref, body.reference_true_date.replace(tzinfo=None))
    elif body.offset_seconds is not None:
        offset = timedelta(seconds=body.offset_seconds)
    else:
        raise HTTPException(400, "Versatz oder Referenzbild angeben")
    start = body.start.replace(tzinfo=None) if body.start else None
    end = body.end.replace(tzinfo=None) if body.end else None
    return offset, camera_shift.affected(db, user.id, body.make, body.model, start, end)


@router.post("/camera-shift/preview")
def shift_preview(body: ShiftBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    offset, assets = _shift_plan(body, user, db)
    items = []
    for a in assets[:200]:
        cur = current_local(a)
        items.append({"asset": _asset_view(a), "from": cur.isoformat(), "to": (cur + offset).isoformat()})
    return {"offsetSeconds": int(offset.total_seconds()), "count": len(assets), "items": items}


@router.post("/camera-shift/apply")
async def shift_apply(body: ShiftBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    offset, assets = _shift_plan(body, user, db)
    reason = _reason(body.reason)
    if not assets:
        return {"applied": 0, "failed": []}
    note = f"Kamera-Uhr korrigiert ({body.make or ''} {body.model or ''}, Versatz {offset})"
    ids = [suggestions.create_manual(db, user.id, a, current_local(a) + offset, note, source="camera_shift")
           for a in assets]
    async with immich_for(user) as immich:
        return await suggestions.apply(db, immich, user.id, ids, reason=reason, note=body.note)


# --- Claude -----------------------------------------------------------------
class ClaudeBody(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=500)
    model: str | None = None
    budget_usd: float | None = Field(None, gt=0, le=100)


_claude_jobs: dict[str, tuple[str, asyncio.Task, dict]] = {}


def _cancel_claude(user_id: str, job_id: str) -> bool:
    entry = _claude_jobs.get(job_id)
    if entry and entry[0] == user_id and not entry[1].done():
        entry[2]["cancelled"] = True
        return True
    return False


@router.post("/claude/estimate")
def claude_estimate(body: ClaudeBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    model = claude.model_name(body.model or db.get_setting(user.id, "claude_model"))
    est = claude.estimate(model, len(body.asset_ids))
    budget = body.budget_usd or db.get_setting(user.id, "claude_budget_usd", DEFAULT_SETTINGS["claude_budget_usd"])
    return {**est, "budget_usd": budget, "configured": bool(settings.anthropic_api_key),
            "fits_budget": est["total_usd"] <= budget}


@router.post("/claude/runs")
async def claude_run(body: ClaudeBody, user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    if not settings.anthropic_api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY ist nicht gesetzt")
    model = claude.model_name(body.model or db.get_setting(user.id, "claude_model"))
    budget = body.budget_usd or db.get_setting(user.id, "claude_budget_usd", DEFAULT_SETTINGS["claude_budget_usd"])
    assets = [_asset(db, user, i) for i in body.asset_ids]
    job_id = uuid.uuid4().hex
    db.execute(
        "INSERT INTO jobs(id,user_id,kind,status,phase,total,started_at,stats) VALUES (?,?,?,?,?,?,?,?)",
        (job_id, user.id, "claude", "running", "claude", len(assets), now_iso(),
         json.dumps({"model": model, "budget_usd": budget, "spent_usd": 0})),
    )
    flags: dict = {"cancelled": False}
    task = asyncio.create_task(_claude_worker(job_id, user, db, assets, model, budget, flags))
    _claude_jobs[job_id] = (user.id, task, flags)
    return _job_view(db.one("SELECT * FROM jobs WHERE id=?", (job_id,)))


async def _claude_worker(job_id: str, user: User, db: Database, assets: list[dict], model: str,
                         budget: float, flags: dict) -> None:
    spent, done, errors, created = 0.0, 0, [], 0
    status, message = "done", None
    per_image_max = claude.estimate(model, 1)["max_per_image_usd"]
    try:
        async with immich_for(user) as immich:
            for a in assets:
                if flags["cancelled"]:
                    status, message = "cancelled", "Abgebrochen"
                    break
                if spent + per_image_max > budget:
                    status, message = "done", f"Budget von {budget:.2f} $ erreicht"
                    break
                ctx = await _claude_context(db, user, immich, a)
                thumb = await immich.thumbnail(a["id"], "preview")
                result = await claude.analyze(thumb.content, a, ctx, model)
                spent += result.cost_usd
                if result.input_tokens:
                    db.execute(
                        "INSERT INTO claude_usage(user_id,asset_id,model,input_tokens,output_tokens,cost_usd,"
                        "created_at) VALUES (?,?,?,?,?,?,?)",
                        (user.id, a["id"], result.model, result.input_tokens, result.output_tokens,
                         result.cost_usd, now_iso()),
                    )
                if result.error:
                    errors.append({"asset_id": a["id"], "error": result.error})
                elif result.candidate:
                    tz = asset_zone(a, settings.default_tz)
                    if combine.matches_current(result.candidate, current_local(a), tz):
                        errors.append({"asset_id": a["id"], "error": "Claude bestätigt das aktuelle Datum"})
                    elif suggestions.store(db, user.id, a, result.candidate):
                        created += 1
                done += 1
                db.execute(
                    "UPDATE jobs SET progress=?, stats=? WHERE id=?",
                    (done, json.dumps({"model": model, "budget_usd": budget, "spent_usd": round(spent, 4),
                                       "suggestions": created, "errors": errors[-50:]}), job_id),
                )
    except Exception as e:  # noqa: BLE001
        log.exception("claude run failed")
        status, message = "failed", str(e)[:300]
    db.execute(
        "UPDATE jobs SET status=?, message=?, finished_at=?, stats=? WHERE id=?",
        (status, message, now_iso(), json.dumps({"model": model, "budget_usd": budget, "spent_usd": round(spent, 4),
                                                 "suggestions": created, "errors": errors[-50:]}), job_id),
    )


async def _claude_context(db: Database, user: User, immich: Immich, a: dict) -> dict:
    ctx: dict = {"issues": [ISSUE_LABELS.get(i, i) for i in a.get("_issues", [])]}
    try:
        rows = await immich.ocr(a["id"])
        ctx["ocr"] = " | ".join(r.get("text", "") for r in rows)
        similar = await immich.similar(a["id"], size=12)
    except ImmichError:
        similar = []
    trusted = {r["id"] for r in db.all(
        f"SELECT id FROM assets WHERE user_id=? AND category='ok' AND make IS NOT NULL AND id IN "
        f"({','.join('?' * len(similar)) or 'NULL'})", (user.id, *[s["id"] for s in similar]))}
    ctx["similar"] = [s["localDateTime"][:10] for s in similar if s["id"] in trusted and s.get("localDateTime")]
    up = a.get("createdAt") or ""
    near = db.all(
        "SELECT file_name, local_dt FROM assets WHERE user_id=? AND id!=? AND category='ok' "
        "ORDER BY ABS(julianday(uploaded_at) - julianday(?)) LIMIT 8", (user.id, a["id"], up))
    ctx["neighbours"] = [f"{r['file_name']}: {(r['local_dt'] or '')[:16]}" for r in near]
    ctx["candidates"] = [f"{r['source']}: {r['proposed'][:16]} ({r['explanation'][:120]})" for r in db.all(
        "SELECT source, proposed, explanation FROM suggestions WHERE user_id=? AND asset_id=? "
        "AND status IN ('pending','superseded','rejected') ORDER BY id DESC LIMIT 6", (user.id, a["id"]))]
    return ctx


@router.get("/claude/usage")
def claude_usage(user: User = Depends(current_user), db: Database = Depends(get_db)) -> dict:
    month = datetime.now().strftime("%Y-%m")
    return {
        "total_usd": round(db.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM claude_usage WHERE user_id=?",
                                     (user.id,)) or 0, 4),
        "month_usd": round(db.scalar("SELECT COALESCE(SUM(cost_usd),0) FROM claude_usage WHERE user_id=? "
                                     "AND created_at LIKE ?", (user.id, f"{month}%")) or 0, 4),
        "calls": db.scalar("SELECT COUNT(*) FROM claude_usage WHERE user_id=?", (user.id,)),
    }

