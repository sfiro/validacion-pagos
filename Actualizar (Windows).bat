@echo off
REM Doble clic para descargar la ultima version desde GitHub.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Falta instalar Python 3: https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% actualizar.py
pause
