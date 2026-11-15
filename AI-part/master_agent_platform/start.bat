@echo off
setlocal
cd /d "%~dp0"
if defined DONGLANPEC_AGENT_PYTHON (
  set "AGENT_PLATFORM_PY=%DONGLANPEC_AGENT_PYTHON%"
  goto run_agent
)
if exist "%~dp0python\python.exe" (
  set "AGENT_PLATFORM_PY=%~dp0python\python.exe"
  goto run_agent
)
if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" (
  set "AGENT_PLATFORM_PY=%CONDA_PREFIX%\python.exe"
  goto run_agent
)
for %%P in ("D:\ProgramData\anaconda3\python.exe" "C:\ProgramData\anaconda3\python.exe" "%USERPROFILE%\anaconda3\python.exe" "%USERPROFILE%\miniconda3\python.exe" "D:\python3.9\python.exe") do if exist "%%~P" (
  set "AGENT_PLATFORM_PY=%%~P"
  goto run_agent
)
where python >nul 2>nul
if errorlevel 1 goto missing_python
set "AGENT_PLATFORM_PY=python"
:run_agent
"%AGENT_PLATFORM_PY%" "%~dp0run.py"
set "AGENT_PLATFORM_EXIT=%ERRORLEVEL%"
if not "%AGENT_PLATFORM_EXIT%"=="0" pause
exit /b %AGENT_PLATFORM_EXIT%
:missing_python
echo No Python environment found. Set DONGLANPEC_AGENT_PYTHON to python.exe.
pause
exit /b 1
