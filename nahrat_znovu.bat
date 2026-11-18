@echo off
rem Rychle (par minut): pripravi uz stazenou databazi data\online.db pro slaby online server
rem (predpocita prehledy trhu) a znovu ji nahraje na GitHub. Nic se nestahuje.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% predpocitat.py data\online.db || goto chyba
%PY% pripravit_db.py --db data\online.db --limit 95 || goto chyba
%PY% nahrat_data.py || goto chyba
echo.
echo HOTOVO. Na Renderu dejte Manual Deploy - Restart service.
pause
exit /b 0
:chyba
echo.
echo Neco se nepovedlo, podivejte se na hlasky vyse.
pause
exit /b 1
