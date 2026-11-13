@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Prvni spusteni: vytvarim prostredi a instaluji knihovny...
  py -m venv .venv 2>nul || python -m venv .venv
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
echo.
echo  TenderScope - competitive intelligence pro verejne zakazky
echo  1) Demo na umelych datech (bez internetu, cca 10 s)
echo  2) Ostry beh - IT sluzby (stahne data za 12 mesicu)
echo  3) Ostry beh - stavebnictvi
echo  4) Jen prepocitat analyzu z uz stazenych dat
echo  5) Profil firmy z ARES
echo.
set /p volba=Vyber cislo: 
if "%volba%"=="1" .venv\Scripts\python tenderscope.py demo
if "%volba%"=="2" .venv\Scripts\python tenderscope.py run --obor it
if "%volba%"=="3" .venv\Scripts\python tenderscope.py run --obor stavebnictvi
if "%volba%"=="4" .venv\Scripts\python tenderscope.py run --bez-stahovani
if "%volba%"=="5" goto firma
goto konec
:firma
set /p ico=Zadej ICO: 
.venv\Scripts\python tenderscope.py firma %ico%
:konec
pause
