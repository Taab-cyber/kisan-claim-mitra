"""Every business rule in agent/rules.py (pure code, no portal needed)."""
from agent import rules

GOOD = {"app_no": "KRB-2026-00748", "claim_status": "approved", "payment_status": "not_credited",
        "season": "Kharif 2026", "crop": "Sugarcane", "missing_documents": [], "record_version": 1}


def test_valid_app_no():
    assert rules.valid_app_no("KRB-2026-00417")
    for bad in ("", None, "KRB-26-417", "krb-2026-00417", "KRB-2026-0041"):
        assert not rules.valid_app_no(bad)


def test_valid_season():
    assert rules.valid_season("Rabi 2026-27") and rules.valid_season("Kharif 2026")
    assert not rules.valid_season("Rabi 2026") and not rules.valid_season("summer")


def test_approved_is_not_paid():
    a = rules.assess_claim(GOOD)
    assert a["verdict"] == "OK" and a["payment"] == "NOT_PAID" and not a["is_paid"]


def test_paid_only_when_credited_and_approved():
    assert rules.payment_state({**GOOD, "payment_status": "credited"}) == "PAID"
    contradictory = {**GOOD, "claim_status": "under_review", "payment_status": "credited"}
    assert rules.payment_state(contradictory) == "UNCERTAIN"
    assert rules.assess_claim(contradictory)["verdict"] == "UNCERTAIN"


def test_missing_field_is_uncertain():
    for field in rules.REQUIRED_FIELDS:
        a = rules.assess_claim({**GOOD, field: None})
        assert a["verdict"] == "UNCERTAIN" and f"missing field: {field}" in a["problems"]


def test_unknown_status_is_uncertain():
    assert rules.assess_claim({**GOOD, "claim_status": "maybe"})["verdict"] == "UNCERTAIN"
    assert rules.payment_state({**GOOD, "payment_status": "processing"}) == "UNCERTAIN"


def test_documents_pending_without_list_is_uncertain():
    a = rules.assess_claim({**GOOD, "claim_status": "documents_pending", "missing_documents": []})
    assert a["verdict"] == "UNCERTAIN"


def test_missing_docs_exact_copy():
    claim = {**GOOD, "missing_documents": ["Land Record (Khatauni)"]}
    docs = rules.missing_documents(claim)
    assert docs == ["Land Record (Khatauni)"] and docs is not claim["missing_documents"]
    assert rules.missing_documents({"missing_documents": None}) == []


def test_season_mismatch():
    assert rules.season_mismatch("Kharif 2026", "Rabi 2026-27")
    assert not rules.season_mismatch("Kharif 2026", "kharif  2026")
    assert not rules.season_mismatch("Kharif 2026", None)


def test_failed_fetch_is_not_not_found():
    kinds = {k: rules.classify_fetch({"kind": k}) for k in ("ok", "not_found", "portal_down", "timeout", "error")}
    assert kinds == {"ok": "FOUND", "not_found": "NOT_FOUND", "portal_down": "PORTAL_DOWN",
                     "timeout": "TIMEOUT", "error": "ERROR"}


def test_intended_state():
    season = {"action_type": "season_change", "to": "Rabi 2026-27"}
    assert rules.intended_state_reached({"season": "Rabi 2026-27"}, season)
    assert not rules.intended_state_reached({"season": "Kharif 2026"}, season)
    doc = {"action_type": "document_upload", "document_name": "Land Record (Khatauni)"}
    done = {"missing_documents": [], "submitted_documents": [{"document_name": "Land Record (Khatauni)"}]}
    assert rules.intended_state_reached(done, doc)
    assert not rules.intended_state_reached({"missing_documents": [], "submitted_documents": []}, doc)
