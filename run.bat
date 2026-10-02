@echo off
cd /d "%~dp0"
title Meteo Agent 2300m

echo ====================================================
echo    Meteo Agent - altitude 2300 m
echo ====================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo IMPORTANT: check "Add python.exe to PATH" during install.
    pause
    exit /b 1
)

echo [OK] Python found:
python --version
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment already exists.
)
echo.

echo [2/4] Activating environment ...
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] Failed to activate .venv
    pause
    exit /b 1
)
echo.

echo [3/4] Installing dependencies (may take 1-2 min) ...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    echo Check your internet connection.
    pause
    exit /b 1
)
echo.

echo [4/4] Starting application ...
echo.
echo ====================================================
echo   Browser will open at: http://localhost:8501
echo   To stop - press Ctrl+C in this window.
echo ====================================================
echo.

REM Открываем браузер вручную - ровно один раз
start "" http://localhost:8501

REM --server.headless=true запрещает Streamlit открывать свой браузер
python -m streamlit run app.py --server.headless=true

echo.
echo Application stopped.
pause