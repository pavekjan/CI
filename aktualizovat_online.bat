@echo off
rem Stahne cerstva data na tomto pocitaci a nahraje je pro online verzi (vetev "data" na GitHubu).
rem Da se spoustet automaticky kazdy den pres Planovac uloh Windows (viz README, kapitola 5).
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
rem doinstaluje knihovny z requirements.txt (kdyz uz jsou, trva to par sekund)
%PY% -m pip install -q --disable-pip-version-check -r requirements.txt
rem Vezme aktualni online databazi (Registr smluv do ni kazdy den doplnuje GitHub Actions)
rem a doplni do ni zakazky z ISVZ, ktere jdou stahnout jen z ceskeho pocitace. Staci jednou za mesic.
rem --ai 400: zakazky, ktere nejdou zaradit podle nazvu, zkusi zaradit AI (jen kdyz je nastavena na strance Data)
%PY% aktualizovat_db.py --online-db auto --jen-zakazky --ai 400 || goto chyba
%PY% pripravit_db.py --db data\online.db --limit 95 || goto chyba
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
