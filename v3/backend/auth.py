"""
Login accounts and sessions.

Accounts live in their own SQLite file (app_auth.db), separate from the utility data, so the
SQL the model writes can never reach password hashes.

  * Passwords are stored as salted PBKDF2-SHA256 hashes, never as text.
  * A login creates a random session token. Only its SHA-256 hash is stored.
  * Repeated wrong passwords for one username pause that username for a few minutes.

Command line:
    python auth.py --list                          show usernames and roles
    python auth.py --set-password USER NEW_PASS    change a password
    python auth.py --reset                         delete app_auth.db (rebuilt on next start)
"""

import argparse
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import access
import config


def _utc_now():
    # naive UTC, kept naive so the stored ISO strings stay comparable
    return datetime.now(timezone.utc).replace(tzinfo=None)


AUTH_DB_PATH = Path(__file__).parent / "app_auth.db"
PBKDF2_ROUNDS = 100_000

_failures = {}                  # username -> list of recent failure timestamps
_failures_lock = threading.Lock()


class AuthError(Exception):
    """Wrong credentials, expired session and so on. The message is safe to show."""


class LockedOut(AuthError):
    pass


def _connect():
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS).hex()


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _add_user(conn, username, password, role, display_name, consumer_type, consumer_ref):
    salt = secrets.token_bytes(16)
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password_hash, salt, role, display_name, "
        "consumer_type, consumer_ref) VALUES (?,?,?,?,?,?,?)",
        (username, _hash(password, salt), salt.hex(), role, display_name, consumer_type, consumer_ref),
    )


def init_auth():
    """Create the accounts file if needed and make sure every consumer has an account."""
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                username       TEXT PRIMARY KEY,
                password_hash  TEXT NOT NULL,
                salt           TEXT NOT NULL,
                role           TEXT NOT NULL CHECK (role IN ('admin', 'user')),
                display_name   TEXT NOT NULL,
                consumer_type  TEXT,
                consumer_ref   TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash  TEXT PRIMARY KEY,
                username    TEXT NOT NULL REFERENCES users (username) ON DELETE CASCADE,
                expires_at  TEXT NOT NULL
            );
        """)
        _add_user(conn, "admin", config.ADMIN_PASSWORD, "admin", "Administrator", None, None)

        data = access.trusted_connection()
        try:
            lt = data.execute("SELECT SCNO, NAME FROM lt_consumer_master").fetchall()
            ht = data.execute("SELECT CONS_NUMBER, NAME FROM ht_consumer_master").fetchall()
        finally:
            data.close()

        existing = {r["username"] for r in conn.execute("SELECT username FROM users")}
        for row in lt:
            if row["SCNO"] not in existing:
                _add_user(conn, row["SCNO"], config.USER_PASSWORD_PREFIX + row["SCNO"],
                          "user", row["NAME"], "LT", row["SCNO"])
        for row in ht:
            if row["CONS_NUMBER"] not in existing:
                _add_user(conn, row["CONS_NUMBER"], config.USER_PASSWORD_PREFIX + row["CONS_NUMBER"],
                          "user", row["NAME"], "HT", row["CONS_NUMBER"])

        # drop accounts whose consumer no longer exists (for example after rebuilding the data)
        valid = {r["SCNO"] for r in lt} | {r["CONS_NUMBER"] for r in ht} | {"admin"}
        for name in existing - valid:
            conn.execute("DELETE FROM users WHERE username = ?", (name,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Login attempts
# ---------------------------------------------------------------------------

def _recent_failures(username):
    cutoff = time.time() - config.LOCKOUT_MINUTES * 60
    with _failures_lock:
        kept = [t for t in _failures.get(username, []) if t > cutoff]
        _failures[username] = kept
        return len(kept)


def _record_failure(username):
    with _failures_lock:
        _failures.setdefault(username, []).append(time.time())


def clear_failures():
    with _failures_lock:
        _failures.clear()


# ---------------------------------------------------------------------------
# Login, sessions
# ---------------------------------------------------------------------------

_DUMMY_SALT = bytes(16)


def login(username, password):
    """Check credentials. Returns (token, UserContext). Raises AuthError if they are wrong."""
    username = (username or "").strip()
    password = password or ""

    if _recent_failures(username) >= config.MAX_FAILED_LOGINS:
        raise LockedOut(f"Too many failed attempts. Try again in {config.LOCKOUT_MINUTES} minutes.")

    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

        # hash even for unknown usernames, so the response time doesn't reveal which exist
        salt = bytes.fromhex(row["salt"]) if row else _DUMMY_SALT
        candidate = _hash(password, salt)
        ok = row is not None and hmac.compare_digest(candidate, row["password_hash"])

        if not ok:
            _record_failure(username)
            raise AuthError("Invalid username or password.")

        user = access.build_user_context(row["username"], row["role"], row["display_name"],
                                         row["consumer_type"], row["consumer_ref"])
        if user is None:
            raise AuthError("This account is no longer linked to a consumer. Contact an administrator.")

        token = secrets.token_urlsafe(32)
        expires = _utc_now() + timedelta(hours=config.SESSION_HOURS)
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_utc_now().isoformat(),))
        conn.execute("INSERT INTO sessions VALUES (?,?,?)",
                     (_hash_token(token), username, expires.isoformat()))
        conn.commit()
        with _failures_lock:
            _failures.pop(username, None)
        return token, user
    finally:
        conn.close()


def user_from_token(token):
    """The UserContext for a valid, unexpired token, otherwise None."""
    if not token:
        return None
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT u.* , s.expires_at FROM sessions s JOIN users u ON u.username = s.username "
            "WHERE s.token_hash = ?", (_hash_token(token),)).fetchone()
        if row is None or row["expires_at"] < _utc_now().isoformat():
            return None
        return access.build_user_context(row["username"], row["role"], row["display_name"],
                                         row["consumer_type"], row["consumer_ref"])
    finally:
        conn.close()


def logout(token):
    if not token:
        return
    conn = _connect()
    try:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))
        conn.commit()
    finally:
        conn.close()


def set_password(username, new_password):
    conn = _connect()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone() is None:
            raise AuthError(f"No such user: {username}")
        salt = secrets.token_bytes(16)
        conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                     (_hash(new_password, salt), salt.hex(), username))
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))   # sign them out everywhere
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage login accounts")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--set-password", nargs=2, metavar=("USER", "PASSWORD"))
    parser.add_argument("--reset", action="store_true", help="delete app_auth.db")
    args = parser.parse_args()

    if args.reset and AUTH_DB_PATH.exists():
        AUTH_DB_PATH.unlink()
        print("Deleted", AUTH_DB_PATH)

    init_auth()
    if args.set_password:
        set_password(*args.set_password)
        print("Password updated for", args.set_password[0])
    if args.list:
        conn = _connect()
        for r in conn.execute("SELECT username, role, display_name FROM users ORDER BY role, username"):
            print(f"{r['username']:<12}{r['role']:<7}{r['display_name']}")
        conn.close()
