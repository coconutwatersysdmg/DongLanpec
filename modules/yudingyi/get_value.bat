@echo off
REM 用法: get_value.bat 封头形式选用 选择1

set TABLENAME=%1
set ID=%2

get_predefined_value.exe "%TABLENAME%" "%ID%"

pause
