"""The Orchestrator agent: coordinates the specialist agents over the message bus.

Pipeline per farmer message (a state machine per session):
  COLLECT -> FETCH -> DECIDE -> (PROPOSE -> AWAIT_APPROVAL -> EXECUTE -> VERIFY) -> RESPOND

  COLLECT  intake agent understands the text; orchestrator remembers app no. / season
  FETCH    investigator agent reads the portal and applies the rules
  DECIDE   orchestrator picks the next step from the findings (plain code, auditable)
  PROPOSE  action agent drafts a change; nothing changes yet
  AWAIT_APPROVAL   the farmer says yes/no (backend-enforced)
  EXECUTE  action agent performs the change exactly once (idempotent)
  VERIFY   verifier agent re-reads the portal independently (maker-checker)
  RESPOND  responder agent writes the reply; auditor agent logs every step

The orchestrator owns the per-session memory but never touches the portal itself.
"""
import threading
import uuid

from agent.agents import (ActionAgent, AuditorAgent, HelpdeskAgent, IntakeAgent,
                          InvestigatorAgent, ResponderAgent, VerifierAgent)
from agent.approvals import ApprovalError
from agent.bus import MessageBus
from agent.evidence import EvidenceLog


class UnknownSession(Exception):
    """The session id does not exist (expired server restart or a typo)."""


CLAIM_INTENTS = {"check_status", "missing_docs", "correct_season", "upload_doc"}
ME = "orchestrator"


class Agent:
    """The Orchestrator. (Kept the name `Agent`: it is the system's single entry point.)"""
    name, role = ME, "Coordinates the specialist agents and keeps each farmer's session memory"

    def __init__(self, client, evidence=None, store=None):
        self.client = client
        self.evidence = evidence or EvidenceLog()
        self.bus = MessageBus()
        IntakeAgent(self.bus)
        InvestigatorAgent(self.bus, client)
        self.action = ActionAgent(self.bus, client, store)
        VerifierAgent(self.bus, client)
        HelpdeskAgent(self.bus)
        ResponderAgent(self.bus)
        AuditorAgent(self.bus, self.evidence)
        self.store, self.runner = self.action.store, self.action.runner
        self.sessions = {}
        self._lock = threading.Lock()

    # ---------- talking to other agents ----------

    def ask(self, agent, type, sid, **payload):
        return self.bus.request(ME, agent, type, sid, **payload)

    def audit(self, sid, step, **data):
        self.ask("auditor", "record", sid, step=step, data=data)

    def say(self, s, key, **kw):
        return self.ask("responder", "compose", s["id"], key=key, lang=s["lang"], **kw)["text"]

    # ---------- sessions (isolated from each other) ----------

    def new_session(self, lang="en"):
        sid = f"s-{uuid.uuid4().hex[:8]}"
        with self._lock:
            self.sessions[sid] = {"id": sid, "lang": lang, "state": "COLLECT", "app_no": None,
                                  "stated_season": None, "pending_intent": None,
                                  "proposal_id": None, "last_reply": None}
        return sid

    def _session(self, sid, lang=None):
        if sid not in self.sessions:
            raise UnknownSession(sid)
        s = self.sessions[sid]
        if lang in ("en", "hi"):
            s["lang"] = lang
        return s

    # ---------- entry points ----------

    def handle(self, sid, text, lang=None):
        """Process one farmer utterance (voice transcript or typed text)."""
        s = self._session(sid, lang)
        trace = ["COLLECT"]
        self.audit(sid, "input", text=text, lang=s["lang"])
        nlu = self.ask("intake", "understand", sid, text=text)
        self.audit(sid, "nlu", intent=nlu["intent"], confidence=nlu["confidence"],
                   entities=nlu["entities"], needs_clarification=nlu["needs_clarification"])

        ents = nlu["entities"]
        if ents.get("app_no"):
            if ents["app_no"] != s["app_no"]:
                self.audit(sid, "validate", app_no=ents["app_no"], valid=nlu["app_no_valid"])
            s["app_no"] = ents["app_no"]
        if ents.get("season"):
            s["stated_season"] = ents["season"]

        intent = nlu["intent"]
        # The farmer is answering our question (number or season) -> continue that task.
        if s["state"] == "COLLECT" and s["pending_intent"] and (ents.get("app_no") or ents.get("season")) \
                and intent not in ("approve", "reject", "repeat"):
            intent = s["pending_intent"]
        elif nlu["needs_clarification"]:
            if s["state"] == "AWAIT_APPROVAL":
                return self._reminder(s, trace, nlu)
            return self._reply(s, self.say(s, "clarify"), trace, nlu)

        if intent == "repeat":
            return self._reply(s, s["last_reply"] or self.say(s, "nothing_to_repeat"), trace, nlu, remember=False)
        if intent in ("approve", "reject"):
            if s["state"] == "AWAIT_APPROVAL":
                trace = ["AWAIT_APPROVAL"]
            return self._decide(s, intent == "approve", trace, nlu)
        if intent == "greet":
            return self._reply(s, self.say(s, "greet"), trace, nlu)
        if intent == "apply_insurance":
            return self._reply(s, self.say(s, "apply_info"), trace, nlu)
        if intent == "book_help":
            ticket = self.ask("helpdesk", "book", sid, app_no=s["app_no"])
            self.audit(sid, "tool", tool="book_help", result=ticket)
            return self._reply(s, self.say(s, "help_booked", ticket=ticket["ticket_id"], slot=ticket["slot"]),
                               trace, nlu, ticket=ticket)
        return self._claim_flow(s, intent, trace, nlu)

    def decide(self, sid, proposal_id, approve):
        """Approve/Reject button in the UI. Must match this session's open proposal."""
        s = self._session(sid)
        p = self.ask("action", "lookup", sid, proposal_id=proposal_id)["proposal"]   # other session -> ApprovalError
        if proposal_id != s["proposal_id"] and p["status"] in ("EXECUTED", "REJECTED", "CANCELLED"):
            # duplicate click after it finished: return the FIRST result, do nothing new
            self.audit(sid, "duplicate_request", proposal_id=proposal_id, status=p["status"])
            return self._reply(s, s["last_reply"], ["RESPOND"], None, remember=False,
                               proposal=_public(p), verification=p["verification"], replayed=True)
        if proposal_id != s["proposal_id"]:
            raise ApprovalError("this proposal is no longer the active one")
        self.audit(sid, "input", button="approve" if approve else "reject", proposal_id=proposal_id)
        return self._decide(s, approve, ["AWAIT_APPROVAL"], None)

    # ---------- FETCH + DECIDE ----------

    def _claim_flow(self, s, intent, trace, nlu):
        sid = s["id"]
        if not s["app_no"]:
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, self.say(s, "ask_app_no"), trace, nlu)
        if intent == "correct_season" and not s["stated_season"]:
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, self.say(s, "ask_season"), trace, nlu)
        s["pending_intent"] = None

        trace.append("FETCH")
        f = self.ask("investigator", "investigate", sid, app_no=s["app_no"], stated_season=s["stated_season"])
        self.audit(sid, "fetch", tool="fetch_claim", app_no=s["app_no"], source=f["source"], result=f["fetch"],
                   status_code=f["status_code"], record_version=f["record_version"], fetched_at=f["fetched_at"])
        if f["fetch"] == "NOT_FOUND":
            app, s["app_no"] = s["app_no"], None
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, self.say(s, "not_found", app=app), trace, nlu)
        if f["fetch"] != "FOUND":   # down / timeout / error: NOT the same as "not found"
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, self.say(s, "portal_down", app=s["app_no"]), trace, nlu)

        claim, a, mismatch = f["claim"], f["assessment"], f["season_mismatch"]
        trace.append("DECIDE")
        self.audit(sid, "decision", verdict=a["verdict"], payment=a["payment"], is_paid=a["is_paid"],
                   missing_documents=a["missing_documents"], season_record=claim.get("season"),
                   season_stated=s["stated_season"], season_mismatch=mismatch, reason=a["reason"])
        extra = {"claim": claim, "assessment": a}
        if a["verdict"] == "UNCERTAIN":
            return self._reply(s, self.say(s, "uncertain", app=claim["app_no"]), trace, nlu, **extra)

        if intent == "correct_season":
            if not mismatch:
                return self._reply(s, self.say(s, "season_already_correct", app=claim["app_no"],
                                               season=claim["season"]), trace, nlu, **extra)
            return self._propose(s, "season_change", claim, s["stated_season"], trace, nlu, extra)
        if intent == "upload_doc":
            if not a["missing_documents"]:
                return self._reply(s, self.say(s, "nothing_to_upload", app=claim["app_no"]), trace, nlu, **extra)
            return self._propose(s, "document_upload", claim, a["missing_documents"][0], trace, nlu, extra)

        # check_status / missing_docs: report, then offer the obvious next step
        text = self.say(s, "status", claim=claim, assessment=a)
        if mismatch:
            return self._propose(s, "season_change", claim, s["stated_season"], trace, nlu, extra, prefix=text)
        if a["missing_documents"]:
            prefix = "" if intent == "missing_docs" else text   # proposal already names the doc
            return self._propose(s, "document_upload", claim, a["missing_documents"][0], trace, nlu, extra, prefix)
        return self._reply(s, text, trace, nlu, **extra)

    # ---------- PROPOSE ----------

    def _propose(self, s, action_type, claim, value, trace, nlu, extra, prefix=""):
        out = self.ask("action", "propose", s["id"], action_type=action_type, claim=claim,
                       value=value, replaces=s["proposal_id"])
        if out.get("error"):
            return self._reply(s, self.say(s, "clarify"), trace, nlu, **extra)
        p = out["proposal"]
        change = p["change"]
        if action_type == "season_change":
            text = self.say(s, "propose_season", app=claim["app_no"], old=change["from"], new=change["to"])
        else:
            text = self.say(s, "propose_upload", app=claim["app_no"], doc=value, file=change["file_ref"])
        s.update(proposal_id=p["id"], state="AWAIT_APPROVAL")
        trace += ["PROPOSE", "AWAIT_APPROVAL"]
        self.audit(s["id"], "proposal", proposal_id=p["id"], change=change,
                   base_version=p["base_version"], idempotency_key=p["idempotency_key"])
        return self._reply(s, (prefix + " " + text).strip(), trace, nlu, proposal=_public(p), **extra)

    # ---------- AWAIT_APPROVAL -> EXECUTE -> VERIFY ----------

    def _decide(self, s, approve, trace, nlu):
        sid = s["id"]
        p = self.ask("action", "lookup", sid, proposal_id=s["proposal_id"])["proposal"] if s["proposal_id"] else None
        if not p or p["status"] not in ("PENDING", "APPROVED", "PENDING_CONFIRMATION", "EXECUTED"):
            return self._reply(s, self.say(s, "nothing_pending"), trace, nlu)

        if not approve:
            if p["status"] == "PENDING_CONFIRMATION":   # may already be applied: cannot cancel
                return self._reply(s, self.say(s, "action_timeout"), trace, nlu, proposal=_public(p))
            if p["status"] == "PENDING":
                self.ask("action", "decide", sid, proposal_id=p["id"], approve=False)
            else:
                self.ask("action", "cancel", sid, proposal_id=p["id"])
            self.audit(sid, "approval", proposal_id=p["id"], decision="REJECTED")
            s.update(state="RESPOND", proposal_id=None)
            return self._reply(s, self.say(s, "rejected"), trace + ["RESPOND"], nlu, proposal=_public(p))

        if p["status"] == "PENDING":
            p = self.ask("action", "decide", sid, proposal_id=p["id"], approve=True)["proposal"]
            self.audit(sid, "approval", proposal_id=p["id"], decision=p["status"])
            if p["status"] != "APPROVED":           # e.g. expired by time
                s.update(state="RESPOND", proposal_id=None)
                return self._reply(s, self.say(s, "expired"), trace, nlu, proposal=_public(p))

        trace.append("EXECUTE")
        p = self.ask("action", "execute", sid, proposal_id=p["id"])["proposal"]
        self.audit(sid, "execution", proposal_id=p["id"], status=p["status"], execution=p["execution"])
        key = {"PENDING_CONFIRMATION": "action_timeout", "APPROVED": "action_portal_down",
               "EXPIRED": "expired", "FAILED": "action_failed"}.get(p["status"])
        if key:
            if p["status"] in ("EXPIRED", "FAILED"):
                s.update(state="RESPOND", proposal_id=None)
            return self._reply(s, self.say(s, key), trace, nlu, proposal=_public(p))

        trace.append("VERIFY")
        v = p["verification"]
        if (v or {}).get("status") != "VERIFIED":        # first time, or an earlier check was not conclusive
            v = self.ask("verifier", "verify", sid, proposal=p)
            p = self.ask("action", "attach_verification", sid, proposal_id=p["id"], verification=v)["proposal"]
        self.audit(sid, "verification", **v)
        s.update(state="RESPOND", proposal_id=None if v["status"] == "VERIFIED" else p["id"])
        if v["status"] == "VERIFIED":
            text = self.say(s, "verified", change=p["change"], verification=v)
        else:
            text = self.say(s, {"FAILED": "verify_failed", "PENDING": "verify_pending"}.get(v["status"], "verify_uncertain"))
        return self._reply(s, text, trace, nlu, proposal=_public(p), verification=v)

    # ---------- RESPOND ----------

    def _reminder(self, s, trace, nlu):
        p = self.ask("action", "lookup", s["id"], proposal_id=s["proposal_id"])["proposal"]
        return self._reply(s, self.say(s, "pending_reminder", change=p["change"]), trace, nlu, proposal=_public(p))

    def _reply(self, s, text, trace, nlu, remember=True, **extra):
        if trace[-1] != "RESPOND":
            trace.append("RESPOND")
        if remember:
            s["last_reply"] = text
        self.audit(s["id"], "reply", text=text, lang=s["lang"], state=s["state"], trace=trace)
        return {"session_id": s["id"], "reply": text, "lang": s["lang"], "state": s["state"],
                "trace": trace, "intent": nlu["intent"] if nlu else None,
                "confidence": nlu["confidence"] if nlu else None,
                "entities": nlu["entities"] if nlu else {}, **extra}


Orchestrator = Agent


def _public(p):
    """Proposal fields safe to show in the UI."""
    return {k: p[k] for k in ("id", "change", "status", "base_version", "execution", "verification")}
