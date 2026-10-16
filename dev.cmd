@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "OSS_PYTHON="
if exist "%~dp0.venv\Scripts\python.exe" call :choose_python "%~dp0.venv\Scripts\python.exe"
if not defined OSS_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" call :choose_python "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not defined OSS_PYTHON for /f "delims=" %%P in ('where python 2^>nul') do if not defined OSS_PYTHON call :choose_python "%%P"
if not defined OSS_PYTHON for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do if not defined OSS_PYTHON call :choose_python "%%P"
if not defined OSS_PYTHON (
    echo Python 3.11 or newer with openpyxl, python-dotenv, openai, reportlab, and playwright was not found.
    echo Run python -m pip install -e ".[ax-llm]" in this folder, then retry.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
"%OSS_PYTHON%" "%~dp0scripts\start_dev.py" %*
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0

:choose_python
"%~1" -c "import sys, openpyxl, dotenv, openai, reportlab, playwright; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 set "OSS_PYTHON=%~1"
exit /b 0
