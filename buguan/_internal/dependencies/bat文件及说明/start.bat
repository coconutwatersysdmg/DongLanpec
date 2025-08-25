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
echo ��ѡ��������ͣ�1.��ͷʽ��ƣ�2.U�͹����
set /p choice=
if "%choice%"=="1" (
	echo ��ѡ�񡾸�ͷʽ��ơ�
 	call %NEW_UNREG_PATH%
    	if %errorlevel% equ 0 (
        	call %PREV_REG_PATH%
        	if %errorlevel% equ 0 (
			echo.
			echo ������������......
            		start "" %LY_EXE_PATH%
       		 )
    	)
) else if "%choice%"=="2" (
	echo ��ѡ��U�͹���ơ�
 	call %PREV_UNREG_PATH%
    	if %errorlevel% equ 0 (
        	call %NEW_REG_PATH%
        	if %errorlevel% equ 0 (
			echo.
			echo ������������......
            		start "" %LY_EXE_PATH%
        	)
    	)
) else (
    echo ������Ч��������1��2��
    echo.
    goto ask_choice
)
pause