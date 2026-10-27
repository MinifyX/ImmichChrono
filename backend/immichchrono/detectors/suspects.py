"""Flag assets whose stored date looks unreliable, without any network access."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..model import parse_iso

SCANNER = re.compile(
    r"(?i)scan|perfection|canoscan|plustek|reflecta|opticfilm|imagebox|kodak scanza|"
    r"fujitsu fi-|docucentre|imageformula|wolverine|digitnow|photomatix"
)
SCAN_NAME = re.compile(r"(?i)(^|[^a-z])(scan|scanned|dia|negativ|negative|epson|img\d{3,4}$)")
MESSENGER = re.compile(r"(?i)whatsapp|-wa\d+|signal-|telegram|photo_\d{4}-|fb_img|mmexport|received_|snapchat")
SCREENSHOT = re.compile(r"(?i)screenshot|bildschirmfoto|screen shot|screen_recording|bildschirmaufnahme")
PHONE_MAKES = re.compile(r"(?i)apple|google|samsung|xiaomi|huawei|oneplus|oppo|motorola|sony mobile|nokia|"
                         r"fairphone|honor|realme|vivo|lg electronics|htc|asus")

DEFAULT_DATES = {(1970, 1, 1), (1980, 1, 1), (1904, 1, 1), (2000, 1, 1), (2001, 1, 1), (2002, 1, 1)}

ISSUE_LABELS = {
    "no_camera_date": "Kein Aufnahmedatum in den Metadaten – Datum stammt vom Dateisystem",
    "near_upload": "Datum liegt am Upload-Zeitpunkt",
    "default_date": "Typisches Standarddatum einer zurückgesetzten Kamera-Uhr",
    "future": "Datum liegt in der Zukunft",
    "scan": "Vermutlich ein eingescanntes Foto",
    "messenger": "Aus einem Messenger gespeichert (Metadaten entfernt)",
    "screenshot": "Screenshot",
    "filename_mismatch": "Dateiname nennt ein anderes Datum",
    "timezone_mismatch": "Abweichung um ganze Stunden – vermutlich falsche Zeitzone",
    "folder_mismatch": "Ordnername nennt ein anderes Datum",
    "camera_clock": "Kamera-Uhr weicht von der GPS-Zeit ab",
    "sequence_outlier": "Passt nicht zu den Nachbarbildern derselben Kamera",
}


@dataclass
class Assessment:
    issues: list[str] = field(default_factory=list)
    category: str = "ok"

    @property
    def suspect(self) -> bool:
        return bool(self.issues) and self.issues != ["screenshot"]


def assess(asset: dict, now: datetime | None = None) -> Assessment:
    now = now or datetime.now()
    exif = asset.get("exifInfo") or {}
    name = asset.get("originalFileName") or ""
    issues: list[str] = []

    dto = parse_iso(exif.get("dateTimeOriginal"))
    local = parse_iso(asset.get("localDateTime"))
    file_created = parse_iso(asset.get("fileCreatedAt"))
    file_modified = parse_iso(asset.get("fileModifiedAt"))
    uploaded = parse_iso(asset.get("createdAt"))
    make_model = f"{exif.get('make') or ''} {exif.get('model') or ''}".strip()

    # Immich falls back to the file time when no EXIF date exists, so a date that
    # equals the file timestamps (and no camera info) means "no real date".
    if dto is None or (
        not make_model
        and any(t is not None and abs((dto - t).total_seconds()) < 2 for t in (file_created, file_modified))
    ):
        issues.append("no_camera_date")

    ref = local or dto
    if ref is not None:
        naive = ref.replace(tzinfo=None)
        reset_clock = (naive.year, naive.month, naive.day) in DEFAULT_DATES and naive.hour in (0, 12) \
            and naive.minute == 0
        if reset_clock or (naive.year < 1990 and make_model and not SCANNER.search(make_model)):
            issues.append("default_date")
        if naive > now + timedelta(days=1):
            issues.append("future")
    if dto and uploaded and "no_camera_date" in issues and abs(dto - uploaded) < timedelta(hours=36):
        issues.append("near_upload")

    if SCANNER.search(make_model) or (not make_model and SCAN_NAME.search(name.rsplit(".", 1)[0])):
        issues.append("scan")
    if MESSENGER.search(name):
        issues.append("messenger")
    if SCREENSHOT.search(name):
        issues.append("screenshot")

    return Assessment(issues=issues, category=_category(issues))


def _category(issues: list[str]) -> str:
    if not issues or issues == ["screenshot"]:
        return "ok"
    if "scan" in issues:
        return "scan"
    if "timezone_mismatch" in issues:
        return "timezone"
    if any(i in issues for i in ("default_date", "future", "camera_clock", "sequence_outlier")):
        return "wrong_clock"
    if any(i in issues for i in ("no_camera_date", "messenger", "near_upload")):
        return "missing"
    return "suspect"


def recategorize(a: Assessment) -> Assessment:
    a.category = _category(a.issues)
    return a


def is_phone(make: str | None) -> bool:
    return bool(make and PHONE_MAKES.search(make))
