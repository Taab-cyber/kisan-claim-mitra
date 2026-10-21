"""Stretch features: signup, mock OTP login, profile, document checks (synthetic samples)."""
import os

import pytest
from fastapi.testclient import TestClient

import server
from farmer import accounts, doccheck, samples

NEW = {"name": "Sita Devi", "mobile": "nau aath saat chhe paanch chaar teen do ek ek",
       "village": "Rampur", "district": "Sample District", "land_acres": "2.5", "main_crop": "गेहूं"}


@pytest.fixture
def api(portal):
    server.configure(portal)
    with TestClient(server.app) as client:      # startup re-seeds accounts + samples
        yield client
    server.STATE.clear()


def sample_bytes(name):
    with open(os.path.join(samples.OUT_DIR, name), "rb") as f:
        return f.read()


def login(api, mobile=accounts.DEMO_MOBILE):
    otp = api.post("/api/auth/otp/request", json={"mobile": mobile}).json()["mock_otp"]
    return api.post("/api/auth/otp/verify", json={"mobile": mobile, "otp": otp}).json()["token"]


# ---------- document checks ----------

@pytest.mark.parametrize("name,status,failed", [
    ("land_record_sample.png", "PASSED", []),
    ("bank_passbook_blurry.png", "NEEDS_FIX", ["blur"]),
    ("land_record_dark.png", "NEEDS_FIX", ["lighting"]),
    ("aadhaar_card_tiny.png", "NEEDS_FIX", ["resolution"]),
    ("pan_card_sample.pdf", "REVIEW", []),
])
def test_sample_checks(name, status, failed):
    r = doccheck.check_document(name, sample_bytes(name))
    bad = [c["name"] for c in r["checks"] if not c["ok"]]
    assert r["status"] == status and all(f in bad for f in failed)


def test_fake_extension_and_size_limits():
    assert doccheck.check_document("photo.png", b"%PDF-1.4" + b"x" * 500)["status"] == "NEEDS_FIX"
    assert doccheck.check_document("virus.exe", b"MZ" + b"x" * 500)["status"] == "NEEDS_FIX"
    assert doccheck.check_document("empty.png", b"")["status"] == "NEEDS_FIX"
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (doccheck.MAX_BYTES + 1)
    assert doccheck.check_document("big.png", big)["checks"][1]["ok"] is False


# ---------- signup ----------

def test_signup_missing_fields_are_listed(api):
    r = api.post("/api/auth/signup", json={"name": "Sita"})
    assert r.status_code == 422 and set(r.json()["fields"]) == {"mobile", "village", "district", "land_acres", "main_crop"}


def test_signup_invalid_fields(api):
    r = api.post("/api/auth/signup", json={**NEW, "mobile": "12345", "land_acres": "lots"})
    assert r.status_code == 422 and set(r.json()["fields"]) == {"mobile", "land_acres"}


def test_signup_spoken_mobile_then_duplicate(api):
    r = api.post("/api/auth/signup", json=NEW)
    assert r.status_code == 200 and r.json()["mobile_masked"] == "98••••••11"
    assert api.post("/api/auth/signup", json=NEW).status_code == 409   # same number again


# ---------- mock OTP ----------

def test_otp_login_flow_and_profile(api):
    res = api.post("/api/auth/otp/request", json={"mobile": "98765 43210"}).json()
    assert res["sent_to"] == "98••••••10" and len(res["mock_otp"]) == 6
    assert api.post("/api/auth/otp/request", json={"mobile": "9876543210"}).status_code == 429  # cooldown
    bad = api.post("/api/auth/otp/verify", json={"mobile": "9876543210", "otp": "000000" if res["mock_otp"] != "000000" else "111111"})
    assert bad.status_code == 401 and bad.json()["attempts_left"] == 4
    ok = api.post("/api/auth/otp/verify", json={"mobile": "9876543210", "otp": res["mock_otp"]}).json()
    assert ok["token"] and ok["profile"]["farmer"]["mobile_verified"]
    # OTP is single-use
    assert api.post("/api/auth/otp/verify", json={"mobile": "9876543210", "otp": res["mock_otp"]}).status_code == 400


def test_otp_locks_after_too_many_wrong_tries(api):
    code = api.post("/api/auth/otp/request", json={"mobile": accounts.DEMO_MOBILE}).json()["mock_otp"]
    wrong = "123456" if code != "123456" else "654321"
    for _ in range(accounts.OTP_MAX_ATTEMPTS):
        api.post("/api/auth/otp/verify", json={"mobile": accounts.DEMO_MOBILE, "otp": wrong})
    r = api.post("/api/auth/otp/verify", json={"mobile": accounts.DEMO_MOBILE, "otp": code})
    assert r.status_code == 429      # even the right code is refused once locked


def test_unregistered_mobile(api):
    assert api.post("/api/auth/otp/request", json={"mobile": "6000000000"}).status_code == 404


def test_otp_and_token_never_in_evidence(api):
    token = login(api)
    log = api.get("/api/evidence").text
    assert token not in log and "[redacted]" in log
    assert accounts.DEMO_MOBILE not in log          # mobile is masked


# ---------- profile + documents ----------

def test_profile_needs_login(api):
    assert api.get("/api/profile").status_code == 401
    assert api.post("/api/profile/documents/land_record",
                    files={"file": ("a.png", b"x")}).status_code == 401


def test_demo_profile_flags_match_mockup(api):
    p = api.get("/api/profile", headers={"Authorization": f"Bearer {login(api)}"}).json()
    status = {d["doc_type"]: d["status"] for d in p["documents"]}
    assert status == {"aadhaar_card": "PASSED", "pan_card": "REVIEW", "land_record": "MISSING",
                      "bank_passbook": "NEEDS_FIX", "insurance_papers": "PASSED"}
    assert set(p["attention"]) == {"land_record", "bank_passbook"}


def test_upload_fixes_flags(api):
    auth = {"Authorization": f"Bearer {login(api)}"}
    for doc, file in [("land_record", "land_record_sample.png"), ("bank_passbook", "bank_passbook_sample.png")]:
        r = api.post(f"/api/profile/documents/{doc}", headers=auth,
                     files={"file": (file, sample_bytes(file), "image/png")}).json()
        assert r["result"]["status"] == "PASSED"
    assert api.get("/api/profile", headers=auth).json()["attention"] == []


def test_unknown_doc_type(api):
    auth = {"Authorization": f"Bearer {login(api)}"}
    r = api.post("/api/profile/documents/passport", headers=auth,
                 files={"file": ("a.png", sample_bytes("land_record_sample.png"))})
    assert r.status_code == 422
