from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, Response

from .config import settings
from .db import Database
from .immich import Immich, ImmichError

COOKIE = "chrono_sid"
# How often a session is re-checked against Immich, so revoked tokens stop working.
REVALIDATE = timedelta(minutes=10)


@dataclass
class User:
    id: str
    name: str
    email: str
    is_admin: bool
    token: str
    session_id: str


def get_db(request: Request) -> Database:
    return request.app.state.db


def create_session(db: Database, request: Request, response: Response, login: dict) -> str:
    sid = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.execute(
        "INSERT INTO sessions(id, token, user_id, name, email, is_admin, created_at, expires_at, checked_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, login["accessToken"], login["userId"], login.get("name"), login.get("userEmail"),
         int(bool(login.get("isAdmin"))), now.isoformat(),
         (now + timedelta(hours=settings.session_ttl_hours)).isoformat(), now.isoformat()),
    )
    response.set_cookie(
        COOKIE, sid, httponly=True, samesite="lax", secure=settings.cookie_secure or request.url.scheme == "https",
        max_age=settings.session_ttl_hours * 3600, path="/",
    )
    return sid


async def current_user(request: Request, db: Database = Depends(get_db)) -> User:
    sid = request.cookies.get(COOKIE)
    if not sid:
        raise HTTPException(401, "Nicht angemeldet")
    row = db.one("SELECT * FROM sessions WHERE id=?", (sid,))
    now = datetime.now(UTC)
    if not row or row["expires_at"] < now.isoformat():
        if row:
            db.execute("DELETE FROM sessions WHERE id=?", (sid,))
        raise HTTPException(401, "Sitzung abgelaufen")
    if (row["checked_at"] or "") < (now - REVALIDATE).isoformat():
        try:
            async with Immich(settings.immich_url, row["token"]) as immich:
                await immich.me()
        except ImmichError as e:
            if e.status == 401:
                db.execute("DELETE FROM sessions WHERE id=?", (sid,))
                raise HTTPException(401, "Sitzung in Immich beendet") from e
        except Exception:  # noqa: BLE001 - Immich unreachable: keep the session, check again later
            pass
        else:
            db.execute("UPDATE sessions SET checked_at=? WHERE id=?", (now.isoformat(), sid))
    return User(row["user_id"], row["name"] or "", row["email"] or "", bool(row["is_admin"]), row["token"], sid)
