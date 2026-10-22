"""Message bus: the ONLY way our agents talk to each other.

Every request and every reply is a Message with a sender, a recipient, a type and a
payload. The bus delivers it to the recipient agent and records both in a transcript,
so judges can watch the agents' conversation (judge console -> "Agent conversation").

Delivery is synchronous and in-process: simple, deterministic and easy to test.
"""
import itertools
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.evidence import _scrub

MAX_TRANSCRIPT = 5000           # keep memory bounded on long-running servers
QUIET_TYPES = {"record"}        # audit records are in the evidence log; keep the chat readable


@dataclass
class Message:
    id: str
    session_id: str
    sender: str
    recipient: str
    type: str
    payload: dict
    reply_to: str = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))


def summarize(payload, limit=160):
    """Short, readable view of a payload for the transcript (full data stays in evidence)."""
    parts = []
    for key, value in (payload or {}).items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        text = str(value)
        parts.append(f"{key}={text[:60] + '…' if len(text) > 60 else text}")
    joined = ", ".join(parts)
    return joined[:limit] + ("…" if len(joined) > limit else "")


class MessageBus:
    def __init__(self):
        self.agents = {}
        self.transcript = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def register(self, agent):
        self.agents[agent.name] = agent

    def request(self, sender, recipient, type, session_id, **payload):
        """Send a message and wait for the recipient's reply (returns the reply payload)."""
        if recipient not in self.agents:
            raise KeyError(f"no agent named {recipient}")
        msg = Message(f"m{next(self._ids)}", session_id, sender, recipient, type, payload)
        self._record(msg)
        result = self.agents[recipient].handle(msg) or {}
        self._record(Message(f"m{next(self._ids)}", session_id, recipient, sender,
                             type + ".result", result, reply_to=msg.id))
        return result

    def _record(self, msg):
        if msg.type.split(".")[0] in QUIET_TYPES:
            return
        entry = {"id": msg.id, "ts": msg.ts, "session_id": msg.session_id, "from": msg.sender,
                 "to": msg.recipient, "type": msg.type, "reply_to": msg.reply_to,
                 "summary": summarize(_scrub(msg.payload))}
        with self._lock:
            self.transcript.append(entry)
            if len(self.transcript) > MAX_TRANSCRIPT:
                del self.transcript[: len(self.transcript) - MAX_TRANSCRIPT]

    def for_session(self, session_id):
        return [m for m in self.transcript if m["session_id"] == session_id]

    def roster(self):
        """Who is on the bus and what each agent can be asked to do."""
        return [{"name": a.name, "role": a.role, "handles": a.handles()} for a in self.agents.values()]
