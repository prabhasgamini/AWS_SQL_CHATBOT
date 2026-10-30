"""
The tools the model can call:

    execute_sql_query    - runs one read-only SELECT, as the signed-in user, through the guardrails
    get_current_datetime - tells the model the current date, time and time zone
    calculate_metric     - power factor, energy, load utilisation, share of the transformer
    calculate            - plain arithmetic, so the model never does maths in its head

Every tool asks the current_user context variable who is calling. If nobody is signed in the
tool refuses, it never falls back to "everything".
"""

import json
import sqlite3
from contextvars import ContextVar
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

import access
import calculator
import config
import guardrails
import metrics
from context import current_user

ROWS_SHOWN_TO_LLM = 50
collected_queries = ContextVar("collected_queries")
collected_metrics = ContextVar("collected_metrics")

NOT_SIGNED_IN = json.dumps({"error": "Not signed in."})


def run_guarded_query(sql, user):
    """Validate, execute (scoped to `user`) and clean one query. Always returns a dict, never raises."""
    if user is None:
        return {"sql": sql, "error": "Not signed in."}

    try:
        cleaned = guardrails.validate_sql(sql, allowed_tables=access.allowed_tables(user))
    except guardrails.GuardrailError as exc:
        return {"sql": sql, "error": str(exc)}

    try:
        columns, rows, truncated = access.run_select(cleaned, user)
    except sqlite3.Error as exc:
        message = str(exc)
        if "no such table" in message:
            return {"sql": cleaned, "error": "That table isn't available to your account."}
        if "not authorized" in message or "prohibited" in message:
            return {"sql": cleaned, "error": "Access denied for that part of the query."}
        return {"sql": cleaned, "error": f"SQL error: {message}"}

    rows = guardrails.sanitize_rows(rows)
    result = {
        "sql": cleaned,
        "columns": columns,
        "row_count": len(rows),
        "truncated": truncated,
        "rows": rows,
    }
    if not rows:
        result["note"] = guardrails.empty_result_note()
    return result


def _remember(var, item):
    try:
        var.get().append(item)
    except LookupError:
        pass 
@tool(description=(
    "Run ONE read-only SELECT query on the local power distribution database and return the "
    "rows as JSON. Anything other than a SELECT is rejected. You only see the rows the signed-in "
    "user is allowed to see."
))
def execute_sql_query(query: str) -> str:
    result = run_guarded_query(query, current_user.get())
    _remember(collected_queries, result)

    llm = dict(result)
    if "rows" in llm and len(llm["rows"]) > ROWS_SHOWN_TO_LLM:
        llm["rows"] = llm["rows"][:ROWS_SHOWN_TO_LLM]
        llm["note"] = (
            f"Only the first {ROWS_SHOWN_TO_LLM} of {result['row_count']} rows are shown to you. "
            "The user can see all of them."
        )
    return json.dumps(llm, default=str)


def _now():
    try:
        return datetime.now(ZoneInfo(config.TIMEZONE))
    except Exception:
        return datetime.now().astimezone()


@tool(description=(
    "Get the current date, time and time zone. Call this whenever the question depends on "
    "'today', 'now', 'yesterday', 'last 24 hours', 'this week' and so on, or when the user "
    "asks what the date or time is. Takes no arguments."
))
def get_current_datetime() -> str:
    now = _now()
    return json.dumps({
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": now.strftime("%A"),
        "timezone": config.TIMEZONE,
        "timezone_abbreviation": now.tzname(),
        "utc_offset": now.strftime("%z"),
        "iso": now.isoformat(timespec="seconds"),
    })


@tool(description=(
    "Calculate a metric exactly instead of estimating it. metric is one of: 'power_factor', "
    "'energy_consumption' (kWh, daily average, peak demand, load factor), 'load_utilisation' "
    "(percent of contracted load for a consumer, percent of capacity for a DTR), "
    "'consumption_share' (a consumer's percent of its transformer's energy), or "
    "'top_consumers' (admin only, needs a DTR code). identifier is a consumer number, a "
    "consumer or plant NAME, or a DTR code like 'DTR-1001'. Leave identifier empty to mean the "
    "signed-in user themselves. days is the look-back window, default 7 (the data holds about 7 days). "
    "Returns the value, the formula, the inputs and a short assessment."
))
def calculate_metric(metric: str, identifier: str = "", days: int = 7) -> str:
    user = current_user.get()
    if user is None:
        return NOT_SIGNED_IN
    try:
        result = metrics.compute_metric(metric, identifier, days, user)
    except (metrics.MetricError, access.AccessDenied) as exc:
        return json.dumps({"error": str(exc)})
    except (ValueError, TypeError):
        return json.dumps({"error": "Invalid input for the metric."})

    _remember(collected_metrics, result)
    return json.dumps(result, default=str)


@tool(description=(
    "Evaluate an arithmetic expression exactly, for example '(45.5 / 120) * 100' or "
    "'sqrt(3) * 415 * 12 / 1000'. Supports + - * / % ** and brackets, and round, abs, min, max, "
    "sqrt, sin, cos, tan, acos, asin, atan, radians, degrees, log, log10, pi. "
    "Use it for any maths instead of working it out yourself."
))
def calculate(expression: str) -> str:
    try:
        return json.dumps({"expression": expression, "result": calculator.calculate(expression)})
    except ValueError as exc:
        return json.dumps({"error": str(exc)})


ALL_TOOLS = [execute_sql_query, get_current_datetime, calculate_metric, calculate]
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}
