import hashlib
import io
import sqlite3
import time
import uuid
from pathlib import Path

import app as app_module


def test_upload_tracks_original_file_path_without_copy(tmp_path):
    original = tmp_path / "protected.txt"
    original.write_text("hello integrity", encoding="utf-8")

    email = f"owner.path.monitor+{uuid.uuid4().hex}@example.com"

    conn = sqlite3.connect(app_module.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"OwnerPathMonitor {uuid.uuid4().hex[:6]}", email, "salt:hash", "salt", "2026-01-01T00:00:00"),
        )
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    finally:
        conn.close()

    client = app_module.app.test_client()
    response = client.post(
        "/api/files",
        data={"user_id": user_id, "file_path": str(original)},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["file"]["path"] == str(original)
    assert body["file"]["trusted_hash"] == hashlib.sha256(b"hello integrity").hexdigest()

    monitored_path = Path(body["file"]["path"])
    assert monitored_path.exists()
    assert monitored_path.parent != app_module.UPLOAD_DIR


def test_uploaded_file_is_monitored_from_browser():
    email = f"owner.upload+{uuid.uuid4().hex}@example.com"
    conn = sqlite3.connect(app_module.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"BrowserUpload {uuid.uuid4().hex[:6]}", email, "salt:hash", "salt", "2026-01-01T00:00:00"),
        )
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    finally:
        conn.close()

    client = app_module.app.test_client()
    response = client.post(
        "/api/files",
        data={
            "user_id": user_id,
            "file": (io.BytesIO(b"uploaded content"), "uploaded.txt"),
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["file"]["name"] == "uploaded.txt"
    assert Path(body["file"]["path"]).exists()
    assert body["file"]["trusted_hash"] == hashlib.sha256(b"uploaded content").hexdigest()


def test_tamper_alert_is_created_after_external_modification(tmp_path):
    original = tmp_path / "tamper_target.txt"
    original.write_text("baseline", encoding="utf-8")

    email = f"owner.alerts+{uuid.uuid4().hex}@example.com"
    conn = sqlite3.connect(app_module.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, salt, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"AlertOwner {uuid.uuid4().hex[:6]}", email, "salt:hash", "salt", "2026-01-01T00:00:00"),
        )
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()[0]
    finally:
        conn.close()

    client = app_module.app.test_client()
    try:
        start_response = client.post("/api/monitor/start")
        assert start_response.status_code == 200

        register_response = client.post(
            "/api/files",
            data={"user_id": user_id, "file_path": str(original)},
        )
        assert register_response.status_code == 200

        original.write_text("tampered", encoding="utf-8")
        time.sleep(4)

        alerts_response = client.get("/api/alerts", query_string={"user_id": user_id})
        assert alerts_response.status_code == 200
        alerts = alerts_response.get_json()["alerts"]
        assert any(alert["file_name"] == original.name for alert in alerts)
    finally:
        stop_response = client.post("/api/monitor/stop")
        assert stop_response.status_code == 200
