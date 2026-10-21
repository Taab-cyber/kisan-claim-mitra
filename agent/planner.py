"""The agent's brain: a small, deterministic state machine per session.

COLLECT -> FETCH -> DECIDE -> (PROPOSE -> AWAIT_APPROVAL -> EXECUTE -> VERIFY) -> RESPOND

The trained NLU only picks WHAT the farmer wants (intent + entities).
Everything else - which tool runs, what is allowed, what we say - is plain code.
"""
import threading
import uuid

from agent import replies, rules, tools
from agent.approvals import ActionRunner, ApprovalError, ApprovalStore
from agent.evidence import EvidenceLog
from agent.nlu.predict import predict

CLAIM_INTENTS = {"check_status", "missing_docs", "correct_season", "upload_doc"}


class Agent:
    def __init__(self, client, evidence=None, store=None):
        self.client = client
        self.evidence = evidence or EvidenceLog()
        self.store = store or ApprovalStore()
        self.runner = ActionRunner(client, self.store)
        self.sessions = {}
        self._lock = threading.Lock()

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
            raise KeyError("unknown session")
        s = self.sessions[sid]
        if lang in ("en", "hi"):
            s["lang"] = lang
        return s

    # ---------- entry points ----------

    def handle(self, sid, text, lang=None):
        """Process one farmer utterance (voice transcript or typed text)."""
        s = self._session(sid, lang)
        trace = ["COLLECT"]
        self.evidence.log(sid, "input", text=text, lang=s["lang"])
        nlu = predict(text)
        self.evidence.log(sid, "nlu", intent=nlu["intent"], confidence=nlu["confidence"],
                          entities=nlu["entities"], needs_clarification=nlu["needs_clarification"])

        ents = nlu["entities"]
        if ents.get("app_no"):
            if ents["app_no"] != s["app_no"]:
                self.evidence.log(sid, "validate", app_no=ents["app_no"],
                                  valid=rules.valid_app_no(ents["app_no"]))
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
            return self._reply(s, replies.render("clarify", s["lang"]), trace, nlu)

        if intent == "repeat":
            text = s["last_reply"] or replies.render("nothing_to_repeat", s["lang"])
            return self._reply(s, text, trace, nlu, remember=False)
        if intent in ("approve", "reject"):
            if s["state"] == "AWAIT_APPROVAL":
                trace = ["AWAIT_APPROVAL"]
            return self._decide(s, intent == "approve", trace, nlu)
        if intent == "greet":
            return self._reply(s, replies.render("greet", s["lang"]), trace, nlu)
        if intent == "apply_insurance":
            return self._reply(s, replies.render("apply_info", s["lang"]), trace, nlu)
        if intent == "book_help":
            ticket = tools.book_help(sid, s["app_no"])
            self.evidence.log(sid, "tool", tool="book_help", result=ticket)
            return self._reply(s, replies.render("help_booked", s["lang"], ticket=ticket["ticket_id"],
                                                 slot=ticket["slot"]), trace, nlu, ticket=ticket)
        return self._claim_flow(s, intent, trace, nlu)

    def decide(self, sid, proposal_id, approve):
        """Approve/Reject button in the UI. Must match this session's open proposal."""
        s = self._session(sid)
        p = self.store.get(proposal_id, sid)   # raises ApprovalError if not this session's
        if proposal_id != s["proposal_id"] and p["status"] in ("EXECUTED", "REJECTED", "CANCELLED"):
            # duplicate click after it finished: return the FIRST result, do nothing new
            self.evidence.log(sid, "duplicate_request", proposal_id=proposal_id, status=p["status"])
            return self._reply(s, s["last_reply"], ["RESPOND"], None, remember=False,
                               proposal=_public(p), verification=p["verification"], replayed=True)
        if proposal_id != s["proposal_id"]:
            raise ApprovalError("this proposal is no longer the active one")
        self.evidence.log(sid, "input", button="approve" if approve else "reject",
                          proposal_id=proposal_id)
        return self._decide(s, approve, ["AWAIT_APPROVAL"], None)

    # ---------- claim flow ----------

    def _claim_flow(self, s, intent, trace, nlu):
        sid, lang = s["id"], s["lang"]
        if not s["app_no"]:
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, replies.render("ask_app_no", lang), trace, nlu)
        if intent == "correct_season" and not s["stated_season"]:
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, replies.render("ask_season", lang), trace, nlu)
        s["pending_intent"] = None

        trace.append("FETCH")
        res = tools.fetch_claim(self.client, s["app_no"])
        kind = rules.classify_fetch(res)
        data = res["data"] or {}
        self.evidence.log(sid, "fetch", tool="fetch_claim", app_no=s["app_no"], source=res["url"],
                          result=kind, status_code=res["status_code"],
                          record_version=data.get("record_version"), fetched_at=data.get("fetched_at"))
        if kind == "NOT_FOUND":
            app, s["app_no"] = s["app_no"], None
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, replies.render("not_found", lang, app=app), trace, nlu)
        if kind != "FOUND":   # down / timeout / error: NOT the same as "not found"
            s.update(state="COLLECT", pending_intent=intent)
            return self._reply(s, replies.render("portal_down", lang, app=s["app_no"]), trace, nlu)

        claim = res["data"]
        trace.append("DECIDE")
        a = rules.assess_claim(claim)
        mismatch = rules.season_mismatch(claim.get("season"), s["stated_season"])
        self.evidence.log(sid, "decision", verdict=a["verdict"], payment=a["payment"],
                          is_paid=a["is_paid"], missing_documents=a["missing_documents"],
                          season_record=claim.get("season"), season_stated=s["stated_season"],
                          season_mismatch=mismatch, reason=a["reason"])
        extra = {"claim": claim, "assessment": a}
        if a["verdict"] == "UNCERTAIN":
            return self._reply(s, replies.render("uncertain", lang, app=claim["app_no"]), trace, nlu, **extra)

        if intent == "correct_season":
            if not mismatch:
                return self._reply(s, replies.render("season_already_correct", lang, app=claim["app_no"],
                                                     season=claim["season"]), trace, nlu, **extra)
            return self._propose_season(s, claim, trace, nlu, extra)
        if intent == "upload_doc":
            if not a["missing_documents"]:
                return self._reply(s, replies.render("nothing_to_upload", lang, app=claim["app_no"]),
                                   trace, nlu, **extra)
            return self._propose_upload(s, claim, a["missing_documents"][0], trace, nlu, extra)

        # check_status / missing_docs: report, then offer the obvious next step
        text = replies.status_reply(claim, a, lang)
        if mismatch:
            return self._propose_season(s, claim, trace, nlu, extra, prefix=text)
        if a["missing_documents"]:
            prefix = "" if intent == "missing_docs" else text   # proposal already names the doc
            return self._propose_upload(s, claim, a["missing_documents"][0], trace, nlu, extra, prefix=prefix)
        return self._reply(s, text, trace, nlu, **extra)

    # ---------- proposals ----------

    def _propose(self, s, change, claim, text, trace, nlu, extra):
        old = self.store.proposals.get(s["proposal_id"])
        if old and old["status"] == "PENDING":
            old["status"] = "SUPERSEDED"     # only one open proposal per session
        p = self.store.create(s["id"], change, claim["record_version"])
        s.update(proposal_id=p["id"], state="AWAIT_APPROVAL")
        trace += ["PROPOSE", "AWAIT_APPROVAL"]
        self.evidence.log(s["id"], "proposal", proposal_id=p["id"], change=change,
                          base_version=p["base_version"], idempotency_key=p["idempotency_key"])
        return self._reply(s, text, trace, nlu, proposal=_public(p), **extra)

    def _propose_season(self, s, claim, trace, nlu, extra, prefix=""):
        change, err = tools.propose_season_correction(claim, s["stated_season"])
        if err:
            return self._reply(s, replies.render("clarify", s["lang"]), trace, nlu, **extra)
        text = replies.render("propose_season", s["lang"], app=claim["app_no"],
                              old=change["from"], new=change["to"])
        return self._propose(s, change, claim, (prefix + " " + text).strip(), trace, nlu, extra)

    def _propose_upload(self, s, claim, doc, trace, nlu, extra, prefix=""):
        change, err = tools.propose_document_upload(claim, doc)
        if err:
            return self._reply(s, replies.render("clarify", s["lang"]), trace, nlu, **extra)
        text = replies.render("propose_upload", s["lang"], app=claim["app_no"], doc=doc,
                              file=change["file_ref"])
        return self._propose(s, change, claim, (prefix + " " + text).strip(), trace, nlu, extra)

    # ---------- approval -> execute -> verify ----------

    def _decide(self, s, approve, trace, nlu):
        sid, lang = s["id"], s["lang"]
        p = self.store.proposals.get(s["proposal_id"]) if s["proposal_id"] else None
        if not p or p["status"] not in ("PENDING", "APPROVED", "PENDING_CONFIRMATION", "EXECUTED"):
            return self._reply(s, replies.render("nothing_pending", lang), trace, nlu)

        if not approve:
            if p["status"] == "PENDING_CONFIRMATION":   # may already be applied: cannot cancel
                return self._reply(s, replies.render("action_timeout", lang), trace, nlu, proposal=_public(p))
            if p["status"] == "PENDING":
                self.store.decide(p["id"], sid, approve=False)
            else:
                p["status"] = "CANCELLED"
            self.evidence.log(sid, "approval", proposal_id=p["id"], decision="REJECTED")
            s.update(state="RESPOND", proposal_id=None)
            return self._reply(s, replies.render("rejected", lang), trace + ["RESPOND"], nlu, proposal=_public(p))

        if p["status"] == "PENDING":
            self.store.decide(p["id"], sid, approve=True)
            self.evidence.log(sid, "approval", proposal_id=p["id"], decision=p["status"])
            if p["status"] != "APPROVED":           # e.g. expired by time
                s.update(state="RESPOND", proposal_id=None)
                return self._reply(s, replies.render("expired", lang), trace, nlu, proposal=_public(p))

        trace.append("EXECUTE")
        p = self.runner.run(p["id"], sid)
        self.evidence.log(sid, "execution", proposal_id=p["id"], status=p["status"],
                          execution=p["execution"])
        key = {"PENDING_CONFIRMATION": "action_timeout", "APPROVED": "action_portal_down",
               "EXPIRED": "expired", "FAILED": "action_failed"}.get(p["status"])
        if key:
            if p["status"] in ("EXPIRED", "FAILED"):
                s.update(state="RESPOND", proposal_id=None)
            return self._reply(s, replies.render(key, lang), trace, nlu, proposal=_public(p))

        trace.append("VERIFY")
        v = p["verification"]
        self.evidence.log(sid, "verification", **v)
        s.update(state="RESPOND", proposal_id=None if v["status"] == "VERIFIED" else p["id"])
        if v["status"] == "VERIFIED":
            text = replies.render("verified", lang, what=_what(p["change"], lang),
                                  fetched=replies.fmt_time(v.get("fetched_at")))
        else:
            text = replies.render({"FAILED": "verify_failed", "PENDING": "verify_pending"}
                                  .get(v["status"], "verify_uncertain"), lang)
        return self._reply(s, text, trace, nlu, proposal=_public(p), verification=v)

    # ---------- output ----------

    def _reminder(self, s, trace, nlu):
        p = self.store.proposals[s["proposal_id"]]
        text = replies.render("pending_reminder", s["lang"], summary=replies.change_summary(p["change"]))
        return self._reply(s, text, trace, nlu, proposal=_public(p))

    def _reply(self, s, text, trace, nlu, remember=True, **extra):
        if trace[-1] != "RESPOND":
            trace.append("RESPOND")
        if remember:
            s["last_reply"] = text
        self.evidence.log(s["id"], "reply", text=text, lang=s["lang"], state=s["state"], trace=trace)
        return {"session_id": s["id"], "reply": text, "lang": s["lang"], "state": s["state"],
                "trace": trace, "intent": nlu["intent"] if nlu else None,
                "confidence": nlu["confidence"] if nlu else None,
                "entities": nlu["entities"] if nlu else {}, **extra}


def _public(p):
    """Proposal fields safe to show in the UI."""
    return {k: p[k] for k in ("id", "change", "status", "base_version", "execution", "verification")}


def _what(change, lang):
    if change["action_type"] == "season_change":
        return ("सीज़न " if lang == "hi" else "season ") + change["to"]
    return f"'{change['document_name']}'" + (" जमा" if lang == "hi" else " received")
