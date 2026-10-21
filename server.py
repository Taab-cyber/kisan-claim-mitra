"""Main web server: farmer app + judge console + agent API + mock portal.

Run:  uvicorn server:app --port 8000      then open http://localhost:8000

The mock portal is mounted at /portal. The agent talks to it over HTTP, exactly
as it would talk to a real external portal.
"""
import os
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import voice
from agent.approvals import ApprovalError
from agent.planner import Agent, UnknownSession
from agent.scenarios import SCENARIOS, run_all
from agent.tools import PortalClient
from farmer import accounts, routes as farmer_routes
from portal import db
from portal.app import app as portal_app

voice.load_env_file()   # reads the gitignored .env (VOICE_PROVIDER, VERBX_API_KEY)

PORT = int(os.getenv("PORT", "8000"))
PORTAL_URL = os.getenv("PORTAL_URL", f"http://127.0.0.1:{PORT}/portal")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

STATE = {}


def configure(http):
    """Point the agent at a portal. Tests pass an in-process client here."""
    STATE["http"] = http
    STATE["agent"] = Agent(PortalClient(http))
    farmer_routes.EVIDENCE["log"] = STATE["agent"].evidence   # one shared evidence log


@asynccontextmanager
async def lifespan(app):
    db.init_db(os.getenv("PORTAL_DB"))      # mounted apps don't run their own startup
    accounts.init_db()                      # demo farmer + synthetic sample documents
    if "agent" not in STATE:
        configure(httpx.Client(base_url=PORTAL_URL))
    yield


app = FastAPI(title="Kisan Claim Mitra", lifespan=lifespan)
app.mount("/portal", portal_app)
app.include_router(farmer_routes.router)
app.add_exception_handler(accounts.AccountError, farmer_routes.account_error_handler)


def agent():
    return STATE["agent"]


@app.exception_handler(ApprovalError)
async def approval_error(request: Request, exc: ApprovalError):
    return JSONResponse(status_code=403, content={"error": "approval_rule", "message": str(exc)})


@app.exception_handler(UnknownSession)
async def unknown_session(request: Request, exc: UnknownSession):
    return JSONResponse(status_code=404, content={"error": "unknown_session", "message": str(exc)})


# ---------- farmer API ----------

class NewSession(BaseModel):
    lang: str = "hi"


class ChatIn(BaseModel):
    session_id: str
    text: str
    lang: Optional[str] = None


class DecisionIn(BaseModel):
    session_id: str
    proposal_id: str
    approve: bool


@app.post("/api/session")
def new_session(body: NewSession):
    return {"session_id": agent().new_session(body.lang), "voice": voice.public_config()}


@app.post("/api/chat")
def chat(body: ChatIn):
    if len(body.text) > 500:
        raise HTTPException(422, "text too long")
    return agent().handle(body.session_id, body.text, body.lang)


@app.post("/api/approve")
def approve(body: DecisionIn):
    return agent().decide(body.session_id, body.proposal_id, body.approve)


# ---------- voice ----------

@app.get("/api/voice/config")
def voice_config():
    return voice.public_config()


class TtsIn(BaseModel):
    text: str
    lang: str = "hi"


@app.post("/api/voice/tts")
def voice_tts(body: TtsIn):
    """Only used when VOICE_PROVIDER=verbx. Any failure -> 503 -> browser falls back."""
    if voice.provider_name() != "verbx":
        raise HTTPException(409, "voice provider is browser")
    try:
        audio = voice.VerbXProvider().synthesize(body.text, body.lang)
    except voice.VoiceProviderError as exc:
        raise HTTPException(503, str(exc))
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/voice/stt")
async def voice_stt(request: Request, lang: str = "hi"):
    if voice.provider_name() != "verbx":
        raise HTTPException(409, "voice provider is browser")
    try:
        text = voice.VerbXProvider().transcribe(await request.body(), lang)
    except voice.VoiceProviderError as exc:
        raise HTTPException(503, str(exc))
    return {"text": text}


# ---------- judge console ----------

@app.get("/api/evidence")
def evidence(session_id: Optional[str] = None, limit: int = 300):
    log = agent().evidence
    entries = log.for_session(session_id) if session_id else log.entries
    return {"entries": entries[-limit:]}


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": [{k: s[k] for k in ("id", "title", "expected", "official")} for s in SCENARIOS]}


class RunIn(BaseModel):
    ids: Optional[List[str]] = None


@app.post("/api/scenarios/run")
def run_scenarios(body: RunIn):
    """Runs real scenarios against the mock portal (this resets the portal)."""
    return {"results": run_all(STATE["http"], only=body.ids)}


# ---------- static web app (mounted last so /api and /portal win) ----------
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
