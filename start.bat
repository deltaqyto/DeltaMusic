@echo off
setlocal

if not exist "%~dp0.venv\Scripts\activate.bat" (
    echo No virtual environment found. Run setup.bat first.
    exit /b 1
)

rem pythonw runs the player without a console window attached.
rem replace with python.exe for debugging issues in the console
set "PYEXE=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYEXE%" set "PYEXE=%~dp0.venv\Scripts\python.exe"

start "DeltaMusic" /d "%~dp0" "%PYEXE%" main.py %*

endlocal
exit /b 0
