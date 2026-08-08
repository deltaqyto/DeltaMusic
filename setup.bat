@echo off
setlocal

rem Run from inside a clone, or from an empty folder to create one.
rem REPO carries no trailing backslash: git clone rejects a destination ending in a separator or a dot.
pushd "%~dp0"
set "REPO=%CD%"
popd
if not exist "%REPO%\.git" set "REPO=%REPO%\DeltaMusic"

where git >nul 2>&1
if errorlevel 1 (
    echo git was not found on PATH. Install git and run this again.
    goto :fail
)

where py >nul 2>&1
if errorlevel 1 (
    set "PY=python"
) else (
    set "PY=py -3"
)

%PY% --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found on PATH. Install Python and run this again.
    goto :fail
)

if exist "%REPO%\.git" (
    echo Updating existing checkout in %REPO%
    git -C "%REPO%" fetch origin master
    if errorlevel 1 goto :fail
    git -C "%REPO%" checkout master
    if errorlevel 1 goto :fail
    git -C "%REPO%" reset --hard origin/master
    if errorlevel 1 goto :fail
) else (
    echo Cloning DeltaMusic into %REPO%
    git clone --branch master "https://github.com/deltaqyto/DeltaMusic.git" "%REPO%"
    if errorlevel 1 goto :fail
)

rem git leaves __pycache__ behind on update, so stale bytecode from a since-moved module can linger.
for /f "delims=" %%d in ('dir /s /b /ad "%REPO%\__pycache__" 2^>nul ^| findstr /l /v /i /c:"\.venv\"') do rd /s /q "%%d"

if not exist "%REPO%\.venv\Scripts\activate.bat" (
    echo Creating virtual environment
    %PY% -m venv "%REPO%\.venv"
    if errorlevel 1 goto :fail
)

call "%REPO%\.venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

python -m pip install --upgrade pip
if errorlevel 1 goto :fail

if exist "%REPO%\requirements.txt" (
    python -m pip install -r "%REPO%\requirements.txt"
    if errorlevel 1 goto :fail
) else (
    echo No requirements.txt found, skipping dependency install.
)

echo Setup complete, starting player.
endlocal & call "%REPO%\start.bat"
exit /b %errorlevel%

:fail
echo Setup failed.
endlocal
pause
exit /b 1
