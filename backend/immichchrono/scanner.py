"""The scan job: fetch the library, run all detectors, store suggestions, auto-apply safe ones."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import suggestions
from .config import settings
from .dates import asset_zone, current_local
from .db import Database, now_iso
from .detectors import combine, context, exifdeep, filename, folder, ocr, suspects
from .immich import Immich, ImmichError
from .model import Candidate, to_local
from .trim import trim

log = logging.getLogger(__name__)

PHASES = ("fetch", "duplicates", "heuristics", "deep", "context", "local_ai", "combine", "auto_apply")


@dataclass
class Job:
    id: str
    user_id: str
    db: Database
    phase: str = "fetch"
    progress: int = 0
    total: int = 0
    stats: dict = field(default_factory=dict)
    cancelled: bool = False

    def update(self, phase: str | None = None, progress: int | None = None, total: int | None = None,
               message: str | None = None) -> None:
        if phase:
            self.phase = phase
        if progress is not None:
            self.progress = progress
        if total is not None:
            self.total = total
        self.db.execute(
            "UPDATE jobs SET phase=?, progress=?, total=?, message=COALESCE(?, message), stats=? WHERE id=?",
            (self.phase, self.progress, self.total, message, json.dumps(self.stats), self.id),
        )


_running: dict[str, tuple[Job, asyncio.Task]] = {}


def running_job(user_id: str) -> Job | None:
    entry = _running.get(user_id)
    return entry[0] if entry and not entry[1].done() else None


def start_scan(db: Database, user_id: str, token: str, *, full: bool = False) -> Job:
    if job := running_job(user_id):
        return job
    job = Job(id=uuid.uuid4().hex, user_id=user_id, db=db)
    db.execute(
        "INSERT INTO jobs(id, user_id, kind, status, phase, started_at) VALUES (?,?,?,?,?,?)",
        (job.id, user_id, "full_scan" if full else "scan", "running", "fetch", now_iso()),
    )
    task = asyncio.create_task(_run(job, token, full))
    _running[user_id] = (job, task)
    return job


def cancel(user_id: str) -> bool:
    if job := running_job(user_id):
        job.cancelled = True
        return True
    return False


async def _run(job: Job, token: str, full: bool) -> None:
    status, message = "done", None
    try:
        async with Immich(settings.immich_url, token) as immich:
            await Scan(job, immich, full).run()
    except asyncio.CancelledError:
        status, message = "cancelled", "Abgebrochen"
    except ImmichError as e:
        status, message = "failed", f"Immich: {e}"
    except Exception as e:  # noqa: BLE001 - report every failure in the UI
        log.exception("scan failed")
        status, message = "failed", str(e)
    if job.cancelled and status == "done":
        status, message = "cancelled", "Abgebrochen"
    job.db.execute(
        "UPDATE jobs SET status=?, message=COALESCE(?, message), finished_at=?, stats=? WHERE id=?",
        (status, message, now_iso(), json.dumps(job.stats), job.id),
    )


class Scan:
    def __init__(self, job: Job, immich: Immich, full: bool):
        self.job, self.immich, self.full, self.db = job, immich, full, job.db
        self.user = job.user_id
        self.assets: dict[str, dict] = {}
        self.assessments: dict[str, suspects.Assessment] = {}
        self.candidates: dict[str, list[Candidate]] = defaultdict(list)
        self.changed: set[str] = set()
        self.dup_groups: dict[str, list[str]] = {}

    def _check(self) -> None:
        if self.job.cancelled:
            raise asyncio.CancelledError

    async def run(self) -> None:
        await self.fetch()
        await self.duplicates()
        self.heuristics()
        await self.deep()
        self.local_context()
        await self.remote_context()
        await self.local_ai()
        created = self.combine()
        await self.auto_apply(created)
        self.job.update(phase="done", progress=self.job.total, message="Fertig")

    # --- phase 1 --------------------------------------------------------
    async def fetch(self) -> None:
        self.job.update(phase="fetch", progress=0, message="Lade Bibliothek aus Immich …")
        known = {r["id"]: r["updated_at"] for r in self.db.all(
            "SELECT id, updated_at FROM assets WHERE user_id=?", (self.user,))}
        seen: set[str] = set()
        count = 0
        async for items, total in self.immich.iter_assets():
            self._check()
            rows = []
            for raw in items:
                if raw.get("visibility") == "hidden" or raw.get("isTrashed"):
                    continue
                a = trim(raw)
                seen.add(a["id"])
                self.assets[a["id"]] = a
                if self.full or known.get(a["id"]) != a.get("updatedAt"):
                    self.changed.add(a["id"])
                exif = a["exifInfo"]
                rows.append((
                    a["id"], self.user, a["originalFileName"], a["originalPath"], a["type"],
                    exif.get("dateTimeOriginal"), a.get("localDateTime"), a.get("createdAt"),
                    exif.get("make"), exif.get("model"), a.get("checksum"), a.get("duplicateId"),
                    a.get("updatedAt"), json.dumps(a),
                ))
            with self.db.tx() as c:
                c.executemany(
                    "INSERT INTO assets(id,user_id,file_name,path,type,date_original,local_dt,uploaded_at,make,"
                    "model,checksum,duplicate_id,updated_at,data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(user_id,id) DO UPDATE SET file_name=excluded.file_name, path=excluded.path, "
                    "type=excluded.type, date_original=excluded.date_original, local_dt=excluded.local_dt, "
                    "uploaded_at=excluded.uploaded_at, make=excluded.make, model=excluded.model, "
                    "checksum=excluded.checksum, duplicate_id=excluded.duplicate_id, data=excluded.data, "
                    "deep_checked=CASE WHEN assets.updated_at IS excluded.updated_at "
                    "THEN assets.deep_checked ELSE 0 END, updated_at=excluded.updated_at",
                    rows,
                )
            count += len(items)
            self.job.update(progress=count, total=total or count)
        gone = set(known) - seen
        if gone:
            with self.db.tx() as c:
                c.executemany("DELETE FROM assets WHERE user_id=? AND id=?", [(self.user, i) for i in gone])
                c.executemany(
                    "UPDATE suggestions SET status='superseded' WHERE user_id=? AND asset_id=? AND status='pending'",
                    [(self.user, i) for i in gone],
                )
        self.job.stats["assets"] = len(self.assets)
        self.job.stats["changed"] = len(self.changed)

    # --- phase 2 --------------------------------------------------------
    async def duplicates(self) -> None:
        self.job.update(phase="duplicates", progress=0, total=1, message="Lade Duplikate …")
        for group in await self.immich.duplicates():
            ids = [a["id"] for a in group.get("assets", []) if a["id"] in self.assets]
            if len(ids) > 1:
                self.dup_groups[group["duplicateId"]] = ids
        self.job.stats["duplicate_groups"] = len(self.dup_groups)

    # --- phase 3 --------------------------------------------------------
    def heuristics(self) -> None:
        self.job.update(phase="heuristics", progress=0, total=len(self.assets), message="Prüfe Metadaten …")
        now = datetime.now()
        for i, (aid, a) in enumerate(self.assets.items()):
            assessment = suspects.assess(a, now)
            tz = asset_zone(a, settings.default_tz)
            cur = current_local(a)
            if fc := filename.detect(a["originalFileName"] or "", now):
                self.candidates[aid].append(fc)
                if cur and not combine.matches_current(fc, cur, tz):
                    diff = abs(to_local(fc.when, tz) - cur)
                    rest = diff.total_seconds() % 900
                    whole_quarter_hours = rest < 120 or rest > 780
                    if fc.precision == "second" and whole_quarter_hours and diff <= timedelta(hours=14, minutes=2):
                        assessment.issues.append("timezone_mismatch")
                    else:
                        assessment.issues.append("filename_mismatch")
                    if "no_camera_date" not in assessment.issues:
                        # Camera date and file name disagree – which one is right needs a human.
                        fc.confidence = min(fc.confidence, 0.8)
                        fc.explanation += " – widerspricht dem Kameradatum, bitte prüfen"
            if fo := folder.detect(a["originalPath"] or "", now):
                self.candidates[aid].append(fo)
                if cur and not combine.matches_current(fo, cur, tz):
                    assessment.issues.append("folder_mismatch")
            self.assessments[aid] = suspects.recategorize(assessment)
            if i % 2000 == 0:
                self.job.update(progress=i)
        self._save_assessments()

    def _save_assessments(self) -> None:
        with self.db.tx() as c:
            c.executemany(
                "UPDATE assets SET issues=?, category=? WHERE user_id=? AND id=?",
                [(json.dumps(sorted(set(a.issues))), a.category, self.user, aid)
                 for aid, a in self.assessments.items()],
            )
        cats: dict[str, int] = defaultdict(int)
        for a in self.assessments.values():
            cats[a.category] += 1
        self.job.stats["categories"] = dict(cats)

    def _trusted(self, aid: str) -> bool:
        a = self.assessments.get(aid)
        exif = self.assets[aid]["exifInfo"]
        return bool(a and not a.suspect and (exif.get("make") or exif.get("model")) and exif.get("dateTimeOriginal"))

    # --- phase 4 --------------------------------------------------------
    async def deep(self) -> None:
        checked = {r["id"] for r in self.db.all(
            "SELECT id FROM assets WHERE user_id=? AND deep_checked=1", (self.user,))}
        todo = []
        for aid, a in self.assets.items():
            exif = a["exifInfo"]
            camera_with_gps = exif.get("latitude") is not None and not suspects.is_phone(exif.get("make"))
            if (self.assessments[aid].suspect or camera_with_gps) and (aid not in checked or aid in self.changed):
                todo.append(aid)
        self.job.update(phase="deep", progress=0, total=len(todo), message="Lese Metadaten der Originale …")
        sem = asyncio.Semaphore(4)
        done = 0
        have_exiftool = await _has_exiftool()
        if not have_exiftool:
            self.job.stats["deep_skipped"] = "exiftool fehlt"
            return

        async def one(aid: str) -> None:
            nonlocal done
            a = self.assets[aid]
            async with sem:
                self._check()
                path = None
                try:
                    is_video = a["type"] == "VIDEO"
                    path = await self.immich.download_original(
                        aid, max_bytes=None if is_video else 2 * 1024 * 1024, cap=1024 * 1024 * 1024)
                    if path is None:
                        return
                    tags = await exifdeep.run_exiftool(path)
                except (ImmichError, OSError, TimeoutError) as e:
                    log.warning("deep metadata for %s failed: %s", aid, e)
                    return
                finally:
                    if path:
                        with suppress(OSError):
                            path.unlink()
            tz = asset_zone(a, settings.default_tz)
            info = exifdeep.analyze(tags, make=a["exifInfo"].get("make"), tz=tz)
            self.candidates[aid].extend(info.candidates)
            if info.issues:
                self.assessments[aid].issues.extend(info.issues)
                suspects.recategorize(self.assessments[aid])
            if info.serial or info.file_number:
                a["serial"], a["fileNumber"] = info.serial, info.file_number
            self.db.execute("UPDATE assets SET deep_checked=1 WHERE user_id=? AND id=?", (self.user, aid))
            done += 1
            if done % 20 == 0:
                self.job.update(progress=done)

        await asyncio.gather(*(one(aid) for aid in todo))
        self.job.stats["deep_checked"] = done
        self._save_assessments()

    # --- phase 5a: context from the library itself -------------------------
    def local_context(self) -> None:
        self.job.update(phase="context", progress=0, total=len(self.assets), message="Vergleiche mit Nachbarbildern …")
        refs: dict[str, context.Ref] = {}
        for aid, a in self.assets.items():
            if self._trusted(aid) and (cur := current_local(a)):
                exif = a["exifInfo"]
                refs[aid] = context.Ref(aid, cur, a["originalFileName"] or "",
                                        f"{exif.get('make') or ''}|{exif.get('model') or ''}")

        for ids in self.dup_groups.values():
            trusted = [refs[i] for i in ids if i in refs]
            for aid in ids:
                if aid not in refs and (c := context.from_duplicates(aid, trusted)):
                    self.candidates[aid].append(c)

        by_camera: dict[str, list[tuple[int, context.Ref]]] = defaultdict(list)
        for r in refs.values():
            if (n := context.sequence_number(r.file_name)) is not None:
                by_camera[r.camera].append((n, r))
        for lst in by_camera.values():
            lst.sort(key=lambda t: t[0])
        for aid, a in self.assets.items():
            exif = a["exifInfo"]
            camera = f"{exif.get('make') or ''}|{exif.get('model') or ''}"
            n = context.sequence_number(a["originalFileName"] or "")
            if n is None or camera == "|" or camera not in by_camera:
                continue
            neighbours = [(m, r) for m, r in by_camera[camera] if r.id != aid]
            if not (c := context.from_sequence(n, neighbours)):
                continue
            cur = current_local(a)
            tz = asset_zone(a, settings.default_tz)
            if aid in refs:
                # A trusted asset only becomes an outlier if its tight neighbours disagree strongly.
                if c.precision == "hour" and cur and abs(cur - c.when) > timedelta(days=2):
                    self.assessments[aid].issues.append("sequence_outlier")
                    suspects.recategorize(self.assessments[aid])
                    self.candidates[aid].append(c)
            elif not combine.matches_current(c, cur, tz):
                self.candidates[aid].append(c)
        self._refs = refs

    # --- phase 5b: OCR + CLIP via Immich ----------------------------------
    def _unresolved(self, threshold: float) -> list[str]:
        out = []
        for aid, a in self.assessments.items():
            if not a.suspect:
                continue
            if max((c.confidence for c in self.candidates.get(aid, [])), default=0) >= threshold:
                continue
            out.append(aid)
        return out

    async def remote_context(self) -> None:
        todo = [aid for aid in self._unresolved(0.9) if aid in self.changed or self.full or self._never_scanned(aid)]
        self.job.update(phase="context", progress=0, total=len(todo), message="Texterkennung und ähnliche Bilder …")
        sem = asyncio.Semaphore(4)
        done = 0

        async def one(aid: str) -> None:
            nonlocal done
            async with sem:
                self._check()
                try:
                    rows = await self.immich.ocr(aid)
                    similar = await self.immich.similar(aid)
                except ImmichError as e:
                    log.warning("context for %s failed: %s", aid, e)
                    return
            if c := ocr.detect(rows):
                self.candidates[aid].append(c)
            sim_refs = [self._refs[s["id"]] for s in similar if s["id"] in self._refs][:10]
            if c := context.from_similar(sim_refs):
                self.candidates[aid].append(c)
            done += 1
            if done % 20 == 0:
                self.job.update(progress=done)

        await asyncio.gather(*(one(aid) for aid in todo))
        self.job.stats["context_checked"] = done

    def _never_scanned(self, aid: str) -> bool:
        return not self.db.scalar("SELECT 1 FROM suggestions WHERE user_id=? AND asset_id=? LIMIT 1", (self.user, aid))

    # --- phase 6: local vision model (optional) ----------------------------
    async def local_ai(self) -> None:
        from . import ollama

        if not settings.ollama_url or not self.db.get_setting(self.user, "ollama_enabled", True):
            return
        todo = [aid for aid in self._unresolved(0.6)
                if self.assets[aid]["type"] == "IMAGE" and self._never_scanned(aid)]
        limit = int(self.db.get_setting(self.user, "ollama_max_per_scan", 200))
        todo = todo[:limit]
        self.job.update(phase="local_ai", progress=0, total=len(todo), message="Lokale KI schätzt das Jahr …")
        for i, aid in enumerate(todo):
            self._check()
            try:
                thumb = await self.immich.thumbnail(aid, "preview")
                if c := await ollama.estimate(thumb.content, self.assets[aid]):
                    self.candidates[aid].append(c)
            except Exception as e:  # noqa: BLE001 - optional component, never fail the scan
                log.warning("ollama for %s failed: %s", aid, e)
                self.job.stats["local_ai_error"] = str(e)[:200]
                break
            self.job.update(progress=i + 1)

    # --- phase 7 --------------------------------------------------------
    def combine(self) -> list[int]:
        self._save_assessments()
        self.job.update(phase="combine", progress=0, total=len(self.assets), message="Bewerte Kandidaten …")
        auto: list[int] = []
        created = 0
        for aid, a in self.assets.items():
            assessment = self.assessments[aid]
            cands = self.candidates.get(aid, [])
            tz = asset_zone(a, settings.default_tz)
            top = combine.best(cands, tz)
            if top is None:
                continue
            if combine.matches_current(top, current_local(a), tz):
                continue
            # Only suggest changes for assets that look wrong, unless the evidence is strong.
            if not assessment.suspect and top.confidence < 0.9:
                continue
            sid = suggestions.store(self.db, self.user, a, top)
            if sid is None:
                continue
            created += 1
            if top.auto_safe:
                auto.append(sid)
        self.job.stats["suggestions"] = created
        self.job.stats["auto_candidates"] = len(auto)
        return auto

    # --- phase 8 --------------------------------------------------------
    async def auto_apply(self, ids: list[int]) -> None:
        if not ids or not self.db.get_setting(self.user, "auto_apply", True):
            return
        self.job.update(phase="auto_apply", progress=0, total=len(ids), message="Übernehme eindeutige Fälle …")
        result = await suggestions.apply(self.db, self.immich, self.user, ids, auto=True)
        self.job.stats["auto_applied"] = result["applied"]


async def _has_exiftool() -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "exiftool", "-ver", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        return await proc.wait() == 0
    except FileNotFoundError:
        return False
