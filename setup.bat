@echo off
setlocal enabledelayedexpansion

echo ============================================================================
echo  SANGVAIL - Blood Bank Inventory, Operations ^& Demand Intelligence Platform
echo  Windows Setup Script
echo ============================================================================
echo.

cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    set "PYTHON_CMD=py"
) else (
    where python >nul 2>nul
    if %ERRORLEVEL%==0 (
        set "PYTHON_CMD=python"
    ) else (
        echo [ERROR] Python 3.11+ was not found on PATH.
        echo Install Python from https://www.python.org/downloads/ and re-run setup.bat.
        exit /b 1
    )
)

echo [1/5] Checking Python version...
%PYTHON_CMD% --version
if errorlevel 1 (
    echo [ERROR] Failed to execute Python.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [2/5] Creating project virtual environment ^(.venv^)...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo [2/5] Existing virtual environment found ^(.venv^). Reusing.
)

echo [3/5] Installing Python dependencies from requirements.txt...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check internet connection or Python version.
    exit /b 1
)

echo [4/5] Preparing local directories and configuration...
if not exist "data" mkdir data
if not exist "data\synthetic" mkdir data\synthetic
if not exist "reports" mkdir reports
if not exist "exports" mkdir exports
if not exist "ml\saved_models" mkdir ml\saved_models

if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo       Created .env from .env.example ^(SQLite local fallback enabled^).
    )
) else (
    echo       Existing .env detected. Preserved without overwriting.
)

echo [5/5] Initializing database schema, views, and operational dataset...
".venv\Scripts\python.exe" database\seed_data.py
if errorlevel 1 (
    echo [ERROR] Database initialization failed.
    exit /b 1
)

echo.
echo [SUCCESS] SANGVAIL setup complete.
echo Run "run.bat" to launch the workstation at http://localhost:8501
echo Default login: admin / admin123
echo.
exit /b 0
