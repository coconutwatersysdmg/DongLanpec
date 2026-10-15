import subprocess
import os
import datetime

# MySQL 配置
MYSQL_USER = "root"       # 改成你的用户名
MYSQL_PASSWORD = "123456" # 改成你的密码
MYSQL_HOST = "localhost"
MYSQL_PORT = 3306

# 备份文件目录
BACKUP_DIR = "./mysql_backup"

def backup_mysql():
    # 确保目录存在
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)

    # 文件名加上时间戳
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dump_file = os.path.join(BACKUP_DIR, f"all_databases_{timestamp}.sql")

    # mysqldump 命令
    cmd = [
        "mysqldump",
        f"-h{MYSQL_HOST}",
        f"-P{MYSQL_PORT}",
        f"-u{MYSQL_USER}",
        f"-p{MYSQL_PASSWORD}",
        "--all-databases",   # 导出所有库
        "--routines",        # 包括存储过程和函数
        "--events",          # 包括事件
        "--triggers",        # 包括触发器
    ]

    # 执行命令并写入文件
    with open(dump_file, "w", encoding="utf-8") as f:
        subprocess.run(cmd, stdout=f, check=True)

    print(f"✅ 所有数据库已成功导出到 {dump_file}")

if __name__ == "__main__":
    backup_mysql()
