@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    exit /b 1
)

echo Running SANGVAIL automated test suite...
".venv\Scripts\python.exe" -m pytest -v
set "TEST_EXIT=%ERRORLEVEL%"

if not "%TEST_EXIT%"=="0" (
    echo.
    echo [FAIL] One or more tests failed ^(exit code %TEST_EXIT%^).
    exit /b %TEST_EXIT%
)

echo.
echo [PASS] All SANGVAIL tests passed.
exit /b 0
