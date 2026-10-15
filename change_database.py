import sys
import re
import pymysql
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QTextEdit, QFileDialog, QMessageBox

class DBSyncApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MySQL 数据库结构同步器")
        self.resize(700, 500)

        layout = QVBoxLayout()

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        self.btn_select = QPushButton("选择SQL文件并执行同步")
        self.btn_select.clicked.connect(self.load_sql_file)

        layout.addWidget(self.btn_select)
        layout.addWidget(self.log)
        self.setLayout(layout)

    def log_msg(self, msg):
        self.log.append(msg)
        print(msg)

    def load_sql_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择SQL文件", "", "SQL Files (*.sql)")
        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                sql_text = f.read()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取文件失败: {e}")
            return

        # 连接数据库
        conn = pymysql.connect(
            host="localhost",
            user="root",
            password="123456",
            database="产品设计活动库",
            charset="utf8mb4"
        )
        cursor = conn.cursor()

        # 找到所有 CREATE TABLE
        tables = re.findall(r"CREATE TABLE `?(\w+)`?\s*\((.*?)\)\s*ENGINE.*?;", sql_text, re.S)
        if not tables:
            self.log_msg("❌ 未找到任何 CREATE TABLE 语句")
            return

        for table_name, cols_part in tables:
            new_columns = self.parse_columns(cols_part)

            cursor.execute("SHOW TABLES LIKE %s", (table_name,))
            exists = cursor.fetchone()

            if not exists:
                # 表不存在 → 直接建表
                create_sql = re.search(rf"(CREATE TABLE `{table_name}`.*?;)", sql_text, re.S).group(1)
                self.log_msg(f"🆕 新建表: {table_name}")
                cursor.execute(create_sql)
                conn.commit()
            else:
                # 表已存在 → 对比结构
                cursor.execute(f"SHOW CREATE TABLE `{table_name}`;")
                old_sql = cursor.fetchone()[1]
                _, old_columns = self.parse_sql_structure_from_text(old_sql)

                alter_sql = self.generate_alter_sql(old_columns, new_columns, table_name)
                if alter_sql:
                    self.log_msg(f"🔄 更新表 {table_name} → {alter_sql}")
                    cursor.execute(alter_sql)
                    conn.commit()
                else:
                    self.log_msg(f"✔ 表 {table_name} 已是最新结构，无需更改")

        cursor.close()
        conn.close()
        QMessageBox.information(self, "完成", "数据库结构同步完成！")

    def parse_columns(self, cols_part):
        """解析字段部分"""
        columns = {}
        for line in cols_part.splitlines():
            line = line.strip().strip(",")
            if line.startswith("`"):
                col_match = re.match(r"`(\w+)`\s+(.*)", line)
                if col_match:
                    col_name = col_match.group(1)
                    col_def = col_match.group(2)
                    columns[col_name] = col_def
        return columns

    def parse_sql_structure_from_text(self, sql):
        match = re.search(r"CREATE TABLE `?(\w+)`?\s*\((.*?)\)\s*ENGINE", sql, re.S)
        if not match:
            raise ValueError("未找到 CREATE TABLE 语句")

        table_name = match.group(1)
        cols_part = match.group(2)
        return table_name, self.parse_columns(cols_part)

    def generate_alter_sql(self, old_cols, new_cols, table_name):
        alters = []

        for col, definition in new_cols.items():
            if col not in old_cols:
                alters.append(f"ADD COLUMN `{col}` {definition}")
            elif old_cols[col] != definition:
                alters.append(f"MODIFY COLUMN `{col}` {definition}")

        for col in old_cols:
            if col not in new_cols:
                alters.append(f"DROP COLUMN `{col}`")

        if not alters:
            return None
        return f"ALTER TABLE `{table_name}` " + ", ".join(alters) + ";"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DBSyncApp()
    win.show()
    sys.exit(app.exec_())
