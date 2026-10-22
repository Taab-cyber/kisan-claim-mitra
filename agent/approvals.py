"""Backend-enforced human approval + idempotent execution.

Rules enforced HERE (not in the browser):
  - nothing is changed unless the farmer approved that exact proposal
  - only the session that owns a proposal can approve/reject/execute it
  - reject = no change, ever
  - a proposal EXPIRES if the portal record_version changed since it was made
  - each proposal has a unique action id + idempotency key: a retry or a
    double-click returns the FIRST result instead of acting twice
  - after a timeout we re-read the portal BEFORE any retry
"""
import threading
import time
import uuid

from agent import rules, tools

PROPOSAL_TTL_SECONDS = 15 * 60


class ApprovalError(Exception):
    """Raised when someone tries to skip or break the approval rules."""


class ApprovalStore:
    def __init__(self):
        self.proposals = {}
        self._lock = threading.Lock()

    def create(self, session_id, change, base_version):
        pid = f"act-{uuid.uuid4().hex[:10]}"
        proposal = {
            "id": pid, "session_id": session_id, "change": change,
            "base_version": base_version, "status": "PENDING",
            "idempotency_key": f"{pid}-key",
            "created_at": time.time(), "execution": None, "verification": None,
        }
        with self._lock:
            self.proposals[pid] = proposal
        return proposal

    def get(self, pid, session_id):
        p = self.proposals.get(pid)
        if p is None or p["session_id"] != session_id:   # sessions are isolated
            raise ApprovalError("proposal not found for this session")
        return p

    def decide(self, pid, session_id, approve):
        """Record the farmer's decision. Only a PENDING, unexpired proposal can be decided."""
        with self._lock:
            p = self.get(pid, session_id)
            if p["status"] != "PENDING":
                return p   # double click on approve/reject: no second effect
            if time.time() - p["created_at"] > PROPOSAL_TTL_SECONDS:
                p["status"] = "EXPIRED"
                return p
            p["status"] = "APPROVED" if approve else "REJECTED"
            p["decided_at"] = time.time()
            return p


class ActionRunner:
    """Executes APPROVED proposals exactly once. It does NOT verify its own work:
    the separate Verifier agent does that (maker-checker)."""

    def __init__(self, client, store):
        self.client, self.store = client, store
        self._locks = {}

    def _lock_for(self, pid):
        return self._locks.setdefault(pid, threading.Lock())

    def run(self, pid, session_id):
        """Returns the proposal with 'execution' filled in."""
        p = self.store.get(pid, session_id)
        with self._lock_for(pid):
            if p["status"] not in ("APPROVED", "EXECUTED", "PENDING_CONFIRMATION"):
                raise ApprovalError(f"cannot execute a proposal in state {p['status']}")
            if p["status"] == "EXECUTED":                    # retry / double click: never re-send
                p["execution"] = {**p["execution"], "replayed": True}
                return p
            self._execute_once(p)
            return p

    def _execute_once(self, p):
        change = p["change"]
        before = tools.fetch_claim(self.client, change["app_no"])

        # 1) If an earlier attempt timed out, CHECK THE PORTAL before any retry.
        if p["status"] == "PENDING_CONFIRMATION" and before["ok"] and \
                rules.intended_state_reached(before["data"], change):
            p["status"] = "EXECUTED"
            p["execution"] = {"kind": "ok", "note": "found already applied after earlier timeout",
                              "attempts": p["execution"]["attempts"]}
            return

        # 2) Stale proposal: the record changed after we proposed -> expire, change nothing.
        if before["ok"] and before["data"]["record_version"] != p["base_version"]:
            p["status"] = "EXPIRED"
            p["execution"] = {"kind": "stale", "attempts": 0,
                              "note": f"record_version {p['base_version']} -> "
                                      f"{before['data']['record_version']}"}
            return
        if not before["ok"]:
            p["execution"] = {"kind": before["kind"], "attempts": 0,
                              "note": "could not read portal before acting; nothing sent"}
            return  # stays APPROVED/PENDING_CONFIRMATION so it can be retried later

        attempts = (p["execution"] or {}).get("attempts", 0)
        result = tools.execute_action(self.client, p)
        attempts += 1
        if result["kind"] == "timeout":
            # Do not blindly retry: read the portal first.
            check = tools.fetch_claim(self.client, change["app_no"])
            if check["ok"] and rules.intended_state_reached(check["data"], change):
                result = {"kind": "ok", "note": "timed out, but portal shows change applied"}
            elif check["ok"]:
                # Not applied: ONE retry with the SAME idempotency key (portal dedups it).
                result = tools.execute_action(self.client, p)
                attempts += 1

        p["execution"] = {"kind": result["kind"], "attempts": attempts,
                          "status_code": result.get("status_code"),
                          "response": result.get("data"), "note": result.get("note")}
        if result["kind"] == "ok":
            p["status"] = "EXECUTED"
        elif result["kind"] == "timeout":
            p["status"] = "PENDING_CONFIRMATION"   # unknown outcome; will check portal first
        elif result["kind"] == "conflict":
            p["status"] = "EXPIRED"
        elif result["kind"] in ("invalid", "not_found", "invalid_input"):
            p["status"] = "FAILED"
        # portal_down: nothing changed, stays APPROVED so the farmer can retry
