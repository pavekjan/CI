@echo off
rem Ukaze, kam dosla posledni aktualizace (pocty v databazi, posledni kroky, konec logu)
rem a jestli se pocitac v noci restartoval nebo usnul.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% stav_behu.py
echo.
echo == Restarty a vypnuti pocitace za posledni 2 dny (Windows):
powershell -NoProfile -Command "Get-WinEvent -FilterHashtable @{LogName='System'; Id=1074,41,6008,42,1; StartTime=(Get-Date).AddDays(-2)} -ErrorAction SilentlyContinue | Select-Object -First 12 TimeCreated, Id, @{n='Co';e={($_.Message -split [Environment]::NewLine)[0]}} | Format-Table -AutoSize -Wrap"
pause
