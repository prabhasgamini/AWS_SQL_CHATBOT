"""FastAPI bridge between the Next.js frontend and the LangChain SQL agent."""

import logging
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import access
import auth
import config
import database
import guardrails
import user_profile
from agent import SqlAgent, explain_llm_error

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("sql-kb")


def refresh_directory():
    """Give the guardrails the consumer names and DTR areas, so questions that use them count as relevant."""
    conn = access.trusted_connection()
    try:
        names = [r[0] for r in conn.execute("SELECT NAME FROM lt_consumer_master")]
        names += [r[0] for r in conn.execute("SELECT NAME FROM ht_consumer_master")]
        places = [r[0] for r in conn.execute("SELECT DTR_LOCATION FROM dtr_master")]
    finally:
        conn.close()
    guardrails.set_directory(names, places)


@asynccontextmanager
async def lifespan(app):
    if database.init_db():
        log.info("Built and seeded %s", database.DB_PATH.name)
    auth.init_auth()
    refresh_directory()

    log.info("Settings read from %s (%s)", config.ENV_PATH, "found" if config.ENV_PATH.exists() else "NOT FOUND, using defaults")
    if config.LLM_PROVIDER == "bedrock":
        log.info("LLM: Bedrock, region %s, model %s, API key %s", config.AWS_REGION,
                 config.BEDROCK_MODEL_ID or "(NOT SET)", "present" if config.BEARER_TOKEN_SET else "MISSING")
    else:
        log.info("LLM: %s, model %s", config.LLM_PROVIDER, config.OLLAMA_MODEL)
    yield


app = FastAPI(title="SQL Knowledge Base Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def get_agent():
    # built on first use so the server still boots if the LLM isn't configured yet
    return SqlAgent()


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None


class WelcomeRequest(BaseModel):
    session_id: str | None = None


class Timings(BaseModel):
    guardrails_ms: float
    llm_ms: float
    sql_ms: float
    total_ms: float


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    session_id: str
    response: str
    generated_sql: str | None = None
    columns: list[str] = []
    data: list[dict] = []
    truncated: bool = False
    blocked: bool = False
    tools_used: list[str] = []
    calculations: list[dict] = []
    timings: Timings
    token_usage: TokenUsage


def _public_user(user):
    return {"username": user.username, "role": user.role, "display_name": user.display_name,
            "consumer_number": user.consumer_ref}


def _no_llm_reply(session_id, text, blocked, guard_ms):
    """Reply built entirely by the guardrails or templates, the model is never called."""
    return ChatResponse(
        session_id=session_id,
        response=text,
        blocked=blocked,
        timings=Timings(guardrails_ms=round(guard_ms, 1), llm_ms=0, sql_ms=0, total_ms=round(guard_ms, 1)),
        token_usage=TokenUsage(),
    )


def _chat_response(session_id, result, guard_ms, total_ms):
    return ChatResponse(
        session_id=session_id,
        response=result["response"],
        generated_sql=result["generated_sql"],
        columns=result["columns"],
        data=result["data"],
        truncated=result["truncated"],
        tools_used=result["tools_used"],
        calculations=result["calculations"],
        timings=Timings(
            guardrails_ms=round(guard_ms, 1),
            llm_ms=round(result["llm_ms"], 1),
            sql_ms=round(result["sql_ms"], 1),
            total_ms=round(total_ms, 1),
        ),
        token_usage=TokenUsage(**result["token_usage"]),
    )


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------

def _token_from(authorization):
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization[7:].strip()


def signed_in(authorization: str | None = Header(default=None)):
    """Dependency: the signed-in user and their token, or a 401."""
    token = _token_from(authorization)
    user = auth.user_from_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user, token


@app.post("/api/auth/login")
def login(req: LoginRequest):
    try:
        token, user = auth.login(req.username, req.password)
    except auth.LockedOut as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"token": token, "expires_in": config.SESSION_HOURS * 3600, "user": _public_user(user)}


@app.post("/api/auth/logout")
def logout(session=Depends(signed_in)):
    _, token = session
    auth.logout(token)
    return {"signed_out": True}


@app.get("/api/auth/me")
def me(session=Depends(signed_in)):
    user, _ = session
    return {"user": _public_user(user)}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok", "database": database.DB_PATH.exists(), "provider": config.LLM_PROVIDER,
            "region": config.AWS_REGION if config.LLM_PROVIDER == "bedrock" else None,
            "model_configured": bool(config.BEDROCK_MODEL_ID) if config.LLM_PROVIDER == "bedrock" else True,
            "api_key_present": config.BEARER_TOKEN_SET if config.LLM_PROVIDER == "bedrock" else None}


def _key(user, session_id):
    # memory is per person, so nobody can read another user's chat by guessing a session id
    return f"{user.username}:{session_id}"


@app.delete("/api/sessions/{session_id}")
def clear_session(session_id: str, session=Depends(signed_in)):
    user, _ = session
    if get_agent.cache_info().currsize:
        get_agent().reset(_key(user, session_id))
    return {"cleared": session_id}


def _agent_or_503():
    try:
        return get_agent()
    except Exception as exc:
        log.exception("Could not build the LLM")
        raise HTTPException(status_code=503, detail=f"The LLM isn't set up yet: {explain_llm_error(exc)}") from exc


@app.post("/api/welcome", response_model=ChatResponse)
def welcome(req: WelcomeRequest, session=Depends(signed_in)):
    """The automatic message right after login: the model greets the user from their own profile."""
    started = time.perf_counter()
    user, _ = session
    session_id = req.session_id or str(uuid.uuid4())

    profile = user_profile.build_profile(user)
    guard_ms = (time.perf_counter() - started) * 1000

    try:
        result = get_agent().greet(_key(user, session_id), user, profile)
    except Exception as exc:
        # logging in must never end on an error, so fall back to a fixed greeting
        log.warning("Greeting by the model failed, using the plain greeting: %s", explain_llm_error(exc))
        return _no_llm_reply(session_id, user_profile.plain_greeting(profile), blocked=False, guard_ms=guard_ms)

    return _chat_response(session_id, result, guard_ms, (time.perf_counter() - started) * 1000)


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, session=Depends(signed_in)):
    started = time.perf_counter()
    user, _ = session
    session_id = req.session_id or str(uuid.uuid4())
    key = _key(user, session_id)

    # pre-processing guardrails
    question = guardrails.sanitize_input(req.message)
    if not question:
        raise HTTPException(status_code=400, detail="Message is empty after cleaning.")

    refusal = guardrails.check_scope(question, user)
    if refusal:
        log.info("Out-of-scope question from %s: %r", user.username, question[:80])
        return _no_llm_reply(session_id, refusal, blocked=True, guard_ms=(time.perf_counter() - started) * 1000)

    # the agent only exists after the first real question, so before that there is no history
    has_history = get_agent.cache_info().currsize > 0 and get_agent().has_history(key)
    kind, message = guardrails.check_intent(question, has_history=has_history)
    guard_ms = (time.perf_counter() - started) * 1000
    if kind == "blocked":
        log.info("Blocked off-topic question: %r", question[:80])
        return _no_llm_reply(session_id, message, blocked=True, guard_ms=guard_ms)
    if kind == "smalltalk":
        return _no_llm_reply(session_id, message, blocked=False, guard_ms=guard_ms)

    agent = _agent_or_503()
    try:
        result = agent.ask(key, question, user)
    except Exception as exc:
        log.exception("Agent failed")
        raise HTTPException(
            status_code=502,
            detail=f"The language model call failed. {explain_llm_error(exc)}",
        ) from exc

    return _chat_response(session_id, result, guard_ms, (time.perf_counter() - started) * 1000)
