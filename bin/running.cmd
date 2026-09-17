@echo off
setlocal
set "ROOT=%~dp0.."
set "APP=%ROOT%\running"
set "PYW=C:\Users\etern\AppData\Local\Programs\Python\Python311\pythonw.exe"

netstat -ano | findstr /r /c:":5001 .*LISTENING" >nul 2>&1
if errorlevel 1 (set "UP=0") else (set "UP=1")

if /i "%~1"=="stop" (
  if "%UP%"=="0" (
    echo   [down]   running : port 5001 was not running
  ) else (
    rem only kills python listeners - never Docker or other processes on the port
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":5001 .*LISTENING"') do (
      tasklist /fi "PID eq %%p" 2>nul | findstr /i "python" >nul && taskkill /pid %%p /f >nul 2>&1 && echo   [stop]   running : port 5001
    )
  )
  exit /b 0
)

if "%UP%"=="1" (
  echo   [up]     running : port 5001 already listening
) else (
  echo   [start]  running : port 5001
  start "" /d "%APP%" "%PYW%" scripts\serve.pyw
)
if /i not "%~1"=="noopen" start "" http://127.0.0.1:5001
echo   running      http://127.0.0.1:5001
exit /b 0
