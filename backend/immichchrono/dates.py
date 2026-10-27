"""Conversions between Immich's date fields and our naive-local / aware representations."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .model import parse_iso, to_aware, zone


def asset_zone(asset: dict, default_tz: str) -> ZoneInfo | None:
    tz = (asset.get("exifInfo") or {}).get("timeZone")
    if tz and tz.upper() in ("UTC", "UTC+0", "ETC/UTC"):
        tz = None  # Immich writes UTC when it did not know better
    return zone(tz, default_tz)


def current_local(asset: dict) -> datetime | None:
    """Immich's localDateTime is the wall-clock time serialised as if it were UTC."""
    value = parse_iso(asset.get("localDateTime"))
    if value is not None:
        return value.replace(tzinfo=None)
    dto = parse_iso((asset.get("exifInfo") or {}).get("dateTimeOriginal"))
    return dto.replace(tzinfo=None) if dto else None


def current_iso(asset: dict, default_tz: str) -> str | None:
    """The asset's current date as an ISO string with offset – used for undo."""
    local = current_local(asset)
    if local is None:
        return None
    return to_aware(local, asset_zone(asset, default_tz)).isoformat()


def to_write_iso(when: datetime, tz: ZoneInfo | None) -> str:
    """Value for Immich's dateTimeOriginal: wall-clock time with explicit offset."""
    return to_aware(when, tz).replace(microsecond=0).isoformat()
