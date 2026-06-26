@echo off
cd /d "%~dp0"
echo Installing dependencies (first run only)...
pip install -r requirements.txt
echo.
echo Starting Dota 2 Replay Tool...
echo Open http://127.0.0.1:5000 in your browser.
python app.py
pause
