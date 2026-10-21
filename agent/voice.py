"""Voice provider switch (backend side).

The browser talks to voice through ONE small interface: listen() and speak(text, lang)
(see web/voice.js). Providers:
  browser (default) - Web Speech API inside the browser. No key, no server work.
  verbx             - selected with env VOICE_PROVIDER=verbx. The key VERBX_API_KEY is
                      read ONLY here, from the environment / gitignored .env file,
                      and is NEVER sent to the browser.

If VerbX is missing, errors or times out, the browser automatically falls back
to the browser provider and shows a small notice.
"""
import os

ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def load_env_file(path=ENV_FILE):
    """Tiny .env reader (KEY=VALUE lines). Real environment variables win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def provider_name():
    name = os.getenv("VOICE_PROVIDER", "browser").strip().lower()
    return name if name in ("browser", "verbx") else "browser"


def public_config():
    """What the browser may know. Never includes the API key."""
    name = provider_name()
    has_key = bool(os.getenv("VERBX_API_KEY"))
    ready = name == "verbx" and has_key and VerbXProvider.IMPLEMENTED
    notice = None
    if name == "verbx" and not ready:
        notice = ("VerbX is not available yet, using the browser voice."
                  if has_key else "VerbX key missing, using the browser voice.")
    return {"provider": name, "verbx_ready": ready, "fallback": "browser", "notice": notice}


class VoiceProviderError(Exception):
    """Any VerbX problem. The browser treats it as 'fall back to browser voice'."""


# =====================================================================
# TODO(VerbX): STUB ONLY. Do NOT implement until the VerbX API docs are
# provided. Fill in synthesize() and transcribe(), then set IMPLEMENTED=True.
# Keep the API key server-side; add a short timeout to every call.
# =====================================================================
class VerbXProvider:
    IMPLEMENTED = False
    TIMEOUT_SECONDS = 5

    def __init__(self):
        self.api_key = os.getenv("VERBX_API_KEY")   # never logged, never returned

    def synthesize(self, text, lang):
        """Text -> audio bytes (e.g. audio/mpeg). Not implemented yet."""
        raise VoiceProviderError("VerbX adapter not implemented yet (waiting for API docs)")

    def transcribe(self, audio_bytes, lang):
        """Audio bytes -> text. Not implemented yet."""
        raise VoiceProviderError("VerbX adapter not implemented yet (waiting for API docs)")
