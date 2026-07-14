import hashlib
import os
import shutil
import sqlite3
import sys
import threading
import time
import getpass
import socket
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import requests # type: ignore
from flask import Flask, jsonify, request, send_from_directory, render_template_string # type: ignore
from flask_cors import CORS # type: ignore

# ===== Supabase Auth (shared accounts across every install - desktop & mobile) =====
# The anon/publishable key is safe to ship in client apps by design - Supabase
# enforces access control server-side, not by hiding this key. Never put the
# service_role key or DB password here; those grant unrestricted admin access
# and must only ever live on a server you control, never in distributed code.
SUPABASE_URL = "https://goqdtnudjcomwvqbwidt.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdvcWR0bnVkamNvbXd2cWJ3aWR0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODMxNTE0NjgsImV4cCI6MjA5ODcyNzQ2OH0.3Ih5Dst0wnVmJNxaUZmjpVEW1j1EoxskTNgawh6unhM"

# ===== Secure Cloud Recovery Module: Google Drive =====
# The client secret for a "Desktop app" OAuth client is not treated as
# confidential by Google's own security model (installed apps can't keep
# secrets truly secret since they ship in the binary) - this is a
# different, lower-stakes category than the Supabase DB password, and
# embedding it here matches Google's documented pattern for this client type.
def _load_secret(placeholder_name: str, ci_placeholder: str) -> str:
    """Resolves a secret three ways, in order:
    1. The CI build step replaces __TOKEN__ with the real value from
       GitHub's encrypted Actions secrets, baked into the compiled .exe -
       so if this still says "__..._​_" we're not running a CI build.
    2. A local, git-ignored local_secrets.py (see local_secrets.py.example)
       - for testing on your own machine without needing a CI build.
    3. Empty string, so the app still runs (with that one feature disabled)
       instead of crashing when a key just isn't configured yet.
    """
    if not ci_placeholder.startswith("__"):
        return ci_placeholder  # already replaced by the CI build step
    try:
        import local_secrets
        return getattr(local_secrets, placeholder_name, "")
    except ImportError:
        return ""


GOOGLE_CLIENT_ID = _load_secret("GOOGLE_CLIENT_ID", "__GOOGLE_CLIENT_ID__")
GOOGLE_CLIENT_SECRET = _load_secret("GOOGLE_CLIENT_SECRET", "__GOOGLE_CLIENT_SECRET__")
GOOGLE_DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

# ===== Secure Cloud Recovery Module: Paystack =====
# PAYSTACK_SECRET_KEY must NEVER be sent to the frontend/JS - it's only
# ever used here, server-side, exactly like the Supabase DB password
# situation earlier. PAYSTACK_PUBLIC_KEY is safe to expose if ever needed
# client-side, but our flow doesn't require the frontend to see either one.
PAYSTACK_SECRET_KEY = _load_secret("PAYSTACK_SECRET_KEY", "__PAYSTACK_SECRET_KEY__")
PAYSTACK_PUBLIC_KEY = _load_secret("PAYSTACK_PUBLIC_KEY", "__PAYSTACK_PUBLIC_KEY__")

# Paystack test keys only process test-mode payments (no real money moves)
# until they're swapped for live keys later.
SUBSCRIPTION_PLANS = {
    "2month": {"label": "2 Months", "amount_usd": 5, "days": 60},
    "5month": {"label": "5 Months", "amount_usd": 10, "days": 150},
    "1year": {"label": "1 Year", "amount_usd": 25, "days": 365},
}

# The administrator gets permanent premium access to all cloud features,
# per the module spec - no subscription required.
ADMIN_EMAIL = "timothymartinluther54@gmail.com"


def supabase_signup(email: str, password: str, name: str) -> tuple[bool, dict]:
    """Returns (success, data). data is the parsed JSON body either way."""
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/signup",
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": password, "data": {"name": name}},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
        print(f"[auth] signup {email} -> HTTP {resp.status_code}: {body}", flush=True)
        return resp.ok, body
    except requests.RequestException as exc:
        print(f"[auth] signup {email} -> EXCEPTION: {exc!r}", flush=True)
        return False, {"message": f"Could not reach the auth server: {exc}"}


def supabase_login(email: str, password: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
        print(f"[auth] login {email} -> HTTP {resp.status_code}: {body}", flush=True)
        return resp.ok, body
    except requests.RequestException as exc:
        print(f"[auth] login {email} -> EXCEPTION: {exc!r}", flush=True)
        return False, {"message": f"Could not reach the auth server: {exc}"}


def supabase_recover(email: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/recover",
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": email},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
        print(f"[auth] recover {email} -> HTTP {resp.status_code}: {body}", flush=True)
        return resp.ok, body
    except requests.RequestException as exc:
        print(f"[auth] recover {email} -> EXCEPTION: {exc!r}", flush=True)
        return False, {"message": f"Could not reach the auth server: {exc}"}


def supabase_verify_signup(email: str, token: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/verify",
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"type": "signup", "email": email, "token": token},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
        print(f"[auth] verify-signup {email} -> HTTP {resp.status_code}: {body}", flush=True)
        return resp.ok, body
    except requests.RequestException as exc:
        print(f"[auth] verify-signup {email} -> EXCEPTION: {exc!r}", flush=True)
        return False, {"message": f"Could not reach the auth server: {exc}"}


def supabase_verify_recovery(email: str, token: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/verify",
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"type": "recovery", "email": email, "token": token},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
        print(f"[auth] verify-recovery {email} -> HTTP {resp.status_code}: {body}", flush=True)
        return resp.ok, body
    except requests.RequestException as exc:
        print(f"[auth] verify-recovery {email} -> EXCEPTION: {exc!r}", flush=True)
        return False, {"message": f"Could not reach the auth server: {exc}"}


def supabase_update_password(access_token: str, new_password: str) -> tuple[bool, dict]:
    try:
        resp = requests.put(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"password": new_password},
            timeout=15,
        )
        body = resp.json() if resp.content else {}
        print(f"[auth] update-password -> HTTP {resp.status_code}: {body}", flush=True)
        return resp.ok, body
    except requests.RequestException as exc:
        print(f"[auth] update-password -> EXCEPTION: {exc!r}", flush=True)
        return False, {"message": f"Could not reach the auth server: {exc}"}


def supabase_error_message(body: dict) -> str:
    msg = body.get("error_description") or body.get("msg") or body.get("message") or body.get("error") or ""
    lowered = msg.lower()
    if "already registered" in lowered or "already exists" in lowered:
        return "An account with this email already exists."
    if "confirm" in lowered and ("email" in lowered or "confirmed" in lowered):
        return "Please verify your email before logging in - check your inbox for the confirmation link."
    if "invalid login credentials" in lowered:
        return "Invalid email or password."
    if "password" in lowered and ("least" in lowered or "short" in lowered or "weak" in lowered):
        return msg or "Password does not meet requirements (minimum 6 characters)."
    return msg or "Something went wrong. Please try again."


# ===== Secure Cloud Recovery Module =====

def get_backup_encryption_key(user_id: str) -> Optional[bytes]:
    """Fetches the user's per-account encryption key from Supabase
    user_metadata. Deliberately NOT derived from their password - if it
    were, resetting the password (a feature we already built) would
    permanently destroy access to every encrypted backup with no way back.
    Generating and storing a separate random key avoids that trap.
    """
    from cryptography.fernet import Fernet

    token_row = get_cloud_token(user_id, "supabase")
    if not token_row:
        return None

    try:
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token_row['access_token']}"},
            timeout=15,
        )
        if not resp.ok:
            return None
        user_data = resp.json()
        existing_key = (user_data.get("user_metadata") or {}).get("backup_key")
        if existing_key:
            return existing_key.encode("utf-8")

        # No key yet - generate one and persist it to this account.
        new_key = Fernet.generate_key()
        put_resp = requests.put(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {token_row['access_token']}",
                "Content-Type": "application/json",
            },
            json={"data": {"backup_key": new_key.decode("utf-8")}},
            timeout=15,
        )
        if not put_resp.ok:
            print(f"[cloud] failed to persist new backup key: {put_resp.text}", flush=True)
            return None
        return new_key
    except requests.RequestException as exc:
        print(f"[cloud] get_backup_encryption_key error: {exc!r}", flush=True)
        return None


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(key).encrypt(data)


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(key).decrypt(data)


# ----- Google Drive -----

def google_auth_url(redirect_uri: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": GOOGLE_DRIVE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def google_exchange_code(code: str, redirect_uri: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )
        return resp.ok, resp.json()
    except requests.RequestException as exc:
        return False, {"error": str(exc)}


def supabase_refresh_token(refresh_token: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "refresh_token"},
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"refresh_token": refresh_token},
            timeout=15,
        )
        return resp.ok, resp.json()
    except requests.RequestException as exc:
        return False, {"message": str(exc)}


def get_valid_supabase_token(user_id: str) -> Optional[str]:
    token_row = get_cloud_token(user_id, "supabase")
    if not token_row:
        return None

    expires_at = token_row.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) > datetime.utcnow():
                return token_row["access_token"]
        except ValueError:
            pass

    if not token_row.get("refresh_token"):
        return None

    ok, body = supabase_refresh_token(token_row["refresh_token"])
    if not ok:
        print(f"[transfer] Supabase token refresh failed: {body}", flush=True)
        return None

    save_cloud_token(user_id, "supabase", body["access_token"], body.get("refresh_token"), body.get("expires_in"))
    return body["access_token"]


def google_refresh_token(refresh_token: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        return resp.ok, resp.json()
    except requests.RequestException as exc:
        return False, {"error": str(exc)}


def get_valid_google_token(user_id: str) -> Optional[str]:
    """Returns a usable Google access token, transparently refreshing it
    first if it has expired."""
    token_row = get_cloud_token(user_id, "google")
    if not token_row:
        return None

    expires_at = token_row.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) > datetime.utcnow():
                return token_row["access_token"]
        except ValueError:
            pass

    if not token_row.get("refresh_token"):
        return None

    ok, body = google_refresh_token(token_row["refresh_token"])
    if not ok:
        print(f"[cloud] Google token refresh failed: {body}", flush=True)
        return None

    save_cloud_token(user_id, "google", body["access_token"], token_row.get("refresh_token"), body.get("expires_in"))
    return body["access_token"]


def google_drive_upload(access_token: str, filename: str, encrypted_bytes: bytes) -> tuple[bool, dict]:
    import json as json_lib
    boundary = "fims_cloud_boundary"
    metadata = json_lib.dumps({"name": filename, "parents": []})
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{metadata}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + encrypted_bytes + f"\r\n--{boundary}--".encode("utf-8")

    try:
        resp = requests.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
            data=body,
            timeout=60,
        )
        return resp.ok, resp.json()
    except requests.RequestException as exc:
        return False, {"error": str(exc)}


def google_drive_download(access_token: str, file_id: str) -> tuple[bool, bytes]:
    try:
        resp = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=60,
        )
        return resp.ok, resp.content
    except requests.RequestException as exc:
        return False, str(exc).encode("utf-8")


def google_drive_delete(access_token: str, file_id: str) -> bool:
    try:
        resp = requests.delete(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        return resp.ok
    except requests.RequestException:
        return False


def google_drive_storage_quota(access_token: str) -> tuple[bool, dict]:
    try:
        resp = requests.get(
            "https://www.googleapis.com/drive/v3/about?fields=storageQuota",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        if not resp.ok:
            return False, {}
        quota = resp.json().get("storageQuota", {})
        return True, {
            "used": int(quota.get("usage", 0)),
            "limit": int(quota["limit"]) if quota.get("limit") else None,  # None = unlimited plan
        }
    except (requests.RequestException, ValueError, KeyError) as exc:
        return False, {}


# ----- Paystack -----

def paystack_initialize(email: str, amount_usd: float, plan_key: str, callback_url: str) -> tuple[bool, dict]:
    try:
        resp = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}", "Content-Type": "application/json"},
            json={
                "email": email,
                "amount": int(amount_usd * 100),  # smallest currency unit (cents)
                "currency": "USD",
                "callback_url": callback_url,
                "metadata": {"plan": plan_key},
            },
            timeout=15,
        )
        return resp.ok, resp.json()
    except requests.RequestException as exc:
        return False, {"message": str(exc)}


def paystack_verify(reference: str) -> tuple[bool, dict]:
    try:
        resp = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
            timeout=15,
        )
        return resp.ok, resp.json()
    except requests.RequestException as exc:
        return False, {"message": str(exc)}


def log_case(user_id: str, file_id, file_name: str, action_type: str) -> None:
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO case_log (user_id, file_id, file_name, action_type, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, file_id, file_name, action_type, now_iso()),
    )
    conn.commit()
    conn.close()


def is_subscription_active(user_id: str, email: str = None) -> bool:
    if email and email.lower() == ADMIN_EMAIL.lower():
        return True  # Admin has permanent access, per spec

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or row["status"] != "active" or not row["expires_at"]:
        return False
    try:
        return datetime.fromisoformat(row["expires_at"]) > datetime.utcnow()
    except ValueError:
        return False


# ===== Secure File Transfer System =====

def postgrest_request(method: str, table: str, access_token: str, **kwargs) -> tuple[bool, Any]:
    """Calls Supabase's auto-generated REST API for a table, using the
    caller's own JWT (not just the anon key) so row-level security is
    enforced as that specific user - never as an all-access admin."""
    try:
        resp = requests.request(
            method,
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Prefer": kwargs.pop("prefer", "return=representation"),
            },
            timeout=15,
            **kwargs,
        )
        body = resp.json() if resp.content else None
        return resp.ok, body
    except requests.RequestException as exc:
        return False, {"message": str(exc)}


def storage_upload(access_token: str, path: str, data: bytes) -> tuple[bool, Any]:
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/fims-transfer/{path}",
            headers={
                "apikey": SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/octet-stream",
            },
            data=data,
            timeout=60,
        )
        return resp.ok, (resp.json() if resp.content else None)
    except requests.RequestException as exc:
        return False, {"message": str(exc)}


def storage_download(access_token: str, path: str) -> tuple[bool, bytes]:
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/storage/v1/object/fims-transfer/{path}",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {access_token}"},
            timeout=60,
        )
        return resp.ok, resp.content
    except requests.RequestException as exc:
        return False, str(exc).encode("utf-8")


def storage_delete(access_token: str, path: str) -> bool:
    try:
        resp = requests.delete(
            f"{SUPABASE_URL}/storage/v1/object/fims-transfer/{path}",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        return resp.ok
    except requests.RequestException:
        return False


def generate_user_code() -> str:
    import secrets
    import string
    alphabet = string.ascii_uppercase + string.digits
    part1 = "".join(secrets.choice(alphabet) for _ in range(4))
    part2 = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"FIMS-{part1}-{part2}"


def ensure_user_code(user_id: str, access_token: str, display_name: str) -> Optional[str]:
    ok, rows = postgrest_request(
        "GET", "fims_directory", access_token,
        params={"user_id": f"eq.{user_id}", "select": "user_code"},
    )
    if ok and rows:
        return rows[0]["user_code"]

    for _ in range(5):  # retry on the astronomically unlikely code collision
        code = generate_user_code()
        ok, body = postgrest_request(
            "POST", "fims_directory", access_token,
            json={"user_code": code, "user_id": user_id, "display_name": display_name},
        )
        if ok:
            return code
    return None


def lookup_user_by_code(access_token: str, code: str) -> Optional[dict]:
    ok, rows = postgrest_request(
        "GET", "fims_directory", access_token,
        params={"user_code": f"eq.{code.strip().upper()}", "select": "user_id,display_name"},
    )
    if ok and rows:
        return rows[0]
    return None


def resource_path() -> Path:
    """Directory containing bundled read-only assets (index.html, script.js, style.css).

    When run from source this is the app.py folder. When packaged with
    PyInstaller (onefile build) it is the temporary extraction folder
    (sys._MEIPASS), which is read-only and wiped between runs.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def app_data_dir() -> Path:
    """Writable per-user directory for the database and monitored uploads.

    Never write inside the install/bundle folder: on Windows that is
    typically Program Files (read-only for standard users) and, when
    frozen, is a temp extraction folder that doesn't persist anyway.
    """
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    data_dir = base / "IntegrityMonitor"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


RESOURCE_DIR = resource_path()
APP_DATA_DIR = app_data_dir()

app = Flask(__name__, static_folder=str(RESOURCE_DIR), static_url_path='')
CORS(app)

BASE_DIR = RESOURCE_DIR
DB_PATH = APP_DATA_DIR / "integrity_monitor.db"
UPLOAD_DIR = APP_DATA_DIR / "uploads"
BACKUP_DIR = APP_DATA_DIR / "backups"  # last known-good bytes per monitored file, for Reverse
LEGACY_DB_PATH = BASE_DIR / "integrity_monitor.db"


def backup_path_for(file_id: int) -> Path:
    return BACKUP_DIR / f"{file_id}.bin"


_storage_initialized = False
_storage_lock = threading.Lock()


def _hide_windows_path(path: Path) -> None:
    """Set the Windows hidden attribute without spawning a console window.

    The previous implementation used os.system("attrib +h ..."), which
    launches cmd.exe. In a windowed (non-console) build that flashes a
    visible console window every time it runs - and it was running on
    every database connection, causing repeated window flicker.
    """
    if os.name != 'nt' or not path.exists():
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def ensure_secure_storage() -> None:
    global _storage_initialized

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Everything below (legacy migration + hiding attributes) only needs to
    # happen once per process, not on every database connection.
    with _storage_lock:
        if _storage_initialized:
            return
        _storage_initialized = True

    if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        backup_path = DB_PATH.parent / "integrity_monitor.db.backup"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(LEGACY_DB_PATH, backup_path)
        except Exception:
            pass
        try:
            os.replace(LEGACY_DB_PATH, DB_PATH)
        except PermissionError:
            try:
                shutil.copy2(LEGACY_DB_PATH, DB_PATH)
                LEGACY_DB_PATH.unlink()
            except Exception:
                pass

    _hide_windows_path(DB_PATH.parent)
    _hide_windows_path(DB_PATH)
    _hide_windows_path(LEGACY_DB_PATH)

ensure_secure_storage()

HOST = os.environ.get('HOST', '127.0.0.1')
PORT = int(os.environ.get('PORT', 5000))


class Database:
    @staticmethod
    def get_connection():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn


def migrate_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()

    files_cols = {row[1] for row in cursor.execute("PRAGMA table_info(files)").fetchall()}
    if "name" not in files_cols:
        if "file_name" in files_cols:
            cursor.execute("ALTER TABLE files RENAME COLUMN file_name TO name")
        else:
            cursor.execute("ALTER TABLE files ADD COLUMN name TEXT")
    if "path" not in files_cols:
        if "file_path" in files_cols:
            cursor.execute("ALTER TABLE files RENAME COLUMN file_path TO path")
        else:
            cursor.execute("ALTER TABLE files ADD COLUMN path TEXT")
    if "trusted_hash" not in files_cols:
        cursor.execute("ALTER TABLE files ADD COLUMN trusted_hash TEXT")
    if "current_hash" not in files_cols:
        cursor.execute("ALTER TABLE files ADD COLUMN current_hash TEXT")
    if "status" not in files_cols:
        cursor.execute("ALTER TABLE files ADD COLUMN status TEXT DEFAULT 'monitoring'")
    if "last_checked" not in files_cols:
        cursor.execute("ALTER TABLE files ADD COLUMN last_checked TEXT")
    if "created_at" not in files_cols:
        cursor.execute("ALTER TABLE files ADD COLUMN created_at TEXT")
    if "uploaded_at" not in files_cols:
        cursor.execute("ALTER TABLE files ADD COLUMN uploaded_at TEXT")

    alerts_cols = {row[1] for row in cursor.execute("PRAGMA table_info(alerts)").fetchall()}
    if "old_hash" in alerts_cols or "alert_time" in alerts_cols or "previous_hash" not in alerts_cols or "timestamp" not in alerts_cols:
        # A previous run may have crashed mid-migration and left a stale
        # alerts_old table behind; clear it so the rename below can't collide.
        cursor.execute("DROP TABLE IF EXISTS alerts_old")
        cursor.execute("ALTER TABLE alerts RENAME TO alerts_old")

        # Don't assume the legacy table has any particular columns (older
        # schema versions varied) - only select ones that actually exist,
        # and default the rest. Referencing a missing column directly in
        # SQL raises OperationalError, which used to crash every request.
        legacy_cols = {row[1] for row in cursor.execute("PRAGMA table_info(alerts_old)").fetchall()}

        def col_or_default(name: str, default_sql: str) -> str:
            return name if name in legacy_cols else default_sql

        user_id_expr = col_or_default("user_id", "0")
        file_id_expr = col_or_default("file_id", "0")
        file_name_expr = col_or_default("file_name", "''")
        resolved_expr = col_or_default("resolved", "0")

        previous_hash_parts = [c for c in ("previous_hash", "old_hash") if c in legacy_cols]
        previous_hash_expr = f"COALESCE({', '.join(previous_hash_parts)}, '')" if previous_hash_parts else "''"

        new_hash_expr = "COALESCE(new_hash, '')" if "new_hash" in legacy_cols else "''"

        timestamp_parts = [c for c in ("timestamp", "alert_time") if c in legacy_cols]
        timestamp_expr = f"COALESCE({', '.join(timestamp_parts)}, '')" if timestamp_parts else "''"

        cursor.execute(
            """
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                file_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                new_hash TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                FOREIGN KEY(file_id) REFERENCES files(id)
            )
            """
        )
        cursor.execute(
            f"""
            INSERT INTO alerts (id, user_id, file_id, file_name, previous_hash, new_hash, timestamp, resolved)
            SELECT
                id,
                {user_id_expr},
                {file_id_expr},
                {file_name_expr},
                {previous_hash_expr},
                {new_hash_expr},
                {timestamp_expr},
                {resolved_expr}
            FROM alerts_old
            """
        )
        cursor.execute("DROP TABLE alerts_old")

    cursor.execute("UPDATE files SET current_hash = trusted_hash WHERE current_hash IS NULL AND trusted_hash IS NOT NULL")

    # Audit columns: who was logged into this machine, and whether they
    # connected remotely, at the moment tampering was detected.
    alerts_cols = {row[1] for row in cursor.execute("PRAGMA table_info(alerts)").fetchall()}
    if "os_username" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN os_username TEXT NOT NULL DEFAULT ''")
    if "hostname" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN hostname TEXT NOT NULL DEFAULT ''")
    if "session_type" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN session_type TEXT NOT NULL DEFAULT ''")
    if "remote_ip" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN remote_ip TEXT NOT NULL DEFAULT ''")
    if "resolution_type" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN resolution_type TEXT")
    if "resolved_at" not in alerts_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN resolved_at TEXT")

    files_cols_2 = {row[1] for row in cursor.execute("PRAGMA table_info(files)").fetchall()}
    if "locked" not in files_cols_2:
        cursor.execute("ALTER TABLE files ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")

    conn.commit()


def init_db():
    ensure_secure_storage()
    conn = Database.get_connection()
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            trusted_hash TEXT NOT NULL,
            current_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'monitoring',
            last_checked TEXT NOT NULL,
            created_at TEXT NOT NULL,
            uploaded_at TEXT
        );

        CREATE TABLE IF NOT EXISTS hash_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            hash_value TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            change_type TEXT NOT NULL,  -- 'initial', 'modified', 'restored'
            FOREIGN KEY(file_id) REFERENCES files(id)
        );

        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            file_id INTEGER NOT NULL,
            file_name TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            new_hash TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            resolved INTEGER DEFAULT 0,
            FOREIGN KEY(file_id) REFERENCES files(id)
        );

        CREATE TABLE IF NOT EXISTS cloud_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            provider TEXT NOT NULL,  -- 'supabase', 'google', 'onedrive', 's3'
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at TEXT,
            UNIQUE(user_id, provider)
        );

        CREATE TABLE IF NOT EXISTS cloud_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            original_name TEXT NOT NULL,
            original_path TEXT NOT NULL,
            provider TEXT NOT NULL,
            remote_file_id TEXT NOT NULL,
            trusted_hash TEXT NOT NULL,
            encrypted_size INTEGER,
            backed_up_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            email TEXT,
            plan TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            activated_at TEXT,
            expires_at TEXT,
            last_reference TEXT
        );

        CREATE TABLE IF NOT EXISTS case_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            file_id INTEGER,
            file_name TEXT NOT NULL,
            action_type TEXT NOT NULL,  -- 'reviewed', 'resolved', 'reversed'
            timestamp TEXT NOT NULL
        );
        """
    )
    migrate_schema(conn)
    conn.commit()
    conn.close()


def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def generate_salt() -> str:
    return hashlib.sha256(os.urandom(32)).hexdigest()


def compute_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def get_session_info() -> dict:
    """Best-effort info about who was logged into this machine, and
    whether it was a local session or a Windows Remote Desktop session,
    at the moment tampering was detected. Never touches the camera or
    any other capture device - just OS session metadata.
    """
    info = {"os_username": "unknown", "hostname": "unknown", "session_type": "local", "remote_ip": ""}

    try:
        info["os_username"] = getpass.getuser()
    except Exception:
        pass
    try:
        info["hostname"] = socket.gethostname()
    except Exception:
        pass

    if os.name == "nt":
        try:
            session_name = os.environ.get("SESSIONNAME", "")
            if session_name and session_name.upper() != "CONSOLE":
                info["session_type"] = "remote"
                result = subprocess.run(
                    ["netstat", "-n"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 4 and parts[0] == "TCP" and parts[1].endswith(":3389") and parts[3] == "ESTABLISHED":
                        foreign = parts[2]
                        info["remote_ip"] = foreign.rsplit(":", 1)[0].strip("[]")
                        break
        except Exception:
            pass

    return info


def save_cloud_token(user_id: str, provider: str, access_token: str, refresh_token: str = None, expires_in: int = None) -> None:
    expires_at = None
    if expires_in:
        expires_at = (datetime.utcnow() + timedelta(seconds=int(expires_in))).isoformat(timespec="seconds")

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO cloud_tokens (user_id, provider, access_token, refresh_token, expires_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, provider) DO UPDATE SET
            access_token = excluded.access_token,
            refresh_token = COALESCE(excluded.refresh_token, cloud_tokens.refresh_token),
            expires_at = excluded.expires_at
        """,
        (user_id, provider, access_token, refresh_token, expires_at),
    )
    conn.commit()
    conn.close()


def get_cloud_token(user_id: str, provider: str) -> Optional[dict]:
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM cloud_tokens WHERE user_id = ? AND provider = ?",
        (user_id, provider),
    )
    row = cursor.fetchone()
    conn.close()
    return row_to_dict(row) if row else None


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


_db_ready = False


@app.before_request
def ensure_db():
    # init_db() already runs once at startup (in both desktop_app.py and
    # app.py's __main__ block). Re-running its migration checks on every
    # single request added needless latency to every API call, including
    # login. This guard keeps the safety net (in case something calls the
    # app without that startup step) without paying the cost every time.
    global _db_ready
    if not _db_ready:
        init_db()
        _db_ready = True


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    import traceback
    traceback.print_exc()
    return jsonify({
        "success": False,
        "message": f"Unexpected server error: {exc}",
    }), 500


# ===== SERVE FRONTEND =====
@app.route('/')
def index():
    """Serve the main HTML page"""
    try:
        with open(RESOURCE_DIR / 'index.html', 'r', encoding='utf-8') as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return jsonify({
            "success": False,
            "message": "index.html not found. Please ensure the file exists."
        }), 404


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files (CSS, JS, etc.)"""
    try:
        return send_from_directory(RESOURCE_DIR, path)
    except FileNotFoundError:
        return jsonify({
            "success": False,
            "message": f"File {path} not found."
        }), 404


# ===== API ENDPOINTS =====

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "success": True,
        "message": "Backend is healthy.",
        "server_time": now_iso()
    })


@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not name or not email or not password:
        return jsonify({"success": False, "message": "All fields are required."}), 400

    ok, body = supabase_signup(email, password, name)
    if not ok:
        return jsonify({"success": False, "message": supabase_error_message(body)}), 400

    user = body.get("user") or body  # Supabase sometimes returns the user object directly
    user_id = user.get("id")
    # Session data can come back flat at the top level, or nested under a
    # "session" key, depending on the API response shape - check both
    # rather than assuming one, since guessing wrong here silently sends
    # confirmed users to an unnecessary "verify your email" screen.
    session_obj = body.get("session") or {}
    has_session = bool(body.get("access_token") or session_obj.get("access_token"))

    if not user_id:
        return jsonify({"success": False, "message": "Registration failed. Please try again."}), 400

    if has_session:
        access_token = body.get("access_token") or session_obj.get("access_token")
        if access_token:
            save_cloud_token(
                user_id, "supabase", access_token,
                body.get("refresh_token") or session_obj.get("refresh_token"),
                body.get("expires_in") or session_obj.get("expires_in"),
            )
        return jsonify({
            "success": True,
            "message": "Account created successfully.",
            "user": {"id": user_id, "name": name, "email": email},
        })

    return jsonify({
        "success": True,
        "requires_email_confirmation": True,
        "message": "Account created! Enter the 6-digit code we emailed you to finish signing up.",
    })


@app.route('/api/verify-signup', methods=['POST'])
def verify_signup():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    token = (data.get('token') or '').strip()

    if not email or not token:
        return jsonify({"success": False, "message": "Email and code are required."}), 400

    ok, body = supabase_verify_signup(email, token)
    if not ok:
        return jsonify({"success": False, "message": supabase_error_message(body)}), 400

    user = body.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Verification failed. Please try again."}), 400

    name = (user.get("user_metadata") or {}).get("name") or email.split("@")[0]

    access_token = body.get("access_token")
    if access_token:
        save_cloud_token(user_id, "supabase", access_token, body.get("refresh_token"), body.get("expires_in"))

    return jsonify({
        "success": True,
        "message": "Email verified! You're logged in.",
        "user": {"id": user_id, "name": name, "email": user.get("email", email)},
    })


@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email:
        return jsonify({"success": False, "message": "Email is required."}), 400

    supabase_recover(email)
    # Always the same response, whether or not the account exists - this is
    # standard practice so the app can't be used to check which emails are
    # registered.
    return jsonify({
        "success": True,
        "message": "If an account exists for that email, a reset code has been sent.",
    })


@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    token = (data.get('token') or '').strip()
    new_password = data.get('new_password') or ''

    if not email or not token or not new_password:
        return jsonify({"success": False, "message": "Email, code, and new password are required."}), 400

    ok, body = supabase_verify_recovery(email, token)
    if not ok:
        return jsonify({"success": False, "message": supabase_error_message(body)}), 400

    access_token = body.get("access_token")
    if not access_token:
        return jsonify({"success": False, "message": "Verification failed. Please try again."}), 400

    ok2, body2 = supabase_update_password(access_token, new_password)
    if not ok2:
        return jsonify({"success": False, "message": supabase_error_message(body2)}), 400

    return jsonify({"success": True, "message": "Password updated! You can now log in."})


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400

    ok, body = supabase_login(email, password)
    if not ok:
        return jsonify({"success": False, "message": supabase_error_message(body)}), 401

    user = body.get("user") or {}
    user_id = user.get("id")
    if not user_id:
        return jsonify({"success": False, "message": "Login failed. Please try again."}), 401

    name = (user.get("user_metadata") or {}).get("name") or user.get("email", "").split("@")[0]

    access_token = body.get("access_token")
    if access_token:
        save_cloud_token(
            user_id, "supabase", access_token,
            body.get("refresh_token"), body.get("expires_in"),
        )

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": {
            "id": user_id,
            "name": name,
            "email": user.get("email", email),
        },
    })


@app.route('/api/files', methods=['GET'])
def get_files():
    user_id = request.args.get('user_id')
    if user_id is None:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM files WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    return jsonify({
        "success": True,
        "files": [row_to_dict(row) for row in rows],
    })


@app.route('/api/files', methods=['POST'])
def upload_file():
    user_id = request.form.get('user_id')
    file_path = (request.form.get('file_path') or '').strip()
    uploaded_file = request.files.get('file')

    if user_id is None:
        return jsonify({"success": False, "message": "User id is required."}), 400

    file_bytes = None
    monitored_path = None
    display_name = None

    if uploaded_file and uploaded_file.filename:
        try:
            file_bytes = uploaded_file.read()
        except Exception as exc:
            return jsonify({"success": False, "message": f"Unable to read uploaded file: {exc}"}), 400

        display_name = uploaded_file.filename or "uploaded_file"
        safe_name = display_name.replace('..', '_').replace('/', '_').replace('\\', '_')
        user_upload_dir = UPLOAD_DIR / f"user_{user_id}"
        user_upload_dir.mkdir(parents=True, exist_ok=True)
        monitored_path = user_upload_dir / f"{int(time.time())}_{safe_name}"
        monitored_path.write_bytes(file_bytes)
    elif file_path:
        try:
            monitored_path = Path(file_path).expanduser().resolve()
        except Exception:
            return jsonify({"success": False, "message": "Invalid file path provided."}), 400

        if not monitored_path.exists() or not monitored_path.is_file():
            return jsonify({"success": False, "message": "The monitored file path does not exist or is not a file."}), 400

        try:
            file_bytes = monitored_path.read_bytes()
        except OSError as exc:
            return jsonify({"success": False, "message": f"Unable to read the selected file: {exc}"}), 400

        display_name = monitored_path.name
    else:
        return jsonify({"success": False, "message": "A file path or uploaded file is required for live monitoring."}), 400

    if file_bytes is None:
        return jsonify({"success": False, "message": "Unable to read the selected file."}), 400

    file_hash = compute_hash(file_bytes)
    timestamp = now_iso()

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO files (user_id, name, path, trusted_hash, current_hash, status, last_checked, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, display_name, str(monitored_path), file_hash, file_hash, 'monitoring', timestamp, timestamp),
    )
    conn.commit()
    file_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO hash_history (file_id, hash_value, timestamp, change_type) VALUES (?, ?, ?, ?)",
        (file_id, file_hash, timestamp, 'initial'),
    )
    conn.commit()
    conn.close()

    try:
        backup_path_for(file_id).write_bytes(file_bytes)
    except OSError as exc:
        print(f"[backup] could not write initial backup for file {file_id}: {exc!r}", flush=True)

    return jsonify({
        "success": True,
        "message": "File is now being monitored successfully.",
        "file": {
            "id": file_id,
            "user_id": user_id,
            "name": display_name,
            "path": str(monitored_path),
            "trusted_hash": file_hash,
            "current_hash": file_hash,
            "status": 'monitoring',
            "last_checked": timestamp,
            "locked": 0,
        },
    })


@app.route('/api/files/<int:file_id>/history', methods=['GET'])
def get_file_history(file_id):
    """Get hash history for a specific file (last 3 hashes)"""
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT hash_value, timestamp, change_type FROM hash_history WHERE file_id = ? ORDER BY id DESC LIMIT 3",
        (file_id,),
    )
    history = cursor.fetchall()
    conn.close()
    
    # Get file info
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, status FROM files WHERE id = ?", (file_id,))
    file_info = cursor.fetchone()
    conn.close()
    
    return jsonify({
        "success": True,
        "file": dict(file_info) if file_info else None,
        "history": [dict(h) for h in history]
    })


@app.route('/api/files/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    """Delete a file and its associated data"""
    conn = Database.get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    file = cursor.fetchone()
    
    if not file:
        conn.close()
        return jsonify({"success": False, "message": "File not found."}), 404

    if file["locked"] and os.name == "nt":
        # Never let a file end up permanently locked with no record left to
        # undo it - always unlock before removing it from monitoring.
        username = get_session_info()["os_username"]
        _run_icacls([file["path"], "/remove:d", username])

    # Keep the original file on disk and only remove monitoring records for this user entry.
    # This ensures the app watches the live file in place without duplicating or deleting it.
    
    # Delete all related data
    cursor.execute("DELETE FROM hash_history WHERE file_id = ?", (file_id,))
    cursor.execute("DELETE FROM alerts WHERE file_id = ?", (file_id,))
    cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()

    try:
        backup_path_for(file_id).unlink(missing_ok=True)
    except OSError:
        pass
    
    return jsonify({
        "success": True,
        "message": "File and associated data deleted successfully."
    })


@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    user_id = request.args.get('user_id')
    if user_id is None:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM alerts WHERE user_id = ? ORDER BY id DESC LIMIT 50",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    alerts = []
    for row in rows:
        alert_dict = row_to_dict(row)
        alert_dict['resolved'] = bool(alert_dict.get('resolved', 0))
        alerts.append(alert_dict)

    return jsonify({
        "success": True,
        "alerts": alerts,
    })


@app.route('/api/alerts/<int:alert_id>/resolve', methods=['POST'])
def resolve_alert(alert_id):
    """The user confirms THEY made this change on purpose: accept the
    current content as the new trusted baseline and resume monitoring.
    (Previously this only flipped the alert's resolved flag and left the
    file stuck showing "tampered" forever - now it actually clears it.)"""
    conn = Database.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
    alert = cursor.fetchone()
    if not alert:
        conn.close()
        return jsonify({"success": False, "message": "Alert not found."}), 404

    file_id = alert["file_id"]
    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    file_row = cursor.fetchone()
    if not file_row:
        conn.close()
        return jsonify({"success": False, "message": "Monitored file not found."}), 404

    if file_row["locked"]:
        conn.close()
        return jsonify({"success": False, "message": "This file is locked. Unlock it first."}), 400

    monitored_path = Path(file_row["path"])
    timestamp = now_iso()

    try:
        current_bytes = monitored_path.read_bytes()
        current_hash = compute_hash(current_bytes)
    except OSError as exc:
        conn.close()
        return jsonify({
            "success": False,
            "message": f"Can't read the file to accept it as-is: {exc}. If it was deleted, use Reverse instead to restore it, or Delete to stop monitoring it.",
        }), 400

    # Accept current content as the new trusted baseline.
    cursor.execute(
        "UPDATE files SET trusted_hash = ?, current_hash = ?, status = 'monitoring', last_checked = ? WHERE id = ?",
        (current_hash, current_hash, timestamp, file_id),
    )
    cursor.execute(
        "INSERT INTO hash_history (file_id, hash_value, timestamp, change_type) VALUES (?, ?, ?, ?)",
        (file_id, current_hash, timestamp, 'accepted'),
    )
    # Clear every pending alert for this file, not just the one clicked -
    # accepting the change means none of them are actionable anymore.
    cursor.execute(
        "UPDATE alerts SET resolved = 1, resolution_type = 'resolved', resolved_at = ? WHERE file_id = ? AND resolved = 0",
        (timestamp, file_id),
    )
    conn.commit()
    conn.close()

    try:
        backup_path_for(file_id).write_bytes(current_bytes)
    except OSError as exc:
        print(f"[backup] could not update backup for file {file_id}: {exc!r}", flush=True)

    log_case(alert["user_id"], file_id, file_row["name"], "resolved")

    return jsonify({
        "success": True,
        "message": "Change accepted. This is now the trusted version - monitoring continues from here.",
    })


@app.route('/api/files/<int:file_id>/reverse', methods=['POST'])
def reverse_file(file_id):
    """The user did NOT make this change: restore the file to its last
    known-good content and keep monitoring against the original baseline."""
    conn = Database.get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    file_row = cursor.fetchone()
    if not file_row:
        conn.close()
        return jsonify({"success": False, "message": "File not found."}), 404

    if file_row["locked"]:
        conn.close()
        return jsonify({"success": False, "message": "This file is locked. Unlock it first."}), 400

    backup_file = backup_path_for(file_id)
    if not backup_file.exists():
        conn.close()
        return jsonify({
            "success": False,
            "message": "No backup is available for this file, so it can't be automatically restored.",
        }), 400

    monitored_path = Path(file_row["path"])
    timestamp = now_iso()

    try:
        backup_bytes = backup_file.read_bytes()
        monitored_path.parent.mkdir(parents=True, exist_ok=True)
        monitored_path.write_bytes(backup_bytes)
    except OSError as exc:
        conn.close()
        return jsonify({"success": False, "message": f"Could not restore the file: {exc}"}), 400

    restored_hash = compute_hash(backup_bytes)

    cursor.execute(
        "UPDATE files SET current_hash = ?, status = 'monitoring', last_checked = ? WHERE id = ?",
        (restored_hash, timestamp, file_id),
    )
    cursor.execute(
        "INSERT INTO hash_history (file_id, hash_value, timestamp, change_type) VALUES (?, ?, ?, ?)",
        (file_id, restored_hash, timestamp, 'restored'),
    )
    cursor.execute(
        "UPDATE alerts SET resolved = 1, resolution_type = 'reversed', resolved_at = ? WHERE file_id = ? AND resolved = 0",
        (timestamp, file_id),
    )
    conn.commit()
    conn.close()

    log_case(file_row["user_id"], file_id, file_row["name"], "reversed")

    return jsonify({
        "success": True,
        "message": "File restored to its last known-good version. Monitoring continues.",
    })


@app.route('/api/files/<int:file_id>/review', methods=['POST'])
def review_file(file_id):
    """Lets the user inspect a monitored file's current state directly in
    the app - metadata plus a text preview when possible - instead of
    minimizing the app to go check the file in its actual folder."""
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    file_row = cursor.fetchone()
    conn.close()

    if not file_row:
        return jsonify({"success": False, "message": "File not found."}), 404

    if file_row["locked"]:
        return jsonify({"success": False, "message": "This file is locked. Unlock it first to review it."}), 400

    path = Path(file_row["path"])
    preview = None
    file_size = None
    modified_at = None

    try:
        stat_result = path.stat()
        file_size = stat_result.st_size
        modified_at = datetime.fromtimestamp(stat_result.st_mtime).isoformat(timespec="seconds")

        raw = path.read_bytes()
        try:
            text = raw[:20000].decode("utf-8")
            preview = text
        except UnicodeDecodeError:
            preview = None  # binary file - metadata only, no text preview
    except OSError as exc:
        return jsonify({"success": False, "message": f"Could not read the file: {exc}"}), 400

    log_case(file_row["user_id"], file_id, file_row["name"], "reviewed")

    return jsonify({
        "success": True,
        "name": file_row["name"],
        "path": str(path),
        "status": file_row["status"],
        "size": file_size,
        "modified_at": modified_at,
        "current_hash": file_row["current_hash"],
        "trusted_hash": file_row["trusted_hash"],
        "preview": preview,
        "is_binary": preview is None,
    })


@app.route('/api/cases', methods=['GET'])
def get_cases():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM case_log WHERE user_id = ? ORDER BY id DESC LIMIT 200",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    return jsonify({"success": True, "cases": [row_to_dict(row) for row in rows]})


@app.route('/api/transfer/my-code', methods=['GET'])
def transfer_my_code():
    user_id = request.args.get('user_id')
    display_name = request.args.get('name', 'User')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    access_token = get_valid_supabase_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Session expired. Please log out and back in."}), 401

    code = ensure_user_code(user_id, access_token, display_name)
    if not code:
        return jsonify({"success": False, "message": "Could not generate a user code."}), 400

    return jsonify({"success": True, "code": code})


@app.route('/api/transfer/lookup', methods=['POST'])
def transfer_lookup():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    code = data.get('code')
    if not user_id or not code:
        return jsonify({"success": False, "message": "user_id and code are required."}), 400

    access_token = get_valid_supabase_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Session expired. Please log out and back in."}), 401

    receiver = lookup_user_by_code(access_token, code)
    if not receiver:
        return jsonify({"success": False, "message": "No user found with that code."}), 404

    return jsonify({"success": True, "receiver_id": receiver["user_id"], "display_name": receiver["display_name"]})


@app.route('/api/transfer/send', methods=['POST'])
def transfer_send():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    sender_name = data.get('sender_name', 'User')
    file_path = data.get('file_path')
    receiver_code = data.get('receiver_code')
    compress = bool(data.get('compress'))

    if not user_id or not file_path or not receiver_code:
        return jsonify({"success": False, "message": "user_id, file_path, and receiver_code are required."}), 400

    access_token = get_valid_supabase_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Session expired. Please log out and back in."}), 401

    receiver = lookup_user_by_code(access_token, receiver_code)
    if not receiver:
        return jsonify({"success": False, "message": "No user found with that code."}), 404
    receiver_id = receiver["user_id"]

    path = Path(file_path)
    try:
        original_bytes = path.read_bytes()
    except OSError as exc:
        return jsonify({"success": False, "message": f"Could not read the file: {exc}"}), 400

    file_name = path.name
    payload = original_bytes

    if compress:
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(path.name, original_bytes)
        payload = buffer.getvalue()
        file_name = path.name + ".zip"

    trusted_hash = compute_hash(payload)

    from cryptography.fernet import Fernet
    transfer_key = Fernet.generate_key()
    encrypted_payload = encrypt_bytes(payload, transfer_key)

    storage_path = f"{user_id}/{receiver_id}/{now_iso().replace(':', '-')}_{file_name}"
    ok, upload_result = storage_upload(access_token, storage_path, encrypted_payload)
    if not ok:
        return jsonify({"success": False, "message": f"Upload failed: {upload_result}"}), 400

    ok2, insert_result = postgrest_request(
        "POST", "transfer_requests", access_token,
        json={
            "sender_id": user_id,
            "receiver_id": receiver_id,
            "sender_name": sender_name,
            "file_name": file_name,
            "storage_path": storage_path,
            "trusted_hash": trusted_hash,
            "transfer_key": transfer_key.decode("utf-8"),
            "file_size": len(payload),
            "compressed": compress,
            "status": "pending",
        },
    )
    if not ok2:
        storage_delete(access_token, storage_path)
        return jsonify({"success": False, "message": f"Could not create transfer request: {insert_result}"}), 400

    log_case(user_id, None, file_name, "sent")

    return jsonify({"success": True, "message": f"{file_name} sent. Waiting for the receiver to accept."})


@app.route('/api/transfer/incoming', methods=['GET'])
def transfer_incoming():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    access_token = get_valid_supabase_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Session expired. Please log out and back in."}), 401

    ok, rows = postgrest_request(
        "GET", "transfer_requests", access_token,
        params={
            "receiver_id": f"eq.{user_id}",
            "status": "eq.pending",
            "select": "id,sender_name,file_name,file_size,compressed,created_at",
            "order": "created_at.desc",
        },
    )
    if not ok:
        return jsonify({"success": False, "message": "Could not load incoming transfers."}), 400

    return jsonify({"success": True, "transfers": rows or []})


@app.route('/api/transfer/sent', methods=['GET'])
def transfer_sent():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    access_token = get_valid_supabase_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Session expired. Please log out and back in."}), 401

    ok, rows = postgrest_request(
        "GET", "transfer_requests", access_token,
        params={
            "sender_id": f"eq.{user_id}",
            "select": "id,file_name,status,file_size,created_at",
            "order": "created_at.desc",
            "limit": "100",
        },
    )
    if not ok:
        return jsonify({"success": False, "message": "Could not load sent transfers."}), 400

    return jsonify({"success": True, "transfers": rows or []})


@app.route('/api/transfer/reject', methods=['POST'])
def transfer_reject():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    transfer_id = data.get('transfer_id')
    if not user_id or not transfer_id:
        return jsonify({"success": False, "message": "user_id and transfer_id are required."}), 400

    access_token = get_valid_supabase_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Session expired. Please log out and back in."}), 401

    ok, rows = postgrest_request(
        "GET", "transfer_requests", access_token,
        params={"id": f"eq.{transfer_id}", "select": "storage_path,file_name"},
    )
    if not ok or not rows:
        return jsonify({"success": False, "message": "Transfer not found."}), 404
    record = rows[0]

    postgrest_request(
        "PATCH", "transfer_requests", access_token,
        params={"id": f"eq.{transfer_id}"},
        json={"status": "rejected"},
    )
    storage_delete(access_token, record["storage_path"])
    log_case(user_id, None, record["file_name"], "rejected")

    return jsonify({"success": True, "message": "Transfer rejected."})


@app.route('/api/transfer/accept', methods=['POST'])
def transfer_accept():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    transfer_id = data.get('transfer_id')
    destination_path = data.get('destination_path')
    verify_hash = data.get('verify_hash', True)

    if not user_id or not transfer_id or not destination_path:
        return jsonify({"success": False, "message": "user_id, transfer_id, and destination_path are required."}), 400

    access_token = get_valid_supabase_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Session expired. Please log out and back in."}), 401

    ok, rows = postgrest_request(
        "GET", "transfer_requests", access_token,
        params={"id": f"eq.{transfer_id}", "select": "*"},
    )
    if not ok or not rows:
        return jsonify({"success": False, "message": "Transfer not found."}), 404
    record = rows[0]

    ok2, encrypted_payload = storage_download(access_token, record["storage_path"])
    if not ok2:
        return jsonify({"success": False, "message": f"Download failed: {encrypted_payload}"}), 400

    try:
        payload = decrypt_bytes(encrypted_payload, record["transfer_key"].encode("utf-8"))
    except Exception as exc:
        return jsonify({"success": False, "message": f"Could not decrypt the file: {exc}"}), 400

    integrity_note = "not checked (skipped by user)"
    if verify_hash:
        actual_hash = compute_hash(payload)
        if actual_hash != record["trusted_hash"]:
            log_case(user_id, None, record["file_name"], "rejected")
            return jsonify({
                "success": False,
                "message": "Integrity check failed: this file doesn't match what the sender sent. It was not saved.",
            }), 400
        integrity_note = "verified, matches sender's hash"

    try:
        if record["compressed"]:
            import io
            import zipfile
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                names = zf.namelist()
                payload = zf.read(names[0]) if names else b""

        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
    except OSError as exc:
        return jsonify({"success": False, "message": f"Could not save the file: {exc}"}), 400

    postgrest_request(
        "PATCH", "transfer_requests", access_token,
        params={"id": f"eq.{transfer_id}"},
        json={"status": "completed"},
    )
    storage_delete(access_token, record["storage_path"])
    log_case(user_id, None, record["file_name"], "received")

    return jsonify({"success": True, "message": f"File received and saved. Integrity: {integrity_note}."})


def _run_icacls(args: list) -> tuple[bool, str]:
    """Run icacls without ever popping a visible console window (see the
    earlier os.system() bug - never repeat that mistake)."""
    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            ["icacls"] + args,
            capture_output=True,
            text=True,
            timeout=10,
            **kwargs,
        )
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return False, str(exc)


@app.route('/api/files/<int:file_id>/lock', methods=['POST'])
def lock_file(file_id):
    """Denies normal read/write/delete access to this file for the current
    Windows user account - which blocks any other program running in this
    session too, not just casual browsing. Deliberately does NOT deny
    permission-changing rights, so the app (running as the same user) can
    still remove the block later via unlock. Windows will show any other
    program a plain, generic "Access is denied" - nothing about our app or
    why is revealed.
    """
    if os.name != "nt":
        return jsonify({"success": False, "message": "File locking is only supported on Windows."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    file_row = cursor.fetchone()
    if not file_row:
        conn.close()
        return jsonify({"success": False, "message": "File not found."}), 404
    if file_row["locked"]:
        conn.close()
        return jsonify({"success": True, "message": "Already locked."})

    path = file_row["path"]
    username = get_session_info()["os_username"]

    ok, output = _run_icacls([path, "/deny", f"{username}:(R,W,D,X)"])
    if not ok:
        conn.close()
        return jsonify({"success": False, "message": f"Could not lock the file: {output}"}), 400

    cursor.execute("UPDATE files SET locked = 1, last_checked = ? WHERE id = ?", (now_iso(), file_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "File locked. It can only be opened again from this app."})


@app.route('/api/files/<int:file_id>/unlock', methods=['POST'])
def unlock_file(file_id):
    if os.name != "nt":
        return jsonify({"success": False, "message": "File locking is only supported on Windows."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    file_row = cursor.fetchone()
    if not file_row:
        conn.close()
        return jsonify({"success": False, "message": "File not found."}), 404
    if not file_row["locked"]:
        conn.close()
        return jsonify({"success": True, "message": "Already unlocked."})

    path = file_row["path"]
    username = get_session_info()["os_username"]

    ok, output = _run_icacls([path, "/remove:d", username])
    if not ok:
        conn.close()
        return jsonify({"success": False, "message": f"Could not unlock the file: {output}"}), 400

    cursor.execute("UPDATE files SET locked = 0, last_checked = ? WHERE id = ?", (now_iso(), file_id))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": "File unlocked. Monitoring resumes normally."})


# ===== Secure Cloud Recovery Module: routes =====

# ===== Secure Cloud Recovery Module: routes =====

_pending_google_auth_user = None


@app.route('/api/cloud/google/connect', methods=['POST'])
def cloud_google_connect():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    redirect_uri = f"{request.host_url.rstrip('/')}/oauth/google/callback"
    auth_url = google_auth_url(redirect_uri)

    try:
        import webbrowser
        webbrowser.open(auth_url)
    except Exception as exc:
        return jsonify({"success": False, "message": f"Could not open browser: {exc}"}), 500

    # Stash which user is completing this flow, since the callback request
    # itself carries no user identity - only Google's redirect does.
    global _pending_google_auth_user
    _pending_google_auth_user = user_id

    return jsonify({
        "success": True,
        "message": "Continue in your browser to connect Google Drive, then come back to this app.",
    })


@app.route('/oauth/google/callback', methods=['GET'])
def oauth_google_callback():
    error = request.args.get('error')
    code = request.args.get('code')

    if error or not code:
        return "<h2>Google Drive connection failed.</h2><p>You can close this tab and try again from the app.</p>", 400

    if not _pending_google_auth_user:
        return "<h2>No pending connection found.</h2><p>Please start connecting Google Drive from the app again.</p>", 400

    redirect_uri = f"{request.host_url.rstrip('/')}/oauth/google/callback"
    ok, body = google_exchange_code(code, redirect_uri)
    if not ok:
        print(f"[cloud] Google token exchange failed: {body}", flush=True)
        return "<h2>Google Drive connection failed.</h2><p>You can close this tab and try again from the app.</p>", 400

    save_cloud_token(
        _pending_google_auth_user, "google",
        body["access_token"], body.get("refresh_token"), body.get("expires_in"),
    )

    return "<h2>Google Drive connected!</h2><p>You can close this tab and return to the app.</p>"


@app.route('/api/cloud/google/status', methods=['GET'])
def cloud_google_status():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    token_row = get_cloud_token(user_id, "google")
    return jsonify({"success": True, "connected": token_row is not None})


@app.route('/api/cloud/google/quota', methods=['GET'])
def cloud_google_quota():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    access_token = get_valid_google_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Google Drive isn't connected."}), 400

    ok, quota = google_drive_storage_quota(access_token)
    if not ok:
        return jsonify({"success": False, "message": "Could not check storage quota."}), 400

    return jsonify({"success": True, "used": quota["used"], "limit": quota["limit"]})


@app.route('/api/auth/confirm-password', methods=['POST'])
def confirm_password():
    """Re-checks the account password without changing the current
    session. Required before any cloud file retrieval, so that if a
    device is left unlocked or stolen while still logged in, files
    still can't be pulled down without the password.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({"success": False, "message": "Password is required."}), 400

    ok, body = supabase_login(email, password)
    if not ok:
        return jsonify({"success": False, "message": "Incorrect password."}), 401

    return jsonify({"success": True, "message": "Confirmed."})


@app.route('/api/cloud/backup', methods=['POST'])
def cloud_backup():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    file_path = data.get('file_path')
    email = data.get('email')

    if not user_id or not file_path:
        return jsonify({"success": False, "message": "user_id and file_path are required."}), 400

    if not is_subscription_active(user_id, email):
        return jsonify({"success": False, "message": "Cloud backup requires an active subscription.", "requires_subscription": True}), 402

    access_token = get_valid_google_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Google Drive isn't connected. Connect it first."}), 400

    encryption_key = get_backup_encryption_key(user_id)
    if not encryption_key:
        return jsonify({"success": False, "message": "Could not access your backup encryption key. Please log out and back in, then try again."}), 400

    path = Path(file_path)
    try:
        original_bytes = path.read_bytes()
    except OSError as exc:
        return jsonify({"success": False, "message": f"Could not read the file: {exc}"}), 400

    trusted_hash = compute_hash(original_bytes)
    encrypted_bytes = encrypt_bytes(original_bytes, encryption_key)

    ok, result = google_drive_upload(access_token, path.name + ".fimsbackup", encrypted_bytes)
    if not ok:
        return jsonify({"success": False, "message": f"Upload failed: {result}"}), 400

    remote_file_id = result.get("id")
    timestamp = now_iso()

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO cloud_backups (user_id, original_name, original_path, provider, remote_file_id, trusted_hash, encrypted_size, backed_up_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, path.name, str(path), "google", remote_file_id, trusted_hash, len(encrypted_bytes), timestamp),
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"{path.name} backed up to Google Drive."})


@app.route('/api/cloud/backups', methods=['GET'])
def cloud_backups_list():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM cloud_backups WHERE user_id = ? ORDER BY id DESC",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    return jsonify({"success": True, "backups": [row_to_dict(row) for row in rows]})


@app.route('/api/cloud/restore', methods=['POST'])
def cloud_restore():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    backup_id = data.get('backup_id')
    destination_path = data.get('destination_path')
    email = data.get('email')

    if not user_id or not backup_id or not destination_path:
        return jsonify({"success": False, "message": "user_id, backup_id, and destination_path are required."}), 400

    if not is_subscription_active(user_id, email):
        return jsonify({"success": False, "message": "Cloud recovery requires an active subscription.", "requires_subscription": True}), 402

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cloud_backups WHERE id = ? AND user_id = ?", (backup_id, user_id))
    backup_row = cursor.fetchone()
    conn.close()

    if not backup_row:
        return jsonify({"success": False, "message": "Backup not found."}), 404

    access_token = get_valid_google_token(user_id)
    if not access_token:
        return jsonify({"success": False, "message": "Google Drive isn't connected."}), 400

    encryption_key = get_backup_encryption_key(user_id)
    if not encryption_key:
        return jsonify({"success": False, "message": "Could not access your backup encryption key."}), 400

    ok, content = google_drive_download(access_token, backup_row["remote_file_id"])
    if not ok:
        return jsonify({"success": False, "message": f"Download failed: {content}"}), 400

    try:
        decrypted_bytes = decrypt_bytes(content, encryption_key)
    except Exception as exc:
        return jsonify({"success": False, "message": f"Could not decrypt the backup: {exc}"}), 400

    restored_hash = compute_hash(decrypted_bytes)
    if restored_hash != backup_row["trusted_hash"]:
        return jsonify({"success": False, "message": "Restored file doesn't match its recorded hash - aborting to avoid restoring corrupted data."}), 400

    try:
        dest = Path(destination_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(decrypted_bytes)
    except OSError as exc:
        return jsonify({"success": False, "message": f"Could not write the restored file: {exc}"}), 400

    return jsonify({"success": True, "message": f"Restored to {destination_path}."})


@app.route('/api/cloud/backup/<int:backup_id>/delete', methods=['POST'])
def cloud_delete_backup(backup_id):
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cloud_backups WHERE id = ? AND user_id = ?", (backup_id, user_id))
    backup_row = cursor.fetchone()
    if not backup_row:
        conn.close()
        return jsonify({"success": False, "message": "Backup not found."}), 404

    access_token = get_valid_google_token(user_id)
    if access_token:
        google_drive_delete(access_token, backup_row["remote_file_id"])
        # Proceed even if the Drive delete fails (e.g. already removed
        # manually) - don't leave an orphaned local record either way.

    cursor.execute("DELETE FROM cloud_backups WHERE id = ?", (backup_id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "message": f"{backup_row['original_name']} deleted."})


# ===== Secure Cloud Recovery Module: Subscription Manager =====

@app.route('/api/subscription/plans', methods=['GET'])
def subscription_plans():
    return jsonify({"success": True, "plans": SUBSCRIPTION_PLANS})


@app.route('/api/subscription/status', methods=['GET'])
def subscription_status():
    user_id = request.args.get('user_id')
    email = request.args.get('email')
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    if email and email.lower() == ADMIN_EMAIL.lower():
        return jsonify({"success": True, "active": True, "plan": "admin", "expires_at": None, "is_admin": True})

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": True, "active": False, "plan": None, "expires_at": None})

    active = is_subscription_active(user_id, email)
    return jsonify({
        "success": True,
        "active": active,
        "plan": row["plan"],
        "expires_at": row["expires_at"],
    })


_pending_paystack_user = {}  # reference -> {user_id, plan_key}


@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    email = data.get('email')
    plan_key = data.get('plan')

    if not user_id or not email or not plan_key:
        return jsonify({"success": False, "message": "user_id, email, and plan are required."}), 400
    if plan_key not in SUBSCRIPTION_PLANS:
        return jsonify({"success": False, "message": "Unknown plan."}), 400

    plan = SUBSCRIPTION_PLANS[plan_key]
    callback_url = f"{request.host_url.rstrip('/')}/payment/paystack/callback"

    ok, body = paystack_initialize(email, plan["amount_usd"], plan_key, callback_url)
    if not ok or not body.get("status"):
        return jsonify({"success": False, "message": f"Could not start payment: {body.get('message', body)}"}), 400

    reference = body["data"]["reference"]
    authorization_url = body["data"]["authorization_url"]
    _pending_paystack_user[reference] = {"user_id": user_id, "plan_key": plan_key}

    try:
        import webbrowser
        webbrowser.open(authorization_url)
    except Exception as exc:
        return jsonify({"success": False, "message": f"Could not open browser: {exc}"}), 500

    return jsonify({
        "success": True,
        "message": "Continue in your browser to complete payment, then come back to this app.",
    })


@app.route('/payment/paystack/callback', methods=['GET'])
def paystack_callback():
    reference = request.args.get('reference')
    if not reference:
        return "<h2>Payment could not be confirmed.</h2><p>No reference was provided. You can close this tab.</p>", 400

    pending = _pending_paystack_user.get(reference)
    if not pending:
        return "<h2>Payment session not found.</h2><p>Please start the subscription again from the app.</p>", 400

    ok, body = paystack_verify(reference)
    if not ok or body.get("data", {}).get("status") != "success":
        return "<h2>Payment was not successful.</h2><p>You can close this tab and try again from the app.</p>", 400

    plan = SUBSCRIPTION_PLANS[pending["plan_key"]]
    now = datetime.utcnow()
    expires_at = (now + timedelta(days=plan["days"])).isoformat(timespec="seconds")

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO subscriptions (user_id, plan, status, activated_at, expires_at, last_reference)
        VALUES (?, ?, 'active', ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            plan = excluded.plan,
            status = 'active',
            activated_at = excluded.activated_at,
            expires_at = excluded.expires_at,
            last_reference = excluded.last_reference
        """,
        (pending["user_id"], pending["plan_key"], now.isoformat(timespec="seconds"), expires_at, reference),
    )
    conn.commit()
    conn.close()
    del _pending_paystack_user[reference]

    return "<h2>Subscription activated!</h2><p>You can close this tab and return to the app.</p>"


@app.route('/api/status', methods=['GET'])
def get_status():
    user_id = request.args.get('user_id')
    if user_id is None:
        return jsonify({"success": False, "message": "user_id is required."}), 400

    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, trusted_hash, current_hash, status, last_checked FROM files WHERE user_id = ?",
        (user_id,),
    )
    files = cursor.fetchall()
    cursor.execute(
        "SELECT COUNT(*) AS count FROM alerts WHERE user_id = ?",
        (user_id,),
    )
    alert_count = cursor.fetchone()["count"]
    conn.close()

    safe_files = sum(1 for file in files if file["status"] in ('monitoring', 'safe'))
    tampered_files = sum(1 for file in files if file["status"] == 'tampered')

    return jsonify({
        "success": True,
        "stats": {
            "files": len(files),
            "alerts": alert_count,
            "safe_files": safe_files,
            "tampered_files": tampered_files,
        },
    })


@app.route('/api/users', methods=['GET'])
def get_users():
    # Listing every registered user requires Supabase's service_role key,
    # which must never be embedded in a distributed desktop/mobile app -
    # anyone could extract it and gain full unrestricted access to every
    # user's data. Admins should view the user list from the Supabase
    # dashboard (Authentication tab) instead.
    return jsonify({
        "success": False,
        "message": "User management now lives in the Supabase dashboard for security reasons.",
    }), 410


@app.route('/api/simulate/<int:file_id>', methods=['POST'])
def simulate_change(file_id):
    """Simulate file tampering by appending text"""
    conn = Database.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE id = ?", (file_id,))
    file = cursor.fetchone()
    conn.close()
    
    if not file:
        return jsonify({"success": False, "message": "File not found."}), 404
    
    if not os.path.exists(file["path"]):
        return jsonify({"success": False, "message": "File does not exist on disk."}), 400
    
    try:
        with open(file["path"], 'a', encoding='utf-8') as f:
            f.write(f"\n# Tamper simulation at {now_iso()}\n")
    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to modify file: {str(e)}"}), 500
    
    return jsonify({
        "success": True,
        "message": "File modified for testing. Monitoring will detect changes."
    })


monitor_lock = threading.Lock()
monitor_running = False


def monitor_files():
    global monitor_running
    while True:
        with monitor_lock:
            if not monitor_running:
                break
        try:
            conn = Database.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, name, path, trusted_hash, current_hash, status, locked FROM files")
            files = cursor.fetchall()

            for file in files:
                if file["locked"]:
                    # Locked files are intentionally inaccessible (even to
                    # this app) until the user unlocks them - don't attempt
                    # to read, and don't treat that as tampering.
                    continue
                try:
                    with open(file["path"], 'rb') as f:
                        current_bytes = f.read()
                    current_hash = compute_hash(current_bytes)
                except FileNotFoundError:
                    if file["status"] != 'tampered':
                        session = get_session_info()
                        cursor.execute(
                            "UPDATE files SET status = 'tampered', last_checked = ? WHERE id = ?",
                            (now_iso(), file["id"]),
                        )
                        cursor.execute(
                            "INSERT INTO alerts (user_id, file_id, file_name, previous_hash, new_hash, timestamp, resolved, os_username, hostname, session_type, remote_ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (file["user_id"], file["id"], file["name"], file["trusted_hash"], "FILE_MISSING", now_iso(), 0,
                             session["os_username"], session["hostname"], session["session_type"], session["remote_ip"]),
                        )
                        # Add to history
                        cursor.execute(
                            "INSERT INTO hash_history (file_id, hash_value, timestamp, change_type) VALUES (?, ?, ?, ?)",
                            (file["id"], "FILE_MISSING", now_iso(), 'modified'),
                        )
                        # Keep only last 3 history entries
                        cursor.execute(
                            "DELETE FROM hash_history WHERE id NOT IN (SELECT id FROM hash_history WHERE file_id = ? ORDER BY id DESC LIMIT 3)",
                            (file["id"],)
                        )
                    continue

                if current_hash != file["trusted_hash"] and file["status"] != 'tampered':
                    # File has been tampered
                    session = get_session_info()
                    cursor.execute(
                        "UPDATE files SET current_hash = ?, status = 'tampered', last_checked = ? WHERE id = ?",
                        (current_hash, now_iso(), file["id"]),
                    )
                    cursor.execute(
                        "INSERT INTO alerts (user_id, file_id, file_name, previous_hash, new_hash, timestamp, resolved, os_username, hostname, session_type, remote_ip) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (file["user_id"], file["id"], file["name"], file["trusted_hash"], current_hash, now_iso(), 0,
                         session["os_username"], session["hostname"], session["session_type"], session["remote_ip"]),
                    )
                    # Add new hash to history
                    cursor.execute(
                        "INSERT INTO hash_history (file_id, hash_value, timestamp, change_type) VALUES (?, ?, ?, ?)",
                        (file["id"], current_hash, now_iso(), 'modified'),
                    )
                    # Keep only last 3 history entries
                    cursor.execute(
                        "DELETE FROM hash_history WHERE id NOT IN (SELECT id FROM hash_history WHERE file_id = ? ORDER BY id DESC LIMIT 3)",
                        (file["id"],)
                    )
                elif current_hash == file["trusted_hash"] and file["status"] == 'tampered':
                    # File was restored to original
                    cursor.execute(
                        "UPDATE files SET current_hash = ?, status = 'monitoring', last_checked = ? WHERE id = ?",
                        (current_hash, now_iso(), file["id"]),
                    )
                    # Add restored hash to history
                    cursor.execute(
                        "INSERT INTO hash_history (file_id, hash_value, timestamp, change_type) VALUES (?, ?, ?, ?)",
                        (file["id"], current_hash, now_iso(), 'restored'),
                    )
                    # Keep only last 3 history entries
                    cursor.execute(
                        "DELETE FROM hash_history WHERE id NOT IN (SELECT id FROM hash_history WHERE file_id = ? ORDER BY id DESC LIMIT 3)",
                        (file["id"],)
                    )
                else:
                    cursor.execute(
                        "UPDATE files SET current_hash = ?, last_checked = ? WHERE id = ?",
                        (current_hash, now_iso(), file["id"]),
                    )

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Monitor error: {e}")
        time.sleep(3)


@app.route('/api/monitor/start', methods=['POST'])
def start_monitor():
    global monitor_running
    with monitor_lock:
        if not monitor_running:
            monitor_running = True
            thread = threading.Thread(target=monitor_files, daemon=True)
            thread.start()
            return jsonify({"success": True, "message": "Monitoring started."})
    return jsonify({"success": True, "message": "Monitoring already running."})


@app.route('/api/monitor/stop', methods=['POST'])
def stop_monitor():
    global monitor_running
    with monitor_lock:
        monitor_running = False
    return jsonify({"success": True, "message": "Monitoring stopped."})


if __name__ == '__main__':
    init_db()
    with monitor_lock:
        if not monitor_running:
            monitor_running = True
            thread = threading.Thread(target=monitor_files, daemon=True)
            thread.start()
    print("🔐 File Integrity Monitor API Server")
    print(f"📁 Database: {DB_PATH}")
    print(f"📁 Uploads: {UPLOAD_DIR}")
    print("🌐 Server running on http://0.0.0.0:5000")
    print("📡 Access from any device on your network using your IP address")
    app.run(debug=False, host=HOST, port=PORT, threaded=True)