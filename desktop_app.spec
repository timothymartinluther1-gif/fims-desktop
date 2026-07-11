# PyInstaller spec for File Integrity Monitor desktop app.
# Build with:  pyinstaller desktop_app.spec
#
# Bundles index.html, script.js, style.css as read-only resources
# (resolved at runtime via resource_path() in app.py / sys._MEIPASS).
# The database and monitored uploads live outside the bundle, in the
# user's AppData folder (see app_data_dir() in app.py) so they survive
# even though the bundle itself is extracted fresh to a temp dir each run.

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('index.html', '.'),
        ('script.js', '.'),
        ('style.css', '.'),
    ],
    hiddenimports=['flask_cors', 'webview', 'requests', 'urllib3', 'idna', 'charset_normalizer', 'certifi', 'cryptography'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='IntegrityMonitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # no terminal window; set True temporarily if you need to debug
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,           # put an .ico path here once you have one, e.g. 'app_icon.ico'
    onefile=True,
)
