@echo off
setlocal

set "ROOT=%~dp0"

if not exist "%ROOT%.venv\Scripts\activate.bat" (
    echo No virtual environment found. Run setup.bat first.
    exit /b 1
)

call "%ROOT%.venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

set "DELTAMUSIC_ONEFILE="
set "CLEAN="

:args
if "%~1"=="" goto :ready
if /i "%~1"=="onefile" set "DELTAMUSIC_ONEFILE=1"
if /i "%~1"=="clean" set "CLEAN=1"
shift /1
goto :args

:ready
python -m pip install -r "%ROOT%requirements-build.txt"
if errorlevel 1 goto :fail

if defined CLEAN (
    if exist "%ROOT%build" rd /s /q "%ROOT%build"
    if exist "%ROOT%dist" rd /s /q "%ROOT%dist"
)

python "%ROOT%build-tools\make_icon.py" "%ROOT%build-tools\icon.ico"
if errorlevel 1 goto :fail

python -m PyInstaller --noconfirm --distpath "%ROOT%dist" --workpath "%ROOT%build" "%ROOT%build-tools\DeltaMusic.spec"
if errorlevel 1 goto :fail

echo.
if defined DELTAMUSIC_ONEFILE (
    echo Built %ROOT%dist\DeltaMusic.exe
) else (
    echo Built %ROOT%dist\DeltaMusic\DeltaMusic.exe
)
endlocal
exit /b 0

:fail
echo Build failed.
endlocal
pause
exit /b 1
