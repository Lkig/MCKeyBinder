@echo off
rem MCKeyBinder Keybind Sync - command line entry (same core as the GUI)
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "cli.py" %*
    goto :done
)

where python >nul 2>nul
if %errorlevel%==0 (
    python "cli.py" %*
    goto :done
)

echo Python 3 was not found. See https://www.python.org/downloads/
pause

:done
endlocal
