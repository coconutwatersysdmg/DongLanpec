import os, time, subprocess, sys, shlex
import pymysql

# === 配置 ===
BASE_MYSQL = r"E:\DongLanpec\mysql"             # 你的那套 MySQL 根目录
MYSQLD     = os.path.join(BASE_MYSQL, "bin", "mysqld.exe")
MYSQL      = os.path.join(BASE_MYSQL, "bin", "mysql.exe")
DATADIR    = os.path.join(BASE_MYSQL, "data")
PORT       = 3306                                # 强烈建议改成 33306，避开系统服务
HOST       = "localhost"
USER       = "root"
PASSWORD   = "123456"                            # 你的 root 密码
SQL_DIR    = r"E:\DongLanpec\mysql\backup1"      # 存放 .sql 的目录
TARGET_DB  = None  # 设为 None = 用“文件名当库名”；设成 "yourdb" = 所有文件都导入到同一库
STARTUP_TIMEOUT = 30
def _norm_dir(p: str) -> str:
    """转为统一正斜杠并保证以 / 结尾，方便与 @@datadir 对比"""
    s = os.path.abspath(p).replace("\\", "/")
    if not s.endswith("/"): s += "/"
    return s

def start_mysqld():
    """启动指定 datadir+port 的 mysqld（必要时可先初始化）"""
    print("[INFO] 启动 mysqld ...")
    os.makedirs(DATADIR, exist_ok=True)

    # 如果是第一次没有 data，可解开下面一行做初始化（只需执行一次）
    # subprocess.run([MYSQLD, f"--datadir={DATADIR}", f"--port={PORT}", "--initialize-insecure"],
    #                cwd=os.path.dirname(MYSQLD), check=True)

    # 真正启动
    proc = subprocess.Popen(
        [MYSQLD, f"--datadir={DATADIR}", f"--port={PORT}"],
        cwd=os.path.dirname(MYSQLD),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # 静默输出，避免编码问题
        creationflags=0x08000000,  # CREATE_NO_WINDOW
    )
    return proc

def wait_mysql_ready():
    """轮询连接，确认端口与 datadir 正确"""
    want_dir = _norm_dir(DATADIR)
    t0 = time.time()
    while time.time() - t0 < STARTUP_TIMEOUT:
        try:
            conn = pymysql.connect(host=HOST, port=PORT, user=USER, password=PASSWORD, connect_timeout=1)
            with conn.cursor() as c:
                c.execute("SELECT @@port, @@datadir")
                port, d = c.fetchone()
                d_norm = _norm_dir(d)
                print(f"[INFO] 已连接: port={port}, datadir={d_norm}")
                if int(port) == PORT and d_norm == want_dir:
                    conn.close()
                    return True
            conn.close()
        except Exception:
            time.sleep(0.5)
    return False

def mysql_exec(args_extra=None, db=None, input_bytes=None):
    """
    以 bytes 与 mysql.exe 交互，避免编码问题。
    - args_extra: 传给 mysql 的额外参数（例如 ["-e", "SQL语句"]）
    - db: 指定默认数据库
    - input_bytes: 通过 stdin 喂给 mysql 的原始字节（用于导入文件）
    """
    args = [
        MYSQL, f"-h{HOST}", f"-P{PORT}",
        f"-u{USER}", f"-p{PASSWORD}",
        "--protocol=TCP",
        "--default-character-set=utf8mb4",
    ]
    if db:
        args.append(db)
    if args_extra:
        args += list(args_extra)

    cp = subprocess.run(
        args,
        input=input_bytes,                # bytes 或 None
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out = (cp.stdout or b"").decode("utf-8", errors="ignore")
    err = (cp.stderr or b"").decode("utf-8", errors="ignore")

    if cp.returncode != 0:
        # 打印并抛出，便于定位
        if err.strip():
            print("[mysql] ERR:", err.strip())
        raise RuntimeError(err or "mysql.exe failed")

    if out.strip():
        print(out.strip())

def ensure_db_exists(dbname: str):
    """确保数据库存在"""
    mysql_exec(args_extra=["-e", f"CREATE DATABASE IF NOT EXISTS `{dbname}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"])

def import_sql_file_via_stdin(dbname: str, sql_path: str):
    """
    最稳的方法：把 .sql 文件内容作为标准输入喂给 mysql.exe
    - 正确支持 DELIMITER/存储过程/触发器
    - 不受 Windows 路径/中文/引号/反斜杠影响
    """
    with open(sql_path, "rb") as f:
        sql_bytes = f.read()
    mysql_exec(args_extra=None, db=dbname, input_bytes=sql_bytes)

def stop_mysqld(proc):
    """安全关闭 MySQL 服务"""
    print("[INFO] 正在关闭 mysqld ...")
    try:
        # 尝试通过 mysqladmin 发送关闭命令（优雅方式）
        subprocess.run([
            os.path.join(BASE_MYSQL, "bin", "mysqladmin.exe"),
            f"-h{HOST}", f"-P{PORT}",
            f"-u{USER}", f"-p{PASSWORD}",
            "shutdown"
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        print("[INFO] mysqld 已通过 mysqladmin 正常关闭。")
    except Exception as e:
        print("[WARN] mysqladmin 关闭失败，尝试终止进程:", e)
        try:
            proc.terminate()
            proc.wait(5)
            print("[INFO] mysqld 已被终止。")
        except Exception as e2:
            print("[ERROR] 无法终止 mysqld:", e2)

def main():
    proc = start_mysqld()
    if not wait_mysql_ready():
        print("[FATAL] mysqld 未在限定时间内就绪。")
        try:
            proc.terminate()
        except Exception:
            pass
        sys.exit(1)

    if not os.path.isdir(SQL_DIR):
        print(f"[FATAL] SQL 目录不存在: {SQL_DIR}")
        stop_mysqld(proc)
        sys.exit(1)

    files = sorted([f for f in os.listdir(SQL_DIR) if f.lower().endswith(".sql")])
    if not files:
        print(f"[INFO] 目录中没有 .sql 文件: {SQL_DIR}")
        stop_mysqld(proc)
        sys.exit(0)

    for f in files:
        sql_path = os.path.join(SQL_DIR, f)
        dbname = TARGET_DB or os.path.splitext(f)[0]
        print(f"[IMPORT] -> DB `{dbname}` :: {sql_path}")
        ensure_db_exists(dbname)
        import_sql_file_via_stdin(dbname, sql_path)
        print(f"[OK] {f} 导入完成")

    print("[DONE] 所有 SQL 文件导入完成。")
    stop_mysqld(proc)

if __name__ == "__main__":
    main()