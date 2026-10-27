from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from immichchrono import claude
from immichchrono.detectors import combine, context, exifdeep, filename, folder, ocr, suspects
from immichchrono.model import Candidate

NOW = datetime(2026, 10, 1, 12, 0)
BERLIN = ZoneInfo("Europe/Berlin")


def test_filename_patterns():
    c = filename.detect("Screenshot_20230514-181502.png", NOW)
    assert c and c.when == datetime(2023, 5, 14, 18, 15, 2) and c.precision == "second"
    c = filename.detect("IMG-20190301-WA0004.jpg", NOW)
    assert c and c.precision == "day" and c.when.date().isoformat() == "2019-03-01"
    c = filename.detect("WhatsApp Image 2021-07-04 at 14.03.22.jpeg", NOW)
    assert c and c.when == datetime(2021, 7, 4, 14, 3, 22)
    c = filename.detect("PXL_20240102_101112345.jpg", NOW)
    assert c and c.when.tzinfo is not None
    assert filename.detect("holiday.jpg", NOW) is None
    assert filename.detect("IMG_19800101_000000.jpg", NOW) is None


def test_folder_hints():
    c = folder.detect("/mnt/photos/2014/07 Urlaub/a.jpg", NOW)
    assert c and c.precision == "month" and (c.when.year, c.when.month) == (2014, 7)
    c = folder.detect("/mnt/photos/Sommer 2009/a.jpg", NOW)
    assert c and c.precision == "year" and c.when.year == 2009
    c = folder.detect("/mnt/photos/Juli 2011/a.jpg", NOW)
    assert c and (c.when.year, c.when.month) == (2011, 7)
    assert folder.detect("/usr/src/app/upload/library/ab/cd/x.jpg", NOW) is None


def _asset(**kw):
    base = {"originalFileName": "DSC_0001.JPG", "localDateTime": "2015-06-01T10:00:00.000Z",
            "fileCreatedAt": "2015-06-01T08:00:00.000Z", "fileModifiedAt": "2015-06-01T08:00:00.000Z",
            "createdAt": "2024-01-01T00:00:00.000Z",
            "exifInfo": {"dateTimeOriginal": "2015-06-01T08:00:00.000Z", "make": "NIKON", "model": "D90"}}
    base.update(kw)
    return base


def test_suspects():
    assert suspects.assess(_asset(), NOW).category == "ok"
    a = _asset(localDateTime="1970-01-01T00:00:00.000Z",
               exifInfo={"dateTimeOriginal": "1970-01-01T00:00:00.000Z", "make": "NIKON", "model": "D90"})
    assert "default_date" in suspects.assess(a, NOW).issues
    a = _asset(originalFileName="IMG-20190301-WA0004.jpg", exifInfo={},
               localDateTime="2024-01-01T00:00:00.000Z", fileCreatedAt="2024-01-01T00:00:00.000Z",
               fileModifiedAt="2024-01-01T00:00:00.000Z")
    r = suspects.assess(a, NOW)
    assert {"no_camera_date", "messenger"} <= set(r.issues) and r.suspect
    a = _asset(exifInfo={"make": "EPSON", "model": "Perfection V600"})
    assert suspects.assess(a, NOW).category == "scan"


def test_ocr_dates():
    found = ocr.find_dates("'98 7 14")
    assert found and found[0][0].date().isoformat() == "1998-07-14"
    c = ocr.detect([{"text": "Geburtstag 12.03.1987"}], NOW)
    assert c and c.when.year == 1987 and c.precision == "day"
    assert ocr.detect([{"text": "no dates here"}], NOW) is None


def test_exif_deep_gps_clock():
    tags = {"EXIF:DateTimeOriginal": "2016:08:10 12:00:00", "Composite:GPSDateTime": "2016:08:10 13:30:00Z"}
    info = exifdeep.analyze(tags, make="NIKON", tz=BERLIN, now=NOW)
    assert "camera_clock" in info.issues
    gps = [c for c in info.candidates if c.source == "gps"]
    assert gps and gps[0].confidence >= 0.9
    assert exifdeep.parse_exif_date("2016:08:10 12:00:00+02:00").utcoffset() == timedelta(hours=2)
    assert exifdeep.parse_exif_date("0000:00:00 00:00:00") is None


def test_context_sequence_and_duplicates():
    refs = [(100, context.Ref("a", datetime(2012, 5, 1, 10), "DSC_0100.JPG", "x")),
            (110, context.Ref("b", datetime(2012, 5, 1, 11), "DSC_0110.JPG", "x"))]
    c = context.from_sequence(105, refs)
    assert c and c.precision == "hour" and c.when.date().isoformat() == "2012-05-01"
    assert context.sequence_number("DSC_0105.JPG") == 105
    dup = context.from_duplicates("z", [context.Ref("y", datetime(2010, 1, 2, 3, 4, 5), "f.jpg", "x")])
    assert dup and dup.source == "duplicate"


def test_combine_agreement_boosts():
    when = datetime(2019, 3, 1, 12)
    cands = [Candidate("filename", when, "day", 0.85, "a"), Candidate("folder", when, "month", 0.7, "b")]
    best = combine.best(cands, BERLIN)
    assert best and best.source == "filename" and best.confidence > 0.85
    assert combine.matches_current(cands[0], datetime(2019, 3, 1, 18), BERLIN)


def test_auto_safe():
    assert Candidate("gps", datetime(2020, 1, 1, tzinfo=UTC), "second", 0.96, "x").auto_safe
    assert not Candidate("ocr", datetime(2020, 1, 1), "day", 0.99, "x").auto_safe


def test_claude_parse_and_estimate():
    c = claude.parse_answer({"earliest": "1985-01-01", "latest": "1989-12-31", "best_guess": "1987-06-01",
                             "precision": "year", "confidence": 0.99, "reasoning": "Kleidung"})
    assert c and c.source == "claude" and c.confidence <= 0.9 and c.when.year == 1987
    est = claude.estimate("claude-haiku-5-5", 10)
    assert 0 < est["total_usd"] < 0.1
