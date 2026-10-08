@echo off
rem =====================================================================
rem  MCKeyBinder Keybind Sync - console launcher / diagnostic fallback
rem
rem  Prefer double-clicking "启动按键同步器.pyw" or the desktop shortcut:
rem  those start with pythonw.exe and show no console window at all.
rem  This .bat is kept as a fallback and for troubleshooting, because it
rem  keeps a console open and prints any error message.
rem
rem  Pure ASCII on purpose: cmd.exe reads .bat in the OEM codepage, so
rem  non-ASCII text here would show as mojibake on some systems.
rem =====================================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 goto :have_py
where python >nul 2>nul
if %errorlevel%==0 goto :have_python

echo.
echo   Python 3 was not found on this system.
echo.
echo   Install Python 3.9 or newer from https://www.python.org/downloads/
echo   Tick "Add python.exe to PATH" during setup, then run this file again.
echo.
pause
goto :done

:have_py
py -3 "main.py" %*
goto :check

:have_python
python "main.py" %*
goto :check

:check
set "RC=%errorlevel%"
if not "%RC%"=="0" (
    echo.
    echo   The program exited with code %RC% before the window opened.
    echo   Please copy the message above and report it.
    echo.
    pause
)

:done
endlocal
