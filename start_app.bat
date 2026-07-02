@echo off
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python -m pip install -r requirements.txt
    python app.py
) else (
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -3 -m pip install -r requirements.txt
        py -3 app.py
    ) else (
        echo Python was not found on this computer.
        echo Please install Python 3 and run this script again.
        pause
        exit /b 1
    )
)

pause
