import os
import pymysql
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime


class MySQLExportTool:
    def __init__(self, root):
        self.root = root
        self.root.title("MySQL 数据表导出工具")
        self.root.geometry("860x650")

        self.conn = None
        self.table_vars = {}

        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill="both", expand=True)

        # ===== 数据库连接区 =====
        conn_frame = ttk.LabelFrame(main_frame, text="数据库连接信息", padding=10)
        conn_frame.pack(fill="x", pady=5)

        ttk.Label(conn_frame, text="Host").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.host_entry = ttk.Entry(conn_frame, width=22)
        self.host_entry.insert(0, "10.32.22.189")
        self.host_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(conn_frame, text="Port").grid(row=0, column=2, sticky="w", padx=5, pady=5)
        self.port_entry = ttk.Entry(conn_frame, width=10)
        self.port_entry.insert(0, "3306")
        self.port_entry.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(conn_frame, text="User").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.user_entry = ttk.Entry(conn_frame, width=22)
        self.user_entry.insert(0, "DongLanpec")
        self.user_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(conn_frame, text="Password").grid(row=1, column=2, sticky="w", padx=5, pady=5)
        self.password_entry = ttk.Entry(conn_frame, width=22, show="DongLanpec704704")
        self.password_entry.grid(row=1, column=3, padx=5, pady=5)

        ttk.Label(conn_frame, text="Database").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.database_entry = ttk.Entry(conn_frame, width=22)
        self.database_entry.grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(conn_frame, text="Charset").grid(row=2, column=2, sticky="w", padx=5, pady=5)
        self.charset_entry = ttk.Entry(conn_frame, width=22)
        self.charset_entry.insert(0, "utf8mb4")
        self.charset_entry.grid(row=2, column=3, padx=5, pady=5)

        btn_frame = ttk.Frame(conn_frame)
        btn_frame.grid(row=3, column=0, columnspan=4, pady=8)

        ttk.Button(btn_frame, text="连接数据库", command=self.connect_db).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="读取表列表", command=self.load_tables).pack(side="left", padx=5)

        # ===== 导出模式 =====
        option_frame = ttk.LabelFrame(main_frame, text="导出选项", padding=10)
        option_frame.pack(fill="x", pady=5)

        self.export_mode = tk.StringVar(value="all")
        ttk.Radiobutton(option_frame, text="导出整个数据库", variable=self.export_mode, value="all").pack(anchor="w")
        ttk.Radiobutton(option_frame, text="只导出选中的表", variable=self.export_mode, value="selected").pack(anchor="w")

        # ===== 表列表 =====
        table_frame = ttk.LabelFrame(main_frame, text="数据表列表", padding=10)
        table_frame.pack(fill="both", expand=True, pady=5)

        top_btn_frame = ttk.Frame(table_frame)
        top_btn_frame.pack(fill="x", pady=5)

        ttk.Button(top_btn_frame, text="全选", command=self.select_all_tables).pack(side="left", padx=5)
        ttk.Button(top_btn_frame, text="全不选", command=self.unselect_all_tables).pack(side="left", padx=5)

        self.canvas = tk.Canvas(table_frame)
        self.scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Configure>", self.on_canvas_configure)

        # ===== 导出文件 =====
        output_frame = ttk.LabelFrame(main_frame, text="导出文件", padding=10)
        output_frame.pack(fill="x", pady=5)

        self.output_entry = ttk.Entry(output_frame)
        self.output_entry.pack(side="left", fill="x", expand=True, padx=5)

        default_name = f"mysql_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        self.output_entry.insert(0, os.path.abspath(default_name))

        ttk.Button(output_frame, text="浏览", command=self.choose_output_file).pack(side="left", padx=5)

        # ===== 导出按钮 =====
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill="x", pady=8)

        ttk.Button(bottom_frame, text="开始导出", command=self.export_sql).pack(side="left", padx=5)

        self.status_text = tk.Text(main_frame, height=10)
        self.status_text.pack(fill="both", expand=False, pady=5)

    def on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def log(self, msg):
        self.status_text.insert("end", msg + "\n")
        self.status_text.see("end")
        self.root.update_idletasks()

    def get_db_config(self):
        return {
            "host": self.host_entry.get().strip(),
            "port": int(self.port_entry.get().strip()),
            "user": self.user_entry.get().strip(),
            "password": self.password_entry.get(),
            "database": self.database_entry.get().strip(),
            "charset": self.charset_entry.get().strip(),
            "cursorclass": pymysql.cursors.Cursor
        }

    def connect_db(self):
        try:
            if self.conn:
                self.conn.close()
                self.conn = None

            config = self.get_db_config()
            self.conn = pymysql.connect(**config)
            self.log("✅ 数据库连接成功")
            messagebox.showinfo("成功", "数据库连接成功")
        except Exception as e:
            self.log(f"❌ 数据库连接失败：{e}")
            messagebox.showerror("错误", f"数据库连接失败：\n{e}")

    def load_tables(self):
        try:
            if not self.conn:
                self.connect_db()
                if not self.conn:
                    return

            for widget in self.scrollable_frame.winfo_children():
                widget.destroy()
            self.table_vars.clear()

            database_name = self.database_entry.get().strip()

            with self.conn.cursor() as cursor:
                cursor.execute(f"SHOW FULL TABLES FROM `{database_name}` WHERE Table_type = 'BASE TABLE';")
                rows = cursor.fetchall()

            tables = [row[0] for row in rows]

            if not tables:
                self.log("⚠️ 当前数据库没有找到表")
                return

            for idx, table_name in enumerate(tables):
                var = tk.BooleanVar(value=True)
                chk = ttk.Checkbutton(self.scrollable_frame, text=table_name, variable=var)
                chk.grid(row=idx, column=0, sticky="w", padx=5, pady=2)
                self.table_vars[table_name] = var

            self.log(f"✅ 已加载 {len(tables)} 个表")
        except Exception as e:
            self.log(f"❌ 读取表列表失败：{e}")
            messagebox.showerror("错误", f"读取表列表失败：\n{e}")

    def select_all_tables(self):
        for var in self.table_vars.values():
            var.set(True)

    def unselect_all_tables(self):
        for var in self.table_vars.values():
            var.set(False)

    def choose_output_file(self):
        file_path = filedialog.asksaveasfilename(
            title="选择导出 SQL 文件",
            defaultextension=".sql",
            filetypes=[("SQL Files", "*.sql"), ("All Files", "*.*")]
        )
        if file_path:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, file_path)

    def escape_value(self, value):
        if value is None:
            return "NULL"
        if isinstance(value, bytes):
            return "0x" + value.hex()
        return self.conn.escape(value)

    def export_table_structure(self, table_name, file_obj):
        with self.conn.cursor() as cursor:
            cursor.execute(f"SHOW CREATE TABLE `{table_name}`;")
            row = cursor.fetchone()
            if not row:
                self.log(f"⚠️ 获取表结构失败：{table_name}")
                return
            create_sql = row[1]

            file_obj.write(f"\n-- ----------------------------\n")
            file_obj.write(f"-- Table structure for `{table_name}`\n")
            file_obj.write(f"-- ----------------------------\n")
            file_obj.write(f"DROP TABLE IF EXISTS `{table_name}`;\n")
            file_obj.write(f"{create_sql};\n")

    def export_table_data(self, table_name, file_obj, batch_size=500):
        with self.conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`;")
            total_rows = cursor.fetchone()[0]

            file_obj.write(f"\n-- ----------------------------\n")
            file_obj.write(f"-- Records of `{table_name}`\n")
            file_obj.write(f"-- ----------------------------\n")

            if total_rows == 0:
                self.log(f"📭 表 `{table_name}` 没有数据")
                return

            cursor.execute(f"SHOW COLUMNS FROM `{table_name}`;")
            columns_info = cursor.fetchall()
            columns = [f"`{col[0]}`" for col in columns_info]
            columns_sql = ", ".join(columns)

            offset = 0
            while offset < total_rows:
                cursor.execute(f"SELECT * FROM `{table_name}` LIMIT {batch_size} OFFSET {offset};")
                rows = cursor.fetchall()
                if not rows:
                    break

                values_sql_list = []
                for row in rows:
                    row_sql = ", ".join(self.escape_value(v) for v in row)
                    values_sql_list.append(f"({row_sql})")

                insert_sql = f"INSERT INTO `{table_name}` ({columns_sql}) VALUES\n"
                insert_sql += ",\n".join(values_sql_list)
                insert_sql += ";\n"

                file_obj.write(insert_sql)
                offset += len(rows)

            self.log(f"✅ 表 `{table_name}` 导出完成，共 {total_rows} 行")

    def export_sql(self):
        try:
            if not self.conn:
                self.connect_db()
                if not self.conn:
                    return

            output_file = self.output_entry.get().strip()
            if not output_file:
                messagebox.showwarning("提示", "请先选择导出文件路径")
                return

            mode = self.export_mode.get()
            if mode == "all":
                tables = list(self.table_vars.keys())
            else:
                tables = [name for name, var in self.table_vars.items() if var.get()]

            if not tables:
                messagebox.showwarning("提示", "没有选择任何表")
                return

            database_name = self.database_entry.get().strip()

            with open(output_file, "w", encoding="utf-8") as f:
                f.write("-- -------------------------------------\n")
                f.write("-- MySQL Export\n")
                f.write(f"-- Database: {database_name}\n")
                f.write(f"-- Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("-- -------------------------------------\n")
                f.write("SET NAMES utf8mb4;\n")
                f.write("SET FOREIGN_KEY_CHECKS = 0;\n")

                for table_name in tables:
                    self.log(f"🚀 正在导出：{table_name}")
                    self.export_table_structure(table_name, f)
                    self.export_table_data(table_name, f)

                f.write("\nSET FOREIGN_KEY_CHECKS = 1;\n")

            self.log(f"🎉 导出完成：{output_file}")
            messagebox.showinfo("成功", f"导出完成：\n{output_file}")

        except Exception as e:
            self.log(f"❌ 导出失败：{e}")
            messagebox.showerror("错误", f"导出失败：\n{e}")

    def __del__(self):
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = MySQLExportTool(root)
    root.mainloop()