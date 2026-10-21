"""Phase 1: the mock portal behaves as the test cases require."""


def test_tc1_under_review(portal):
    r = portal.get("/claims/KRB-2026-00417")
    assert r.status_code == 200
    c = r.json()
    assert (c["claim_status"], c["season"], c["crop"]) == ("under_review", "Kharif 2026", "Paddy")
    for field in ("payment_status", "missing_documents", "record_version", "fetched_at", "source"):
        assert field in c


def test_tc2_missing_document_exact_name(portal):
    c = portal.get("/claims/KRB-2026-00521").json()
    assert c["missing_documents"] == ["Land Record (Khatauni)"]


def test_tc3_record_season_is_kharif(portal):
    assert portal.get("/claims/KRB-2026-00633").json()["season"] == "Kharif 2026"


def test_tc4_approved_not_credited(portal):
    c = portal.get("/claims/KRB-2026-00748").json()
    assert (c["claim_status"], c["payment_status"]) == ("approved", "not_credited")


def test_not_found_vs_down_are_different(portal):
    r = portal.get("/claims/KRB-2026-99999")
    assert r.status_code == 404 and r.json()["error"] == "not_found"
    portal.post("/admin/mode", json={"mode": "down"})
    r = portal.get("/claims/KRB-2026-00417")
    assert r.status_code == 503 and r.json()["error"] == "portal_down"


def test_season_change_bumps_version(portal):
    r = portal.post("/claims/KRB-2026-00633/season",
                    json={"season": "Rabi 2026-27", "expected_version": 1})
    assert r.status_code == 200 and r.json()["record_version"] == 2
    assert portal.get("/claims/KRB-2026-00633").json()["season"] == "Rabi 2026-27"


def test_invalid_season_rejected(portal):
    r = portal.post("/claims/KRB-2026-00633/season", json={"season": "Summer"})
    assert r.status_code == 422


def test_stale_version_conflict(portal):
    r = portal.post("/claims/KRB-2026-00633/season",
                    json={"season": "Rabi 2026-27", "expected_version": 7})
    assert r.status_code == 409 and r.json()["current_version"] == 1


def test_document_upload_clears_missing_and_status(portal):
    r = portal.post("/claims/KRB-2026-00521/documents",
                    json={"document_name": "Land Record (Khatauni)", "file_ref": "sample.pdf"})
    assert r.status_code == 200
    c = portal.get("/claims/KRB-2026-00521").json()
    assert c["missing_documents"] == [] and c["claim_status"] == "under_review"


def test_document_must_match_exactly(portal):
    r = portal.post("/claims/KRB-2026-00521/documents",
                    json={"document_name": "Land record", "file_ref": "sample.pdf"})
    assert r.status_code == 422 and r.json()["error"] == "document_not_requested"


def test_idempotency_key_replays_first_result(portal):
    body = {"season": "Rabi 2026-27", "idempotency_key": "act-1"}
    first = portal.post("/claims/KRB-2026-00633/season", json=body).json()
    second = portal.post("/claims/KRB-2026-00633/season", json=body).json()
    assert second["replayed"] is True and second["record_version"] == first["record_version"]
    assert portal.get("/claims/KRB-2026-00633").json()["record_version"] == 2  # applied once


def test_drop_writes_says_ok_but_does_not_save(portal):
    portal.post("/admin/mode", json={"mode": "drop_writes"})
    r = portal.post("/claims/KRB-2026-00633/season", json={"season": "Rabi 2026-27"})
    assert r.status_code == 200
    assert portal.get("/claims/KRB-2026-00633").json()["season"] == "Kharif 2026"


def test_slow_mode_still_applies_write(portal):
    portal.post("/admin/mode", json={"mode": "slow", "slow_seconds": 0.1})
    portal.post("/claims/KRB-2026-00633/season", json={"season": "Rabi 2026-27"})
    assert portal.get("/claims/KRB-2026-00633").json()["season"] == "Rabi 2026-27"


def test_simulate_credit(portal):
    assert portal.post("/simulate/credit/KRB-2026-00417").status_code == 409  # not approved
    c = portal.post("/simulate/credit/KRB-2026-00748").json()
    assert c["payment_status"] == "credited"


def test_incomplete_record_has_unknown_payment(portal):
    assert portal.get("/claims/KRB-2026-00850").json()["payment_status"] is None


def test_reset_reseeds(portal):
    portal.post("/claims/KRB-2026-00633/season", json={"season": "Rabi 2026-27"})
    portal.post("/admin/reset")
    assert portal.get("/claims/KRB-2026-00633").json()["season"] == "Kharif 2026"
