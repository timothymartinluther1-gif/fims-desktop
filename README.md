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

## Android app

A native Kotlin/Jetpack Compose app lives in `android/`. It shares the same
Supabase accounts as the desktop app - register on one, log in on the other.

**Why it's a separate codebase, not a port:** Android sandboxes file access
(no arbitrary paths - files are picked via the system file picker and
accessed by permission-scoped URI) and throttles background processes
aggressively. Continuous 3-second polling like the desktop app isn't
possible; instead it checks every monitored file **every 15 minutes** via
WorkManager, Android's minimum interval for periodic background work.

**Build it (GitHub Actions, no Android Studio needed):**
Push to `main` and the workflow in `.github/workflows/build-android.yml`
builds a debug APK on a CI runner and uploads it as `IntegrityMonitor-android`
under the Actions tab, the same way the Windows build works.

**Build it locally** (needs Android Studio / Android SDK):
```
cd android
./gradlew assembleDebug
```
(If there's no `gradlew` wrapper checked in, open the `android/` folder in
Android Studio once and it will generate one, or run `gradle assembleDebug`
if you have Gradle installed.)

**Installing the APK:** since it's not signed for the Play Store, Android
will show an "install blocked" / "unknown sources" warning the first time -
same idea as the Windows SmartScreen warning, not a bug. Enable
"Install unknown apps" for whichever app you use to open the APK file.

**Heads up:** this Kotlin project was written and reviewed carefully but
could not be compiled or run in this environment (no Android SDK, no
network access here) - the very first CI build may surface an issue that
needs a follow-up fix, the same way the Windows build did.

## Turning the .exe into a proper installer (optional, next step)

Right now `IntegrityMonitor.exe` is a single portable executable — users can just double-click
it, no install needed. If you'd like a "real" installer experience (Start Menu shortcut,
uninstaller, Program Files placement), the next step is wrapping it with
Inno Setup (jrsoftware.org/isinfo.php) — ask and this can be added.
