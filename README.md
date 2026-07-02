# Integrity Monitor

A local file-integrity monitor with a web-style dashboard, packaged as a Windows desktop app.

## Why desktop, not hosted?

This app watches files on the machine it runs on. A website hosted on Vercel/Railway/etc.
runs in a datacenter and has no access to a visitor's local files — browsers don't allow
that, for good security reasons. So "monitor files on the systems using it" requires the
app to actually run on those systems, as a local/desktop app. That's what this build does.

## Run from source (development)

```
pip install -r requirements.txt
python desktop_app.py
```

This starts the Flask backend on `127.0.0.1` (a free port, preferring 5000) and opens it
in a native app window (via `pywebview`) — no browser required.

You can still run the old browser-based flow if you want:
```
python app.py
```
then open `http://localhost:5000` yourself.

## Build a Windows .exe

**Option 1 — GitHub Actions (recommended, no Windows machine needed):**
Push to `main`. The workflow in `.github/workflows/build-windows.yml` builds the app on a
real Windows runner and uploads `IntegrityMonitor.exe` as a downloadable artifact under the
Actions tab of your repo run. You can also trigger it manually from the Actions tab
("Run workflow").

**Option 2 — build locally on a Windows machine:**
```
pip install -r requirements.txt
pip install -r requirements-build.txt
pyinstaller desktop_app.spec
```
The finished executable is at `dist/IntegrityMonitor.exe` — a single file, no Python
install required on the end user's machine.

## Where data is stored

The database and monitored file copies live in the user's local app-data folder, **not**
inside the install folder (which may be read-only, e.g. under `Program Files`):
- Windows: `%LOCALAPPDATA%\IntegrityMonitor\`
- macOS/Linux: `~/.local/share/IntegrityMonitor/`

## Turning the .exe into a proper installer (optional, next step)

Right now `IntegrityMonitor.exe` is a single portable executable — users can just double-click
it, no install needed. If you'd like a "real" installer experience (Start Menu shortcut,
uninstaller, Program Files placement), the next step is wrapping it with
Inno Setup (jrsoftware.org/isinfo.php) — ask and this can be added.
