@echo off
setlocal
set "PYTHONUTF8=1"
cd /d "%~dp0"

rem Prefer the interpreter already verified on this computer.
set "DEMO_PYTHON=python"
if exist "D:\ProgramData\anaconda3\python.exe" set "DEMO_PYTHON=D:\ProgramData\anaconda3\python.exe"
if defined DONG_LANPEC_PYTHON set "DEMO_PYTHON=%DONG_LANPEC_PYTHON%"

"%DEMO_PYTHON%" "%~dp0run_tube_ai_demo.py" %*
set "DEMO_EXIT=%ERRORLEVEL%"
if not "%DEMO_EXIT%"=="0" (
  echo.
  echo [ERROR] Tube AI Demo could not start. See the error above.
  echo Python: "%DEMO_PYTHON%"
  echo Keep this window open and report the error message.
  pause
)
exit /b %DEMO_EXIT%
