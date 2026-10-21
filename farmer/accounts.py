"""Farmer accounts, mock OTP login and document check results (SYNTHETIC data only).

- Profile data lives in its own SQLite DB, re-seeded with one demo farmer at startup.
- OTP is a MOCK: the code is returned to the UI and shown as a "demo SMS". The farmer
  must type it in themselves; the agent never fills or bypasses it.
- Uploaded files are NOT stored. Only the file name, size and check results are kept.
- We never ask for or store Aadhaar/PAN/bank numbers.
"""
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time

from agent.nlu.entities import CROPS, extract_digits
from farmer import doccheck, samples

DOC_TYPES = {   # key -> (Hindi, English)
    "aadhaar_card": ("आधार कार्ड", "Aadhaar card"),
    "pan_card": ("पैन कार्ड", "PAN card"),
    "land_record": ("भूमि रिकॉर्ड (खतौनी)", "Land Record (Khatauni)"),
    "bank_passbook": ("बैंक पासबुक", "Bank passbook"),
    "insurance_papers": ("बीमा पॉलिसी", "Insurance papers"),
}
OTP_TTL, OTP_COOLDOWN, OTP_MAX_ATTEMPTS = 300, 30, 5
DEMO_MOBILE = "9876543210"

_conn, _lock = None, threading.Lock()
_otps, _tokens = {}, {}     # mobile -> otp record ; token -> farmer id (in memory)


class AccountError(Exception):
    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def mask_mobile(mobile):
    return mobile[:2] + "•" * 6 + mobile[-2:]


# ---------- storage ----------

def init_db():
    """Fresh DB with one demo farmer whose documents match the mockup (checked for real)."""
    global _conn
    samples.ensure_samples()
    with _lock:
        _conn = sqlite3.connect(":memory:", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript("""
            CREATE TABLE farmers (id INTEGER PRIMARY KEY, name TEXT, mobile TEXT UNIQUE, village TEXT,
                                  district TEXT, land_acres REAL, main_crop TEXT, mobile_verified INTEGER);
            CREATE TABLE documents (farmer_id INTEGER, doc_type TEXT, file_name TEXT, status TEXT,
                                    result TEXT, checked_at REAL, PRIMARY KEY (farmer_id, doc_type));""")
        _conn.execute("INSERT INTO farmers VALUES (1,'Ramlal Singh (synthetic)',?,'Rampur',"
                      "'Sample District',3.5,'Paddy',1)", (DEMO_MOBILE,))
        _conn.commit()
    _otps.clear()
    _tokens.clear()
    for doc_type, file in [("aadhaar_card", "aadhaar_card_sample.png"), ("pan_card", "pan_card_sample.pdf"),
                           ("bank_passbook", "bank_passbook_blurry.png"),
                           ("insurance_papers", "insurance_papers_sample.png")]:
        with open(os.path.join(samples.OUT_DIR, file), "rb") as f:
            save_document(1, doc_type, file, f.read())   # land_record stays MISSING


def _farmer(farmer_id):
    with _lock:
        row = _conn.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
    return dict(row) if row else None


# ---------- signup ----------

def validate_signup(data):
    """Returns cleaned fields. Missing fields -> 422 listing them (we ask, never guess)."""
    fields = ("name", "mobile", "village", "district", "land_acres", "main_crop")
    missing = [f for f in fields if not str(data.get(f) or "").strip()]
    if missing:
        raise AccountError(422, "missing_fields", "Some details are missing.", fields=missing)
    errors, clean = {}, {}
    clean["name"] = " ".join(str(data["name"]).split())[:60]
    if len(clean["name"]) < 2:
        errors["name"] = "too short"
    clean["mobile"] = extract_digits(str(data["mobile"]))
    if not re.fullmatch(r"[6-9]\d{9}", clean["mobile"]):
        errors["mobile"] = "must be a 10-digit Indian mobile number starting with 6-9"
    for f in ("village", "district"):
        clean[f] = " ".join(str(data[f]).split())[:60]
        if len(clean[f]) < 2:
            errors[f] = "too short"
    try:
        clean["land_acres"] = float(str(data["land_acres"]).replace(",", "."))
        if not 0 < clean["land_acres"] <= 1000:
            errors["land_acres"] = "must be between 0 and 1000"
    except ValueError:
        errors["land_acres"] = "must be a number, e.g. 3.5"
    crop = str(data["main_crop"]).strip()
    clean["main_crop"] = CROPS.get(crop.lower(), crop[:30])
    if errors:
        raise AccountError(422, "invalid_fields", "Some details need correction.", fields=errors)
    return clean


def signup(data):
    clean = validate_signup(data)
    with _lock:
        if _conn.execute("SELECT 1 FROM farmers WHERE mobile = ?", (clean["mobile"],)).fetchone():
            raise AccountError(409, "already_registered", "This mobile number is already registered. Please log in.")
        cur = _conn.execute("INSERT INTO farmers (name, mobile, village, district, land_acres, main_crop, "
                            "mobile_verified) VALUES (?,?,?,?,?,?,0)",
                            tuple(clean[k] for k in ("name", "mobile", "village", "district", "land_acres", "main_crop")))
        _conn.commit()
    return {"farmer_id": cur.lastrowid, "mobile_masked": mask_mobile(clean["mobile"])}


# ---------- mock OTP ----------

def request_otp(mobile):
    mobile = extract_digits(mobile or "")
    with _lock:
        row = _conn.execute("SELECT id FROM farmers WHERE mobile = ?", (mobile,)).fetchone()
    if not row:
        raise AccountError(404, "not_registered", "This mobile number is not registered. Please create an account.")
    old = _otps.get(mobile)
    if old and time.time() - old["sent_at"] < OTP_COOLDOWN:
        wait = int(OTP_COOLDOWN - (time.time() - old["sent_at"])) + 1
        raise AccountError(429, "cooldown", f"Please wait {wait} seconds before asking again.", retry_after=wait)
    code = f"{secrets.randbelow(10**6):06d}"
    _otps[mobile] = {"code": code, "sent_at": time.time(), "attempts": 0, "farmer_id": row["id"]}
    # MOCK SMS: returned so the UI can show it. A real system would send an SMS instead.
    return {"sent_to": mask_mobile(mobile), "mock_otp": code, "expires_in": OTP_TTL, "resend_in": OTP_COOLDOWN}


def verify_otp(mobile, code):
    mobile = extract_digits(mobile or "")
    rec = _otps.get(mobile)
    if not rec:
        raise AccountError(400, "no_otp", "Please request an OTP first.")
    if time.time() - rec["sent_at"] > OTP_TTL:
        _otps.pop(mobile, None)
        raise AccountError(410, "expired", "This OTP has expired. Please request a new one.")
    if rec["attempts"] >= OTP_MAX_ATTEMPTS:
        raise AccountError(429, "locked", "Too many wrong tries. Please request a new OTP.")
    if not hmac.compare_digest(rec["code"], str(code or "").strip()):
        rec["attempts"] += 1
        raise AccountError(401, "wrong_otp", "Wrong OTP.", attempts_left=OTP_MAX_ATTEMPTS - rec["attempts"])
    _otps.pop(mobile, None)
    with _lock:
        _conn.execute("UPDATE farmers SET mobile_verified = 1 WHERE id = ?", (rec["farmer_id"],))
        _conn.commit()
    token = secrets.token_urlsafe(24)
    _tokens[token] = rec["farmer_id"]
    return token, rec["farmer_id"]


def farmer_for_token(token):
    fid = _tokens.get(token or "")
    if not fid:
        raise AccountError(401, "not_logged_in", "Please log in.")
    return fid


def logout(token):
    _tokens.pop(token or "", None)


# ---------- documents + profile ----------

def save_document(farmer_id, doc_type, file_name, content):
    if doc_type not in DOC_TYPES:
        raise AccountError(422, "unknown_doc_type", f"Unknown document type {doc_type}.")
    result = doccheck.check_document(file_name, content)   # file bytes are NOT stored
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?)",
                      (farmer_id, doc_type, os.path.basename(file_name or "")[:80], result["status"],
                       json.dumps(result), time.time()))
        _conn.commit()
    return result


def profile(farmer_id):
    f = _farmer(farmer_id)
    with _lock:
        rows = {r["doc_type"]: dict(r) for r in
                _conn.execute("SELECT * FROM documents WHERE farmer_id = ?", (farmer_id,))}
    docs = []
    for key, (hi, en) in DOC_TYPES.items():
        r = rows.get(key)
        result = json.loads(r["result"]) if r else None
        docs.append({"doc_type": key, "name_hi": hi, "name_en": en,
                     "status": r["status"] if r else "MISSING",
                     "file_name": r["file_name"] if r else None,
                     "problems": [c for c in (result or {}).get("checks", []) if not c["ok"]],
                     "checks": (result or {}).get("checks", [])})
    attention = [d for d in docs if d["status"] in ("MISSING", "NEEDS_FIX")]
    return {"farmer": {k: f[k] for k in ("name", "village", "district", "land_acres", "main_crop")}
            | {"mobile_masked": mask_mobile(f["mobile"]), "mobile_verified": bool(f["mobile_verified"])},
            "documents": docs, "attention": [d["doc_type"] for d in attention]}
