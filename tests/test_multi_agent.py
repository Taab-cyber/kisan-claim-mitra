"""Multi-agent structure: agents talk only via the bus; maker-checker; readable transcript."""
import pytest

from agent.bus import MessageBus, summarize
from agent.planner import Agent
from agent.tools import PortalClient

SPECIALISTS = {"intake", "investigator", "action", "verifier", "helpdesk", "responder", "auditor"}


@pytest.fixture
def agent(portal):
    return Agent(PortalClient(portal, timeout=1))


def conversation(agent, sid):
    """(from, to, type) of every request in a session, in order."""
    return [(m["from"], m["to"], m["type"]) for m in agent.bus.for_session(sid) if not m["type"].endswith(".result")]


def test_roster_has_all_specialists(agent):
    roster = {a["name"]: a for a in agent.bus.roster()}
    assert set(roster) == SPECIALISTS
    assert "verify" in roster["verifier"]["handles"] and "execute" in roster["action"]["handles"]


def test_tc3_conversation_between_agents(agent):
    sid = agent.new_session("hi")
    agent.handle(sid, "mera rabi 2026-27 ka claim KRB-2026-00633 ka status batao")
    agent.handle(sid, "haan kar do")
    steps = [(f, t, ty) for f, t, ty in conversation(agent, sid)]
    order = [("orchestrator", "intake", "understand"), ("orchestrator", "investigator", "investigate"),
             ("orchestrator", "action", "propose"), ("orchestrator", "action", "execute"),
             ("orchestrator", "verifier", "verify")]
    positions = [steps.index(o) for o in order]
    assert positions == sorted(positions)            # the agents were asked in pipeline order
    # every request got exactly one reply on the bus
    msgs = agent.bus.for_session(sid)
    assert len([m for m in msgs if m["type"].endswith(".result")]) == len(steps)


def test_maker_checker_executor_never_verifies(agent, portal):
    sid = agent.new_session()
    pid = agent.handle(sid, "KRB-2026-00633 season galat hai rabi 2026-27 karo")["proposal"]["id"]
    agent.store.decide(pid, sid, approve=True)
    p = agent.runner.run(pid, sid)                    # the action agent's executor alone
    assert p["status"] == "EXECUTED" and p["verification"] is None
    v = agent.ask("verifier", "verify", sid, proposal=p)   # only the verifier can confirm it
    assert v["status"] == "VERIFIED"


def test_only_the_bus_connects_agents(agent):
    for specialist in agent.bus.agents.values():
        assert not any(isinstance(v, Agent) for v in vars(specialist).values())   # no back-references
        others = [v for v in vars(specialist).values() if hasattr(v, "handle") and v is not specialist]
        assert others == []                           # no direct handle on another agent


def test_unknown_message_type_is_refused(agent):
    with pytest.raises(ValueError):
        agent.ask("verifier", "execute", "s-x", proposal_id="act-1")   # verifier cannot execute


def test_transcript_redacts_secrets():
    bus = MessageBus()

    class Echo:
        name, role = "echo", "test"
        def handle(self, msg): return {"ok": True}
        def handles(self): return []

    bus.register(Echo())
    bus.request("me", "echo", "ping", "s1", otp="123456", token="abc", note="hi")
    text = " ".join(m["summary"] for m in bus.transcript)
    assert "123456" not in text and "abc" not in text and "note=hi" in text


def test_summary_is_short():
    assert len(summarize({"claim": {"x": "y" * 500}})) < 200
