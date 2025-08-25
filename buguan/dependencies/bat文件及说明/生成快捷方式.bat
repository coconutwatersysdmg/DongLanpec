@echo off
set "batPath=%~dp0\start.bat"
set "iconPath=%~dp0\logo.ico"
set "desktop=%userprofile%\Desktop"
set "shortcutPath=%desktop%\LYDesign.lnk"

echo Set oWS = WScript.CreateObject("WScript.Shell") > create_shortcut.vbs
echo sLinkFile = "%shortcutPath%" >> create_shortcut.vbs
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> create_shortcut.vbs
echo oLink.TargetPath = "%batPath%" >> create_shortcut.vbs
echo oLink.IconLocation = "%iconPath%" >> create_shortcut.vbs
echo oLink.Save >> create_shortcut.vbs


cscript //nologo create_shortcut.vbs
del create_shortcut.vbs

rem ʹ�� PowerShell �޸Ŀ�ݷ�ʽ�Թ���ԱȨ������
powershell -Command "$bytes = [System.IO.File]::ReadAllBytes('%shortcutPath%'); $bytes[21] = $bytes[21] -bor 0x20; [System.IO.File]::WriteAllBytes('%shortcutPath%', $bytes)"

echo ���������ϴ�����ݷ�ʽ��
pause    