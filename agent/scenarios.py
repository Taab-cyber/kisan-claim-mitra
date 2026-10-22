"""Official test cases (TC1-TC4) and failure scenarios, written ONCE and used by:
  - run_tests.py (writes TEST_EVIDENCE.md)
  - pytest (tests/test_scenarios.py)
  - the judge console's test runner in the web app

Each scenario resets the portal, talks to a fresh agent like a farmer would,
and checks the result against the portal itself (never against the agent's word).
"""
from agent.planner import Agent
from agent.tools import PortalClient

SCENARIOS = []


def scenario(sid, title, expected, official=False):
    def wrap(fn):
        SCENARIOS.append({"id": sid, "title": title, "expected": expected,
                          "official": official, "fn": fn})
        return fn
    return wrap


class Ctx:
    """A tiny farmer simulator: one agent, one session, and direct portal access."""

    def __init__(self, http, lang="en", timeout=0.5):
        self.http = http
        self.http.post("/admin/reset")                      # known starting state
        self.agent = Agent(PortalClient(http, timeout=timeout))
        self.sid = self.agent.new_session(lang)
        self.inputs, self.replies, self.checks = [], [], []

    def say(self, text):
        self.inputs.append(text)
        r = self.agent.handle(self.sid, text)
        self.replies.append(r["reply"])
        return r

    def click(self, proposal_id, approve=True):
        self.inputs.append(f"[button: {'Approve' if approve else 'Reject'} {proposal_id}]")
        r = self.agent.decide(self.sid, proposal_id, approve)
        self.replies.append(r["reply"])
        return r

    def mode(self, mode, slow_seconds=None):
        self.http.post("/admin/mode", json={"mode": mode, "slow_seconds": slow_seconds})

    def portal(self, app_no):
        """Ground truth: read the portal directly (bypasses the agent)."""
        return self.http.get(f"/claims/{app_no}").json()

    def check(self, label, ok):
        self.checks.append({"label": label, "ok": bool(ok)})


# ---------------- official cases ----------------

@scenario("TC1", "Valid application under review (English)", official=True,
          expected="Agent asks for the application number, then reports: claim Under review, "
                   "Kharif 2026, Paddy, money not credited, no missing document, with source and fetched time.")
def tc1(c):
    r1 = c.say("what is my claim status")
    r2 = c.say("KRB-2026-00417")
    c.check("asks for the application number first", r1["state"] == "COLLECT" and "application number" in r1["reply"])
    c.check("claim status is under_review (from portal)", r2.get("claim", {}).get("claim_status") == "under_review")
    c.check("reply says Under review, Paddy, Kharif 2026",
            all(w in r2["reply"] for w in ("Under review", "Paddy", "Kharif 2026")))
    c.check("reply shows source and fetched time", "/claims/KRB-2026-00417" in r2["reply"] and "IST" in r2["reply"])
    c.check("no change proposed", r2.get("proposal") is None)


@scenario("TC2", "Missing document named exactly; upload with approval (Hindi)", official=True,
          expected="Agent names the missing document exactly as 'Land Record (Khatauni)', proposes an upload, "
                   "uploads only after approval, then re-reads the portal and reports VERIFIED.")
def tc2(c):
    c.agent.sessions[c.sid]["lang"] = "hi"
    r1 = c.say("आवेदन KRB-2026-00521 में कौन सा कागज़ बाकी है")
    c.check("exact document name in reply", "Land Record (Khatauni)" in r1["reply"])
    c.check("proposal waits for approval", r1["state"] == "AWAIT_APPROVAL" and r1.get("proposal"))
    c.check("portal unchanged before approval",
            c.portal("KRB-2026-00521")["missing_documents"] == ["Land Record (Khatauni)"])
    r2 = c.say("हाँ")
    c.check("verification is VERIFIED", (r2.get("verification") or {}).get("status") == "VERIFIED")
    c.check("portal now has no missing document", c.portal("KRB-2026-00521")["missing_documents"] == [])


@scenario("TC3", "Season mismatch: farmer says Rabi 2026-27, record says Kharif 2026 (Hinglish)", official=True,
          expected="Agent detects the mismatch, proposes Kharif 2026 -> Rabi 2026-27, changes it only after "
                   "approval, and verifies the portal now shows Rabi 2026-27.")
def tc3(c):
    c.agent.sessions[c.sid]["lang"] = "hi"
    r1 = c.say("mera rabi 2026-27 ka claim KRB-2026-00633 ka status batao")
    p = r1.get("proposal") or {}
    c.check("mismatch detected and proposed", p.get("change", {}).get("to") == "Rabi 2026-27"
            and p.get("change", {}).get("from") == "Kharif 2026")
    c.check("portal unchanged before approval", c.portal("KRB-2026-00633")["season"] == "Kharif 2026")
    r2 = c.say("haan kar do")
    c.check("verification is VERIFIED", (r2.get("verification") or {}).get("status") == "VERIFIED")
    c.check("portal season is now Rabi 2026-27", c.portal("KRB-2026-00633")["season"] == "Rabi 2026-27")


@scenario("TC4", "Approved but NOT paid (English)", official=True,
          expected="Agent says the claim is Approved AND that money is NOT credited yet; it never says paid.")
def tc4(c):
    r = c.say("has my money come for KRB-2026-00748")
    a = r.get("assessment", {})
    c.check("approval and payment kept separate", a.get("claim_status") == "approved" and a.get("payment") == "NOT_PAID")
    c.check("reply says Approved and NOT credited", "Approved" in r["reply"] and "NOT been credited" in r["reply"])
    c.check("reply never claims money credited", "credited to your account" not in r["reply"])


# ---------------- failure cases ----------------

@scenario("F1", "Invalid application number", "Agent does not call the portal; asks for a valid number.")
def f1(c):
    r = c.say("status of KRB-26-17")
    c.check("asks for the number again", r["state"] == "COLLECT" and "FETCH" not in r["trace"])


@scenario("F2", "Not found vs portal down", "Unknown number -> 'not found'. Portal down -> 'portal not working', never 'not found'.")
def f2(c):
    r1 = c.say("status KRB-2026-99999")
    c.check("unknown number reported as not found", "could not find" in r1["reply"])
    c.mode("down")
    r2 = c.say("status KRB-2026-00417")
    c.check("portal down is NOT reported as not found",
            "not working" in r2["reply"] and "could not find" not in r2["reply"])


@scenario("F3", "Missing field on record -> UNCERTAIN", "Payment status is missing, so the agent says UNCERTAIN and does not guess.")
def f3(c):
    r = c.say("status KRB-2026-00850")
    c.check("verdict UNCERTAIN", r.get("assessment", {}).get("verdict") == "UNCERTAIN")
    c.check("does not claim paid or not paid", "credited" not in r["reply"])


@scenario("F4", "Rejected approval", "Farmer says no -> nothing changes on the portal.")
def f4(c):
    c.say("KRB-2026-00633 season galat hai rabi 2026-27 karo")
    r = c.say("nahi")
    claim = c.portal("KRB-2026-00633")
    c.check("proposal rejected", (r.get("proposal") or {}).get("status") == "REJECTED")
    c.check("portal unchanged", claim["season"] == "Kharif 2026" and claim["record_version"] == 1)


@scenario("F5", "Duplicate request (double click)", "Second Approve click returns the first result; change applied once.")
def f5(c):
    pid = c.say("KRB-2026-00633 season galat hai rabi 2026-27 karo")["proposal"]["id"]
    first = c.click(pid)
    second = c.click(pid)
    c.check("second click replayed", second.get("replayed") is True)
    c.check("same verification result", first["verification"]["status"] == second["verification"]["status"] == "VERIFIED")
    c.check("portal changed exactly once", c.portal("KRB-2026-00633")["record_version"] == 2)


@scenario("F6", "Action timeout", "Write times out; agent re-reads the portal BEFORE retrying, sees it applied, does not send again.")
def f6(c):
    c.say("KRB-2026-00633 season galat hai rabi 2026-27 karo")
    c.mode("slow_writes", slow_seconds=c.agent.client.timeout * 2)
    r = c.say("haan")
    ex = r["proposal"]["execution"]
    c.check("only one write attempt", ex["attempts"] == 1)
    c.check("timeout resolved by checking portal", "portal shows change applied" in (ex.get("note") or ""))
    c.check("verified", r["verification"]["status"] == "VERIFIED")
    c.check("portal changed exactly once", c.portal("KRB-2026-00633")["record_version"] == 2)


@scenario("F7", "Verification failure", "Portal says ok but does not save; agent's fresh re-read catches it -> FAILED.")
def f7(c):
    c.say("KRB-2026-00633 season galat hai rabi 2026-27 karo")
    c.mode("drop_writes")
    r = c.say("haan")
    c.check("verification FAILED", r["verification"]["status"] == "FAILED")
    c.check("reply does not claim success", "NOT there" in r["reply"])


@scenario("F8", "Approved but not paid, then credited", "Before credit: NOT_PAID. After /simulate/credit: PAID.")
def f8(c):
    r1 = c.say("status KRB-2026-00748")
    c.http.post("/simulate/credit/KRB-2026-00748")
    r2 = c.say("status KRB-2026-00748")
    c.check("before credit: not paid", r1["assessment"]["payment"] == "NOT_PAID")
    c.check("after credit: paid", r2["assessment"]["payment"] == "PAID" and "credited to your account" in r2["reply"])


@scenario("F9", "Stale proposal", "Record changes after the proposal -> proposal EXPIRES, agent changes nothing.")
def f9(c):
    c.say("KRB-2026-00633 season galat hai rabi 2026-27 karo")
    c.http.post("/claims/KRB-2026-00633/season", json={"season": "Zaid 2027"})  # someone else edits
    r = c.say("haan")
    c.check("proposal expired", r["proposal"]["status"] == "EXPIRED")
    c.check("portal keeps the other edit", c.portal("KRB-2026-00633")["season"] == "Zaid 2027")


# ---------------- runner ----------------

def _short_evidence(entries):
    """One readable line per evidence entry."""
    lines = []
    for e in entries:
        d = e["data"]
        if e["step"] == "reply":
            d = {"state": d.get("state"), "trace": " > ".join(d.get("trace", []))}
        parts = ", ".join(f"{k}={v}" for k, v in d.items() if v not in (None, "", [], {}))
        lines.append(f"{e['step']}: {parts}"[:400])
    return lines


def agent_conversation(messages):
    """One line per bus message: who asked whom for what (requests and replies)."""
    return [f"{m['from']} -> {m['to']}: {m['type']}  ({m['summary']})"[:300] for m in messages]


def run_scenario(sc, http, timeout=0.5):
    c = Ctx(http, timeout=timeout)
    error = None
    try:
        sc["fn"](c)
    except Exception as exc:          # a crash is a real FAIL, reported honestly
        error = f"{type(exc).__name__}: {exc}"
    finally:
        http.post("/admin/reset")
    passed = error is None and bool(c.checks) and all(ch["ok"] for ch in c.checks)
    return {"id": sc["id"], "title": sc["title"], "official": sc["official"],
            "expected": sc["expected"], "inputs": c.inputs, "actual": c.replies,
            "checks": c.checks, "error": error, "passed": passed,
            "evidence": _short_evidence(c.agent.evidence.for_session(c.sid)),
            "messages": agent_conversation(c.agent.bus.for_session(c.sid))}


def run_all(http, only=None, timeout=0.5):
    return [run_scenario(sc, http, timeout) for sc in SCENARIOS if not only or sc["id"] in only]
