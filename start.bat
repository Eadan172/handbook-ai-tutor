@echo off
setlocal enableextensions
title AI Learning Tutor - Launcher

REM ============================================================
REM  AI Learning Tutor - one click local launcher
REM  - Double click to start backend + frontend and open the browser
REM  - Closing this window does NOT stop services and does NOT erase data
REM  - Data lives in: backend\tutor.db  and  data\storage\
REM ============================================================

REM ---------- 1. Resolve paths from this script location ----------
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "BE=%ROOT%\backend"
set "FE=%ROOT%\frontend"
set "DATA=%ROOT%\data"
set "DBFILE=%ROOT%\backend\tutor.db"
set "PYSITE=%ROOT%\.venv\Scripts\python.exe"

echo.
echo ============================================================
echo   AI Learning Tutor - local launcher
echo ============================================================
echo   Project : %ROOT%
echo.

REM ---------- 2. Preflight checks ----------
if not exist "%PYSITE%" goto :err_python
if not exist "%BE%\app\main.py" goto :err_layout
if not exist "%FE%\node_modules\next\dist\bin\next" goto :err_frontend

REM ---------- 3. Locate Node.js ----------
set "PF86=%ProgramFiles(x86)%"
set "NODE_DIR="
call :probe_node "D:\nodejs"
call :probe_node "%ProgramFiles%\nodejs"
call :probe_node "%PF86%\nodejs"
call :probe_node "%LOCALAPPDATA%\Programs\nodejs"
if not defined NODE_DIR for /f "delims=" %%N in ('where node 2^>nul') do call :probe_node "%%~dpN"
if not defined NODE_DIR goto :err_node

REM Give child windows this project venv python + detected node first
set "PATH=%ROOT%\.venv\Scripts;%NODE_DIR%;%PATH%"

REM Local ffmpeg (downloaded on demand into tools\ffmpeg). Video upload needs it
REM for audio extraction; without it mp4 ingest fails at the first step.
if exist "%ROOT%\tools\ffmpeg\bin\ffmpeg.exe" set "PATH=%ROOT%\tools\ffmpeg\bin;%PATH%"

REM ---------- 4. Runtime environment (all data is persisted on disk) ----------
if not exist "%DATA%" mkdir "%DATA%" >nul 2>&1
if not exist "%DATA%\storage" mkdir "%DATA%\storage" >nul 2>&1

call :tofwds "%DBFILE%"
set "DATABASE_URL=sqlite+aiosqlite:///%FWDS%"
set "DATABASE_URL_SYNC=sqlite:///%FWDS%"
set "TASK_BACKEND=inline"
set "STORAGE_BACKEND=local"
REM NOTE: do NOT set LOCAL_STORAGE_PATH here. Its code default is already
REM "%DATA%\storage", and a process environment variable would PIN it, which
REM would make the storage-location field on /settings/llm read-only. Leave it
REM to .env / the settings page.
REM NOTE: do NOT set LLM_DEFAULT_PROVIDER / LLM_PROVIDER_* here.
REM This process environment overrides the .env file, so pinning it to "mock"
REM would silently disable the real LLM. Routing is governed by .env instead.
REM NOTE: STT_PROVIDER is likewise left to .env (mock | faster_whisper) so the
REM video pipeline can be switched without editing this script.
set "RAG_PROVIDER=pgvector"
REM OCR: reading images / scanned PDFs. "auto" uses the offline ONNX engine when
REM it is installed, otherwise falls back to a vision LLM. OCR_LANG=auto switches
REM to the Japanese model automatically when kana come out at low confidence.
REM Leave these unset to use the defaults; override in .env when needed.
REM   set "OCR_PROVIDER=auto"
REM   set "OCR_LANG=auto"
set "SECRET_KEY=dev-secret-change-me-use-at-least-32-bytes"
set "CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000"
set "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000"

REM ---------- 5. Start backend ----------
call :port_busy 8000
if "%BUSY%"=="1" goto :be_running
echo   [start] backend api on port 8000 ...
start "AI Tutor Backend (8000)" /D "%BE%" cmd /k "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
goto :be_done
:be_running
REM A listener on 8000 is not proof of a working API. If the process was started
REM by hand without the local env vars below, it tried to reach the postgres /
REM redis hosts named in .env and died on startup -- while still holding the port
REM for a moment? No: it exits, but a zombie or an unrelated service can linger.
REM Either way the UI then shows "Failed to fetch" on sign in, so probe /health.
echo   [reuse] port 8000 is busy, checking it answers /health ...
set /a HCHK=0
:be_health
curl -f -s -o NUL -m 3 "http://127.0.0.1:8000/health" >nul 2>&1
if not errorlevel 1 goto :be_healthy
set /a HCHK+=1
if %HCHK% GEQ 10 goto :be_unhealthy
timeout /t 1 /nobreak >nul 2>&1
goto :be_health
:be_healthy
echo   [reuse] existing backend answered /health, keeping it
goto :be_done
:be_unhealthy
echo.
echo   ************************************************************
echo   WARNING
echo   Something is listening on port 8000 but /health does NOT
echo   answer. The web page will show "Failed to fetch" when you
echo   try to sign in.
echo.
echo   Close the stale process and run this script again:
echo.
echo     powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"
echo.
echo   Most likely cause: the API was started by hand WITHOUT the
echo   local env vars, so it tried to reach the postgres / redis
echo   hosts in .env and exited. Always start it with this script,
echo   or with:  bash scripts/run_local_backend.sh
echo   ************************************************************
echo.
goto :be_done
:be_done

REM ---------- 6. Start frontend ----------
call :port_busy 3000
if "%BUSY%"=="1" goto :fe_running
echo   [start] frontend on port 3000 ...
start "AI Tutor Frontend (3000)" /D "%FE%" cmd /k "node node_modules\next\dist\bin\next start -p 3000"
goto :fe_done
:fe_running
echo   [reuse] port 3000 already listening, keeping the running frontend
:fe_done

REM ---------- 7. Wait until both are ready ----------
echo.
call :wait_url "http://127.0.0.1:8000/health" "backend api"
call :wait_url "http://127.0.0.1:3000/" "frontend ui"

REM ---------- 8. Open the browser ----------
echo.
if /i "%~1"=="/nobrowser" goto :no_browser
echo   [open] browser http://localhost:3000
start "" "http://localhost:3000"
goto :done
:no_browser
echo   [skip] /nobrowser given, browser not opened
:done

echo.
echo ============================================================
echo   Ready
echo ============================================================
echo   App      : http://localhost:3000
echo   API docs : http://127.0.0.1:8000/docs
echo.
echo   Data     : backend\tutor.db   (accounts, sources, quizzes)
echo              data\storage\      (uploaded files)
echo   Closing this window keeps services and data intact.
echo   To stop, close the "AI Tutor Backend" and
echo   "AI Tutor Frontend" windows.
echo ============================================================
echo.
pause
goto :eof

REM ============================================================
REM  Subroutines
REM ============================================================

REM Record %1 as node dir when it holds node.exe
:probe_node
if defined NODE_DIR goto :eof
if exist "%~1\node.exe" set "NODE_DIR=%~1"
goto :eof

REM Backslashes to forward slashes, result in FWDS
:tofwds
set "FWDS=%~1"
set "FWDS=%FWDS:\=/%"
goto :eof

REM BUSY=1 when port %1 is already listened on
:port_busy
set "BUSY=0"
netstat -an | findstr /c:":%~1 " | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 set "BUSY=1"
goto :eof

REM Poll %1 until it answers, 90s budget, label %2
:wait_url
setlocal
set "URL=%~1"
set "LABEL=%~2"
set /a TRIES=0
:wu_loop
curl -f -s -o NUL -m 3 "%URL%" >nul 2>&1
if not errorlevel 1 goto :wu_ok
set /a TRIES+=1
if %TRIES% GEQ 90 goto :wu_fail
timeout /t 1 /nobreak >nul 2>&1
goto :wu_loop
:wu_ok
echo   [ready] %LABEL%
endlocal
goto :eof
:wu_fail
echo   [timeout] %LABEL% not ready within 90s, check its window for errors
endlocal
goto :eof

REM ============================================================
REM  Error messages
REM ============================================================

:err_python
echo   [ERROR] python venv not found: %PYSITE%
echo           Run these first:
echo             python -m venv .venv
echo             .venv\Scripts\python.exe -m pip install -e "./backend[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
goto :halt

:err_layout
echo   [ERROR] missing %BE%\app\main.py
echo           Keep start.bat next to the backend and frontend folders.
goto :halt

:err_frontend
echo   [ERROR] frontend dependencies missing: %FE%\node_modules
echo           Run first:
echo             cd frontend
echo             npm install
goto :halt

:err_node
echo   [ERROR] Node.js not found. Install Node.js 18+ and make sure node.exe is on PATH.
goto :halt

:halt
echo.
pause
endlocal
exit /b 1
