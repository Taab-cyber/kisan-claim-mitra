"""SQLite storage for the mock insurance portal.

All data is SYNTHETIC. The database is dropped and re-seeded every time the
portal starts, so the demo always begins from the same known state.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

# One shared connection + a lock keeps things simple and safe for a small demo.
_conn = None
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE claims (
    app_no            TEXT PRIMARY KEY,
    farmer_name       TEXT,
    district          TEXT,
    season            TEXT,
    crop              TEXT,
    claim_status      TEXT,   -- under_review | documents_pending | approved | rejected
    payment_status    TEXT,   -- not_credited | credited  (NULL = unknown)
    missing_documents TEXT,   -- JSON list of exact document names
    submitted_documents TEXT, -- JSON list of {document_name, file_ref}
    record_version    INTEGER NOT NULL DEFAULT 1,
    updated_at        TEXT
);
-- Remembers write requests so a retried request returns the first result.
CREATE TABLE idempotency (
    key       TEXT PRIMARY KEY,
    response  TEXT NOT NULL
);
"""

# Synthetic seed data. TC1-TC4 are the official test cases.
SEED_CLAIMS = [
    # TC1: valid application, simply under review
    dict(app_no="KRB-2026-00417", farmer_name="Ramesh Kumar (synthetic)", district="Sitapur",
         season="Kharif 2026", crop="Paddy", claim_status="under_review",
         payment_status="not_credited", missing_documents=[]),
    # TC2: one document missing - name must be shown EXACTLY as below
    dict(app_no="KRB-2026-00521", farmer_name="Sunita Devi (synthetic)", district="Barabanki",
         season="Kharif 2026", crop="Cotton", claim_status="documents_pending",
         payment_status="not_credited", missing_documents=["Land Record (Khatauni)"]),
    # TC3: record says Kharif 2026, farmer will say Rabi 2026-27
    dict(app_no="KRB-2026-00633", farmer_name="Mohan Singh (synthetic)", district="Hardoi",
         season="Kharif 2026", crop="Wheat", claim_status="under_review",
         payment_status="not_credited", missing_documents=[]),
    # TC4: claim approved but money NOT credited yet (approved != paid)
    dict(app_no="KRB-2026-00748", farmer_name="Geeta Yadav (synthetic)", district="Lakhimpur",
         season="Kharif 2026", crop="Sugarcane", claim_status="approved",
         payment_status="not_credited", missing_documents=[]),
    # Extra: incomplete record (payment status unknown) -> agent must say UNCERTAIN
    dict(app_no="KRB-2026-00850", farmer_name="Arjun Pal (synthetic)", district="Unnao",
         season="Kharif 2026", crop="Maize", claim_status="approved",
         payment_status=None, missing_documents=[]),
]


def now_iso():
    """Current UTC time as an ISO string, e.g. 2026-10-21T10:15:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db(path=None):
    """Create a fresh database and seed it. Safe to call again to reset."""
    global _conn
    path = path or os.getenv("PORTAL_DB", ":memory:")
    with _lock:
        if _conn is not None:
            _conn.close()
        if path != ":memory:" and os.path.exists(path):
            os.remove(path)  # always start from a clean, known state
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        for c in SEED_CLAIMS:
            _conn.execute(
                "INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                (c["app_no"], c["farmer_name"], c["district"], c["season"], c["crop"],
                 c["claim_status"], c["payment_status"], json.dumps(c["missing_documents"]),
                 json.dumps([]), now_iso()),
            )
        _conn.commit()


def get_claim(app_no):
    """Return the claim as a dict, or None if it does not exist."""
    with _lock:
        row = _conn.execute("SELECT * FROM claims WHERE app_no = ?", (app_no,)).fetchone()
    if row is None:
        return None
    claim = dict(row)
    claim["missing_documents"] = json.loads(claim["missing_documents"])
    claim["submitted_documents"] = json.loads(claim["submitted_documents"])
    return claim


def update_claim(app_no, **fields):
    """Update some fields and bump record_version by 1. Lists are stored as JSON."""
    for key in ("missing_documents", "submitted_documents"):
        if key in fields:
            fields[key] = json.dumps(fields[key])
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        _conn.execute(
            f"UPDATE claims SET {sets}, record_version = record_version + 1 WHERE app_no = ?",
            (*fields.values(), app_no),
        )
        _conn.commit()


def get_idempotent(key):
    """Return the saved response for an idempotency key, or None."""
    with _lock:
        row = _conn.execute("SELECT response FROM idempotency WHERE key = ?", (key,)).fetchone()
    return json.loads(row["response"]) if row else None


def save_idempotent(key, response):
    with _lock:
        _conn.execute("INSERT OR REPLACE INTO idempotency VALUES (?, ?)", (key, json.dumps(response)))
        _conn.commit()
