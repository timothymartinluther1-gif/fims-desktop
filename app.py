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
from datetime import datetime
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
                user_id INTEGER NOT NULL,
                file_id INTEGER NOT NULL,
                file_name TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                new_hash TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                resolved INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id),
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


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


@app.before_request
def ensure_db():
    init_db()


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
    has_session = bool(body.get("access_token"))

    if not user_id:
        return jsonify({"success": False, "message": "Registration failed. Please try again."}), 400

    if has_session:
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
        "UPDATE alerts SET resolved = 1 WHERE file_id = ? AND resolved = 0",
        (file_id,),
    )
    conn.commit()
    conn.close()

    try:
        backup_path_for(file_id).write_bytes(current_bytes)
    except OSError as exc:
        print(f"[backup] could not update backup for file {file_id}: {exc!r}", flush=True)

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
        "UPDATE alerts SET resolved = 1 WHERE file_id = ? AND resolved = 0",
        (file_id,),
    )
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "message": "File restored to its last known-good version. Monitoring continues.",
    })


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
            cursor.execute("SELECT id, user_id, name, path, trusted_hash, current_hash, status FROM files")
            files = cursor.fetchall()

            for file in files:
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