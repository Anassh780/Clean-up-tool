@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Sweep - windows cleanup console

rem Sweep launcher: finds a usable Python 3.10+, then starts the TUI.
rem Search order: SWEEP_PYTHON, py -3, python, python3, a bundled runtime next
rem to this file, then the development runtime. Arguments pass straight through.
rem Delayed expansion is deliberately off so arguments containing "!" survive.

set "PYEXE="
set "PYARGS="

if defined SWEEP_PYTHON (
    call :try_python "%SWEEP_PYTHON%" ""
    if defined PYEXE goto :check_vendor
    echo.
    echo   Note: SWEEP_PYTHON is set but is not a Python 3.10+ interpreter.
    echo   Falling back to the normal search.
)

call :try_python "py" "-3"
if defined PYEXE goto :check_vendor

call :try_python "python" ""
if defined PYEXE goto :check_vendor

call :try_python "python3" ""
if defined PYEXE goto :check_vendor

call :try_python "%~dp0python\python.exe" ""
if defined PYEXE goto :check_vendor

call :try_python "%~dp0runtime\python.exe" ""
if defined PYEXE goto :check_vendor

call :try_python "%~dp0vendor\python\python.exe" ""
if defined PYEXE goto :check_vendor

call :try_python "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" ""
if defined PYEXE goto :check_vendor

echo.
echo   Sweep needs Python 3.10 or newer.
echo   Install it from https://www.python.org/downloads/windows/
echo   and tick "Add python.exe to PATH", then run this file again.
echo.
echo   No Python? Use the portable Sweep.exe build instead - it needs nothing installed.
echo.
pause
exit /b 1

:check_vendor
rem The portable zip vendors compiled libraries (psutil). A Python with a
rem different ABI would fail with a DLL error deep in an import; say it plainly.
if exist "%~dp0vendor\psutil" (
    "%PYEXE%" %PYARGS% -c "import sys; sys.path.insert(0, 'vendor'); import psutil" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo   This portable build's bundled libraries do not match the Python found.
        echo   Use Python 3.12, or install the package instead:
        echo       python -m pip install .
        echo   The standalone Sweep.exe build needs no Python at all.
        echo.
        pause
        exit /b 1
    )
)

:run
"%PYEXE%" %PYARGS% "%~dp0main.py" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo   Sweep exited with an error. The message above has the details.
    pause
)
exit /b %RC%

:try_python
rem %1 = executable (quoted), %2 = fixed launcher args such as -3.
"%~1" %~2 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 exit /b 1
set "PYEXE=%~1"
set "PYARGS=%~2"
exit /b 0
