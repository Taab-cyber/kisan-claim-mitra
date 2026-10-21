"""Tools the agent may call. Every tool validates its inputs and returns a plain dict.

Tools: fetch_claim, propose_season_correction, propose_document_upload,
execute_action, reverify, book_help.

Every portal call returns a "kind" so that a FAILED fetch (portal_down, timeout)
is never confused with a record that does NOT exist (not_found).
"""
import itertools
import os
import re
import time

import httpx

from agent import rules

DEFAULT_TIMEOUT = float(os.getenv("PORTAL_TIMEOUT_SECONDS", "2"))


class PortalClient:
    """Thin wrapper around an httpx-style client pointed at the mock portal.

    `http` can be a real httpx.Client (production) or FastAPI's TestClient (tests).
    A response that arrives AFTER the timeout is treated as a timeout and ignored,
    exactly like a real network client would do.
    """

    def __init__(self, http=None, base_url="", timeout=DEFAULT_TIMEOUT):
        self.http = http or httpx.Client(base_url=base_url)
        self.base_url = base_url
        self.timeout = timeout

    def _call(self, method, path, body=None):
        url = f"{self.base_url}{path}"
        started = time.monotonic()
        try:
            resp = self.http.request(method, path, json=body, timeout=self.timeout)
        except httpx.TimeoutException:
            return {"ok": False, "kind": "timeout", "url": url, "status_code": None, "data": None}
        except httpx.HTTPError as exc:
            return {"ok": False, "kind": "portal_down", "url": url, "status_code": None,
                    "data": {"message": type(exc).__name__}}
        if time.monotonic() - started > self.timeout:
            return {"ok": False, "kind": "timeout", "url": url, "status_code": None, "data": None}

        try:
            data = resp.json()
        except ValueError:
            data = None
        kind = {200: "ok", 404: "not_found", 409: "conflict", 422: "invalid",
                503: "portal_down"}.get(resp.status_code, "error")
        return {"ok": kind == "ok", "kind": kind, "url": url,
                "status_code": resp.status_code, "data": data}

    def get_claim(self, app_no):
        return self._call("GET", f"/claims/{app_no}")

    def post_season(self, app_no, body):
        return self._call("POST", f"/claims/{app_no}/season", body)

    def post_document(self, app_no, body):
        return self._call("POST", f"/claims/{app_no}/documents", body)


# ---------- read tools ----------

def fetch_claim(client, app_no):
    """Read a claim. Refuses badly formatted numbers before touching the portal."""
    if not rules.valid_app_no(app_no):
        return {"ok": False, "kind": "invalid_input", "url": None, "status_code": None,
                "data": {"message": "Application number must look like KRB-2026-00417."}}
    return client.get_claim(app_no)


def reverify(client, app_no):
    """An independent fresh read used ONLY for verification (never reuses old data)."""
    return fetch_claim(client, app_no)


# ---------- proposal tools (they never change anything) ----------

def propose_season_correction(claim, new_season):
    """Build a change proposal. Returns (change, error_message)."""
    if not rules.valid_season(new_season):
        return None, "invalid_season"
    if not rules.season_mismatch(claim.get("season"), new_season):
        return None, "season_already_correct"
    return {"action_type": "season_change", "app_no": claim["app_no"],
            "field": "season", "from": claim["season"], "to": new_season}, None


def sample_file_ref(document_name):
    """A SYNTHETIC sample file reference, e.g. samples/land_record_khatauni_synthetic.pdf"""
    slug = re.sub(r"[^a-z0-9]+", "_", document_name.lower()).strip("_")
    return f"samples/{slug}_synthetic.pdf"


def propose_document_upload(claim, document_name, file_ref=None):
    """Only a document the PORTAL lists as missing can be proposed (exact match)."""
    if document_name not in rules.missing_documents(claim):
        return None, "document_not_requested"
    return {"action_type": "document_upload", "app_no": claim["app_no"],
            "field": "missing_documents", "document_name": document_name,
            "file_ref": file_ref or sample_file_ref(document_name)}, None


# ---------- write tool ----------

def execute_action(client, proposal):
    """Send ONE approved change to the portal. Approval/idempotency checks live in
    approvals.ActionRunner; this function only performs the HTTP write."""
    change = proposal["change"]
    common = {"expected_version": proposal["base_version"],
              "idempotency_key": proposal["idempotency_key"]}
    if change["action_type"] == "season_change":
        return client.post_season(change["app_no"], {"season": change["to"], **common})
    if change["action_type"] == "document_upload":
        return client.post_document(change["app_no"], {
            "document_name": change["document_name"], "file_ref": change["file_ref"], **common})
    return {"ok": False, "kind": "invalid_input", "url": None, "status_code": None,
            "data": {"message": "unknown action"}}


# ---------- help booking (local, synthetic) ----------

_ticket_counter = itertools.count(1001)


def book_help(session_id, app_no=None):
    """Book a (synthetic) call-back from a help-desk officer."""
    return {"ok": True, "ticket_id": f"HELP-{next(_ticket_counter)}", "app_no": app_no,
            "slot": "tomorrow 10:00-12:00", "session_id": session_id}
