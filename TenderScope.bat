@echo off
rem Primo spusti aplikaci s realnymi daty (bez menu)
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Prvni spusteni: vytvarim prostredi a instaluji knihovny...
  py -m venv .venv 2>nul || python -m venv .venv
)
rem doinstaluje knihovny pridane v nove verzi (kdyz uz jsou, trva to par sekund)
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
.venv\Scripts\python server.py
pause
