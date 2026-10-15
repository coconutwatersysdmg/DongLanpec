import datetime
import os
import re
import shutil
import subprocess
import traceback
import pymysql
import openpyxl
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QGroupBox, QCheckBox, QHBoxLayout,
    QPushButton, QMessageBox, QFileDialog, QApplication,
    QLabel, QWidget, QGridLayout, QFrame, QSizePolicy, QSpacerItem
)
from collections import defaultdict
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QEventLoop
from PyQt5.QtGui import QFont
from modules.condition_input.view import check_project_and_product
from modules.wenbenshengcheng import cunguige
from modules.wenbenshengcheng.CalculateReport import generate_calReport
from modules.wenbenshengcheng.calculateReport_doc import (
    export_diaoer_calculation_doc,
    export_fengtou_calculation_doc,
    export_zhuiqiao_calculation_doc,
)
from modules.wenbenshengcheng.cunguige import add_template_sheet, fill_template_values, \
    copy_u_tube_value_openpyxl
from modules.wenbenshengcheng.generate_material_list import generate_material_list  # 材料清单

from modules.chanpinguanli.chanpinguanli_main import product_manager
from modules.chanpinguanli.ui_style import (
    CHANPINGUANLI_BUTTON_QSS,
    apply_chanpinguanli_font,
    show_chanpinguanli_message,
)
from modules.wenbenshengcheng.jiegoucanshu_shuchu import fill_all_components
from modules.generate_icon import make_generate_icon
from modules.wenbenshengcheng.jisuanjiance_tongyong import fill_calculation_report
from modules.wenbenshengcheng.jisuanjiance_tongyong import \
    fill_final_excel_from_intermediate as fill_final_excel_from_intermediate_tongyong
from modules.wenbenshengcheng.jisuanjiance_office import \
    fill_final_excel_from_intermediate as fill_final_excel_from_intermediate_office

product_id = None


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)


class DocumentGenerationDialog(QDialog):

    def __init__(self, parent=None, line_tip=None):
        super().__init__(parent)
        self.line_tip = line_tip
        apply_chanpinguanli_font(self)

        print("准备检查项目和产品状态...")
        can_open, msg = check_project_and_product()
        if not can_open:
            show_chanpinguanli_message(
                self, QMessageBox.Information, "提示", msg
            )
            self.deleteLater()
            return

        self.setWindowTitle("报告输出")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 760)

        # 这里保持 name 不变，避免影响 generate_documents 里的判断逻辑
        self.doc_types = [
            {
                "name": "计算报告",
                "display": "计算报告（xlsx + docx）",
                "icon_mode": "excel_word"
            },
            {
                "name": "结构参数表",
                "display": "结构参数表（xlsx）",
                "icon_mode": "excel"
            },
            {
                "name": "材料清单",
                "display": "材料清单（xlsx）",
                "icon_mode": "excel"
            }
        ]

        self.checkboxes = {}
        self.card_frames = {}

        self._init_report_output_ui()

    def clear_current_selection(self):
        """
        取消当前选择：
        只取消已勾选的文档类型，不关闭当前页面。
        """
        for cb in self.checkboxes.values():
            cb.setChecked(False)
    def _init_report_output_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #f6f7f9;
            }

            QLabel#pageTitle {
                font-size: 18px;
                font-weight: bold;
                color: #004a99;
                padding: 8px 12px;
                background: #e9eef5;
                border-bottom: 1px solid #d5dce5;
            }

            QLabel#sectionTitle {
                font-size: 16px;
                font-weight: bold;
                color: #111;
                padding: 6px 2px;
            }

            QFrame#toolbarFrame {
                background: #ffffff;
                border-bottom: 1px solid #d9e1ec;
            }

            QLabel#toolbarTitle {
                font-size: 14px;
                color: #222;
                padding-left: 2px;
            }

            QFrame#docCard {
                background: white;
                border: 1px solid #d6dbe3;
            }

            QFrame#docCard:hover {
                border: 1px solid #7aa7d9;
                background: #fcfdff;
            }

            QFrame#docPreview {
                background: #ffffff;
                border: 1px solid #d6dbe3;
            }

            QCheckBox {
                font-size: 12px;
                color: #222;
                spacing: 6px;
            }

        """ + CHANPINGUANLI_BUTTON_QSS)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶部标题
        # page_title = QLabel("报告输出")
        # page_title.setObjectName("pageTitle")
        # main_layout.addWidget(page_title, 0)

        # 与图纸绘制页面一致的顶部标题栏。
        toolbar = QFrame()
        toolbar.setObjectName("toolbarFrame")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(16, 10, 16, 10)
        toolbar_layout.setSpacing(12)

        toolbar_title = QLabel("选择要生成的文档")
        toolbar_title.setObjectName("toolbarTitle")
        toolbar_layout.addWidget(toolbar_title)
        toolbar_layout.addStretch(1)
        main_layout.addWidget(toolbar, 0)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 18, 24, 18)
        content_layout.setSpacing(16)

        # 卡片区
        cards_widget = QWidget()
        cards_layout = QGridLayout(cards_widget)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setHorizontalSpacing(26)
        cards_layout.setVerticalSpacing(18)

        for idx, doc in enumerate(self.doc_types):
            card_widget = self._create_doc_card(doc)
            row = idx // 3
            col = idx % 3
            cards_layout.addWidget(card_widget, row, col)

        # 占位弹簧，保证卡片靠左上
        cards_layout.addItem(
            QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum),
            0, 3
        )

        content_layout.addWidget(cards_widget, 0, Qt.AlignTop)

        # 中间空白撑开
        content_layout.addStretch(1)

        main_layout.addWidget(content_widget, 1)

        # 与项目管理页面最下方“保存”按钮一致：用弹簧把操作按钮推到右下角。
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(16, 10, 16, 10)
        action_layout.setSpacing(12)
        action_layout.addStretch(1)

        self.cancel_btn = QPushButton("取消选择")
        self.cancel_btn.clicked.connect(self.clear_current_selection)
        action_layout.addWidget(self.cancel_btn)

        self.generate_btn = QPushButton("生成所选文档")
        self.generate_btn.setIcon(make_generate_icon())
        self.generate_btn.setIconSize(QSize(16, 16))
        self.generate_btn.clicked.connect(self.generate_documents)
        action_layout.addWidget(self.generate_btn)

        main_layout.addWidget(action_widget, 0)

    def _create_doc_card(self, doc):
        """
        创建一个文档卡片：
        上方预览框 + 下方复选框说明
        """
        outer = ClickableFrame()
        outer.setObjectName("docCard")
        outer.setFixedWidth(270)
        outer.setCursor(Qt.PointingHandCursor)

        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(12, 12, 12, 12)
        outer_layout.setSpacing(10)

        preview = ClickableFrame()
        preview.setObjectName("docPreview")
        preview.setFixedSize(250, 150)

        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(0)

        # 图标区域
        icon_container = QWidget()
        icon_layout = QHBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(14)
        icon_layout.setAlignment(Qt.AlignCenter)

        if doc["icon_mode"] == "excel_word":
            icon_layout.addWidget(self._build_file_icon("X", "#69b36d"))
            icon_layout.addWidget(self._build_file_icon("W", "#4f88d9"))
        elif doc["icon_mode"] == "excel":
            icon_layout.addWidget(self._build_file_icon("X", "#69b36d"))
        else:
            icon_layout.addWidget(self._build_file_icon("D", "#999999"))

        preview_layout.addStretch(1)
        preview_layout.addWidget(icon_container, 0, Qt.AlignCenter)
        preview_layout.addStretch(1)

        outer_layout.addWidget(preview, 0, Qt.AlignCenter)

        checkbox = QCheckBox(doc["display"])
        checkbox.setChecked(False)
        self.checkboxes[doc["name"]] = checkbox
        self.card_frames[doc["name"]] = preview

        outer_layout.addWidget(checkbox, 0)

        # 图片区域和卡片空白区域都可以切换勾选；复选框自身仍直接响应。
        outer.clicked.connect(lambda d=doc["name"]: self._toggle_doc_card(d))
        preview.clicked.connect(lambda d=doc["name"]: self._toggle_doc_card(d))
        checkbox.stateChanged.connect(
            lambda state, d=doc["name"]: self._update_doc_card_style(d, state == Qt.Checked)
        )

        self._update_doc_card_style(doc["name"], False)
        return outer

    def _build_file_icon(self, text, bg_color):
        """
        用 QLabel 画一个简洁文件图标
        """
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setFixedSize(32, 32)
        lbl.setStyleSheet(f"""
            QLabel {{
                background: {bg_color};
                color: white;
                font-size: 16px;
                font-weight: bold;
                border-radius: 4px;
                border: 1px solid rgba(0,0,0,0.08);
            }}
        """)
        return lbl

    def _toggle_doc_card(self, doc_name):
        cb = self.checkboxes.get(doc_name)
        if cb:
            cb.setChecked(not cb.isChecked())

    def _update_doc_card_style(self, doc_name, checked):
        frame = self.card_frames.get(doc_name)
        if not frame:
            return

        if checked:
            frame.setStyleSheet("""
                QFrame#docPreview {
                    background: #eef6ff;
                    border: 2px solid #6aa4e8;
                }
            """)
        else:
            frame.setStyleSheet("""
                QFrame#docPreview {
                    background: #ffffff;
                    border: 1px solid #d6dbe3;
                }
            """)

    def generate_documents(self):
        if not any(cb.isChecked() for cb in self.checkboxes.values()):
            show_chanpinguanli_message(
                self, QMessageBox.Warning, "警告", "请至少选择一种文档类型！"
            )
            return

        # ===== 1) 从“产品设计活动表”查询该产品的默认文件夹绝对路径 =====
        def get_product_abs_dir(product_id: str) -> str:

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            try:
                with conn.cursor() as cursor:
                    # ✅ 你按实际表名/字段名改这里两处即可：
                    # - 表名：产品设计活动表_产品表（示例）
                    # - 字段：产品文件夹绝对路径（示例）
                    cursor.execute("""
                        SELECT `产品文件夹绝对路径` AS abs_dir
                        FROM `产品设计活动表`
                        WHERE `产品ID` = %s
                        LIMIT 1
                    """, (product_id,))
                    row = cursor.fetchone()
                    abs_dir = (row.get("abs_dir") or "").strip() if row else ""

            finally:
                conn.close()

            # 兜底：不存在/无效就回退到用户目录
            if not abs_dir or not os.path.isdir(abs_dir):
                abs_dir = os.path.expanduser("~")
            return abs_dir

        default_dir = get_product_abs_dir(product_id)  # 你项目里已有的 product_id

        # ===== 2) 选择保存目录：默认打开 default_dir =====
        save_dir = QFileDialog.getExistingDirectory(self, "选择保存目录", default_dir)
        if not save_dir:
            return

        if self.line_tip is not None:
            self.line_tip.clear()
            self.line_tip.setToolTip("")

        try:
            any_error = False
            completed_docs = []
            conn = pymysql.connect(
                host='localhost',
                user='root',
                password='123456',
                database='产品设计活动库',
                charset='utf8mb4'
            )
            cursor = conn.cursor(pymysql.cursors.DictCursor)

            cursor.execute("""
                            SELECT 产品型式 FROM 产品设计活动表
                            WHERE 产品ID = %s
                        """, (product_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("未找到产品型式")
            exchanger_type = row["产品型式"]
            json_path = "jisuan_output_new_tidai.json"  # 替换为实际路径
            if not os.path.exists(json_path):
                raise FileNotFoundError(f"{json_path} 文件不存在！")
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            error_log_path = os.path.join(save_dir, f"错误日志_{timestamp}.txt")

            for doc in self.doc_types:
                if self.checkboxes[doc["name"]].isChecked():
                    try:
                        if doc["name"] == "计算报告":
                            # ✅ 按型式选择模板
                            if exchanger_type == "AEU":
                                excel_template = "强度计算元件输出参数表_AEU.xlsx"
                                target_path = "计算报告（AEU）.xlsx"
                            elif exchanger_type == "BEU":
                                excel_template = "强度计算元件输出参数表_BEU.xlsx"
                                target_path = "计算报告（BEU）.xlsx"
                            elif exchanger_type == "BES":
                                excel_template = f"强度计算元件输出参数表_BES.xlsx"
                                target_path = "计算报告（BES）.xlsx"
                            elif exchanger_type == "AES":
                                excel_template = "强度计算元件输出参数表_AES.xlsx"
                                target_path = "计算报告（AES）.xlsx"
                            elif exchanger_type == "NEN":
                                excel_template = "强度计算元件输出参数表_NEN.xlsx"
                                target_path = "计算报告（NEN）.xlsx"
                            elif exchanger_type == "BEM":
                                excel_template = "强度计算元件输出参数表_BEM.xlsx"
                                target_path = "计算报告（BEM）.xlsx"
                            elif exchanger_type == "AEM":
                                excel_template = "强度计算元件输出参数表_AEM.xlsx"
                                target_path = "计算报告（AEM）.xlsx"
                            elif exchanger_type == "BKU":
                                excel_template = "强度计算元件输出参数表_BKU.xlsx"
                                target_path = "计算报告（BKU）.xlsx"
                            elif exchanger_type == "AKU":
                                excel_template = "强度计算元件输出参数表_AKU.xlsx"
                                target_path = "计算报告（AKU）.xlsx"
                            elif exchanger_type == "单腔型":
                                excel_template = "强度计算元件输出参数表_单腔型.xlsx"
                                target_path = "计算报告（单腔型）.xlsx"
                            output_path = os.path.join(save_dir, f"计算输出参数总览表_{timestamp}.xlsx")
                            fill_calculation_report(json_path, excel_template, output_path)
                            excel_type = detect_default_excel_app()

                            # 这里 final_path 只是“基准路径”，函数内部会输出：_工况1/_工况2...
                            final_base_path = os.path.join(save_dir, f"计算报告_标准版_{timestamp}.xlsx")

                            if excel_type == "office":
                                print("✔ 使用 Microsoft Excel → 调用 jisuanjiance_office")
                                fill_final_excel_from_intermediate_office(
                                    output_path,  # intermediate_excel_path
                                    target_path,  # target_excel_path (模板)
                                    final_base_path,  # output_excel_path (基准名)
                                    json_path
                                )
                            else:
                                fill_final_excel_from_intermediate_tongyong(
                                    output_path,
                                    target_path,
                                    final_base_path,
                                    json_path
                                )
                            export_fengtou_calculation_doc(
                                product_id,
                                save_dir,
                                json_path=json_path,
                            )
                            # try:
                            #     export_diaoer_calculation_doc(product_id, save_dir)
                            #     export_zhuiqiao_calculation_doc(product_id, save_dir)
                            # except Exception as e:
                            #     print(f"生成吊耳计算书失败：{e}")
                        elif doc["name"] == "材料清单":
                            output_path = os.path.join(save_dir, f"材料清单-生成_{timestamp}.xlsx")
                            material_sheet_name = "Sheet1"
                            template_file_path = os.path.join("modules", "wenbenshengcheng", "U形管计算-模板.xlsx")
                            # 材料清单模板：B/C 分列名称与规格，O:R 为重量列，S:U 为状态/类型/备注。
                            generate_material_list(product_id, output_path)
                            if exchanger_type == "AEU" or exchanger_type == "BEU" or exchanger_type == "AKU" or exchanger_type == "BKU":
                                add_template_sheet(output_path, template_file_path)
                                fill_template_values(output_path, product_id)
                                copy_u_tube_value_openpyxl(output_path)
                            # 固定材料尾行紧跟生成内容；O:R 合计写在最后一条重量明细的下一行。
                            cunguige.main(json_path, output_path, material_sheet_name, product_id)

                        elif doc["name"] == "结构参数表":
                            excel_template = "结构数据关联.xlsx"

                            output_path = os.path.join(save_dir, f"结构参数表_生成_{timestamp}.xlsx")
                            fill_all_components(product_id, excel_template, output_path, conn)
                        else:
                            self.copy_template_document(doc["name"], doc["ext"], doc["filter"], save_dir)

                    except Exception as e:
                        any_error = True  # 记录有错误
                        print("❌ 整体写入过程中发生异常：")
                        traceback.print_exc()
                        # 同一次文档生成共用一个带时间戳的日志文件，避免跨次混写。
                        with open(error_log_path, "a", encoding="utf-8") as f:
                            f.write("❌ 整体写入过程中发生异常：\n")
                            traceback.print_exc(file=f)
                        show_chanpinguanli_message(
                            self, QMessageBox.Critical, "错误", f"生成文档时出错:\n{str(e)}"
                        )
                    else:
                        completed_docs.append("计算书" if doc["name"] == "计算报告" else doc["name"])

            if completed_docs and self.line_tip is not None:
                # 先处理耗时生成期间到期的旧提示清空回调，再写入本次完成提示。
                QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
                tip_text = f"{'/'.join(completed_docs)}已完成生成"
                self.line_tip.setStyleSheet("color: black;")
                self.line_tip.setText(tip_text)
                self.line_tip.setToolTip(tip_text)
                self.line_tip.repaint()

            # ✅ 在生成逻辑的最后加入
            import platform

            if not any_error:
                try:
                    if platform.system() == "Windows":
                        os.startfile(save_dir)
                    elif platform.system() == "Darwin":
                        subprocess.Popen(["open", save_dir])
                    else:
                        subprocess.Popen(["xdg-open", save_dir])
                except Exception as e:
                    show_chanpinguanli_message(
                        self, QMessageBox.Warning, "提示", f"打开文件夹失败：{e}"
                    )

        except Exception as e:
            show_chanpinguanli_message(
                self, QMessageBox.Critical, "错误", f"生成文档时出错:\n{str(e)}"
            )

    def copy_template_document(self, doc_name, extension, file_filter, save_dir):
        if extension == ".xlsx" and doc_name == "计算报告":
            # 新方法生成计算报告
            generate_calReport(product_id)
        else:
            # 其他文档仍使用手动复制模板
            template_path, _ = QFileDialog.getOpenFileName(
                self,
                f"选择{doc_name}模板文件",
                "",
                file_filter
            )
            if not template_path:
                raise Exception(f"{doc_name}模板未选择")

            dest_path = os.path.join(save_dir, f"{doc_name}{extension}")
            shutil.copy2(template_path, dest_path)


import winreg


def detect_default_excel_app(debug=True):
    """
    检测 Windows 下 .xlsx 的默认打开方式
    返回:
        'office' - 默认打开为 Microsoft Excel
        'wps'    - 默认打开为 WPS 表格
        'none'   - 没有关联或不可识别
    """

    def log(msg):
        if debug:
            print(msg)

    log("========== 检测 .xlsx 默认打开方式 ==========")

    try:
        # Step 1：读取 .xlsx 的关联项
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, ".xlsx")
        prog_id, _ = winreg.QueryValueEx(key, None)
        log(f"[Step 1] .xlsx = {prog_id!r}")
        winreg.CloseKey(key)
    except Exception as e:
        log(f"[Step 1] 无法读取 .xlsx 关联: {e}")
        return "none"

    # Step 2：根据 ProgID 判断
    prog_id = prog_id.lower()

    log(f"[Step 2] ProgID 小写形式 = {prog_id}")

    # ---- Office Excel 典型 ProgID ----
    office_ids = [
        "excel.sheet.12",
        "excel.sheet.8",
        "xlsxfile",
    ]

    if any(oid in prog_id for oid in office_ids):
        log("[Step 2] 命中 Office ProgID → office")
        return "office"

    # ---- WPS 表格典型 ProgID ----
    wps_ids = [
        "kwps.xlsx.12",
        "wps.xlsx",
        "et.xlsx",  # WPS 兼容模式
        "wps.sheet",  # WPS 新版
    ]

    if any(wid in prog_id for wid in wps_ids):
        log("[Step 2] 命中 WPS ProgID → wps")
        return "wps"

    log("[Step 2] ProgID 无法识别 → none")
    return "none"
