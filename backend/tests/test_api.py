"""HTTP API contract."""
from __future__ import annotations

import os

from app.config import settings


def test_health_endpoints(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/health").json() == {"status": "ok"}


def test_meta_exposes_profiles_but_no_secrets(client):
    data = client.get("/api/meta").json()
    keys = {p["key"] for p in data["profiles"]}
    assert {"clean_win_chrome", "clean_iphone", "clean_android", "clean_firefox", "returning_visitor"} <= keys
    assert data["unified_conditions"]["locale"] == "de-DE"
    assert [c["key"] for c in data["cookie_modes"]] == ["necessary", "all", "none"]
    assert "*.msccruises.de" in data["allowed_domains"]
    assert data["proxy_labels"] == ["DE Testanschluss"]
    body = client.get("/api/meta").text
    assert "proxysecret" not in body and "proxyuser" not in body
    assert any(p["key"] == "msc" and p["status"] == "aktiv" for p in data["providers"])
    assert any(p["key"] == "check24" and p["status"] == "geplant" for p in data["providers"])


def test_parse_url_preview(client):
    response = client.post(
        "/api/parse-url",
        json={"url": "https://www.msccruises.de/booking?ship=euribia&departureDate=11.09.2026&nights=7&adults=2"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ship"] == "MSC Euribia"
    assert data["departure_date"] == "2026-09-11"
    assert data["return_date"] == "2026-09-18"
    assert data["adults"] == 2


def test_parse_url_rejects_foreign_domain(client):
    response = client.post("/api/parse-url", json={"url": "https://www.dreamlines.de/kreuzfahrt/1"})
    assert response.status_code == 400
    assert "nicht freigegeben" in response.json()["detail"]


def test_parse_url_rejects_ssrf_targets(client):
    for url in ("file:///etc/passwd", "http://169.254.169.254/", "https://localhost/x"):
        assert client.post("/api/parse-url", json={"url": url}).status_code == 400


def test_cruise_crud_and_scan_cycle(client):
    created = client.post(
        "/api/cruises",
        json={
            "url": "mock://cruise/api-1?variant=default",
            "start_scan": False,
            "schedule_interval": "daily",
        },
    )
    assert created.status_code == 201
    cruise = created.json()["cruise"]
    cruise_id = cruise["id"]
    assert cruise["provider"] == "mock"
    assert cruise["ship"] == "MSC Euribia (Demo)"
    assert cruise["nights"] == 7

    # dashboard list
    listed = client.get("/api/cruises").json()
    assert any(item["id"] == cruise_id for item in listed)

    # run a scan synchronously so the test is deterministic
    from app.db import session_scope
    from app.models import Scan, ScanStatus
    from app.scanner.runner import execute_scan

    session = session_scope()
    scan = Scan(
        cruise_id=cruise_id,
        status=ScanStatus.QUEUED.value,
        conditions={"profiles": ["clean_win_chrome", "clean_iphone"], "rounds": 1},
    )
    session.add(scan)
    session.commit()
    scan_id = scan.id
    session.close()
    execute_scan(scan_id)

    detail = client.get(f"/api/scans/{scan_id}").json()
    assert detail["status"] == "DONE"
    assert len(detail["results"]) == 2
    assert detail["analysis"]["verdict"] == "difference"
    assert detail["results"][0]["conditions"]["locale"] == "de-DE"

    # artifacts are reachable
    screenshot = detail["results"][0]["screenshot_path"]
    assert screenshot
    artifact = client.get(f"/api/artifacts/{screenshot}")
    assert artifact.status_code == 200
    assert artifact.headers["content-type"].startswith("image/png")

    # html snapshot is served as plain text (never executed)
    html_paths = [a["html"] for a in detail["results"][0]["artifacts"] if a.get("html")]
    if html_paths:
        snapshot = client.get(f"/api/artifacts/{html_paths[0]}")
        assert snapshot.status_code == 200
        assert snapshot.headers["content-type"].startswith("text/plain")

    # history + detail view
    cruise_detail = client.get(f"/api/cruises/{cruise_id}").json()
    assert cruise_detail["overview"]["best_price_ever"] == 2876.0
    assert cruise_detail["history"][-1]["lowest_price"] == 2876.0
    assert cruise_detail["latest_analysis"]["verdict"] == "difference"

    history = client.get(f"/api/cruises/{cruise_id}/history").json()
    assert history[-1]["highest_price"] == 2998.0

    # logs (debug trail)
    logs = client.get(f"/api/scans/{scan_id}/logs").json()
    assert logs and all("proxysecret" not in row["message"] for row in logs)

    # patch + delete
    patched = client.patch(f"/api/cruises/{cruise_id}", json={"schedule_interval": "manual", "title": "Testreise"})
    assert patched.json()["title"] == "Testreise"
    assert patched.json()["next_check_at"] is None
    assert client.delete(f"/api/cruises/{cruise_id}").status_code == 204
    assert client.get(f"/api/cruises/{cruise_id}").status_code == 404


def test_artifact_path_traversal_is_blocked(client):
    assert client.get("/api/artifacts/../../etc/passwd").status_code in (400, 404)
    assert client.get("/api/artifacts/%2e%2e%2f%2e%2e%2fetc%2fpasswd").status_code in (400, 404)


def test_artifact_type_restriction(client):
    path = os.path.join(settings.data_dir, "secret.env")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("API_KEY=abc")
    response = client.get("/api/artifacts/secret.env")
    assert response.status_code == 403


def test_alerts_api(client):
    cruise_id = client.post(
        "/api/cruises", json={"url": "mock://cruise/api-alert", "start_scan": False}
    ).json()["cruise"]["id"]
    bad = client.post(f"/api/cruises/{cruise_id}/alerts", json={"channel": "email"})
    assert bad.status_code == 400
    created = client.post(
        f"/api/cruises/{cruise_id}/alerts",
        json={"channel": "telegram", "threshold_total": 2800, "target": "12345"},
    )
    assert created.status_code == 201
    alert_id = created.json()["id"]
    assert client.get(f"/api/cruises/{cruise_id}/alerts").json()[0]["threshold_total"] == 2800.0
    test_result = client.post(f"/api/alerts/{alert_id}/test").json()
    assert test_result["sent"] is False  # channel not configured in tests
    assert client.delete(f"/api/alerts/{alert_id}").status_code == 204


def test_scan_rejects_unknown_cruise(client):
    assert client.post("/api/cruises/999999/scans", json={"rounds": 1}).status_code == 404


def test_scan_options_are_validated(client):
    cruise_id = client.post(
        "/api/cruises", json={"url": "mock://cruise/api-validate", "start_scan": False}
    ).json()["cruise"]["id"]
    assert client.post(f"/api/cruises/{cruise_id}/scans", json={"rounds": 99}).status_code == 422


def test_admin_endpoints(client):
    status = client.get("/api/admin/status").json()
    assert status["counts"]["cruises"] >= 0
    assert status["queue"]["max_concurrent_scans"] >= 1
    assert status["scheduler"]["enabled"] is False
    assert [p["label"] for p in status["proxy_profiles"]] == ["DE Testanschluss"]
    assert "proxysecret" not in client.get("/api/admin/status").text
    assert isinstance(client.get("/api/admin/errors").json(), list)


def test_admin_debug_view_has_no_secrets(client):
    from app.db import session_scope
    from app.models import Scan
    from app.scanner.runner import execute_scan
    from app.services import get_or_create_cruise

    session = session_scope()
    cruise = get_or_create_cruise(session, "mock://cruise/api-debug")
    scan = Scan(cruise_id=cruise.id, conditions={"profiles": ["clean_win_chrome"], "rounds": 1})
    session.add(scan)
    session.commit()
    scan_id = scan.id
    session.close()
    execute_scan(scan_id)

    debug = client.get(f"/api/admin/debug/scan/{scan_id}")
    assert debug.status_code == 200
    data = debug.json()
    assert data["profiles"][0]["current_url"]
    assert data["profiles"][0]["page_type"] == "summary"
    assert data["profiles"][0]["prices_found"]["final_price"] == 2876.0
    assert data["logs"]
    text = debug.text.lower()
    for forbidden in ("proxysecret", "proxyuser", "set-cookie", "authorization"):
        assert forbidden not in text


def test_api_key_protects_mutations(monkeypatch, client):
    monkeypatch.setattr(settings, "api_key", "geheim")
    assert client.post("/api/cruises", json={"url": "mock://cruise/api-key"}).status_code == 401
    assert client.get("/api/admin/status").status_code == 401
    assert client.get("/api/cruises").status_code == 200  # reading stays open
    ok = client.post(
        "/api/cruises",
        json={"url": "mock://cruise/api-key", "start_scan": False},
        headers={"X-API-Key": "geheim"},
    )
    assert ok.status_code == 201


def test_openapi_is_available(client):
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"]
    assert "/api/cruises" in schema["paths"]


def test_timestamps_are_returned_with_timezone(client):
    """Zeitstempel muessen eine Zone tragen -- sonst zeigt die UI sie verschoben."""
    import re

    from app.db import session_scope
    from app.models import Scan
    from app.scanner.runner import execute_scan
    from app.services import get_or_create_cruise

    session = session_scope()
    cruise = get_or_create_cruise(session, "mock://cruise/api-timestamps")
    scan = Scan(cruise_id=cruise.id, conditions={"profiles": ["clean_win_chrome"], "rounds": 1})
    session.add(scan)
    session.commit()
    cruise_id, scan_id = cruise.id, scan.id
    session.close()
    execute_scan(scan_id)

    zone = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")

    scan_payload = client.get(f"/api/scans/{scan_id}").json()
    for field in ("started_at", "finished_at"):
        assert zone.search(scan_payload[field]), f"{field} ohne Zeitzone: {scan_payload[field]}"
    assert zone.search(scan_payload["results"][0]["created_at"])

    overview = next(item for item in client.get("/api/cruises").json() if item["id"] == cruise_id)
    assert zone.search(overview["last_checked_at"])

    history = client.get(f"/api/cruises/{cruise_id}/history").json()
    assert zone.search(history[-1]["timestamp"])

    logs = client.get(f"/api/scans/{scan_id}/logs").json()
    assert zone.search(logs[0]["created_at"])
