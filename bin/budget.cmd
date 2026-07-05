@echo off
setlocal
set "DIR=%~dp0..\budgets"
set "URL=https://budget.tubby.asia"

if /i "%~1"=="stop" (
  rem stops the LOCAL dev server only - never Docker, never the droplet
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":5002 .*LISTENING"') do (
    tasklist /fi "PID eq %%p" 2>nul | findstr /i "python" >nul && taskkill /pid %%p /f >nul 2>&1 && echo local budgets stopped
  )
  exit /b 0
)

if /i "%~1"=="local" (
  netstat -ano | findstr /r /c:":5002 .*LISTENING" >nul 2>&1
  if errorlevel 1 (
    echo starting local budgets on port 5002...
    start "budgets :5002" /min /d "%DIR%" cmd /k python scripts\gui.py
    ping -n 3 127.0.0.1 >nul
  )
  start "" http://127.0.0.1:5002
  exit /b 0
)

if /i "%~1"=="deploy" (
  echo deploying budgets subtree to droplet...
  tar -czf - --exclude=budgets/data --exclude=budgets/samples --exclude=__pycache__ -C "%~dp0.." budgets | ssh avery "tar xzf - -C /opt --overwrite && systemctl restart budgets && sleep 2 && echo service: $(systemctl is-active budgets)"
  exit /b %errorlevel%
)

start "" %URL%
