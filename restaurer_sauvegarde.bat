@echo off
REM Restaurer une sauvegarde de la base ODDO Sequences.
REM L'application doit etre fermee avant (fenetre noire fermee).
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
    echo Lancez d'abord start.bat une fois pour installer l'application.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m app.restore
pause
