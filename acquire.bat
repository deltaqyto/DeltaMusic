@echo off
setlocal

if not exist "%~dp0.venv\Scripts\activate.bat" (
    echo No virtual environment found. Run setup.bat first.
    pause
    exit /b 1
)

call "%~dp0.venv\Scripts\activate.bat"
if errorlevel 1 (
    echo Could not activate the virtual environment.
    pause
    exit /b 1
)

pushd "%~dp0"
python -m entry.acquire %*
set "RC=%errorlevel%"
popd

echo.
echo Acquisition exited with code %RC%.
pause

endlocal & exit /b %RC%
