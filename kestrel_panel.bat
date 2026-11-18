@echo off
REM Opens the Kestrel control panel on Windows. Run setup_windows.bat once first.
REM Work from the folder this file is in, wherever it was copied to.
cd /d "%~dp0"
REM If setup has not been run, say so and stop.
if not exist .venv\Scripts\python.exe goto nosetup
REM Start the control panel with Kestrel's own Python.
.venv\Scripts\python.exe tools\kestrel_panel.py
REM Finished; skip the message below.
goto done
:nosetup
REM The private environment is missing.
echo Kestrel is not set up on this computer yet. Double-click setup_windows.bat first.
REM Keep the window open so the message can be read.
pause
:done
