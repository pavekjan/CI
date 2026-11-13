@echo off
rem VSE NAJEDNOU, NA NOC: zakazky z ISVZ (12 mesicu) + Registr smluv za 3 roky + nahrani pro online verzi.
rem Spustte jednou a nechte bezet (typicky 3 az 6 hodin podle internetu a procesoru). Nic se nepta.
rem Kdyz se beh prerusi, spustte znovu: hotove mesice se preskoci.
rem Nespoustejte mezi 5:00 a 6:30 rano, kdy bezi aktualizace na GitHubu.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% -m pip install -q --disable-pip-version-check -r requirements.txt
%PY% aktualizovat_db.py --online-db auto --vse-najednou --ai 400 || goto chyba
%PY% pripravit_db.py --db data\online.db --limit 95 || goto chyba
%PY% nahrat_data.py || goto chyba
echo.
echo HOTOVO. Na Renderu dejte Manual Deploy - Restart service (nebo pockejte na probuzeni) a data jsou online.
pause
exit /b 0
:chyba
echo.
echo Neco se nepovedlo, podivejte se na hlasky vyse. Spustte znovu, uz hotove mesice se preskoci.
pause
exit /b 1
