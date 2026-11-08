@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Python is not installed. Get it from python.org and tick "Add Python to PATH". & pause & exit /b 1)
if not exist .venv ( python -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
python -m streamlit run app.py
pause
