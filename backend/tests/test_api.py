import json
import time
from functools import partial

import httpx
import pytest
from fastapi.testclient import TestClient

from immichchrono import api, immich, scanner
from immichchrono.main import create_app

USER = "u1"


def asset(aid, name, local, dto=None, make=None, path=None, created="2024-03-01T10:00:00.000Z"):
    return {
        "id": aid, "originalFileName": name, "originalPath": path or f"/usr/src/app/upload/library/{name}",
        "type": "IMAGE", "localDateTime": local, "fileCreatedAt": created, "fileModifiedAt": created,
        "createdAt": created, "updatedAt": "2024-03-01T10:00:00.000Z", "isTrashed": False,
        "visibility": "timeline", "checksum": f"sum-{aid}", "people": [],
        "exifInfo": {"dateTimeOriginal": dto or created, "make": make, "model": None, "timeZone": None},
    }


ASSETS = [
    # WhatsApp image uploaded 2024 – real date is in the name (day precision, review needed).
    asset("a1", "IMG-20190301-WA0004.jpg", "2024-03-01T11:00:00.000Z"),
    # Screenshot with exact timestamp in the name: auto-safe.
    asset("a2", "Screenshot_20230514-181502.png", "2024-03-01T11:00:00.000Z"),
    # Correct camera photo.
    asset("a3", "DSC_0001.JPG", "2015-06-01T10:00:00.000Z", dto="2015-06-01T08:00:00.000Z", make="NIKON",
          created="2015-06-01T08:00:00.000Z"),
]


class FakeImmich:
    def __init__(self):
        self.updates: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix("/api"), request.method
        if path == "/auth/login":
            body = json.loads(request.content)
            if body["password"] != "pw":
                return httpx.Response(401, json={"message": "Incorrect email or password"})
            return httpx.Response(201, json={"accessToken": "tok", "userId": USER, "name": "Test",
                                             "userEmail": "user@example.com", "isAdmin": True})
        if path == "/server/version":
            return httpx.Response(200, json={"major": 2, "minor": 1, "patch": 0})
        if path == "/search/metadata":
            return httpx.Response(200, json={"assets": {"items": ASSETS, "nextPage": None, "total": len(ASSETS)}})
        if path == "/search/smart":
            return httpx.Response(200, json={"assets": {"items": [], "nextPage": None}})
        if path == "/duplicates":
            return httpx.Response(200, json=[])
        if path.endswith("/ocr"):
            return httpx.Response(200, json=[])
        if method == "PUT" and path.startswith("/assets/"):
            aid = path.split("/")[2]
            self.updates.append((aid, json.loads(request.content)["dateTimeOriginal"]))
            return httpx.Response(200, json={"id": aid})
        if path == "/auth/logout":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"message": f"unhandled {method} {path}"})


@pytest.fixture
def fake(monkeypatch):
    f = FakeImmich()
    transport = httpx.MockTransport(f)
    patched = partial(immich.Immich, transport=transport)
    monkeypatch.setattr(api, "Immich", patched)
    monkeypatch.setattr(scanner, "Immich", patched)

    async def no_exiftool():
        return False

    monkeypatch.setattr(scanner, "_has_exiftool", no_exiftool)
    return f


def wait(client, job_id):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_login_scan_review_apply(fake, tmp_path):
    (tmp_path / "index.html").write_text("<html>app</html>")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/auth/me").status_code == 401
        assert client.post("/api/auth/login", json={"email": "user@example.com", "password": "x"}).status_code == 401
        r = client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
        assert r.status_code == 200 and client.get("/api/auth/me").json()["id"] == USER

        job = wait(client, client.post("/api/scans", json={"full": True}).json()["id"])
        assert job["status"] == "done", job

        # Screenshot was auto-applied with its exact timestamp.
        assert ("a2", "2023-05-14T18:15:02+02:00") in fake.updates
        pending = client.get("/api/suggestions").json()
        by_asset = {s["asset_id"]: s for s in pending["items"]}
        assert set(by_asset) == {"a1"}
        assert by_asset["a1"]["proposed"].startswith("2019-03-01")

        r = client.post("/api/suggestions/apply", json={"ids": [by_asset["a1"]["id"]]}).json()
        assert r["applied"] == 1 and fake.updates[-1][0] == "a1"

        hist = client.get("/api/suggestions", params={"status": "history"}).json()["items"]
        undo_id = next(s["id"] for s in hist if s["asset_id"] == "a1")
        assert client.post(f"/api/suggestions/{undo_id}/undo").json()["ok"]
        assert fake.updates[-1] == ("a1", "2024-03-01T11:00:00+01:00")

        summary = client.get("/api/summary").json()
        assert summary["total"] == 3 and summary["categories"].get("ok") == 1

        assert client.get("/").text == "<html>app</html>"
        assert client.get("/some/route").text == "<html>app</html>"
        assert client.get("/api/nope").status_code == 404


def test_settings_and_estimate(fake, tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
        s = client.put("/api/settings", json={"auto_apply": False, "claude_budget_usd": 0.5}).json()
        assert s["auto_apply"] is False and s["claude_budget_usd"] == 0.5
        est = client.post("/api/claude/estimate", json={"asset_ids": ["a1", "a2"], "model": "claude-haiku-5-5"}).json()
        assert est["fits_budget"] and est["configured"] is False
        assert client.post("/api/claude/runs", json={"asset_ids": ["a1"]}).status_code == 400


def test_cross_origin_writes_are_rejected(fake, tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
        r = client.post("/api/auth/logout", headers={"Sec-Fetch-Site": "same-site"})
        assert r.status_code == 403
        r = client.post("/api/auth/logout", headers={"Origin": "http://evil.example"})
        assert r.status_code == 403
        assert client.get("/api/auth/me").status_code == 200
        assert client.get("/api/assets/..%3Fx/thumbnail").status_code in (404, 422)
        r = client.post("/api/auth/logout", headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
        assert r.status_code == 200 and r.headers["x-frame-options"] == "DENY"


def test_decision_log(fake, tmp_path, capsys):
    with TestClient(create_app(tmp_path)) as client:
        client.post("/api/auth/login", json={"email": "user@example.com", "password": "pw"})
        assert wait(client, client.post("/api/scans", json={"full": True}).json()["id"])["status"] == "done"
        server = client.get("/api/server").json()
        assert any(r["code"] == "not_capture" for r in server["decisionReasons"])

        sid = next(s["id"] for s in client.get("/api/suggestions").json()["items"] if s["asset_id"] == "a1")
        assert client.post("/api/suggestions/reject", json={"ids": [sid], "reason": "nope"}).status_code == 422
        assert client.post("/api/suggestions/reject", json={"ids": [sid], "note": "x" * 501}).status_code == 422
        r = client.post("/api/suggestions/reject", json={"ids": [sid, 999], "reason": "wrong_day", "note": "eher Juli"})
        assert r.json()["rejected"] == 1

        r = client.post("/api/assets/a1/manual", json={"date": "2019-07-01T12:00:00", "reason": "wrong_day"})
        assert r.json()["applied"] == 1
        hist = client.get("/api/suggestions", params={"status": "history"}).json()["items"]
        manual_id = next(s["id"] for s in hist if s["asset_id"] == "a1")
        assert client.post(f"/api/suggestions/{manual_id}/undo", json={"reason": "old_correct"}).json()["ok"]

        # The test database is shared between tests: only look at what this test added.
        lines = [json.loads(x) for x in client.get("/api/decisions/export").text.splitlines()]
        assert ("auto_applied", "auto") in [(d["action"], d["reason"]) for d in lines]
        lines = lines[-3:]
        assert [(d["action"], d["reason"]) for d in lines] == [
            ("rejected", "wrong_day"), ("manual", "wrong_day"), ("reverted", "old_correct")]
        rejected = lines[0]
        assert rejected["note"] == "eher Juli" and rejected["reason_label"] == "Richtiges Jahr, falscher Tag"
        f = rejected["features"]
        assert f["name_pattern"] == "IMG-########-WA####.jpg" and f["source"] == "filename"
        assert f["previous_date"].startswith("2024-03-01") and f["delta_days"] < -1800
        # The undo keeps the features from before the change, not the "fixed" asset state.
        assert lines[2]["features"]["category"] == lines[1]["features"]["category"] != "fixed"

        stats = client.get("/api/decisions/stats").json()
        src = {row["key"]: row for row in stats["bySource"]}
        assert src["filename"]["rejected"] >= 1 and src["filename"]["auto"] >= 1
        assert src["manual"]["rejected"] >= 1  # a reverted manual change counts against it
        pairs = {(r["action"], r["reason"]) for r in stats["reasons"]}
        assert pairs >= {("rejected", "wrong_day"), ("reverted", "old_correct")}  # latest per suggestion

    # CLI export reads the same database; backfill is idempotent.
    from immichchrono import decisions as dec
    from immichchrono import export
    from immichchrono.config import settings
    from immichchrono.db import Database

    assert dec.backfill(Database(settings.db_path)) == 0
    assert export.main(["--user", USER]) == 0
    assert len(capsys.readouterr().out.splitlines()) >= 4


def test_decision_backfill():
    from immichchrono import decisions as dec
    from immichchrono.db import Database

    db = Database(":memory:")
    for status, source in [("rejected", "album"), ("applied", "manual"), ("pending", "album")]:
        db.execute("INSERT INTO suggestions(user_id, asset_id, source, proposed, precision, confidence, explanation, "
                   "status, previous_date, created_at) VALUES ('u','x',?, '2020-01-01T12:00:00', 'day', 0.5, '', ?, "
                   "'2021-01-01T12:00:00', '2024-01-01T00:00:00+00:00')", (source, status))
    assert dec.backfill(db) == 2 and dec.backfill(db) == 0
    rows = db.all("SELECT action, reason FROM decisions ORDER BY id")
    assert rows == [{"action": "rejected", "reason": "unbekannt"}, {"action": "manual", "reason": "unbekannt"}]
    assert json.loads(db.scalar("SELECT features FROM decisions LIMIT 1"))["delta_days"] == -366.0
