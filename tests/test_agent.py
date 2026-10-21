"""Agent safety properties: approval enforcement, isolation, idempotency, timeouts, evidence."""
import threading

import httpx
import pytest

from agent import tools
from agent.approvals import ApprovalError
from agent.evidence import EvidenceLog
from agent.planner import Agent
from agent.tools import PortalClient

SEASON_FIX = "KRB-2026-00633 season galat hai rabi 2026-27 karo"


class ScriptedHttp:
    """Wraps the test portal and injects timeouts on chosen calls.
    script: list of (method, how) consumed in order; how = 'lost' (send, then
    lose the response) or 'drop' (time out before reaching the portal)."""

    def __init__(self, http, script):
        self.http, self.script, self.posts = http, list(script), 0

    def request(self, method, path, **kw):
        if method == "POST":
            self.posts += 1
        if self.script and self.script[0][0] == method:
            _, how = self.script.pop(0)
            if how == "lost":
                self.http.request(method, path, **kw)
            raise httpx.ReadTimeout("injected")
        return self.http.request(method, path, **kw)

    def post(self, *a, **kw):
        return self.http.post(*a, **kw)


@pytest.fixture
def agent(portal):
    return Agent(PortalClient(portal, timeout=1))


def test_cannot_execute_without_approval(agent):
    sid = agent.new_session()
    pid = agent.handle(sid, SEASON_FIX)["proposal"]["id"]
    with pytest.raises(ApprovalError):
        agent.runner.run(pid, sid)      # backend refuses: still PENDING


def test_sessions_are_isolated(agent, portal):
    a, b = agent.new_session(), agent.new_session()
    pid = agent.handle(a, SEASON_FIX)["proposal"]["id"]
    with pytest.raises(ApprovalError):
        agent.decide(b, pid, True)
    assert agent.handle(b, "haan")["reply"].startswith("There is nothing")
    assert portal.get("/claims/KRB-2026-00633").json()["season"] == "Kharif 2026"


def test_timeout_not_applied_retries_once_with_same_key(portal):
    http = ScriptedHttp(portal, [("POST", "drop")])
    agent = Agent(PortalClient(http, timeout=1))
    sid = agent.new_session()
    agent.handle(sid, SEASON_FIX)
    r = agent.handle(sid, "haan")
    assert r["proposal"]["execution"]["attempts"] == 2
    assert r["verification"]["status"] == "VERIFIED"
    assert portal.get("/claims/KRB-2026-00633").json()["record_version"] == 2


def test_timeout_unknown_then_check_before_retry(portal):
    # write applied but answer lost, AND the check-read also times out -> unknown outcome
    http = ScriptedHttp(portal, [("POST", "lost"), ("GET", "drop")])
    agent = Agent(PortalClient(http, timeout=1))
    sid = agent.new_session()
    agent.handle(sid, SEASON_FIX)
    r1 = agent.handle(sid, "haan")
    assert r1["proposal"]["status"] == "PENDING_CONFIRMATION"
    assert agent.handle(sid, "nahi")["proposal"]["status"] == "PENDING_CONFIRMATION"  # cannot cancel
    r2 = agent.handle(sid, "haan")                        # portal is checked first...
    assert r2["verification"]["status"] == "VERIFIED"
    assert http.posts == 1                                # ...so nothing is sent twice
    assert portal.get("/claims/KRB-2026-00633").json()["record_version"] == 2


def test_concurrent_double_click_executes_once(agent, portal):
    sid = agent.new_session()
    pid = agent.handle(sid, SEASON_FIX)["proposal"]["id"]
    agent.store.decide(pid, sid, approve=True)
    threads = [threading.Thread(target=agent.runner.run, args=(pid, sid)) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert portal.get("/claims/KRB-2026-00633").json()["record_version"] == 2


def test_low_confidence_asks_and_does_not_fetch(agent):
    r = agent.handle(agent.new_session(), "what is the weather today")
    assert "did not understand" in r["reply"] and "FETCH" not in r["trace"]


def test_every_execution_has_separate_verification(agent):
    sid = agent.new_session()
    agent.handle(sid, "KRB-2026-00521 kaunsa document missing hai")
    agent.handle(sid, "haan")
    steps = [e["step"] for e in agent.evidence.for_session(sid)]
    assert steps.index("execution") < steps.index("verification")
    v = [e for e in agent.evidence.for_session(sid) if e["step"] == "verification"][0]["data"]
    assert v["status"] == "VERIFIED" and v["source"].endswith("KRB-2026-00521")


def test_evidence_never_stores_secrets():
    log = EvidenceLog()
    e = log.log("s1", "test", verbx_api_key="sk-123", nested={"otp": "4321", "ok": 1})
    assert e["data"]["verbx_api_key"] == "[redacted]" and e["data"]["nested"]["otp"] == "[redacted]"


def test_repeat_returns_last_reply(agent):
    sid = agent.new_session()
    first = agent.handle(sid, "status KRB-2026-00417")["reply"]
    assert agent.handle(sid, "phir se bolo")["reply"] == first


def test_upload_only_documents_portal_asked_for(portal):
    claim = portal.get("/claims/KRB-2026-00521").json()
    change, err = tools.propose_document_upload(claim, "Aadhaar Card")
    assert change is None and err == "document_not_requested"


def test_book_help(agent):
    r = agent.handle(agent.new_session(), "mujhe madad chahiye")
    assert r["ticket"]["ticket_id"].startswith("HELP-")
