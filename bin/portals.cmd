@echo off
setlocal
set "ROOT=%~dp0.."

if /i "%~1"=="stop" (
  call :stopport 5000 replay-gui
  call :stopport 5001 running
  call :stopport 5002 budgets
  exit /b 0
)

call :launch "replay-gui" 5000 "%ROOT%\dota-replay-gui" app.py
call :launch "running"    5001 "%ROOT%\running"         scripts\gui.py
call :launch "budgets"    5002 "%ROOT%\budgets"         scripts\gui.py
echo.
echo   replay-gui   http://127.0.0.1:5000
echo   running      http://127.0.0.1:5001
echo   budgets      http://127.0.0.1:5002
exit /b 0

:launch
netstat -ano | findstr /r /c:":%~2 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo   [up]     %~1 : port %~2 already listening
) else (
  echo   [start]  %~1 : port %~2
  start "%~1 :%~2" /min /d "%~3" cmd /k python %~4
)
exit /b 0

:stopport
rem only kills python listeners - never Docker or other processes on the port
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%~1 .*LISTENING"') do (
  tasklist /fi "PID eq %%p" 2>nul | findstr /i "python" >nul && taskkill /pid %%p /f >nul 2>&1 && echo   [stop]   %~2 : port %~1
)
exit /b 0
