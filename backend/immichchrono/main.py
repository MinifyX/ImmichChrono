from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from . import __version__, decisions
from .api import router
from .config import settings
from .db import Database, now_iso

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    # Jobs that were running when the container stopped can't resume.
    db.execute("UPDATE jobs SET status='failed', message='Neustart während des Laufs', finished_at=? "
               "WHERE status='running'", (now_iso(),))
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now_iso(),))
    if n := decisions.backfill(db):
        logging.getLogger(__name__).info("Entscheidungsprotokoll: %d frühere Entscheidungen übernommen", n)
    app.state.db = db
    yield


def create_app(static_dir: Path | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title="ImmichChrono", version=__version__, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json", redoc_url=None)
    app.include_router(router)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # CSRF: state-changing requests must come from this origin (cookie auth, SameSite=Lax alone
        # still lets sibling subdomains through).
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            # Browsers send Sec-Fetch-Site; the Origin comparison is only a fallback for older ones
            # (it can't see through reverse proxies that rewrite Host).
            site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            hosts = {request.headers.get("host"), request.headers.get("x-forwarded-host")}
            if (site not in ("same-origin", "none") if site else origin and urlsplit(origin).netloc not in hosts):
                return JSONResponse({"message": "Fremde Herkunft abgelehnt"}, status_code=403)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/api/health", include_in_schema=False)
    def health() -> dict:
        return {"ok": True}

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"message": exc.detail}, status_code=exc.status_code)

    static = (static_dir or settings.static_dir).resolve()
    index = static / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        file = (static / path).resolve()
        if path and file.is_file() and file.is_relative_to(static):
            cache = "public, max-age=31536000, immutable" if "/immutable/" in f"/{path}" else "no-cache"
            return FileResponse(file, headers={"Cache-Control": cache})
        if index.is_file():
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        raise HTTPException(404, "Frontend nicht gebaut")

    return app


app = create_app()
