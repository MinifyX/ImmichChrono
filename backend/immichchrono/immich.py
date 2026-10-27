"""Minimal async client for the parts of the Immich API ImmichChrono needs."""

from __future__ import annotations

import contextlib
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx


class ImmichError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _raise(r: httpx.Response) -> None:
    if r.is_success:
        return
    try:
        msg = r.json().get("message", r.text)
    except ValueError:
        msg = r.text
    if isinstance(msg, list):
        msg = "; ".join(map(str, msg))
    raise ImmichError(r.status_code, str(msg)[:300])


class Immich:
    def __init__(self, base_url: str, token: str | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.AsyncClient(
            base_url=f"{base_url}/api", headers=headers, timeout=httpx.Timeout(60, connect=10),
            transport=transport, follow_redirects=True,
        )

    async def __aenter__(self) -> Immich:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _json(self, method: str, url: str, **kw: Any) -> Any:
        r = await self._http.request(method, url, **kw)
        _raise(r)
        return r.json() if r.content else None

    # --- auth -----------------------------------------------------------
    async def login(self, email: str, password: str) -> dict:
        return await self._json("POST", "/auth/login", json={"email": email, "password": password})

    async def logout(self) -> None:
        with contextlib.suppress(ImmichError, httpx.HTTPError):
            await self._json("POST", "/auth/logout")

    async def me(self) -> dict:
        return await self._json("GET", "/users/me")

    async def version(self) -> dict:
        return await self._json("GET", "/server/version")

    # --- assets ---------------------------------------------------------
    async def iter_assets(
        self, *, page_size: int = 1000, **filters: Any
    ) -> AsyncIterator[tuple[list[dict], int | None]]:
        """Yield (items, total) pages from /search/metadata including EXIF and people."""
        page: int | None = 1
        while page:
            body = {"page": page, "size": page_size, "withExif": True, "withPeople": True,
                    "withDeleted": False, "order": "asc", **filters}
            data = await self._json("POST", "/search/metadata", json=body)
            assets = data["assets"]
            yield assets["items"], assets.get("total")
            nxt = assets.get("nextPage")
            page = int(nxt) if nxt else None

    async def asset(self, asset_id: str) -> dict:
        return await self._json("GET", f"/assets/{asset_id}")

    async def ocr(self, asset_id: str) -> list[dict]:
        try:
            return await self._json("GET", f"/assets/{asset_id}/ocr") or []
        except ImmichError as e:
            if e.status in (400, 404):
                return []
            raise

    async def similar(self, asset_id: str, size: int = 16) -> list[dict]:
        body = {"queryAssetId": asset_id, "size": size, "page": 1, "withExif": True}
        try:
            data = await self._json("POST", "/search/smart", json=body)
        except ImmichError as e:
            if e.status in (400, 404, 500):  # smart search disabled or no embedding yet
                return []
            raise
        return [a for a in data["assets"]["items"] if a["id"] != asset_id]

    async def duplicates(self) -> list[dict]:
        try:
            return await self._json("GET", "/duplicates") or []
        except ImmichError as e:
            if e.status in (403, 404):
                return []
            raise

    async def update_date(self, asset_id: str, date_time_original: str) -> dict:
        return await self._json("PUT", f"/assets/{asset_id}", json={"dateTimeOriginal": date_time_original})

    async def bulk_update_date(self, ids: list[str], date_time_original: str) -> None:
        await self._json("PUT", "/assets", json={"ids": ids, "dateTimeOriginal": date_time_original})

    async def thumbnail(self, asset_id: str, size: str = "thumbnail") -> httpx.Response:
        r = await self._http.get(f"/assets/{asset_id}/thumbnail", params={"size": size})
        _raise(r)
        return r

    async def download_original(self, asset_id: str, *, max_bytes: int | None, cap: int) -> Path | None:
        """Download (a prefix of) the original into a temp file. Returns None if larger than ``cap``."""
        headers = {"Range": f"bytes=0-{max_bytes - 1}"} if max_bytes else {}
        async with self._http.stream("GET", f"/assets/{asset_id}/original", headers=headers) as r:
            if r.status_code not in (200, 206):
                await r.aread()
                _raise(r)
            size = int(r.headers.get("content-length") or 0)
            if r.status_code == 200 and not max_bytes and size > cap:
                return None
            written = 0
            with tempfile.NamedTemporaryFile(prefix="chrono-", delete=False) as fd:
                async for chunk in r.aiter_bytes(256 * 1024):
                    fd.write(chunk)
                    written += len(chunk)
                    if (max_bytes and written >= max_bytes) or written > cap:
                        break
            return Path(fd.name)
