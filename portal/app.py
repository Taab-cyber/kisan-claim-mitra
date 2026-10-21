"""Mock crop-insurance portal (our designated demo target).

Run alone:  uvicorn portal.app:app --port 8001
Everything here is SYNTHETIC. No real farmer, Aadhaar, PAN or bank data.

Failure simulation ("mode"), set by env PORTAL_MODE or POST /admin/mode:
  normal       - everything works
  down         - every claim endpoint returns 503 "portal_down"
  slow         - responses are delayed PORTAL_SLOW_SECONDS (writes ARE applied first,
                 like a real server that finished the work but answered too late)
  slow_writes  - like slow, but only for writes (reads stay fast)
  drop_writes  - writes answer "ok" but are NOT saved (lets us test verification failure)
"""
import asyncio
import os
import re
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from portal import db

MODES = ("normal", "down", "slow", "slow_writes", "drop_writes")
STATE = {
    "mode": os.getenv("PORTAL_MODE", "normal"),
    "slow_seconds": float(os.getenv("PORTAL_SLOW_SECONDS", "3")),
}

# Valid season formats: "Kharif 2026", "Zaid 2027", "Rabi 2026-27"
SEASON_RE = re.compile(r"^((Kharif|Zaid) \d{4}|Rabi \d{4}-\d{2})$")


@asynccontextmanager
async def lifespan(app):
    db.init_db()  # fresh, re-seeded database on every startup
    yield


app = FastAPI(title="Mock Crop Insurance Portal (synthetic)", lifespan=lifespan)


# ---------- helpers ----------

def error(status, code, message, **extra):
    """Uniform error body so the agent can tell 404 'not found' from 503 'portal down'."""
    return JSONResponse(status_code=status, content={"error": code, "message": message, **extra})


async def apply_mode():
    """Return a 503 response if the portal is 'down'; sleep if it is 'slow'."""
    if STATE["mode"] == "down":
        return error(503, "portal_down", "Portal is temporarily unavailable. Please try later.")
    if STATE["mode"] == "slow":
        await asyncio.sleep(STATE["slow_seconds"])
    return None


def public_view(claim):
    """The fields the portal exposes for a claim, plus where/when it was read."""
    return {
        "app_no": claim["app_no"],
        "farmer_name": claim["farmer_name"],
        "district": claim["district"],
        "season": claim["season"],
        "crop": claim["crop"],
        "claim_status": claim["claim_status"],
        "payment_status": claim["payment_status"],
        "missing_documents": claim["missing_documents"],
        "submitted_documents": claim["submitted_documents"],
        "record_version": claim["record_version"],
        "source": f"/claims/{claim['app_no']}",
        "fetched_at": db.now_iso(),
    }


def check_write_preconditions(app_no, req):
    """Shared checks for write endpoints. Returns (claim, error_response_or_None)."""
    claim = db.get_claim(app_no)
    if claim is None:
        return None, error(404, "not_found", f"No application found with number {app_no}.")
    if req.expected_version is not None and req.expected_version != claim["record_version"]:
        return claim, error(409, "version_conflict", "Record changed since it was read.",
                            current_version=claim["record_version"])
    return claim, None


# ---------- request bodies ----------

class SeasonChange(BaseModel):
    season: str
    expected_version: Optional[int] = None   # optimistic lock: reject if record changed
    idempotency_key: Optional[str] = None    # same key twice -> same first result


class DocumentUpload(BaseModel):
    document_name: str                       # must EXACTLY match a missing document
    file_ref: str                            # reference to a synthetic sample file
    expected_version: Optional[int] = None
    idempotency_key: Optional[str] = None


class ModeChange(BaseModel):
    mode: str
    slow_seconds: Optional[float] = None


# ---------- claim endpoints ----------

@app.get("/claims")
async def list_claims():
    """List seeded application numbers (handy for the judge console)."""
    if (resp := await apply_mode()) is not None:
        return resp
    return {"app_nos": [c["app_no"] for c in db.SEED_CLAIMS]}


@app.get("/claims/{app_no}")
async def read_claim(app_no: str):
    if (resp := await apply_mode()) is not None:
        return resp
    claim = db.get_claim(app_no)
    if claim is None:
        return error(404, "not_found", f"No application found with number {app_no}.")
    return public_view(claim)


@app.post("/claims/{app_no}/season")
async def change_season(app_no: str, req: SeasonChange):
    if STATE["mode"] == "down":
        return await apply_mode()
    if req.idempotency_key and (saved := db.get_idempotent(req.idempotency_key)):
        return {**saved, "replayed": True}
    if not SEASON_RE.match(req.season):
        return error(422, "invalid_season", "Season must look like 'Kharif 2026' or 'Rabi 2026-27'.")
    claim, err = check_write_preconditions(app_no, req)
    if err:
        return err

    if STATE["mode"] != "drop_writes" and req.season != claim["season"]:
        db.update_claim(app_no, season=req.season)
    after = db.get_claim(app_no)
    result = {"ok": True, "app_no": app_no, "action": "season_change",
              "requested_season": req.season, "record_version": after["record_version"]}
    if req.idempotency_key:
        db.save_idempotent(req.idempotency_key, result)
    if STATE["mode"] in ("slow", "slow_writes"):
        await asyncio.sleep(STATE["slow_seconds"])  # work done, answer arrives late
    return result


@app.post("/claims/{app_no}/documents")
async def upload_document(app_no: str, req: DocumentUpload):
    if STATE["mode"] == "down":
        return await apply_mode()
    if req.idempotency_key and (saved := db.get_idempotent(req.idempotency_key)):
        return {**saved, "replayed": True}
    claim, err = check_write_preconditions(app_no, req)
    if err:
        return err
    if req.document_name not in claim["missing_documents"]:
        return error(422, "document_not_requested",
                     f"'{req.document_name}' is not in the missing documents list.",
                     missing_documents=claim["missing_documents"])

    if STATE["mode"] != "drop_writes":
        missing = [d for d in claim["missing_documents"] if d != req.document_name]
        submitted = claim["submitted_documents"] + [
            {"document_name": req.document_name, "file_ref": req.file_ref}]
        fields = {"missing_documents": missing, "submitted_documents": submitted}
        if not missing and claim["claim_status"] == "documents_pending":
            fields["claim_status"] = "under_review"  # all papers in -> back to review
        db.update_claim(app_no, **fields)
    after = db.get_claim(app_no)
    result = {"ok": True, "app_no": app_no, "action": "document_upload",
              "document_name": req.document_name, "record_version": after["record_version"]}
    if req.idempotency_key:
        db.save_idempotent(req.idempotency_key, result)
    if STATE["mode"] in ("slow", "slow_writes"):
        await asyncio.sleep(STATE["slow_seconds"])
    return result


# ---------- simulation + admin (for demos and tests) ----------

@app.post("/simulate/credit/{app_no}")
async def simulate_credit(app_no: str):
    """Pretend the bank credited the money. Only an approved claim can be paid."""
    if (resp := await apply_mode()) is not None:
        return resp
    claim = db.get_claim(app_no)
    if claim is None:
        return error(404, "not_found", f"No application found with number {app_no}.")
    if claim["claim_status"] != "approved":
        return error(409, "not_approved", "Only an approved claim can be credited.")
    db.update_claim(app_no, payment_status="credited")
    return public_view(db.get_claim(app_no))


@app.get("/admin/mode")
async def get_mode():
    return STATE


@app.post("/admin/mode")
async def set_mode(req: ModeChange):
    if req.mode not in MODES:
        return error(422, "invalid_mode", f"Mode must be one of {MODES}.")
    STATE["mode"] = req.mode
    if req.slow_seconds is not None:
        STATE["slow_seconds"] = req.slow_seconds
    return STATE


@app.post("/admin/reset")
async def reset():
    """Re-seed the database and go back to normal mode."""
    db.init_db()
    STATE["mode"] = "normal"
    return {"ok": True, "mode": "normal"}
