"""
Guardrails that sit on both sides of the LLM.

Before the model:
    sanitize_input    - strips markup and obvious prompt-injection phrases
    check_intent      - only questions about the power data reach the model (names count too)
    check_scope       - a consumer can't even ask about another person, a DTR that isn't theirs,
                        or "all consumers". Refused here, before any model call
    validate_sql      - only lets a single read-only SELECT through, on tables the user may use

After the model / database:
    sanitize_rows     - cleans strings, masks phone numbers, caps field size
    clean_output      - removes active content from the model's reply
    empty_result_note - friendly hint when a query returns nothing

check_scope is a politeness layer and a cheap early exit. The real protection is in access.py,
where a consumer's connection simply doesn't contain anyone else's rows.
"""

import re

from database import TABLE_NAMES

MAX_QUESTION_CHARS = 1000


class GuardrailError(Exception):
    """Raised when something is blocked. The message is safe to show to the user."""


# ---------------------------------------------------------------------------
# Input cleaning
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<\s*/?\s*(script|style|iframe|object|embed)[^>]*>", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]{1,200}>")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|rules|prompts?)",
    r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)?\s*(instructions|rules)",
    r"forget\s+(everything|all)\s+(you|above|previous)",
    r"(reveal|show|print|repeat)\s+(me\s+)?(your|the)\s+(system|hidden|initial)\s+(prompt|instructions)",
    r"you\s+are\s+now\s+(?:a|an|in)\b",
    r"act\s+as\s+(?:a|an)\s+(?:unrestricted|jailbroken|different)",
    r"(i\s+am|i'm|im|treat\s+me\s+as|pretend\s+i\s+am)\s+(the\s+|an?\s+)?(admin|administrator|root|superuser)",
    r"developer\s+mode",
    r"<\|.*?\|>",
    r"\[/?(INST|SYS)\]",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.I)


def sanitize_input(text):
    text = text or ""
    text = _CONTROL_RE.sub("", text)
    text = _TAG_RE.sub("", text)
    text = _ANY_TAG_RE.sub("", text)
    text = _INJECTION_RE.sub("[removed]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_QUESTION_CHARS]


# ---------------------------------------------------------------------------
# Directory of known names, so "show me Ravi Patel" counts as a data question
# ---------------------------------------------------------------------------

_name_tokens = set()      # every word of every consumer / plant name
_place_tokens = set()     # first word of each DTR location, e.g. "uppal"


def _words(text):
    return re.findall(r"[a-z]+", (text or "").lower())


def set_directory(names, places):
    """Called at startup with the consumer names and DTR locations from the database."""
    _name_tokens.clear()
    _place_tokens.clear()
    for name in names:
        _name_tokens.update(w for w in _words(name) if len(w) >= 3)
    for place in places:
        words = _words(place)
        if words and len(words[0]) >= 4:
            _place_tokens.add(words[0])


# ---------------------------------------------------------------------------
# Relevance check: only questions about this database go to the LLM
# ---------------------------------------------------------------------------

# Words that point at this power distribution data
_DOMAIN_WORDS = {
    "dtr", "dtrs", "transformer", "transformers", "consumer", "consumers", "customer", "customers",
    "meter", "meters", "metering", "reading", "readings", "consumption", "consume", "consumed",
    "consuming", "usage", "feeder", "feeders", "plant", "plants", "kwh", "kva", "kw", "kvar", "vah",
    "ht", "lt", "scno", "ukscno", "msn", "amr", "pf", "electricity", "energy", "voltage", "substation",
    "capacity", "phase", "load", "loading", "overloaded", "utilisation", "utilization", "demand",
    "billing", "bill", "bills", "category", "categories", "domestic", "commercial", "industrial",
    "agriculture", "interval", "installed", "smart", "database", "table", "tables", "schema", "sql",
    "column", "columns", "supply", "contracted", "losses",
}

_DOMAIN_PHRASES_RE = re.compile(
    r"power\s+factor|load\s+factor|who\s+am\s+i|about\s+me\b|"
    r"\bmy\s+(name|details|profile|account|information|info|address|connection|supply)\b",
    re.I,
)

# Topics turned away by name, so the refusal is obvious and follow-ups can't sneak them in
_OFF_TOPIC_RE = re.compile(
    r"\b(president|prime\s+minister|chief\s+minister|minister|election|elections|politic\w*|"
    r"celebrity|actor|actress|movie|movies|film|song|songs|lyrics|music|singer|cricket|football|"
    r"ipl|sports?|olympics|weather|forecast|recipe|recipes|cook\w*|restaurant|joke|jokes|poem|"
    r"story|essay|horoscope|astrology|religion|bitcoin|crypto|stocks?|shares?|capital\s+of|"
    r"population|translate|homework|math|write\s+(a|an|me)|tell\s+me\s+a)\b",
    re.I,
)

_ID_RE = re.compile(r"\b(DTR|SM|HT|UK|HTM)[-_]?\d+|\b\d{6,}\b", re.I)

# "what is the date", "what time is it", "current time", "time zone"
_DATETIME_RE = re.compile(
    r"what\s+time\s+is\s+it|what\s+day\s+is\s+(it|today)|today'?s\s+date|current\s+(date|time)|"
    r"time\s?zone|what('?s|\s+is)\s+the\s+(current\s+)?(date|time|day)(\s+(today|now))?\s*\??$",
    re.I,
)

# Short replies like "and the second one?" are fine once a conversation exists
_FOLLOW_UP_RE = re.compile(
    r"\b(and|also|what\s+about|how\s+about|same|again|more|those|them|these|that|this|it|its|"
    r"previous|above|earlier|first|second|third|last|next|only|instead|sort|top|compare|which|how\s+many)\b",
    re.I,
)

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|good\s+(morning|afternoon|evening)|thanks|thank\s+you|ok|okay|help|"
    r"what\s+can\s+you\s+do)\b[\s\w!.?,]{0,20}$",
    re.I,
)

GREETING_REPLY = (
    "Hi! I can look things up in the power distribution database and work out figures such as "
    "power factor, consumption and load utilisation. Try \"What is my power factor?\" or "
    "\"How much did I consume this week?\""
)

REFUSAL_REPLY = (
    "I can only help with questions about the power distribution data: DTRs, consumers, "
    "smart meters, readings, consumption and related calculations. That question looks "
    "unrelated, so I haven't sent it to the model."
)


def check_intent(text, has_history=False):
    """
    Decide what to do with a question. Returns (kind, message):
        ("relevant", "")      pass it to the LLM
        ("smalltalk", reply)  answer with a canned reply, no LLM call
        ("blocked", reply)    refuse, no LLM call
    """
    stripped = text.strip()

    if _GREETING_RE.match(stripped):
        return "smalltalk", GREETING_REPLY

    words = set(_words(stripped))
    if words & _DOMAIN_WORDS or _DOMAIN_PHRASES_RE.search(stripped):
        return "relevant", ""
    if _ID_RE.search(stripped) or _DATETIME_RE.search(stripped):
        return "relevant", ""

    if _OFF_TOPIC_RE.search(stripped):
        return "blocked", REFUSAL_REPLY

    # a consumer's name or a DTR's area ("show Ravi Patel", "load at Uppal")
    if words & _name_tokens or words & _place_tokens:
        return "relevant", ""

    short_follow_up = (
        has_history
        and len(stripped.split()) <= 12
        and _FOLLOW_UP_RE.search(stripped)
    )
    if short_follow_up:
        return "relevant", ""

    return "blocked", REFUSAL_REPLY


# ---------------------------------------------------------------------------
# Scope check: what a consumer (not an admin) may ask about
# ---------------------------------------------------------------------------

_AGGREGATE_RE = re.compile(
    r"\b(all|every|each|other|another|everyone|everybody|total|how\s+many)\s+(number\s+of\s+)?(the\s+)?(other\s+)?"
    r"(consumers?|customers?|users?|dtrs?|transformers?|plants?|people|accounts?|meters?)\b|"
    r"\b(neighbou?rs?|someone\s+else|somebody\s+else|other\s+people|other\s+consumers|everyone|everybody)\b|"
    r"\b(list|show|compare)\b.{0,30}\b(consumers|customers|users|dtrs|transformers|plants)\b",
    re.I,
)

_PERSON_ID_RE = re.compile(r"\b(72\d{5}|HT\d{4}|UK\d{7}|SM\d{7})\b", re.I)
_DTR_ID_RE = re.compile(r"\bDTR[-_ ]?(\d+)\b", re.I)


def _own_ids(user):
    values = [user.consumer_ref, user.ukscno, user.meter_sno]
    return {str(v).upper() for v in values if v}


def check_scope(text, user):
    """
    Returns None if the question stays within the user's own data, otherwise the refusal to show.
    Admins are never restricted.
    """
    if user.is_admin:
        return None

    own = f"your account ({user.display_name}, number {user.consumer_ref})"
    refusal = (f"I can only share details for {own}. I can't give out other consumers' "
               "information or system-wide figures. Ask me about your own consumption, "
               "power factor or load and I'll work it out.")

    if _AGGREGATE_RE.search(text):
        return refusal

    for found in _PERSON_ID_RE.findall(text):
        if found.upper() not in _own_ids(user):
            return refusal

    for digits in _DTR_ID_RE.findall(text):
        if not user.dtr_code or f"DTR-{digits}" != user.dtr_code.upper():
            return refusal

    own_words = set(_words(user.display_name))
    other_names = (set(_words(text)) & _name_tokens) - own_words
    if other_names:
        return refusal

    return None


# ---------------------------------------------------------------------------
# SQL validation
# ---------------------------------------------------------------------------

_LITERAL_OR_COMMENT = re.compile(r"('(?:[^']|'')*')|--[^\n]*|/\*.*?\*/", re.S)
_LITERAL = re.compile(r"'(?:[^']|'')*'")

_BLOCKED = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|"
    r"GRANT|REVOKE|EXEC|EXECUTE|LOAD_EXTENSION)\b",
    re.I,
)
_TABLE_REF = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w.]*)", re.I)


def _drop_comments(sql):
    # keep string literals untouched, replace comments with a space
    return _LITERAL_OR_COMMENT.sub(lambda m: m.group(1) if m.group(1) else " ", sql)


def validate_sql(sql, allowed_tables=None):
    """
    Check a model-written query and return a cleaned version for SQLite.
    Raises GuardrailError with a readable reason if the query isn't allowed.
    allowed_tables limits which tables may be used (defaults to all of them).
    """
    if not sql or not sql.strip():
        raise GuardrailError("Empty query.")

    allowed = [t.lower() for t in (allowed_tables if allowed_tables is not None else TABLE_NAMES)]
    cleaned = _drop_comments(sql).strip().rstrip(";").strip()

    # everything below is checked on a copy with string contents blanked out,
    # so a value like 'update' inside quotes doesn't trigger a false alarm
    scrubbed = _LITERAL.sub("''", cleaned)

    if ";" in scrubbed:
        raise GuardrailError("Only one SQL statement is allowed per call.")

    first_word = scrubbed.split(None, 1)[0].upper() if scrubbed else ""
    if first_word not in ("SELECT", "WITH"):
        raise GuardrailError("Only read-only SELECT queries are allowed.")

    hit = _BLOCKED.search(scrubbed)
    if hit:
        raise GuardrailError(f"Blocked keyword '{hit.group(1).upper()}'. This assistant is read-only.")

    # SQLite doesn't know the epdatalake schema prefix or ILIKE, so translate
    cleaned = re.sub(r"\bepdatalake\.", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bILIKE\b", "LIKE", cleaned, flags=re.I)

    # reject tables we don't have, or that this user may not use, with a clear reason
    ctes = {c.lower() for c in re.findall(r"\b([A-Za-z_]\w*)\s+AS\s*\(", cleaned, re.I)}
    for table in _TABLE_REF.findall(_LITERAL.sub("''", cleaned)):
        name = table.split(".")[-1].lower()
        if name in ctes or name in allowed:
            continue
        if name in TABLE_NAMES:
            raise GuardrailError(f"Table '{table}' isn't available to your account.")
        raise GuardrailError(
            f"Table '{table}' isn't available in this database. "
            f"Available tables: {', '.join(t for t in TABLE_NAMES if t in allowed)}."
        )

    return cleaned


# ---------------------------------------------------------------------------
# Output side
# ---------------------------------------------------------------------------

def _mask_phone(value):
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 6:
        return value
    return "*" * (len(digits) - 4) + digits[-4:]


def _clean_cell(column, value):
    if value is None or isinstance(value, (int, float)):
        return value
    if isinstance(value, bytes):
        return "<binary>"
    text = _CONTROL_RE.sub("", str(value))
    text = _TAG_RE.sub("", text)
    text = _ANY_TAG_RE.sub("", text)
    if "MOBILE" in column.upper() or "PHONE" in column.upper():
        text = _mask_phone(text)
    return text[:300]


def sanitize_rows(rows):
    return [{col: _clean_cell(col, val) for col, val in row.items()} for row in rows]


_ACTIVE_CONTENT = re.compile(r"<\s*/?\s*(script|style|iframe|object|embed)[^>]*>|javascript:", re.I)


def clean_output(text):
    return _ACTIVE_CONTENT.sub("", text or "").strip()


def empty_result_note():
    return (
        "The query ran fine but matched no rows. Identifiers such as DTR codes and "
        "consumer numbers must match exactly, and some consumers have no smart meter. "
        "Check the spelling, loosen the filter, or ask me to list valid values first."
    )
