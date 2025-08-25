import json
import traceback

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit
import os

from modules.qiangdujisuan.jiekou_python.combine_json_new import calculate_heat_exchanger_strength
from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.qiangdujisuan.jiekou_python.combine_json_new_aeu import calculate_heat_exchanger_strength_AEU

product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id
product_manager.product_id_changed.connect(on_product_id_changed)
class JisuanResultViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        self.text_view = QTextEdit(self)
        self.text_view.setReadOnly(True)
        layout.addWidget(self.text_view)

        self.load_result()

    def load_result(self):
        print(product_id)

        try:
            result = calculate_heat_exchanger_strength(product_id)
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

            # 转为字符串展示
            pretty_result = json.dumps(simple_result, ensure_ascii=False, indent=4)
            self.text_view.setPlainText(pretty_result)

        except Exception:

            self.text_view.setPlainText(f"发生错误：\n{traceback.format_exc()}")
