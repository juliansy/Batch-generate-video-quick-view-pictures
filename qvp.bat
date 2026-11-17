@echo off
rem Quick start for qvp.py.
rem   Double-click       -- process the videos next to this file
rem   Drop a folder/file -- process that instead
rem   Extra arguments    -- passed straight to qvp.py
rem Set QVP_NOPAUSE=1 to skip the final pause (for scripts).

chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
    where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    echo Python 3.9 or newer was not found on PATH.
    echo Install it from https://www.python.org/downloads/ and try again.
    if not defined QVP_NOPAUSE pause
    exit /b 2
)

%PY% "%~dp0qvp.py" %*
set "RC=%errorlevel%"

if "%RC%"=="1" echo.
if "%RC%"=="1" echo One or more files failed; the table above says why.
if "%RC%"=="2" echo Bad arguments, no usable input, or a missing dependency.
if not defined QVP_NOPAUSE pause
exit /b %RC%