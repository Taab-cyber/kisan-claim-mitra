"""Evidence log: an audit trail that explains every decision.

Each entry: session id, step name, time, and the data for that step (validated
inputs, source URL + record_version + fetched_at, decision + reason, proposal,
approval, execution, verification, final reply). Secrets are never stored.
"""
import json
import threading
from datetime import datetime, timezone

SECRET_KEYS = {"api_key", "verbx_api_key", "password", "otp", "token", "aadhaar", "pan",
               "bank_account", "authorization"}


def _scrub(value):
    """Recursively replace any secret-looking field with '[redacted]'."""
    if isinstance(value, dict):
        return {k: "[redacted]" if k.lower() in SECRET_KEYS else _scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


class EvidenceLog:
    def __init__(self, path=None):
        self.entries = []
        self.path = path            # optional JSONL file for a permanent copy
        self._lock = threading.Lock()

    def log(self, session_id, step, **data):
        entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                 "session_id": session_id, "step": step, "data": _scrub(data)}
        with self._lock:
            self.entries.append(entry)
            if self.path:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def for_session(self, session_id):
        return [e for e in self.entries if e["session_id"] == session_id]

    def clear(self):
        with self._lock:
            self.entries.clear()
