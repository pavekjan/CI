@echo off
rem Stahne cerstva data na tomto pocitaci a nahraje je pro online verzi (vetev "data" na GitHubu).
rem Da se spoustet automaticky kazdy den pres Planovac uloh Windows (viz README, kapitola 5).
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% aktualizovat_db.py || goto chyba
%PY% pripravit_db.py --limit 95 || goto chyba
%PY% nahrat_data.py || goto chyba
echo.
echo Hotovo. Online verze bude mit nova data po pristim startu (nejpozdeji po usnuti a probuzeni).
if "%1"=="/tichy" exit /b 0
pause
exit /b 0
:chyba
echo.
echo Neco se nepovedlo, podivejte se na hlasky vyse.
if "%1"=="/tichy" exit /b 1
pause
exit /b 1
