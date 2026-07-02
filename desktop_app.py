"""
Desktop launcher for File Integrity Monitor.

Runs the Flask backend in a background thread and opens it in a native
app window via pywebview, so end users get a real desktop app instead of
having to open a browser and type localhost:5000.

This is the entry point PyInstaller builds into the .exe.
"""
import socket
import threading
import time

import webview  # pywebview

import app as backend  # our Flask app module (app.py)


def find_free_port(preferred: int = 5000) -> int:
    """Use the preferred port if free, otherwise let the OS pick one."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Could not find a free port")


def wait_for_server(host: str, port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.15)
    return False


def start_backend(host: str, port: int) -> None:
    backend.init_db()
    with backend.monitor_lock:
        if not backend.monitor_running:
            backend.monitor_running = True
            threading.Thread(target=backend.monitor_files, daemon=True).start()
    # threaded=True lets the UI keep polling (setInterval) while requests are in flight
    backend.app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


def main() -> None:
    host = "127.0.0.1"
    port = find_free_port(5000)

    server_thread = threading.Thread(target=start_backend, args=(host, port), daemon=True)
    server_thread.start()

    if not wait_for_server(host, port):
        raise RuntimeError("Backend server did not start in time.")

    webview.create_window(
        "File Integrity Monitor",
        f"http://{host}:{port}",
        width=1280,
        height=860,
        min_size=(960, 640),
    )
    webview.start()


if __name__ == "__main__":
    main()
