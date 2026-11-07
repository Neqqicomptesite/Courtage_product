@echo off
REM Lance tous les tests automatiques (aucun email reel n'est envoye :
REM les tests utilisent de faux serveurs sur ce PC, et une base temporaire).
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
    echo Lancez d'abord start.bat une fois pour installer l'application.
    pause
    exit /b 1
)
echo Installation des outils de test (la premiere fois seulement)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-dev.txt
if errorlevel 1 (
    echo Installation impossible : verifiez la connexion internet.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q -p no:cacheprovider
echo.
echo Resultat ci-dessus : la derniere ligne doit indiquer "passed" sans "failed".
pause
