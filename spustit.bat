@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Prvni spusteni: vytvarim prostredi a instaluji knihovny...
  py -m venv .venv 2>nul || python -m venv .venv
)
rem doinstaluje knihovny pridane v nove verzi (kdyz uz jsou, trva to par sekund)
.venv\Scripts\python -m pip install -q --disable-pip-version-check -r requirements.txt
echo.
echo  TenderScope - konkurenceschopnost firem ve verejnych zakazkach
echo.
echo  1) APLIKACE - realna data   (otevre se v prohlizeci)
echo  2) APLIKACE - demo data     (vymyslene firmy, bez internetu)
echo  3) Textovy brief pro obor IT (prikazova radka)
echo  4) Textovy brief pro stavebnictvi
echo.
set /p volba=Vyber cislo: 
if "%volba%"=="1" .venv\Scripts\python server.py
if "%volba%"=="2" .venv\Scripts\python server.py --demo
if "%volba%"=="3" .venv\Scripts\python tenderscope.py run --obor it --rychle
if "%volba%"=="4" .venv\Scripts\python tenderscope.py run --obor stavebnictvi --rychle
pause
