@echo off
setlocal EnableExtensions
rem Tiny PATH shim: lets a checkout or the portable folder act like an
rem installed "sweep" command. No pause, no window title, safe in scripts.
set "SWEEP_DIR=%~dp0"
set "PYTHONPATH=%SWEEP_DIR%;%SWEEP_DIR%vendor;%PYTHONPATH%"

if defined SWEEP_PYTHON goto :run_override

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 goto :run_py

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 goto :run_python

echo Sweep needs Python 3.10 or newer, or the portable Sweep.exe build. 1>&2
echo Install Python from https://www.python.org/downloads/windows/ 1>&2
echo and tick "Add python.exe to PATH", then run sweep again. 1>&2
exit /b 9009

:run_override
"%SWEEP_PYTHON%" "%SWEEP_DIR%main.py" %*
goto :done

:run_py
py -3 "%SWEEP_DIR%main.py" %*
goto :done

:run_python
python "%SWEEP_DIR%main.py" %*
goto :done

:done
exit /b %errorlevel%
