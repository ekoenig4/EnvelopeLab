@echo off
rem Set up EnvelopeLab on Windows (see scripts\install_env.ps1 for the options, e.g.
rem   scripts\install_env.cmd -InstallPython -Shortcut
rem ). Runs the PowerShell script with the execution policy bypassed for this run only,
rem so it works where "running scripts is disabled on this system"; nothing is changed
rem permanently. Double-click it, or run it from a command prompt.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_env.ps1" %*
set RESULT=%ERRORLEVEL%
rem Keep the window open when started by a double-click (no arguments).
if "%~1"=="" pause
exit /b %RESULT%
