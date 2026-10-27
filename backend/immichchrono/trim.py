"""Reduce Immich asset payloads to the fields ImmichChrono stores."""

from __future__ import annotations

ASSET_KEYS = (
    "id", "originalFileName", "originalPath", "type", "fileCreatedAt", "fileModifiedAt", "createdAt",
    "localDateTime", "updatedAt", "duplicateId", "checksum", "livePhotoVideoId", "visibility", "isFavorite",
)
EXIF_KEYS = (
    "dateTimeOriginal", "modifyDate", "timeZone", "make", "model", "lensModel", "latitude", "longitude",
    "city", "state", "country", "description", "exifImageWidth", "exifImageHeight", "fileSizeInByte",
)


def trim(asset: dict) -> dict:
    out = {k: asset.get(k) for k in ASSET_KEYS}
    exif = asset.get("exifInfo") or {}
    out["exifInfo"] = {k: exif.get(k) for k in EXIF_KEYS}
    out["people"] = [
        {"name": p.get("name"), "birthDate": p.get("birthDate")}
        for p in asset.get("people") or [] if p.get("name")
    ]
    return out
