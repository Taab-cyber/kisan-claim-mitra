"""The specialist agents. Each owns ONE job and its own tools, and is only reachable
through the message bus (agent/bus.py). The Orchestrator (agent/planner.py) coordinates them.

  intake        understands the farmer: trained NLU model -> intent + entities
  investigator  reads the portal record and applies the business rules
  action        drafts proposals, records approvals, executes changes exactly once
  verifier      independently re-reads the portal after every action (maker-checker)
  helpdesk      books a (synthetic) call-back with an officer
  responder     writes the Hindi/English reply from fixed templates
  auditor       writes every step into the evidence log (secrets redacted)

No agent calls another directly: they only answer messages. That keeps each one
small, testable and replaceable (e.g. a different NLU) without touching the others.
"""
from agent import replies, rules, tools, verify
from agent.approvals import ActionRunner, ApprovalStore
from agent.nlu.predict import predict


class BaseAgent:
    name = "base"
    role = ""

    def __init__(self, bus):
        self.bus = bus
        bus.register(self)

    def handle(self, msg):
        """Dispatch a message of type 'x_y' to the method on_x_y(session_id, **payload)."""
        handler = getattr(self, "on_" + msg.type, None)
        if handler is None:
            raise ValueError(f"{self.name} cannot handle '{msg.type}'")
        return handler(msg.session_id, **msg.payload)

    def handles(self):
        return sorted(m[3:] for m in dir(self) if m.startswith("on_"))


class IntakeAgent(BaseAgent):
    name, role = "intake", "Understands the farmer (our trained intent model + rule-based entities)"

    def on_understand(self, sid, text):
        nlu = predict(text)
        app_no = nlu["entities"].get("app_no")
        return {**nlu, "app_no_valid": rules.valid_app_no(app_no) if app_no else None}


class InvestigatorAgent(BaseAgent):
    name, role = "investigator", "Reads the claim from the portal and applies the business rules"

    def __init__(self, bus, client):
        super().__init__(bus)
        self.client = client

    def on_investigate(self, sid, app_no, stated_season=None):
        res = tools.fetch_claim(self.client, app_no)
        kind = rules.classify_fetch(res)          # FOUND / NOT_FOUND / PORTAL_DOWN / TIMEOUT / ...
        data = res["data"] or {}
        findings = {"fetch": kind, "source": res["url"], "status_code": res["status_code"],
                    "record_version": data.get("record_version"), "fetched_at": data.get("fetched_at"),
                    "claim": None, "assessment": None, "season_mismatch": False}
        if kind == "FOUND":
            findings.update(claim=data, assessment=rules.assess_claim(data),
                            season_mismatch=rules.season_mismatch(data.get("season"), stated_season))
        return findings


class ActionAgent(BaseAgent):
    name, role = "action", "Drafts proposals, records the farmer's decision, executes approved changes once"

    def __init__(self, bus, client, store=None):
        super().__init__(bus)
        self.store = store or ApprovalStore()
        self.runner = ActionRunner(client, self.store)

    def on_propose(self, sid, action_type, claim, value, replaces=None):
        if action_type == "season_change":
            change, err = tools.propose_season_correction(claim, value)
        else:
            change, err = tools.propose_document_upload(claim, value)
        if err:
            return {"error": err}
        old = self.store.proposals.get(replaces)
        if old and old["status"] == "PENDING":
            old["status"] = "SUPERSEDED"         # only one open proposal per session
        return {"proposal": self.store.create(sid, change, claim["record_version"])}

    def on_lookup(self, sid, proposal_id):
        return {"proposal": self.store.get(proposal_id, sid)}   # raises if another session's

    def on_decide(self, sid, proposal_id, approve):
        return {"proposal": self.store.decide(proposal_id, sid, approve)}

    def on_cancel(self, sid, proposal_id):
        p = self.store.get(proposal_id, sid)
        p["status"] = "CANCELLED"
        return {"proposal": p}

    def on_execute(self, sid, proposal_id):
        return {"proposal": self.runner.run(proposal_id, sid)}   # backend-enforced approval inside

    def on_attach_verification(self, sid, proposal_id, verification):
        p = self.store.get(proposal_id, sid)
        p["verification"] = verification
        return {"proposal": p}


class VerifierAgent(BaseAgent):
    name, role = "verifier", "Independently re-reads the portal and checks the intended change (never trusts the executor)"

    def __init__(self, bus, client):
        super().__init__(bus)
        self.client = client

    def on_verify(self, sid, proposal):
        return verify.verify(self.client, proposal)


class HelpdeskAgent(BaseAgent):
    name, role = "helpdesk", "Books a (synthetic) call-back from a help-desk officer"

    def on_book(self, sid, app_no=None):
        return tools.book_help(sid, app_no)


class ResponderAgent(BaseAgent):
    name, role = "responder", "Writes the Hindi/English reply from fixed templates using portal data"

    def on_compose(self, sid, key, lang, claim=None, assessment=None, change=None,
                   verification=None, **kw):
        if key == "status":
            text = replies.status_reply(claim, assessment, lang)
        elif key == "verified":
            text = replies.render("verified", lang, what=_what(change, lang),
                                  fetched=replies.fmt_time(verification.get("fetched_at")))
        elif key == "pending_reminder":
            text = replies.render(key, lang, summary=replies.change_summary(change))
        else:
            text = replies.render(key, lang, **kw)
        return {"text": text}


class AuditorAgent(BaseAgent):
    name, role = "auditor", "Writes every step into the evidence log (secrets redacted)"

    def __init__(self, bus, evidence):
        super().__init__(bus)
        self.evidence = evidence

    def on_record(self, sid, step, data):
        self.evidence.log(sid, step, **data)
        return {}


def _what(change, lang):
    if change["action_type"] == "season_change":
        return ("सीज़न " if lang == "hi" else "season ") + change["to"]
    return f"'{change['document_name']}'" + (" जमा" if lang == "hi" else " received")
