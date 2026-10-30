"""
Settings for the backend. Every value comes from backend/.env (see .env.example), with the
defaults below used when a line is missing. Edit .env, then restart the server.

The .env file is found next to this file, so it works no matter which folder you start
the server from. Values in .env win over any same-named variable already set in your shell,
so a stale shell variable can't silently override what you wrote in the file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH, override=True)


def _text(name, default=""):
    return os.getenv(name, default).strip()


def _number(name, default, cast):
    raw = _text(name)
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        raise ValueError(f"{name} in backend/.env must be a number, got '{raw}'") from None


def _flag(name, default):
    raw = _text(name)
    return default if not raw else raw.lower() in {"1", "true", "yes", "on"}


def _list(name, default):
    raw = _text(name)
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else default


# --- Which model backend -------------------------------------------------
# "bedrock" (AWS) or "ollama" (local)
LLM_PROVIDER = _text("LLM_PROVIDER", "bedrock").lower()
LLM_TEMPERATURE = _number("LLM_TEMPERATURE", 0.0, float)

# --- AWS Bedrock ---------------------------------------------------------
AWS_REGION = _text("AWS_REGION", "us-east-1")
# The exact model ID or inference profile ID (for example "us.anthropic.claude-...") or an ARN
BEDROCK_MODEL_ID = _text("BEDROCK_MODEL_ID")
# Only needed if BEDROCK_MODEL_ID is an ARN, so the model family can't be read from the ID.
# For example "anthropic" or "amazon".
BEDROCK_PROVIDER = _text("BEDROCK_PROVIDER")
BEDROCK_MAX_TOKENS = _number("BEDROCK_MAX_TOKENS", 2000, int)

# The Bedrock API key (bearer token). It is NOT read here: AWS's own SDK (boto3) picks up
# AWS_BEARER_TOKEN_BEDROCK from the environment, which load_dotenv() has just filled from .env.
# We only note whether it is present, so we can warn, and never print its value.
BEARER_TOKEN_SET = bool(_text("AWS_BEARER_TOKEN_BEDROCK"))
OTHER_AWS_CREDENTIALS_SET = bool(_text("AWS_ACCESS_KEY_ID") or _text("AWS_PROFILE"))

# --- Ollama (local alternative) ------------------------------------------
OLLAMA_MODEL = _text("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = _text("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_NUM_CTX = _number("OLLAMA_NUM_CTX", 8192, int)

# --- General -------------------------------------------------------------
# Time zone reported by the get_current_datetime tool (any IANA name)
TIMEZONE = _text("TIMEZONE", "Asia/Kolkata")

# Browser origins allowed to call the API directly (the Next.js proxy doesn't need this)
ALLOWED_ORIGINS = _list("ALLOWED_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"])

# --- Login ---------------------------------------------------------------
# Accounts are created automatically the first time the backend starts:
#   admin account:     username "admin",   password = ADMIN_PASSWORD
#   each LT consumer:  username = consumer number (SCNO), password = USER_PASSWORD_PREFIX + SCNO
#   each HT consumer:  username = HT consumer number,     password = USER_PASSWORD_PREFIX + number
# These are demo passwords. Change them in .env BEFORE the first start (or later with
# `python auth.py --set-password <username> <new password>`).
ADMIN_PASSWORD = _text("ADMIN_PASSWORD", "Admin")
USER_PASSWORD_PREFIX = _text("USER_PASSWORD_PREFIX", "Pass")

SESSION_HOURS = _number("SESSION_HOURS", 8, int)          # how long a login lasts
MAX_FAILED_LOGINS = _number("MAX_FAILED_LOGINS", 5, int)  # wrong passwords allowed...
LOCKOUT_MINUTES = _number("LOCKOUT_MINUTES", 5, int)      # ...within this many minutes

# Can a consumer see what share of their transformer's load they account for?
# It only reveals a percentage, never another consumer's data.
USERS_CAN_SEE_DTR_SHARE = _flag("USERS_CAN_SEE_DTR_SHARE", True)