"""
Desktop launcher for File Integrity Monitor.

Runs the Flask backend in a background thread and opens it in a native
app window via pywebview, so end users get a real desktop app instead of
having to open a browser and type localhost:5000.

This is the entry point PyInstaller builds into the .exe.
"""
import socket
import sys
import threading
import time
import traceback

import webview  # pywebview

import app as backend  # our Flask app module (app.py)


def show_error_dialog(title: str, message: str) -> None:
    """Native Windows message box - no extra dependency (ctypes is
    built into Python), and doesn't require a console window. This is
    the only way anyone would ever see a startup failure, since the
    build runs with console=False (needed to avoid the earlier
    flashing-console-window bug)."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:
        print(f"{title}: {message}")


def log_crash(context: str, exc: BaseException) -> None:
    try:
        log_path = backend.APP_DATA_DIR / "crash_log.txt"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {context} ---\n")
            f.write(traceback.format_exc())
        return log_path
    except Exception:
        return None


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


backend_start_error = None


def start_backend(host: str, port: int) -> None:
    global backend_start_error
    try:
        backend.init_db()
        with backend.monitor_lock:
            if not backend.monitor_running:
                backend.monitor_running = True
                threading.Thread(target=backend.monitor_files, daemon=True).start()
        # threaded=True lets the UI keep polling (setInterval) while requests are in flight
        backend.app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
    except Exception as exc:
        backend_start_error = exc
        log_crash("start_backend", exc)


class Api:
    """Exposed to the frontend as window.pywebview.api.

    create_file_dialog is pywebview's native OS file picker. Unlike an
    HTML <input type="file">, it returns the real absolute path on disk -
    which is what lets the backend monitor the user's actual file in
    place instead of a private copy.
    """

    def pick_file(self):
        try:
            result = webview.windows[0].create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False)
        except Exception:
            return None
        if not result:
            return None
        return result[0]

    def pick_save_location(self, default_name=""):
        """Used when restoring a cloud backup - lets the user choose where
        to save the recovered file."""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.SAVE_DIALOG, save_filename=default_name or "restored_file"
            )
        except Exception:
            return None
        if not result:
            return None
        return result if isinstance(result, str) else result[0]


def main() -> None:
    host = "127.0.0.1"
    port = find_free_port(5000)

    server_thread = threading.Thread(target=start_backend, args=(host, port), daemon=True)
    server_thread.start()

    if not wait_for_server(host, port):
        if backend_start_error is not None:
            log_path = log_crash("main", backend_start_error)
            show_error_dialog(
                "Integrity Monitor failed to start",
                f"The app couldn't start due to an internal error:\n\n{backend_start_error}\n\n"
                f"Details were saved to:\n{log_path or '(could not write log file)'}\n\n"
                "Please share this file so the issue can be fixed.",
            )
        else:
            show_error_dialog(
                "Integrity Monitor failed to start",
                "The app's background server didn't respond in time. "
                "Try running it again - if this keeps happening, check "
                "for a crash_log.txt file in %LOCALAPPDATA%\\IntegrityMonitor.",
            )
        sys.exit(1)

    webview.create_window(
        "File Integrity Monitor",
        f"http://{host}:{port}",
        width=1280,
        height=860,
        min_size=(960, 640),
        js_api=Api(),
    )
    webview.start(debug=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log_path = log_crash("main (top-level)", exc)
        show_error_dialog(
            "Integrity Monitor failed to start",
            f"An unexpected error occurred:\n\n{exc}\n\n"
            f"Details were saved to:\n{log_path or '(could not write log file)'}\n\n"
            "Please share this file so the issue can be fixed.",
        )
        sys.exit(1)
