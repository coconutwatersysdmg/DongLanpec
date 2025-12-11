@echo off

set ADDIN_PATH="%~dp0\DigitalProjectAddIn.dll"
set REGASM_X64="C:\Windows\Microsoft.NET\Framework64\v4.0.30319\RegAsm.exe"

%REGASM_X64% /u %ADDIN_PATH%
