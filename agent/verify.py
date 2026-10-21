"""Independent verification after every action.

We NEVER trust the write response ("ok") as proof. We re-read the portal and
compare what it shows now with the state we intended:
  VERIFIED   - fresh record shows the intended change
  FAILED     - fresh record read fine but does NOT show the change
  PENDING    - could not read the portal right now (down / timeout); check later
  UNCERTAIN  - record read but the relevant data is missing/odd, or record vanished
"""
from agent import rules, tools


def verify(client, proposal):
    change = proposal["change"]
    fresh = tools.reverify(client, change["app_no"])
    kind = rules.classify_fetch(fresh)
    result = {"proposal_id": proposal["id"], "source": fresh["url"], "fetch": kind,
              "expected": _expected(change)}

    if kind in ("PORTAL_DOWN", "TIMEOUT"):
        return {**result, "status": "PENDING", "reason": f"verification read failed: {kind}"}
    if kind != "FOUND":
        return {**result, "status": "UNCERTAIN", "reason": f"record could not be read: {kind}"}

    claim = fresh["data"]
    result.update(observed=_observed(claim, change), record_version=claim.get("record_version"),
                  fetched_at=claim.get("fetched_at"))
    field = "season" if change["action_type"] == "season_change" else "missing_documents"
    if claim.get(field) is None:
        return {**result, "status": "UNCERTAIN", "reason": f"portal record has no '{field}'"}
    if rules.intended_state_reached(claim, change):
        return {**result, "status": "VERIFIED", "reason": "fresh portal read shows the intended change"}
    return {**result, "status": "FAILED", "reason": "fresh portal read does NOT show the intended change"}


def _expected(change):
    if change["action_type"] == "season_change":
        return {"season": change["to"]}
    return {"document_name": change["document_name"], "in_missing_documents": False}


def _observed(claim, change):
    if change["action_type"] == "season_change":
        return {"season": claim.get("season")}
    return {"missing_documents": claim.get("missing_documents"),
            "submitted_documents": [d.get("document_name") for d in claim.get("submitted_documents") or []]}
