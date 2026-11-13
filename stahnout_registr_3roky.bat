@echo off
rem Stahne Registr smluv za 3 roky najednou (misto postupneho doplnovani na GitHubu, ktere trva asi tyden)
rem a nahraje databazi pro online verzi (vetev "data" na GitHubu).
rem Trva 2 az 4 hodiny podle rychlosti internetu (stahuje se cca 25-40 GB, zpracovane soubory se hned mazou).
rem Nespoustejte mezi 5:00 a 6:30 rano, kdy bezi aktualizace na GitHubu.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m pip install -q --disable-pip-version-check -r requirements.txt
%PY% aktualizovat_db.py --online-db auto --jen-registr || goto chyba
%PY% pripravit_db.py --db data\online.db --limit 95 || goto chyba
%PY% nahrat_data.py || goto chyba
echo.
echo Hotovo. Online verze bude mit Registr smluv za 3 roky po pristim startu (na Renderu Manual Deploy - Restart service).
pause
exit /b 0
:chyba
echo.
echo Neco se nepovedlo, podivejte se na hlasky vyse. Spustte znovu, uz stazene mesice se preskoci.
pause
exit /b 1
