@echo off
REM -------------------------------
REM 一键启动免安装 MySQL 并初始化数据库（改进版）
REM -------------------------------

REM 将 cmd 切换到 UTF-8 输出（Windows 10/11 推荐）
chcp 65001 >nul

REM 切换到 MySQL bin 目录
cd /d "%~dp0\mysql\bin"

REM 启动 MySQL 服务（后台运行），把控制台输出也写到日志以便查看
start "" mysqld.exe --defaults-file=..\my.ini --standalone --console > "%~dp0\mysql\mysql_server.log" 2>&1

REM 等待 MySQL 启动（根据电脑速度可调整时间，建议 5-8 秒）
timeout /t 6 /nobreak >nul

REM -------------------------------
REM 初始化数据库（仅第一次使用）
REM -------------------------------

for %%f in ("%~dp0..\db_sql\*.sql") do (
    REM 用 powershell 输出中文，避免 cmd 直接 echo 的编码问题
    powershell -NoProfile -Command "Write-Host ('正在导入 {0}' -f '%%~nxf')"
    "%~dp0\mysql\bin\mysql.exe" -u root -p123456 --default-character-set=utf8mb4 < "%%f"
    if errorlevel 1 (
        powershell -NoProfile -Command "Write-Host ('导入失败: {0}' -f '%%~nxf')"
    ) else (
        powershell -NoProfile -Command "Write-Host ('导入成功: {0}' -f '%%~nxf')"
    )
)

powershell -NoProfile -Command "Write-Host 'MySQL 已启动并初始化完成！日志：' (Join-Path '%~dp0' 'mysql\mysql_server.log')"
pause
