@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PY=python

if "%~1"=="" (
  echo Usage: convert.bat input.mid output.asm
  exit /b 1
)

"%PY%" "%SCRIPT_DIR%midi_to_ngpc.py" %*
endlocal
