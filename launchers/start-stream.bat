@echo off
rem Simple launcher. Edit PLATFORM / PRESET below, then double-click.
set PYTHONPATH=%~dp0..\src
set PLATFORM=twitch
set PRESET=light
rem Optional: capture only the game window (exact title), e.g. BlueStacks
rem set WINDOW=BlueStacks App Player
set /p STREAM_KEY=Paste your stream key (it is not saved): 
if defined WINDOW (
  python -m lightstream start --platform %PLATFORM% --preset %PRESET% --window "%WINDOW%"
) else (
  python -m lightstream start --platform %PLATFORM% --preset %PRESET%
)
set STREAM_KEY=
pause
