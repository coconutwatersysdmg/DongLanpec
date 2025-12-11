import json
import traceback

import pymysql
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QMessageBox
import os

from modules.condition_input.view import check_project_and_product
from modules.qiangdujisuan.jiekou_python.combine_json_new import calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_ABEU
from modules.qiangdujisuan.jiekou_python.combine_json_new_abes import calculate_heat_exchanger_strength as calculate_heat_exchanger_strength_ABES

from modules.chanpinguanli.chanpinguanli_main import product_manager

product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id
product_manager.product_id_changed.connect(on_product_id_changed)
class JisuanResultViewer(QWidget):
    def __init__(self, line_tip=None, parent=None):
        super().__init__(parent)

        # # 0903会议纪要 首先进行项目和产品检查
        # print("准备检查项目和产品状态...")
        # can_open, msg = check_project_and_product()
        # if not can_open:
        #     QMessageBox.information(self, "提示", msg)
        #     self.deleteLater()  # 不打开界面
        #     return  # 立即返回

        self.line_tip = line_tip  # 保存主界面传进来的 line_tip
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        self.text_view = QTextEdit(self)
        self.text_view.setReadOnly(True)
        layout.addWidget(self.text_view)

        self.load_result()

    def load_result(self):
        print(product_id)

        try:
            # 查询产品型式
            conn = pymysql.connect(
                host="localhost",  # 数据库地址
                user="root",  # 用户名
                password="123456",  # 密码
                database="产品设计活动库",  # 数据库名
                charset="utf8mb4"
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 产品型式 
                FROM 产品设计活动表 
                WHERE 产品ID = %s
            """, (product_id,))
            row = cursor.fetchone()
            conn.close()
            print("产品型式为",row[0])
            if not row:
                raise ValueError(f"未找到 product_id={product_id} 对应的产品型式")

            product_type = row[0]

            # 根据产品型式调用不同方法
            if product_type in ("AEU", "BEU"):
                result = calculate_heat_exchanger_strength_ABEU(product_id)
            elif product_type in ("AES", "BES"):
                result = calculate_heat_exchanger_strength_ABES(product_id)
            else:
                raise ValueError(f"未知的产品型式: {product_type}")

            # 如果 result 是字符串（不是 dict），就先解析
            if isinstance(result, str):
                result = json.loads(result)

            # 确保 DictOutDatas 的每个子项都是 dict 且含 IsSuccess
            simple_result = {
                "Logs": result["Logs"],
                "DictOutDatas": {
                    name: data["IsSuccess"]
                    for name, data in result["DictOutDatas"].items()
                    if isinstance(data, dict) and "IsSuccess" in data
                }
            }

            # 判断是否有失败
            has_failure = any(not success for success in simple_result["DictOutDatas"].values())

            # 转为字符串展示
            pretty_result = json.dumps(simple_result, ensure_ascii=False, indent=4)

            self.text_view.setPlainText(pretty_result)

            # 如果有失败，更新 line_tip
            if has_failure and self.line_tip:
                self.line_tip.setStyleSheet("color: orange;")  # 设置文字颜色为橘黄色

                self.line_tip.setText(
                    "计算结果出现不通过的情况，请对照输入输出文件核查：shuru_jisuan.json 与 jisuan_output_new.json\n\n"
                )



        except Exception:

            self.text_view.setPlainText(f"发生错误：\n{traceback.format_exc()}")
