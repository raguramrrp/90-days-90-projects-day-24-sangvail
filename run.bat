@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

echo ============================================================================
echo  Starting SANGVAIL Workstation
echo  Local URL : http://localhost:8501
echo  Login     : admin / admin123
echo ============================================================================
echo.

".venv\Scripts\python.exe" database\seed_data.py
if errorlevel 1 (
    echo [ERROR] Database check failed. Review the error output above.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m streamlit run app\main.py --server.port=8501 --server.address=localhost
if errorlevel 1 (
    echo.
    echo [ERROR] SANGVAIL exited with an error.
    pause
    exit /b 1
)
