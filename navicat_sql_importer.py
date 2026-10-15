import json
import os
import queue
import re
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import pymysql
from pymysql.constants import CLIENT

APP_TITLE = "Navicat SQL 导入工具"
APP_DIR = Path.home() / ".navicat_sql_importer"
CONFIG_PATH = APP_DIR / "config.json"
LOG_DIR = APP_DIR / "logs"


def ensure_app_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_text_file(path: str) -> str:
    encodings = ["utf-8-sig", "utf-8", "gb18030", "gbk", "latin1"]
    last_err = None
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except Exception as e:
            last_err = e
    raise RuntimeError(f"文件读取失败：{last_err}")


class SqlSplitter:
    """按 MySQL 常见导出格式切分 SQL 语句，支持 DELIMITER。"""

    def __init__(self, text: str):
        self.text = text

    def split(self):
        text = self.text
        n = len(text)
        i = 0
        delimiter = ";"
        current = []
        in_single = False
        in_double = False
        in_backtick = False
        in_line_comment = False
        in_block_comment = False
        line_start = True

        while i < n:
            # 仅在“行首 + 不在字符串/注释内”时识别 DELIMITER
            if line_start and not any([in_single, in_double, in_backtick, in_line_comment, in_block_comment]):
                j = i
                while j < n and text[j] in " \t\r":
                    j += 1
                line_end = text.find("\n", j)
                if line_end == -1:
                    line_end = n
                logical_line = text[j:line_end]
                upper_line = logical_line.upper()
                if upper_line.startswith("DELIMITER "):
                    new_delimiter = logical_line.split(None, 1)[1].strip()
                    if new_delimiter:
                        delimiter = new_delimiter
                    i = line_end + (1 if line_end < n else 0)
                    line_start = True
                    continue

            ch = text[i]
            nxt2 = text[i:i + 2]

            if in_line_comment:
                current.append(ch)
                i += 1
                if ch == "\n":
                    in_line_comment = False
                    line_start = True
                else:
                    line_start = False
                continue

            if in_block_comment:
                current.append(ch)
                i += 1
                if ch == "*" and i < n and text[i] == "/":
                    current.append("/")
                    i += 1
                    in_block_comment = False
                line_start = (ch == "\n")
                continue

            if in_single:
                current.append(ch)
                i += 1
                if ch == "\\" and i < n:
                    current.append(text[i])
                    i += 1
                elif ch == "'":
                    if i < n and text[i] == "'":
                        current.append(text[i])
                        i += 1
                    else:
                        in_single = False
                line_start = (ch == "\n")
                continue

            if in_double:
                current.append(ch)
                i += 1
                if ch == "\\" and i < n:
                    current.append(text[i])
                    i += 1
                elif ch == '"':
                    if i < n and text[i] == '"':
                        current.append(text[i])
                        i += 1
                    else:
                        in_double = False
                line_start = (ch == "\n")
                continue

            if in_backtick:
                current.append(ch)
                i += 1
                if ch == "`":
                    if i < n and text[i] == "`":
                        current.append(text[i])
                        i += 1
                    else:
                        in_backtick = False
                line_start = (ch == "\n")
                continue

            # ---- 以下是不在字符串 / 注释中的状态 ----
            if ch == "#":
                in_line_comment = True
                current.append(ch)
                i += 1
                line_start = False
                continue

            if nxt2 == "--" and (i + 2 >= n or text[i + 2] in " \t\r\n"):
                in_line_comment = True
                current.append("--")
                i += 2
                line_start = False
                continue

            if nxt2 == "/*":
                in_block_comment = True
                current.append("/*")
                i += 2
                line_start = False
                continue

            if ch == "'":
                in_single = True
                current.append(ch)
                i += 1
                line_start = False
                continue

            if ch == '"':
                in_double = True
                current.append(ch)
                i += 1
                line_start = False
                continue

            if ch == "`":
                in_backtick = True
                current.append(ch)
                i += 1
                line_start = False
                continue

            if delimiter and text.startswith(delimiter, i):
                stmt = "".join(current).strip()
                if stmt:
                    yield stmt
                current = []
                i += len(delimiter)
                line_start = False
                continue

            current.append(ch)
            i += 1
            line_start = (ch == "\n")

        tail = "".join(current).strip()
        if tail:
            yield tail


class ImportApp:
    def __init__(self, root: tk.Tk):
        ensure_app_dirs()
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("920x700")
        self.root.minsize(860, 620)

        self.queue = queue.Queue()
        self.import_thread = None
        self.running = False
        self.current_log_file = None

        self._build_ui()
        self._load_config()
        self.root.after(150, self._process_queue)

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        conn_labelframe = ttk.LabelFrame(main, text="数据库连接")
        conn_labelframe.pack(fill="x", pady=(0, 10))

        file_labelframe = ttk.LabelFrame(main, text="SQL 文件")
        file_labelframe.pack(fill="x", pady=(0, 10))

        action_frame = ttk.Frame(main)
        action_frame.pack(fill="x", pady=(0, 10))

        log_frame = ttk.LabelFrame(main, text="执行日志")
        log_frame.pack(fill="both", expand=True)

        # 连接区
        self.host_var = tk.StringVar(value="127.0.0.1")
        self.port_var = tk.StringVar(value="3306")
        self.user_var = tk.StringVar(value="root")
        self.password_var = tk.StringVar(value="")
        self.db_var = tk.StringVar(value="")
        self.continue_on_error_var = tk.BooleanVar(value=False)

        fields = [
            ("主机", self.host_var),
            ("端口", self.port_var),
            ("用户名", self.user_var),
            ("密码", self.password_var),
            ("默认数据库（可空）", self.db_var),
        ]

        for idx, (label, var) in enumerate(fields):
            row = idx // 2
            col = (idx % 2) * 3
            ttk.Label(conn_labelframe, text=label).grid(row=row, column=col, padx=8, pady=8, sticky="w")
            show = "*" if label == "密码" else ""
            width = 28 if label != "默认数据库（可空）" else 62
            entry = ttk.Entry(conn_labelframe, textvariable=var, width=width, show=show)
            entry.grid(row=row, column=col + 1, padx=8, pady=8, sticky="ew")

        conn_labelframe.columnconfigure(1, weight=1)
        conn_labelframe.columnconfigure(4, weight=1)

        # 文件区
        self.file_var = tk.StringVar()
        ttk.Entry(file_labelframe, textvariable=self.file_var).grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        ttk.Button(file_labelframe, text="选择 SQL 文件", command=self.choose_file).grid(row=0, column=1, padx=8, pady=8)
        ttk.Checkbutton(file_labelframe, text="遇错继续执行", variable=self.continue_on_error_var).grid(
            row=1, column=0, padx=8, pady=(0, 8), sticky="w"
        )
        file_labelframe.columnconfigure(0, weight=1)

        # 操作区
        self.test_btn = ttk.Button(action_frame, text="测试连接", command=self.test_connection)
        self.test_btn.pack(side="left", padx=(0, 8))
        self.import_btn = ttk.Button(action_frame, text="开始导入", command=self.start_import)
        self.import_btn.pack(side="left", padx=(0, 8))
        self.clear_btn = ttk.Button(action_frame, text="清空日志", command=self.clear_log)
        self.clear_btn.pack(side="left", padx=(0, 8))
        self.open_log_btn = ttk.Button(action_frame, text="打开日志目录", command=self.open_log_dir)
        self.open_log_btn.pack(side="left")

        self.progress = ttk.Progressbar(action_frame, mode="determinate")
        self.progress.pack(side="right", fill="x", expand=True, padx=(10, 0))

        # 日志区
        self.log_text = ScrolledText(log_frame, wrap="word", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.configure(state="disabled")

    def _load_config(self):
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                self.host_var.set(data.get("host", self.host_var.get()))
                self.port_var.set(str(data.get("port", self.port_var.get())))
                self.user_var.set(data.get("user", self.user_var.get()))
                self.db_var.set(data.get("database", self.db_var.get()))
                self.file_var.set(data.get("last_file", self.file_var.get()))
                self.continue_on_error_var.set(bool(data.get("continue_on_error", False)))
            except Exception:
                pass

    def _save_config(self):
        data = {
            "host": self.host_var.get().strip(),
            "port": self.port_var.get().strip(),
            "user": self.user_var.get().strip(),
            "database": self.db_var.get().strip(),
            "last_file": self.file_var.get().strip(),
            "continue_on_error": self.continue_on_error_var.get(),
        }
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {msg}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        if self.current_log_file:
            try:
                with open(self.current_log_file, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    def clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="选择 SQL 文件",
            filetypes=[("SQL 文件", "*.sql"), ("所有文件", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def open_log_dir(self):
        ensure_app_dirs()
        path = str(LOG_DIR)
        try:
            os.startfile(path)
        except Exception:
            messagebox.showinfo("提示", f"日志目录：\n{path}")

    def _get_conn_kwargs(self):
        host = self.host_var.get().strip()
        port_text = self.port_var.get().strip()
        user = self.user_var.get().strip()
        password = self.password_var.get()
        database = self.db_var.get().strip()

        if not host:
            raise ValueError("主机不能为空")
        if not port_text.isdigit():
            raise ValueError("端口必须是数字")
        if not user:
            raise ValueError("用户名不能为空")

        kwargs = {
            "host": host,
            "port": int(port_text),
            "user": user,
            "password": password,
            "charset": "utf8mb4",
            "autocommit": False,
            "client_flag": CLIENT.MULTI_STATEMENTS,
        }
        if database:
            kwargs["database"] = database
        return kwargs
    def _is_duplicate_entry_error(self, err) -> bool:
        try:
            return isinstance(err, Exception) and getattr(err, "args", None) and err.args[0] == 1062
        except Exception:
            return False

    def _extract_insert_info(self, stmt: str):
        """
        解析：
        INSERT INTO `表名` (`col1`, `col2`, ...) VALUES ...
        或
        INSERT INTO 表名 (col1, col2, ...) VALUES ...

        返回:
            table_name, columns(list)
        失败返回 (None, None)
        """
        s = self._strip_leading_comments(stmt).strip().rstrip(";").strip()

        pattern = re.compile(
            r"""INSERT\s+INTO\s+
                (?P<table>`[^`]+`|[^\s(]+)\s*
                \((?P<cols>.*?)\)\s*
                VALUES\b
            """,
            re.IGNORECASE | re.DOTALL | re.VERBOSE
        )

        m = pattern.search(s)
        if not m:
            return None, None

        table_name = m.group("table").strip()
        cols_str = m.group("cols").strip()

        cols = []
        cur = []
        in_backtick = False

        for ch in cols_str:
            if ch == "`":
                in_backtick = not in_backtick
                cur.append(ch)
            elif ch == "," and not in_backtick:
                col = "".join(cur).strip()
                if col:
                    cols.append(col)
                cur = []
            else:
                cur.append(ch)

        tail = "".join(cur).strip()
        if tail:
            cols.append(tail)

        cleaned_cols = []
        for c in cols:
            c = c.strip()
            if c.startswith("`") and c.endswith("`"):
                c = c[1:-1]
            cleaned_cols.append(c)

        if table_name.startswith("`") and table_name.endswith("`"):
            table_name = table_name[1:-1]

        return table_name, cleaned_cols
    def _get_primary_key_columns(self, cursor, table_name: str):
        """
        获取当前数据库下某个表的主键列名列表
        """
        cursor.execute("SELECT DATABASE()")
        row = cursor.fetchone()
        current_db = row[0] if row else None
        if not current_db:
            return []

        sql = """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA = %s
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = 'PRIMARY'
            ORDER BY ORDINAL_POSITION
        """
        cursor.execute(sql, (current_db, table_name))
        rows = cursor.fetchall()
        return [r[0] for r in rows] if rows else []

    def _build_upsert_sql(self, cursor, stmt: str):
        """
        把 INSERT INTO ... VALUES ...
        改成 INSERT ... ON DUPLICATE KEY UPDATE ...
        """
        clean_stmt = self._strip_leading_comments(stmt).strip().rstrip(";").strip()

        table_name, columns = self._extract_insert_info(clean_stmt)
        if not table_name or not columns:
            return None

        pk_cols = set(self._get_primary_key_columns(cursor, table_name))

        # 非主键字段优先更新
        update_cols = [c for c in columns if c not in pk_cols]

        # 如果整条记录全是主键列，至少保底更新主键本身（虽然这种情况极少）
        if not update_cols:
            update_cols = list(columns)

        update_clause = ", ".join([f"`{c}`=VALUES(`{c}`)" for c in update_cols])

        upsert_sql = f"{clean_stmt} ON DUPLICATE KEY UPDATE {update_clause}"
        return upsert_sql
    def test_connection(self):
        try:
            kwargs = self._get_conn_kwargs()
            conn = pymysql.connect(**kwargs)
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT VERSION()")
                    version = cursor.fetchone()[0]
                messagebox.showinfo("连接成功", f"数据库连接成功。\nMySQL 版本：{version}")
            finally:
                conn.close()
        except Exception as e:
            messagebox.showerror("连接失败", str(e))

    def _set_running(self, running: bool):
        self.running = running
        state = "disabled" if running else "normal"
        self.import_btn.configure(state=state)
        self.test_btn.configure(state=state)
        self.clear_btn.configure(state=state)
        self.open_log_btn.configure(state=state)

    def start_import(self):
        if self.running:
            return
        sql_file = self.file_var.get().strip()
        if not sql_file:
            messagebox.showwarning("提示", "请先选择 SQL 文件")
            return
        if not os.path.isfile(sql_file):
            messagebox.showwarning("提示", "SQL 文件不存在")
            return

        try:
            self._get_conn_kwargs()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return

        self._save_config()
        ensure_app_dirs()
        self.current_log_file = str(LOG_DIR / f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        self.progress["value"] = 0
        self.progress["maximum"] = 100
        self._set_running(True)
        self.log(f"开始导入：{sql_file}")
        self.import_thread = threading.Thread(target=self._import_worker, daemon=True)
        self.import_thread.start()

    def _queue_log(self, msg: str):
        self.queue.put(("log", msg))

    def _queue_progress(self, value: int, maximum: int):
        self.queue.put(("progress", value, maximum))

    def _queue_done(self, success: bool, message: str):
        self.queue.put(("done", success, message))

    def _import_worker(self):
        start_ts = time.time()
        sql_file = self.file_var.get().strip()
        continue_on_error = self.continue_on_error_var.get()

        try:
            kwargs = self._get_conn_kwargs()
            text = load_text_file(sql_file)
            splitter = SqlSplitter(text)
            statements = list(splitter.split())
            if not statements:
                raise RuntimeError("没有解析到可执行的 SQL 语句")

            self._queue_log(f"解析完成，共 {len(statements)} 条 SQL 语句")

            conn = pymysql.connect(**kwargs)
            try:
                with conn.cursor() as cursor:
                    # 如果用户填了默认数据库，先创建并切换，便于兼容不带 USE 的脚本
                    default_db = self.db_var.get().strip()
                    if default_db:
                        cursor.execute(
                            f"CREATE DATABASE IF NOT EXISTS `{default_db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                        )
                        cursor.execute(f"USE `{default_db}`")
                        conn.commit()
                        self._queue_log(f"已切换到默认数据库：{default_db}")

                    success_count = 0
                    error_count = 0

                    for idx, stmt in enumerate(statements, 1):
                        preview = stmt.replace("\n", " ").strip()
                        preview = preview[:120] + ("..." if len(preview) > 120 else "")

                        try:
                            cursor.execute(stmt)
                            while cursor.nextset():
                                pass
                            conn.commit()
                            success_count += 1

                            if idx <= 5 or idx % 20 == 0 or idx == len(statements):
                                self._queue_log(f"[{idx}/{len(statements)}] 执行成功：{preview}")

                        except Exception as e:
                            conn.rollback()

                            # === 如果是重复主键，则自动改为增量更新 ===
                            if self._is_duplicate_entry_error(e):
                                try:
                                    upsert_sql = self._build_upsert_sql(cursor, stmt)
                                    if upsert_sql:
                                        cursor.execute(upsert_sql)
                                        while cursor.nextset():
                                            pass
                                        conn.commit()
                                        success_count += 1
                                        self._queue_log(f"[{idx}/{len(statements)}] 主键重复，已自动转为增量更新")
                                        if idx <= 5 or idx % 20 == 0 or idx == len(statements):
                                            self._queue_log(f"[{idx}/{len(statements)}] 更新成功：{preview}")
                                    else:
                                        error_count += 1
                                        self._queue_log(
                                            f"[{idx}/{len(statements)}] 无法将该语句解析为 INSERT，不能自动转增量更新")
                                        self._queue_log(f"原始 SQL（前300字符）：{stmt[:300].replace(chr(10), ' ')}")
                                        if not continue_on_error:
                                            raise RuntimeError(f"第 {idx} 条 SQL 不是可自动改写的 INSERT 语句")
                                except Exception as upsert_err:
                                    conn.rollback()
                                    error_count += 1
                                    self._queue_log(f"[{idx}/{len(statements)}] 增量更新失败：{upsert_err}")
                                    self._queue_log(f"出错 SQL：{preview}")
                                    if not continue_on_error:
                                        raise RuntimeError(f"第 {idx} 条 SQL 增量更新失败：{upsert_err}")

                            else:
                                error_count += 1
                                self._queue_log(f"[{idx}/{len(statements)}] 执行失败：{e}")
                                self._queue_log(f"出错 SQL：{preview}")
                                if not continue_on_error:
                                    raise RuntimeError(f"第 {idx} 条 SQL 执行失败：{e}")

                        self._queue_progress(idx, len(statements))
                elapsed = time.time() - start_ts
                self._queue_done(True, f"导入完成。成功 {success_count} 条，失败 {error_count} 条，耗时 {elapsed:.2f} 秒。")
            finally:
                conn.close()
        except Exception as e:
            self._queue_done(False, f"导入失败：{e}")

    def _strip_leading_comments(self, sql: str) -> str:
        """
        去掉 SQL 开头连续的注释：
        -- ...
        # ...
        /* ... */
        /*! ... */
        """
        s = sql.strip()

        while True:
            old = s

            # 去掉 -- 注释行
            s = re.sub(r'^\s*--[^\n]*(?:\n|$)', '', s, flags=re.MULTILINE)

            # 去掉 # 注释行
            s = re.sub(r'^\s*#[^\n]*(?:\n|$)', '', s, flags=re.MULTILINE)

            # 去掉 /* ... */ 或 /*! ... */
            s = re.sub(r'^\s*/\*.*?\*/\s*', '', s, flags=re.DOTALL)

            s = s.lstrip()

            if s == old:
                break

        return s
    def _process_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.log(item[1])
                elif kind == "progress":
                    _, value, maximum = item
                    self.progress["maximum"] = max(1, maximum)
                    self.progress["value"] = value
                elif kind == "done":
                    _, success, message = item
                    self.log(message)
                    self._set_running(False)
                    if success:
                        messagebox.showinfo("完成", message)
                    else:
                        messagebox.showerror("失败", message)
        except queue.Empty:
            pass
        self.root.after(150, self._process_queue)


if __name__ == "__main__":
    root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    style = ttk.Style()
    try:
        style.theme_use("vista")
    except Exception:
        pass

    app = ImportApp(root)
    root.mainloop()