@echo off
REM ODDO Sequences - lanceur Windows.
REM Premier lancement : cree l'environnement Python et installe les dependances.
REM Lancements suivants : reinstalle seulement si requirements.txt a change.
setlocal
cd /d "%~dp0"
title ODDO Sequences - ne pas fermer cette fenetre

REM Bascule V2.6 : le mode test n'est plus verrouille. Il reste ACTIVE tant que vous ne le
REM desactivez pas vous-meme dans Reglages > Mode test.

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creation de l'environnement Python...
    py -3.12 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 goto :no_python
)

fc /b requirements.txt ".venv\requirements.installed" >nul 2>&1
if errorlevel 1 (
    echo [2/3] Installation des dependances, quelques minutes la premiere fois...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 goto :pip_failed
    copy /y requirements.txt ".venv\requirements.installed" >nul
)

echo [3/3] Demarrage...
".venv\Scripts\python.exe" -m app.launcher %*
if errorlevel 1 (
    echo.
    echo L'application s'est arretee avec une erreur. Voir data\logs\app.log
    pause
)
exit /b 0

:no_python
echo.
echo Python 3.12 est introuvable. Installez-le depuis python.org en cochant
echo "Add python.exe to PATH", puis relancez start.bat. Voir README.md.
pause
exit /b 1

:pip_failed
echo.
echo L'installation des dependances a echoue. Verifiez la connexion internet
echo puis relancez start.bat.
pause
exit /b 1
