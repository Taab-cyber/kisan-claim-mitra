"""Web API: farmer flow, backend approval enforcement, voice provider switch, console runner."""
import pytest
from fastapi.testclient import TestClient

import server
from portal.app import app as portal_app


@pytest.fixture
def api(portal, monkeypatch):
    monkeypatch.setenv("VOICE_PROVIDER", "browser")
    server.configure(portal)               # agent talks to the in-process portal
    with TestClient(server.app) as client:
        yield client
    server.STATE.clear()


def new_session(api, lang="en"):
    return api.post("/api/session", json={"lang": lang}).json()["session_id"]


def test_pages_are_served(api):
    assert "Kisan Claim Mitra" in api.get("/").text
    assert "Judge Console" in api.get("/console.html").text


def test_chat_tc4_over_api(api):
    sid = new_session(api)
    r = api.post("/api/chat", json={"session_id": sid, "text": "status KRB-2026-00748"}).json()
    assert r["assessment"]["payment"] == "NOT_PAID" and "NOT been credited" in r["reply"]


def test_approve_endpoint_flow_and_isolation(api, portal):
    a, b = new_session(api), new_session(api)
    r = api.post("/api/chat", json={"session_id": a, "text": "KRB-2026-00633 season rabi 2026-27 karo"}).json()
    pid = r["proposal"]["id"]
    stolen = api.post("/api/approve", json={"session_id": b, "proposal_id": pid, "approve": True})
    assert stolen.status_code == 403
    assert portal.get("/claims/KRB-2026-00633").json()["season"] == "Kharif 2026"
    ok = api.post("/api/approve", json={"session_id": a, "proposal_id": pid, "approve": True}).json()
    assert ok["verification"]["status"] == "VERIFIED"
    again = api.post("/api/approve", json={"session_id": a, "proposal_id": pid, "approve": True}).json()
    assert again["replayed"] is True
    assert portal.get("/claims/KRB-2026-00633").json()["record_version"] == 2


def test_unknown_session_is_404(api):
    r = api.post("/api/chat", json={"session_id": "nope", "text": "hi"})
    assert r.status_code == 404


def test_voice_browser_is_default(api):
    cfg = api.get("/api/voice/config").json()
    assert cfg["provider"] == "browser" and cfg["notice"] is None
    assert api.post("/api/voice/tts", json={"text": "hi"}).status_code == 409


def test_verbx_key_never_reaches_browser_and_falls_back(api, monkeypatch):
    monkeypatch.setenv("VOICE_PROVIDER", "verbx")
    monkeypatch.setenv("VERBX_API_KEY", "secret-test-key-123")
    for path in ("/api/voice/config",):
        assert "secret-test-key-123" not in api.get(path).text
    session = api.post("/api/session", json={"lang": "hi"})
    assert "secret-test-key-123" not in session.text
    cfg = session.json()["voice"]
    assert cfg["provider"] == "verbx" and cfg["verbx_ready"] is False and cfg["notice"]
    tts = api.post("/api/voice/tts", json={"text": "नमस्ते", "lang": "hi"})
    assert tts.status_code == 503 and "secret" not in tts.text      # browser falls back


def test_console_runs_real_scenario(api):
    ids = [s["id"] for s in api.get("/api/scenarios").json()["scenarios"]]
    assert ids[:4] == ["TC1", "TC2", "TC3", "TC4"]
    res = api.post("/api/scenarios/run", json={"ids": ["TC4"]}).json()["results"]
    assert res[0]["passed"] and res[0]["evidence"]


def test_evidence_endpoint_filters_by_session(api):
    sid = new_session(api)
    api.post("/api/chat", json={"session_id": sid, "text": "namaste"})
    entries = api.get(f"/api/evidence?session_id={sid}").json()["entries"]
    assert entries and all(e["session_id"] == sid for e in entries)
