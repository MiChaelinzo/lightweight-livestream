@echo off
rem Opens the easy streaming window.
cd /d "%~dp0.."
set PYTHONPATH=%CD%\src
start "" pythonw -m lightstream gui 2>nul || py -m lightstream gui
