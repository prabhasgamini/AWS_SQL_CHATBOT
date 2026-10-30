"""
Data-level access control. This is what actually keeps one consumer away from another's data.

The model writes SQL, so we can't rely on it (or on the person typing) to stay inside their own
rows. Instead of filtering what they ask for, we control what exists on their connection:

  * A consumer's query runs on a throwaway IN-MEMORY database that is filled with only that
    consumer's rows (their master record, their meter, their readings, their transformer).
    Other people's data is not on that connection at all, so no clever SQL (UNION, CTEs,
    `main.` prefixes, subqueries) can reach it. Tables a consumer shouldn't see, such as the
    DTR meter readings, aren't created, so the query just fails with "no such table".
  * A SQLite authorizer adds a second layer: SELECT only, no PRAGMA / ATTACH, no schema tables.
  * Admins query the real file, still read-only and still behind the authorizer.

(An earlier version used per-user views over the real tables. A CTE with a matching name got
around it in testing, which is why the rows are physically separated now.)
"""

import sqlite3
from datetime import datetime

from context import UserContext
from database import DB_PATH, TABLE_NAMES

# sqlite authorizer action codes and return values (numbers so this works on any Python 3.10+)
_SQLITE_OK, _SQLITE_DENY = 0, 1
_READ, _SELECT, _FUNCTION, _RECURSIVE = 20, 21, 31, 33

_BAD_FUNCTIONS = {"load_extension", "zeroblob", "randomblob", "readfile", "writefile", "edit"}

LT_USER_TABLES = [
    "lt_consumer_master", "consumer_mapping", "dtr_master", "smart_meters_install_m",
    "t_blp_sp", "t_blp_tp", "lt_meter_data", "lt_category_master",
]
HT_USER_TABLES = ["ht_consumer_master", "lt_category_master"]


class AccessDenied(Exception):
    """The signed-in user asked for something outside their own data."""


def allowed_tables(user):
    if user.is_admin:
        return list(TABLE_NAMES)
    return list(LT_USER_TABLES if user.consumer_type == "LT" else HT_USER_TABLES)


def _row_filters(user):
    """table name -> (WHERE clause, parameters) selecting only this user's rows."""
    if user.consumer_type == "HT":
        return {
            "ht_consumer_master": ("CONS_NUMBER = ?", (user.consumer_ref,)),
            "lt_category_master": ("1 = 1", ()),
        }

    if user.meter_sno:
        meter = ("msn = ?", (user.meter_sno,))
    else:
        meter = ("1 = 0", ())          # non-smart: no interval readings exist for them
    return {
        "lt_consumer_master": ("SCNO = ?", (user.consumer_ref,)),
        "consumer_mapping": ("CONS_NO = ?", (user.consumer_ref,)),
        "dtr_master": ("DTR_STRUCTURE_CODE = ?", (user.dtr_code,)),
        "smart_meters_install_m": ("UKSCNO = ?", (user.ukscno,)),
        "t_blp_sp": meter,
        "t_blp_tp": meter,
        "lt_meter_data": ("CONS_NUMBER = ?", (user.cons_id,)),
        "lt_category_master": ("1 = 1", ()),
    }


def _make_authorizer():
    def authorizer(action, arg1, arg2, db_name, source):
        if action in (_SELECT, _RECURSIVE):
            return _SQLITE_OK
        if action == _FUNCTION:
            return _SQLITE_DENY if (arg2 or "").lower() in _BAD_FUNCTIONS else _SQLITE_OK
        if action == _READ:
            return _SQLITE_DENY if (arg1 or "").lower().startswith("sqlite_") else _SQLITE_OK
        return _SQLITE_DENY            # writes, ATTACH, PRAGMA, everything else
    return authorizer


def trusted_connection():
    """Plain read-only connection with no row filtering. Only for our own code, never for model SQL."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _copy_user_rows(user):
    """Build an in-memory database that holds only this user's rows."""
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    source = trusted_connection()
    try:
        for table, (where, params) in _row_filters(user).items():
            ddl = source.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                                 (table,)).fetchone()[0]
            mem.execute(ddl)
            rows = source.execute(f"SELECT * FROM {table} WHERE {where}", params).fetchall()
            if rows:
                marks = ",".join("?" * len(rows[0]))
                mem.executemany(f"INSERT INTO {table} VALUES ({marks})", [tuple(r) for r in rows])
        mem.commit()
    finally:
        source.close()
    return mem


def open_connection(user):
    """Connection for running model-written SQL on behalf of this user."""
    if user is None:
        raise AccessDenied("Not signed in.")

    conn = trusted_connection() if user.is_admin else _copy_user_rows(user)
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(_make_authorizer())          # last, so our own setup isn't blocked
    return conn


def run_select(sql, user, limit=200, timeout_s=5):
    """
    Run an already-validated SELECT as this user.
    Returns (columns, rows, truncated). Rows are plain dicts.
    """
    conn = open_connection(user)
    started = datetime.now()

    def _too_slow():
        # returning non-zero makes sqlite abort the statement
        return 1 if (datetime.now() - started).total_seconds() > timeout_s else 0

    conn.set_progress_handler(_too_slow, 10000)
    try:
        cur = conn.execute(sql)
        fetched = cur.fetchmany(limit + 1)
        columns = [c[0] for c in cur.description] if cur.description else []
        truncated = len(fetched) > limit
        return columns, [dict(r) for r in fetched[:limit]], truncated
    finally:
        conn.close()


def build_user_context(username, role, display_name, consumer_type, consumer_ref):
    """Look up everything the tools need to know about a signed-in person."""
    if role == "admin":
        return UserContext(username=username, role="admin", display_name=display_name)

    conn = trusted_connection()
    try:
        if consumer_type == "HT":
            row = conn.execute("SELECT ID, NAME FROM ht_consumer_master WHERE CONS_NUMBER = ?",
                               (consumer_ref,)).fetchone()
            if row is None:
                return None
            return UserContext(username=username, role="user", display_name=row["NAME"],
                               consumer_type="HT", consumer_ref=consumer_ref, cons_id=row["ID"])

        row = conn.execute(
            "SELECT c.ID, c.UKSCNO, c.NAME, c.PHASE, m.DTR_STRUC_CODE, s.MTR_SNO "
            "FROM lt_consumer_master c "
            "LEFT JOIN consumer_mapping m ON m.CONS_NO = c.SCNO "
            "LEFT JOIN smart_meters_install_m s ON s.UKSCNO = c.UKSCNO "
            "WHERE c.SCNO = ?", (consumer_ref,)).fetchone()
        if row is None:
            return None
        return UserContext(username=username, role="user", display_name=row["NAME"],
                           consumer_type="LT", consumer_ref=consumer_ref, cons_id=row["ID"],
                           ukscno=row["UKSCNO"], dtr_code=row["DTR_STRUC_CODE"],
                           meter_sno=row["MTR_SNO"], phase=row["PHASE"])
    finally:
        conn.close()
