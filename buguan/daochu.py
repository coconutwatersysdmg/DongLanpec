import sys
import os
import datetime
import pymysql
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QTextEdit,
    QFileDialog, QVBoxLayout, QHBoxLayout
)


def read_databases_from_txt(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def export_mysql_database(host, port, user, password, databases, output_dir, log_callback):
    os.makedirs(output_dir, exist_ok=True)
    for database in databases:
        try:
            date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = os.path.join(output_dir, f"{database}_{date_str}.sql")

            conn = pymysql.connect(
                host=host,
                port=int(port),
                user=user,
                password=password,
                database=database,
                charset="utf8mb4"
            )
            cursor = conn.cursor()

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(f"-- 导出数据库: {database}\n")
                f.write(f"-- 时间: {datetime.datetime.now()}\n\n")
                f.write("SET FOREIGN_KEY_CHECKS=0;\n\n")

                cursor.execute("SHOW TABLES;")
                tables = [row[0] for row in cursor.fetchall()]

                for table in tables:
                    cursor.execute(f"SHOW CREATE TABLE `{table}`;")
                    create_stmt = cursor.fetchone()[1]
                    f.write(f"-- ----------------------------\n")
                    f.write(f"-- 表结构: {table}\n")
                    f.write(f"-- ----------------------------\n")
                    f.write(f"DROP TABLE IF EXISTS `{table}`;\n")
                    f.write(f"{create_stmt};\n\n")

                    cursor.execute(f"SELECT * FROM `{table}`;")
                    rows = cursor.fetchall()
                    if rows:
                        columns = [desc[0] for desc in cursor.description]
                        f.write(f"-- ----------------------------\n")
                        f.write(f"-- 数据: {table}\n")
                        f.write(f"-- ----------------------------\n")
                        for row in rows:
                            values = []
                            for val in row:
                                if val is None:
                                    values.append("NULL")
                                elif isinstance(val, (int, float)):
                                    values.append(str(val))
                                else:
                                    values.append("'" + str(val).replace("\\", "\\\\").replace("'", "\\'") + "'")
                            insert_stmt = f"INSERT INTO `{table}` ({', '.join(['`'+c+'`' for c in columns])}) VALUES ({', '.join(values)});"
                            f.write(insert_stmt + "\n")
                        f.write("\n")

                f.write("SET FOREIGN_KEY_CHECKS=1;\n")

            cursor.close()
            conn.close()
            log_callback(f"✅ 数据库 {database} 已导出到 {output_file}")
        except Exception as e:
            log_callback(f"❌ 导出数据库 {database} 失败: {e}")


class ExportApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MySQL 数据库导出工具")
        self.resize(600, 400)

        layout = QVBoxLayout()

        # 数据库连接信息
        form_layout = QHBoxLayout()
        self.host_input = QLineEdit("127.0.0.1")
        self.port_input = QLineEdit("3306")
        self.user_input = QLineEdit("root")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        form_layout.addWidget(QLabel("Host:"))
        form_layout.addWidget(self.host_input)
        form_layout.addWidget(QLabel("Port:"))
        form_layout.addWidget(self.port_input)
        form_layout.addWidget(QLabel("User:"))
        form_layout.addWidget(self.user_input)
        form_layout.addWidget(QLabel("Password:"))
        form_layout.addWidget(self.password_input)
        layout.addLayout(form_layout)

        # TXT 选择
        self.txt_path = QLineEdit()
        self.txt_btn = QPushButton("选择数据库列表(txt)")
        self.txt_btn.clicked.connect(self.choose_txt)
        txt_layout = QHBoxLayout()
        txt_layout.addWidget(self.txt_path)
        txt_layout.addWidget(self.txt_btn)
        layout.addLayout(txt_layout)

        # 输出目录
        self.out_dir = QLineEdit("./exports")
        self.out_btn = QPushButton("选择导出目录")
        self.out_btn.clicked.connect(self.choose_dir)
        out_layout = QHBoxLayout()
        out_layout.addWidget(self.out_dir)
        out_layout.addWidget(self.out_btn)
        layout.addLayout(out_layout)

        # 开始按钮
        self.export_btn = QPushButton("开始导出")
        self.export_btn.clicked.connect(self.start_export)
        layout.addWidget(self.export_btn)

        # 日志显示
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log)

        self.setLayout(layout)

    def choose_txt(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择数据库列表文件", ".", "Text Files (*.txt)")
        if file:
            self.txt_path.setText(file)

    def choose_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "选择导出目录", ".")
        if dir_path:
            self.out_dir.setText(dir_path)

    def log_message(self, msg):
        self.log.append(msg)

    def start_export(self):
        txt_file = self.txt_path.text()
        if not os.path.exists(txt_file):
            self.log_message("❌ 数据库列表文件不存在")
            return

        databases = read_databases_from_txt(txt_file)
        if not databases:
            self.log_message("❌ txt 文件中没有数据库名")
            return

        export_mysql_database(
            host=self.host_input.text(),
            port=self.port_input.text(),
            user=self.user_input.text(),
            password=self.password_input.text(),
            databases=databases,
            output_dir=self.out_dir.text(),
            log_callback=self.log_message
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ExportApp()
    window.show()
    sys.exit(app.exec_())
