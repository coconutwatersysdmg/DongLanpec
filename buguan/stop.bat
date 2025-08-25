@echo off
echo 正在尝试结束 buguan.exe 进程...

:: 强制结束所有名为 buguan.exe 的进程
taskkill /f /im buguan.exe >nul 2>&1

:: 判断是否成功
if %errorlevel%==0 (
    echo ✅ buguan.exe 已成功结束。
) else (
    echo ⚠️ 未找到 buguan.exe 或结束失败。
)

pause
