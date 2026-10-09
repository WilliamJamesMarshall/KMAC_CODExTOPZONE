@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "OSS_URL=http://127.0.0.1:8765"

rem An already running OSS server can be reused.
powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Uri '%OSS_URL%/api/demo' -TimeoutSec 2; if ($r.analysis_meta) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 (
    start "" "%OSS_URL%"
    exit /b 0
)

set "OSS_PYTHON="
if exist "%~dp0.venv\Scripts\python.exe" call :choose_python "%~dp0.venv\Scripts\python.exe"
if not defined OSS_PYTHON if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" call :choose_python "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not defined OSS_PYTHON for /f "delims=" %%P in ('where python 2^>nul') do if not defined OSS_PYTHON call :choose_python "%%P"
if not defined OSS_PYTHON for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do if not defined OSS_PYTHON call :choose_python "%%P"
if not defined OSS_PYTHON (
    echo Python 3.11 or newer with openpyxl was not found.
    echo Run python -m pip install -e . in this folder, then retry.
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
start "OSS AX local server" /min "%OSS_PYTHON%" -m oss.web_server --port 8765
powershell -NoProfile -Command "$url='%OSS_URL%'; for ($i=0; $i -lt 40; $i++) { try { $r=Invoke-RestMethod -Uri ($url+'/api/demo') -TimeoutSec 2; if ($r.analysis_meta) { Start-Process $url; exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
    echo Local server did not start. Check the Python window for details.
    pause
    exit /b 1
)
exit /b 0

:choose_python
"%~1" -c "import sys, openpyxl; assert sys.version_info >= (3, 11)" >nul 2>&1
if not errorlevel 1 set "OSS_PYTHON=%~1"
exit /b 0
