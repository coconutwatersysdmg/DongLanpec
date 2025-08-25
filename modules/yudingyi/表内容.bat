@echo off
setlocal enabledelayedexpansion

:: 数据库连接参数
set HOST=localhost
set PORT=3306
set USER=root
set PASSWORD=123456
set DATABASE=配置库

:: 输出文件名
set OUTPUT_FILE=database_full_info.txt

:: 清空旧内容并写入标题
echo 表名列表：>%OUTPUT_FILE%
mysql -h%HOST% -P%PORT% -u%USER% -p%PASSWORD% --default-character-set=utf8mb4 ^
  -e "SELECT TABLE_NAME AS 表名 FROM information_schema.TABLES WHERE TABLE_SCHEMA = '%DATABASE%';" >> %OUTPUT_FILE%

:: 插入分隔线
echo.>>%OUTPUT_FILE%
echo =====================================================>>%OUTPUT_FILE%
echo 所有表结构：>>%OUTPUT_FILE%

:: 表结构信息
mysql -h%HOST% -P%PORT% -u%USER% -p%PASSWORD% --default-character-set=utf8mb4 ^
  -e "SELECT TABLE_NAME AS 表名, COLUMN_NAME AS 列名, COLUMN_TYPE AS 数据类型, IS_NULLABLE AS 是否可为空, COLUMN_KEY AS 键类型, COLUMN_DEFAULT AS 默认值, EXTRA AS 额外信息 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = '%DATABASE%' ORDER BY TABLE_NAME, ORDINAL_POSITION;" >> %OUTPUT_FILE%

:: 查询所有表名，用于遍历导出每个表的内容
for /f "skip=1 tokens=*" %%T in ('mysql -h%HOST% -P%PORT% -u%USER% -p%PASSWORD% --default-character-set=utf8mb4 -N -e "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = '%DATABASE%';"') do (
    echo.>>%OUTPUT_FILE%
    echo =====================================================>>%OUTPUT_FILE%
    echo 表 %%T 内容如下：>>%OUTPUT_FILE%
    mysql -h%HOST% -P%PORT% -u%USER% -p%PASSWORD% --default-character-set=utf8mb4 ^
      -e "SELECT * FROM %DATABASE%.%%T;" >> %OUTPUT_FILE%
)

echo.
echo ✅ 所有表名、表结构和表内容已保存至：%OUTPUT_FILE%
pause
