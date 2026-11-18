@echo off
REM One-time setup of Kestrel on a Windows computer. Double-click this file.
REM It needs Python 3.10 or newer from python.org already installed.
REM Work from the folder this file is in, wherever it was copied to.
cd /d "%~dp0"
REM Prefer the Python launcher, which python.org installs as "py".
set PY=py -3
REM Check that the launcher is there.
%PY% --version >nul 2>&1
REM If it is not, fall back to plain "python".
if errorlevel 1 set PY=python
REM Check that some Python answered.
%PY% --version >nul 2>&1
REM If none did, explain and stop.
if errorlevel 1 goto nopython
REM Tell the operator what is happening.
echo Creating Kestrel's own Python environment (the .venv folder)...
REM Build the private environment so nothing else on the computer is changed.
%PY% -m venv .venv
REM Tell the operator the next step, which needs the internet.
echo Installing the packages Kestrel needs (this needs the internet)...
REM Install the packages listed in requirements.txt into that environment.
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
REM If the install failed, explain and stop.
if errorlevel 1 goto failed
REM Say that setup worked and what to do next.
echo.
echo Setup finished. Double-click kestrel_panel.bat to open the control panel.
REM Skip over the error messages.
goto done
:nopython
REM No Python was found on this computer.
echo Python was not found. Install Python 3.10 or newer from python.org, then run this file again.
REM Skip to the end.
goto done
:failed
REM The package install did not finish.
echo The packages could not be installed. Check the internet connection and run this file again.
:done
REM Keep the window open so the messages can be read.
pause
