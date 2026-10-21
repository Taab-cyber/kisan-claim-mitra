"""Business rules. Plain code only - no ML here, so every decision is auditable.

Key rules:
  - missing documents are the EXACT strings from the portal, never invented
  - claim approval and payment are separate; "paid" only if payment_status == "credited"
  - missing or contradictory data -> UNCERTAIN (we never guess)
  - a failed fetch (portal down / timeout) is NOT the same as "record not found"
"""
import re

APP_NO_RE = re.compile(r"^KRB-\d{4}-\d{5}$")
SEASON_RE = re.compile(r"^((Kharif|Zaid) \d{4}|Rabi \d{4}-\d{2})$")

CLAIM_STATUSES = {"under_review", "documents_pending", "approved", "rejected"}
PAYMENT_STATUSES = {"not_credited", "credited"}
REQUIRED_FIELDS = ("claim_status", "payment_status", "season", "crop",
                   "missing_documents", "record_version")


def valid_app_no(app_no):
    return bool(app_no) and bool(APP_NO_RE.match(app_no))


def valid_season(season):
    return bool(season) and bool(SEASON_RE.match(season))


def classify_fetch(result):
    """Map a tool result to FOUND / NOT_FOUND / PORTAL_DOWN / TIMEOUT / INVALID / ERROR."""
    return {"ok": "FOUND", "not_found": "NOT_FOUND", "portal_down": "PORTAL_DOWN",
            "timeout": "TIMEOUT", "invalid_input": "INVALID"}.get(result["kind"], "ERROR")


def missing_documents(claim):
    """Exactly what the portal says - a copy of its list, nothing added or renamed."""
    docs = claim.get("missing_documents")
    return list(docs) if isinstance(docs, list) else []


def season_mismatch(record_season, stated_season):
    """True if the farmer's season differs from the record (case/space-insensitive)."""
    if not record_season or not stated_season:
        return False
    norm = lambda s: " ".join(s.lower().split())
    return norm(record_season) != norm(stated_season)


def payment_state(claim):
    """PAID / NOT_PAID / UNCERTAIN. Approval alone NEVER means paid."""
    status, payment = claim.get("claim_status"), claim.get("payment_status")
    if payment not in PAYMENT_STATUSES:
        return "UNCERTAIN"
    if payment == "credited":
        # money credited on a claim that is not approved is contradictory
        return "PAID" if status == "approved" else "UNCERTAIN"
    return "NOT_PAID"


def assess_claim(claim):
    """Full decision for a fetched claim. Returns a dict with a verdict and reasons."""
    problems = [f"missing field: {f}" for f in REQUIRED_FIELDS if claim.get(f) is None]
    status = claim.get("claim_status")
    if status is not None and status not in CLAIM_STATUSES:
        problems.append(f"unknown claim_status: {status}")
    if claim.get("payment_status") is not None and claim["payment_status"] not in PAYMENT_STATUSES:
        problems.append(f"unknown payment_status: {claim['payment_status']}")
    if claim.get("payment_status") == "credited" and status != "approved":
        problems.append("contradiction: payment credited but claim not approved")
    docs = missing_documents(claim)
    if status == "documents_pending" and not docs:
        problems.append("contradiction: documents pending but no missing document listed")

    payment = payment_state(claim)
    return {
        "verdict": "UNCERTAIN" if problems else "OK",
        "claim_status": status,
        "payment": payment,
        "is_paid": payment == "PAID",
        "missing_documents": docs,
        "problems": problems,
        "reason": "; ".join(problems) if problems else
                  f"claim_status={status}, payment_status={claim.get('payment_status')}, "
                  f"missing_documents={docs}",
    }


def intended_state_reached(claim, change):
    """Does the portal record now show the change we intended? (used by verify.py)"""
    if change["action_type"] == "season_change":
        return claim.get("season") == change["to"]
    if change["action_type"] == "document_upload":
        submitted = [d.get("document_name") for d in claim.get("submitted_documents") or []]
        return (change["document_name"] not in missing_documents(claim)
                and change["document_name"] in submitted)
    return False
