@echo off
REM Windows: double-click this file.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul || (echo Python 3 not found. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) & pause & exit /b 1)
if not exist .venv (
  echo First run: creating a private Python environment ^(one-time, about 1 minute^)...
  %PY% -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip >nul
  .venv\Scripts\pip install -r requirements.txt || (echo Package install failed - see messages above. & pause & exit /b 1)
)
if not exist .env copy .env.example .env >nul
start "" http://127.0.0.1:8765
.venv\Scripts\python -m app.server
pause
