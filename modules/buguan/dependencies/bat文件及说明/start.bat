@echo off
set "iconpath=%~dp0\logo.ico"

set PREV_PATH="%~dp0\lb1"
set NEW_PATH="%~dp0\LB"

set PREV_REG_PATH=%PREV_PATH%\bin\register.bat
set PREV_UNREG_PATH=%PREV_PATH%\bin\unregister.bat

set NEW_REG_PATH=%NEW_PATH%\BIN\register.bat
set NEW_UNREG_PATH=%NEW_PATH%\BIN\unregister.bat

set LY_EXE_PATH="%~dp0\PROGRAM\LYDesign.exe"

:ask_choice
echo 请选择设计类型，1.浮头式设计，2.U型管设计
set /p choice=
if "%choice%"=="1" (
	echo 已选择【浮头式设计】
 	call %NEW_UNREG_PATH%
    	if %errorlevel% equ 0 (
        	call %PREV_REG_PATH%
        	if %errorlevel% equ 0 (
			echo.
			echo 正在启动蓝翼......
            		start "" %LY_EXE_PATH%
       		 )
    	)
) else if "%choice%"=="2" (
	echo 已选择【U型管设计】
 	call %PREV_UNREG_PATH%
    	if %errorlevel% equ 0 (
        	call %NEW_REG_PATH%
        	if %errorlevel% equ 0 (
			echo.
			echo 正在启动蓝翼......
            		start "" %LY_EXE_PATH%
        	)
    	)
) else (
    echo 输入无效，请输入1或2。
    echo.
    goto ask_choice
)
pause