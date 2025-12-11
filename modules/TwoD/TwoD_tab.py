import json
import os
import time

import chardet
import configparser

import pythoncom
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel,
                             QMessageBox, QHBoxLayout, QSpacerItem, QSizePolicy)
from PyQt5.QtCore import Qt, QPropertyAnimation, QPoint, QEasingCurve
from PyQt5.QtGui import (QPalette, QColor, QPainter, QBrush,
                         QPainterPath, QLinearGradient, QFont, QPen)
from win32com.universal import com_error

from modules.TwoD.toubiaotu_biaozhu import extract_dimensions, auto_save_copy
from modules.chanpinguanli.chanpinguanli_main import product_manager
import logging
import os
import sys
import traceback

# 日志文件路径
log_dir = os.path.join(os.getcwd(), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def log_info(msg):
    logging.info(msg)

def log_warn(msg):
    logging.warning(msg)

def log_error(msg):
    logging.error(msg)
def global_exception_hook(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        # Ctrl+C 直接退出
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.critical("未捕获异常!", exc_info=(exc_type, exc_value, exc_traceback))
    # 可选：弹窗提示
    try:
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.critical(None, "程序错误", f"发生未捕获异常:\n{exc_value}")
    except Exception:
        pass


product_id = None


def on_product_id_changed(new_id):
    print(f"Received new PRODUCT_ID: {new_id}")
    global product_id
    product_id = new_id


# 测试用产品 ID（真实情况中由外部输入）
product_manager.product_id_changed.connect(on_product_id_changed)
class ThreeDRedButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(200, 200)  # Even larger button
        self.setFont(QFont('Arial', 14, QFont.Bold))
        self.default_text_color = Qt.white
        self.complete_text_color = Qt.black
        self.current_text_color = self.default_text_color
        self.pressed_offset = QPoint(0, 5)  # Press down movement
        self.normal_pos = QPoint(0, 0)
        self.is_pressed = False

        # Setup press animation
        self.press_animation = QPropertyAnimation(self, b"pos_offset")
        self.press_animation.setDuration(100)
        self.press_animation.setEasingCurve(QEasingCurve.OutQuad)

    def get_pos_offset(self):
        return self._pos_offset if hasattr(self, '_pos_offset') else QPoint(0, 0)

    def set_pos_offset(self, offset):
        self._pos_offset = offset
        self.update()

    pos_offset = property(get_pos_offset, set_pos_offset)

    def mousePressEvent(self, event):
        self.is_pressed = True
        self.press_animation.stop()
        self.press_animation.setStartValue(self.normal_pos)
        self.press_animation.setEndValue(self.pressed_offset)
        self.press_animation.start()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.is_pressed = False
        self.press_animation.stop()
        self.press_animation.setStartValue(self.pos_offset)
        self.press_animation.setEndValue(self.normal_pos)
        self.press_animation.start()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Adjust position based on press state
        if self.is_pressed:
            painter.translate(self.pressed_offset)

        # Draw main button body
        path = QPainterPath()
        path.addEllipse(5, 5, self.width() - 10, self.height() - 10)

        # Enhanced 3D gradient (darker when pressed)
        gradient = QLinearGradient(0, 0, 0, self.height())
        if self.is_pressed:
            gradient.setColorAt(0, QColor(180, 0, 0))
            gradient.setColorAt(1, QColor(120, 0, 0))
        else:
            gradient.setColorAt(0, QColor(255, 50, 50))
            gradient.setColorAt(1, QColor(180, 0, 0))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)

        # Add 3D edge
        edge_pen = QPen(QColor(100, 0, 0), 3)
        painter.setPen(edge_pen)
        painter.drawEllipse(5, 5, self.width() - 10, self.height() - 10)

        # Add highlight (smaller when pressed)
        highlight = QPainterPath()
        if self.is_pressed:
            highlight.addEllipse(20, 20, self.width() - 40, self.height() / 4)
            painter.setBrush(QBrush(QColor(255, 255, 255, 60)))
        else:
            highlight.addEllipse(15, 15, self.width() - 30, self.height() / 3)
            painter.setBrush(QBrush(QColor(255, 255, 255, 80)))
        painter.drawPath(highlight)

        # Draw text (with shadow when not pressed)
        if not self.is_pressed:
            painter.setPen(QColor(0, 0, 0, 100))
            painter.drawText(self.rect().translated(2, 2), Qt.AlignCenter, self.text())

        painter.setPen(self.current_text_color)
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())

    def setComplete(self):
        self.current_text_color = self.complete_text_color
        self.setText("生成完成")
        self.update()


class TwoDGeneratorTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        # Set light blue background
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(200, 230, 255))  # Lighter blue
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Center container
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)

        # Add flexible space above
        center_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        # Horizontal centering layout
        h_layout = QHBoxLayout()
        h_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Create the 3D animated button
        self.generate_button = ThreeDRedButton("点击生成\n二维图")
        self.generate_button.clicked.connect(self.run_generation)
        h_layout.addWidget(self.generate_button)

        h_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        center_layout.addLayout(h_layout)

        # Add flexible space below
        center_layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Minimum, QSizePolicy.Expanding))

        main_layout.addWidget(center_container)
        self.setLayout(main_layout)

    def run_generation(self):

        global out_len_map
        from modules.TwoD.toubiaotu_wenziduixiang import twoDgeneration
        from modules.TwoD.toubiaotu_biaozhu import apply_dimension_labels
        from modules.TwoD.toubiaotu_wenziduixiang_BEU_4 import twoDgeneration as twoDgeneration_BEU_4
        from modules.TwoD.toubiaotu_wenziduixiang_AEU_2 import twoDgeneration as twoDgeneration_AEU_2
        from modules.TwoD.toubiaotu_wenziduixiang_AEU_4 import twoDgeneration as twoDgeneration_AEU_4
        from modules.TwoD.toubiaotu_wenziduixiang_BES_2 import twoDgeneration as twoDgeneration_BES_2
        from modules.TwoD.toubiaotu_wenziduixiang_BES_4_1 import twoDgeneration as twoDgeneration_BES_4_1
        from modules.TwoD.toubiaotu_wenziduixiang_BES_4_2 import twoDgeneration as twoDgeneration_BES_4_2
        from modules.TwoD.toubiaotu_wenziduixiang_BES_4_3 import twoDgeneration as twoDgeneration_BES_4_3
        from modules.TwoD.toubiaotu_wenziduixiang_BES_6_1 import twoDgeneration as twoDgeneration_BES_6_1
        from modules.TwoD.toubiaotu_wenziduixiang_BES_6_2 import twoDgeneration as twoDgeneration_BES_6_2
        from modules.TwoD.toubiaotu_wenziduixiang_AES_2 import twoDgeneration as twoDgeneration_AES_2
        from modules.TwoD.toubiaotu_wenziduixiang_AES_4_1 import twoDgeneration as twoDgeneration_AES_4_1
        from modules.TwoD.toubiaotu_wenziduixiang_AES_4_2 import twoDgeneration as twoDgeneration_AES_4_2
        from modules.TwoD.toubiaotu_wenziduixiang_AES_4_3 import twoDgeneration as twoDgeneration_AES_4_3
        from modules.TwoD.toubiaotu_wenziduixiang_AES_6_1 import twoDgeneration as twoDgeneration_AES_6_1
        from modules.TwoD.toubiaotu_wenziduixiang_AES_6_2 import twoDgeneration as twoDgeneration_AES_6_2
        from modules.TwoD.toubiaotu_wenziduixiang_flange_ao import twoDgeneration as twoDgeneration_flange_ao
        from modules.TwoD.toubiaotu_wenziduixiang_flange_ao_fuceng import twoDgeneration as twoDgeneration_flange_ao_fuceng
        from modules.TwoD.toubiaotu_wenziduixiang_flange_tu import twoDgeneration as twoDgeneration_flange_tu
        from modules.TwoD.toubiaotu_wenziduixiang_flange_tu_fuceng import twoDgeneration as twoDgeneration_flange_tu_fuceng
        from modules.TwoD.toubiaotu_biaozhu import generate_and_save_flange


        # === 1. 获取产品型式 ===
        def get_product_type(product_id):
            import pymysql

            print("🔍 调试：查询产品ID =", product_id)
            conn = None
            try:
                conn = pymysql.connect(
                    host="localhost", user="root", password="123456",
                    database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
                )
                with conn.cursor() as cursor:
                    sql = """
                        SELECT 产品型式 FROM 产品设计活动表
                        WHERE 产品ID = %s LIMIT 1
                    """
                    print("🔍 执行 SQL:", sql, "参数:", product_id)
                    cursor.execute(sql, (str(product_id),))  # 转成字符串以防类型不一致
                    row = cursor.fetchone()

                    if not row:
                        print(f"⚠️ 没有找到 产品ID={product_id} 的记录")
                        return None

                    product_type = row.get("产品型式")
                    if not product_type:
                        print(f"⚠️ 产品ID={product_id} 的产品型式字段为空")
                        return None

                    print(f"✅ 查询结果: 产品型式={product_type}")
                    return product_type.strip()

            except Exception as e:
                import traceback
                print(f"❌ 查询产品型式出错: {e}")
                traceback.print_exc()
                return None

            finally:
                if conn:
                    conn.close()

        # === 2. 读取 config.ini 获取布管输入参数 JSON 路径 ===
        # === 数据库连接方法 ===
        import pymysql

        # === 数据库连接方法 ===
        def get_db_connection():
            conn = pymysql.connect(
                host="localhost",
                port=3306,
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            return conn, conn.cursor()

        def check_flanges(product_id):
            conn, cursor = get_db_connection()
            try:
                # 1️⃣ 查所有符合条件的法兰
                cursor.execute("""
                    SELECT DISTINCT 元件名称
                    FROM 产品设计活动表_元件附加参数表
                    WHERE 产品ID = %s AND 元件名称 LIKE %s AND 元件名称 != '浮头法兰'
                """, (product_id, '%法兰'))
                flanges = [row["元件名称"] for row in cursor.fetchall()]

                results = []
                for flange in flanges:
                    # 2️⃣ 查该法兰的密封面类型
                    cursor.execute("""
                        SELECT 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '法兰密封面'
                        LIMIT 1
                    """, (product_id, flange))
                    row = cursor.fetchone()
                    face_type = str(row["参数值"]).strip() if row else None

                    # 3️⃣ 查该法兰的是否添加覆层
                    cursor.execute("""
                        SELECT 参数值
                        FROM 产品设计活动表_元件附加参数表
                        WHERE 产品ID = %s AND 元件名称 = %s AND 参数名称 = '是否添加覆层'
                        LIMIT 1
                    """, (product_id, flange))
                    row = cursor.fetchone()
                    coating = str(row["参数值"]).strip() if row else None

                    # 4️⃣ 保存结果
                    results.append({
                        "法兰名称": flange,
                        "密封面": face_type,
                        "覆层": coating
                    })

                    print(f"{flange}: 密封面={face_type}, 覆层={coating}")

                return results
            finally:
                cursor.close()
                conn.close()

        # === 从数据库提取管程数 ===
        def get_passes_info(product_id):
            conn, cursor = get_db_connection()
            try:
                cursor.execute("""
                    SELECT 参数值
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '管程程数'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                if row:
                    tube_pass = str(row["参数值"]).strip()
                    print(f"{tube_pass}")
                    return tube_pass
                return None
            finally:
                cursor.close()
                conn.close()
        def get_fencheng_info(product_id):
            conn, cursor = get_db_connection()
            try:
                cursor.execute("""
                    SELECT 参数值
                    FROM 产品设计活动表_布管参数表
                    WHERE 产品ID = %s AND 参数名 = '管程分程形式'
                    LIMIT 1
                """, (product_id,))
                row = cursor.fetchone()
                if row:
                    tube_pass = str(row["参数值"]).strip()
                    print(f"{tube_pass}")
                    return tube_pass
                return None
            finally:
                cursor.close()
                conn.close()



        # === 主逻辑 ===
        product_type = get_product_type(product_id)
        passes = get_passes_info(product_id)
        fenchengxingshi = get_fencheng_info(product_id)
        flange_info = check_flanges(product_id)
        print("flange:",flange_info)
        # === 5. 调用对应函数 ===
        if product_type == "BEU" and passes == "2":

            twoDgeneration(product_id)
            # extract_dimensions()
            handle_label_dict = {
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '8188F': '底座高度+500',
                '779ED': '管口和底座差值',
                "77995": '封头到管箱距离',
                "77C78": "管程连接厚度",
                "819E9": "支座高度"
            }
            # === 读取 JSON 文件 ===
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            saddle_height = None

            # === 遍历 DictOutData 中的支座条目 ===
            for item in data.get("DictOutData", {}).get("支座", []):
                if item.get("Id") == "m_Saddle_h":
                    saddle_height = item.get("Value", "0")
                    break
            handle_label_dict["819E9"] = saddle_height

            print(f"✅ 鞍式支座高度h: {saddle_height}")
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                extra = (get_val_by_id_and_name("固定管板", "工况1：TSH14", "管板名义厚度") -
                         2 * get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * get_val_by_id_and_name("壳体法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * tutai_height +
                         get_val_by_id_and_name("管箱法兰", "工况1：FL155", "法兰总高") +
                         get_val_by_id_and_name("壳体法兰", "工况1：FL155", "法兰总高")
                         )
                handle_label_dict["81881"] = round(base_distance + extra, 3)
            else:
                handle_label_dict["81881"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "81886":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱封头", "椭圆形封头直边高度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高")+
                            get_val("壳体封头", "椭圆形封头名义厚度") +
                            get_val("壳体封头", "椭圆形封头外曲面深度") +
                            get_val("壳体封头", "椭圆形封头直边高度")+
                           get_val("壳体法兰", "法兰总高")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "77991":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter1 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter2 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter3 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter4 = float(row["Value"]) / 2 if row else 0.0

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n1_len = out_len_map.get("管程入口接管", "")
            n2_len = out_len_map.get("管程出口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            import pymysql
            middle_value = None
            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                            SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND 管口功能 IN ('管程入口', '管程出口','壳程出口','壳程入口')
                        """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                            SELECT 公称尺寸类型, 公称压力类型
                            FROM 产品设计活动表_管口类型选择表
                            WHERE 产品ID = %s
                        """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu5 = None  # 排液口
            gaodu6 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]

                        if func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                        elif func == "壳程入口":
                            gaodu5 = val
                        elif func == "壳程出口":
                            gaodu6 = val
                    break  # 找到一个匹配项就退出

            middle_value = str(float(n1_len) + float(cylinder_inner_diameter1) + float(gaodu3))

            handle_label_dict["831ce"] = f"{middle_value}±3"
            print(f"✅ 管口 N1 → 外伸高度 → handle 831ce = {n1_len}")

            middle_value2 = float(n2_len) + float(cylinder_inner_diameter2) + float(gaodu4)
            handle_label_dict["831cf"] = f"{middle_value2}±3"
            print(f"✅ 管口 N2 → 外伸高度 → handle 831cf = {n2_len}")
            middle_value3 = str(float(n3_len) + float(cylinder_inner_diameter3) + float(gaodu5))

            handle_label_dict["8308e"] = f"{middle_value3}±3"
            print(f"✅ 管口 N3 → 外伸高度 → handle 8308e = {n3_len}")

            middle_value4 = float(n4_len) + float(cylinder_inner_diameter4) + float(gaodu6)
            handle_label_dict["8308f"] = f"{middle_value4}±3"
            print(f"✅ 管口 N4 → 外伸高度 → handle 8308f = {n4_len}")


            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break

            # === 从数据库中查公称直径（注意：名称可能为“公称直径DN”或类似） ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            nominal_diameter = float(row["Value"]) if row else 0.0
            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # === 计算最终高度：鞍式支座高度h + 公称直径/2
            handle_label_dict["8188F"] = round(float(support_height) + float(nominal_diameter) / 2 + float(cylinder_nominal_thickness), 3)
            print(f"✅ 8188F → {support_height} + {nominal_diameter / 2} = {handle_label_dict['8188F']}")
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            handle_label_dict["819E9"] = support_height
            jianju = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    try:
                        jianju = float(entry.get("Value", 0))
                    except:
                        jianju = 0
                    break
            handle_label_dict["81881"] = jianju
            l1_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81888"] = float(l1_val) - 10
            handle_label_dict["81592"] = float(l1_val) - 10
            handle_label_dict["81596"] = l1_val

            fuban_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["81593"] = fuban_val
            handle_label_dict["815C3"] = f"2-{fuban_val}"
            l9_val=0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81881"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81882"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["81595"] = f"{l2_val}±2"
            handle_label_dict["81887"] = f"{l2_val}±2"
            handle_label_dict["816FD"] = l2_val
            b5_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["81883"] = b5_val
            handle_label_dict["81592"] = b5_val
            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b1_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["815C1"] = int(b1_val) / 2
            handle_label_dict["815C2"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["8158E"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["8158F"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["817F3"] = str(l3_val) + "±2"

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81594"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            gp_exit_val = 0
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = 0
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "818BB": "管程入口接管",
                "81A03": "管程出口接管",
                "81905": "壳程入口接管",
                "819E5": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = ""
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

                if gt_value:
                    handle_label_dict["8188B"] = f"∅{gt_value}"
                    print(f"✅ 管程公称直径 → handle 8188B = {gt_value}")
                if kt_value:
                    handle_label_dict["81889"] = f"∅{kt_value}"
                    print(f"✅ 壳程公称直径 → handle 81889 = {kt_value}")
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["82b59"] = yuantong_thickness
            yuantong_thickness = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["82b88"] = yuantong_thickness
            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass=None
            shell_pass=None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "BEU" and (passes == "4" or passes == "6"):
            twoDgeneration_BEU_4(product_id)
            # extract_dimensions()
            handle_label_dict = {
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '8188F': '底座高度+500',
                '779ED': '管口和底座差值',
                "77995": '封头到管箱距离',
                "77C78": "管程连接厚度",
                "819E9": "支座高度"
            }
            # === 读取 JSON 文件 ===
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            saddle_height = None

            # === 遍历 DictOutData 中的支座条目 ===
            for item in data.get("DictOutData", {}).get("支座", []):
                if item.get("Id") == "m_Saddle_h":
                    saddle_height = item.get("Value", "0")
                    break
            handle_label_dict["819E9"] = saddle_height

            print(f"✅ 鞍式支座高度h: {saddle_height}")
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = None  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                extra = (get_val_by_id_and_name("固定管板", "工况1：TSH14", "管板名义厚度") -
                         2 * get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * get_val_by_id_and_name("壳体法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * tutai_height +
                         get_val_by_id_and_name("管箱法兰", "工况1：FL155", "法兰总高") +
                         get_val_by_id_and_name("壳体法兰", "工况1：FL155", "法兰总高")
                         )
                handle_label_dict["81881"] = round(base_distance + extra, 3)
            else:
                handle_label_dict["81881"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "81886":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱封头", "椭圆形封头直边高度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("壳体封头", "椭圆形封头名义厚度") +
                            get_val("壳体封头", "椭圆形封头外曲面深度") +
                            get_val("壳体封头", "椭圆形封头直边高度") +

                            get_val("壳体法兰", "法兰总高")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "77991":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break

            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter1 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter2 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter3 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter4 = float(row["Value"]) / 2 if row else 0.0


            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n1_len = out_len_map.get("管程入口接管", "")
            n2_len = out_len_map.get("管程出口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            import pymysql
            middle_value = None
            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                            SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND 管口功能 IN ('管程入口', '管程出口','壳程出口','壳程入口')
                        """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                            SELECT 公称尺寸类型, 公称压力类型
                            FROM 产品设计活动表_管口类型选择表
                            WHERE 产品ID = %s
                        """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu5 = None  # 排液口
            gaodu6 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]

                        if func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                        elif func == "壳程入口":
                            gaodu5 = val
                        elif func == "壳程出口":
                            gaodu6 = val
                    break  # 找到一个匹配项就退出

            middle_value = str(float(n1_len) + float(cylinder_inner_diameter1) + float(gaodu3))

            handle_label_dict["831ce"] = f"{middle_value}±3"
            print(f"✅ 管口 N1 → 外伸高度 → handle 831ce = {n1_len}")

            middle_value2 = float(n2_len) + float(cylinder_inner_diameter2) + float(gaodu4)
            handle_label_dict["831cf"] = f"{middle_value2}±3"
            print(f"✅ 管口 N2 → 外伸高度 → handle 831cf = {n2_len}")
            middle_value3 = str(float(n3_len) + float(cylinder_inner_diameter3) + float(gaodu5))

            handle_label_dict["831d0"] = f"{middle_value3}±3"
            print(f"✅ 管口 N3 → 外伸高度 → handle 831d0 = {n3_len}")

            middle_value4 = float(n4_len) + float(cylinder_inner_diameter4) + float(gaodu6)
            handle_label_dict["831d1"] = f"{middle_value4}±3"
            print(f"✅ 管口 N4 → 外伸高度 → handle 831d1 = {n4_len}")

            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break


            # === 从数据库中查公称直径（注意：名称可能为“公称直径DN”或类似） ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            nominal_diameter = float(row["Value"]) if row else 0.0
            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # === 计算最终高度：鞍式支座高度h + 公称直径/2
            handle_label_dict["8188F"] = round(float(support_height) + float(nominal_diameter) / 2 + float(cylinder_nominal_thickness), 3)
            print(f"✅ 8188F → {support_height} + {nominal_diameter / 2} = {handle_label_dict['8188F']}")
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            handle_label_dict["819E9"] = support_height
            l1_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81888"] = float(l1_val) - 10
            handle_label_dict["81592"] = float(l1_val) - 10
            handle_label_dict["81596"] = l1_val

            fuban_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["81593"] = fuban_val
            handle_label_dict["815C3"] = f"2-{fuban_val}"
            l9_val=0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81881"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81882"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["81595"] = f"{l2_val}±2"
            handle_label_dict["81887"] = f"{l2_val}±2"
            handle_label_dict["816FD"] = l2_val
            b5_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["81883"] = b5_val
            handle_label_dict["81592"] = b5_val
            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b1_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["815C1"] = int(b1_val) / 2
            handle_label_dict["815C2"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["8158E"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["8158F"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["817F3"] = str(l3_val) + "±2"

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81594"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            gp_exit_val = 0
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "818BB": "管程入口接管",
                "81A03": "管程出口接管",
                "81905": "壳程入口接管",
                "819E5": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["83081"] = yuantong_thickness
            yuantong_thickness = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["82c1b"] = yuantong_thickness
            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

                if gt_value:
                    handle_label_dict["8188B"] = f"∅{gt_value}"
                    print(f"✅ 管程公称直径 → handle 8188B = {gt_value}")
                if kt_value:
                    handle_label_dict["83080"] = f"∅{kt_value}"
                    print(f"✅ 壳程公称直径 → handle 83080 = {kt_value}")

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = 0
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass=None
            shell_pass=None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)


        if product_type == "AEU" and passes == "2":

            twoDgeneration_AEU_2(product_id)
            # extract_dimensions()
            handle_label_dict = {
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '8188F': '底座高度+500',
                '779ED': '管口和底座差值',
                "77995": '封头到管箱距离',
                "77C78": "管程连接厚度",
                "819E9": "支座高度"
            }
            # === 读取 JSON 文件 ===
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            saddle_height = None

            # === 遍历 DictOutData 中的支座条目 ===
            for item in data.get("DictOutData", {}).get("支座", []):
                if item.get("Id") == "m_Saddle_h":
                    saddle_height = item.get("Value", "0")
                    break
            handle_label_dict["819E9"] = saddle_height

            print(f"✅ 鞍式支座高度h: {saddle_height}")
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                extra = (get_val_by_id_and_name("固定管板", "工况1：TSH14", "管板名义厚度") -
                         2 * get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * get_val_by_id_and_name("壳体法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * tutai_height +
                         get_val_by_id_and_name("管箱法兰", "工况1：FL155", "法兰总高") +
                         get_val_by_id_and_name("壳体法兰", "工况1：FL155", "法兰总高")
                         )
                handle_label_dict["81881"] = round(base_distance + extra, 3)
            else:
                handle_label_dict["81881"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "81886":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("管箱平盖", "法兰名义厚度") +

                            get_val("头盖法兰", "法兰总高") +
                            get_val("壳体封头", "椭圆形封头名义厚度") +
                            get_val("壳体封头", "椭圆形封头外曲面深度") +
                            get_val("壳体封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "77991":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break

            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter1 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter2 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter3 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter4 = float(row["Value"]) / 2 if row else 0.0

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n1_len = out_len_map.get("管程入口接管", "")
            n2_len = out_len_map.get("管程出口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            import pymysql
            middle_value = None
            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                            SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND 管口功能 IN ('管程入口', '管程出口','壳程出口','壳程入口')
                        """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                            SELECT 公称尺寸类型, 公称压力类型
                            FROM 产品设计活动表_管口类型选择表
                            WHERE 产品ID = %s
                        """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu5 = None  # 排液口
            gaodu6 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]

                        if func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                        elif func == "壳程入口":
                            gaodu5 = val
                        elif func == "壳程出口":
                            gaodu6 = val
                    break  # 找到一个匹配项就退出

            middle_value = str(float(n1_len) + float(cylinder_inner_diameter1) + float(gaodu3))

            handle_label_dict["831ce"] = f"{middle_value}±3"
            print(f"✅ 管口 N1 → 外伸高度 → handle 831ce = {n1_len}")

            middle_value2 = float(n2_len) + float(cylinder_inner_diameter2) + float(gaodu4)
            handle_label_dict["831cf"] = f"{middle_value2}±3"
            print(f"✅ 管口 N2 → 外伸高度 → handle 831cf = {n2_len}")
            middle_value3 = str(float(n3_len) + float(cylinder_inner_diameter3) + float(gaodu5))

            handle_label_dict["82df8"] = f"{middle_value3}±3"
            print(f"✅ 管口 N3 → 外伸高度 → handle 82df8 = {n3_len}")

            middle_value4 = float(n4_len) + float(cylinder_inner_diameter4) + float(gaodu6)
            handle_label_dict["82e2b"] = f"{middle_value4}±3"
            print(f"✅ 管口 N4 → 外伸高度 → handle 82e2b = {n4_len}")



            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break

            # === 从数据库中查公称直径（注意：名称可能为“公称直径DN”或类似） ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            nominal_diameter = float(row["Value"]) if row else 0.0
            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            handle_label_dict["82b01"] = cylinder_nominal_thickness

            # === 计算最终高度：鞍式支座高度h + 公称直径/2
            handle_label_dict["8188F"] = round(float(support_height) + float(nominal_diameter) / 2 + float(cylinder_nominal_thickness), 3)
            print(f"✅ 8188F → {support_height} + {nominal_diameter / 2} = {handle_label_dict['8188F']}")
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            handle_label_dict["819E9"] = support_height
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81888"] = float(l1_val) - 10
            handle_label_dict["81592"] = float(l1_val) - 10
            handle_label_dict["81596"] = l1_val

            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["81593"] = fuban_val
            handle_label_dict["815C3"] = f"2-{fuban_val}"
            l9_val=None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81881"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81882"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["81595"] = f"{l2_val}±2"
            handle_label_dict["81887"] = f"{l2_val}±2"
            handle_label_dict["816FD"] = l2_val
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["81883"] = b5_val
            handle_label_dict["81592"] = b5_val
            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["815C1"] = int(b1_val) / 2
            handle_label_dict["815C2"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["8158E"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["8158F"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["817F3"] = str(l3_val) + "±2"

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81594"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "818BB": "管程入口接管",
                "81A03": "管程出口接管",
                "81905": "壳程入口接管",
                "819E5": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = ""
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["82b99"] = yuantong_thickness
            yuantong_thickness = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["82b9a"] = yuantong_thickness
            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

                if gt_value:
                    handle_label_dict["8188B"] = f"∅{gt_value}"
                    print(f"✅ 管程公称直径 → handle 8188B = {gt_value}")
                if kt_value:
                    handle_label_dict["81889"] = f"∅{kt_value}"
                    print(f"✅ 壳程公称直径 → handle 81889 = {kt_value}")

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass=None
            shell_pass=None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass

            apply_dimension_labels(handle_label_dict)

        if product_type == "AEU" and (passes == "4" or passes == "6"):

            twoDgeneration_AEU_4(product_id)
            # extract_dimensions()
            handle_label_dict = {
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '8188F': '底座高度+500',
                '779ED': '管口和底座差值',
                "77995": '封头到管箱距离',
                "77C78": "管程连接厚度",
                "819E9": "支座高度"
            }
            # === 读取 JSON 文件 ===
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                data = json.load(f)

            saddle_height = None

            # === 遍历 DictOutData 中的支座条目 ===
            for item in data.get("DictOutData", {}).get("支座", []):
                if item.get("Id") == "m_Saddle_h":
                    saddle_height = item.get("Value", "0")
                    break
            handle_label_dict["819E9"] = saddle_height

            print(f"✅ 鞍式支座高度h: {saddle_height}")
            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                extra = (get_val_by_id_and_name("固定管板", "工况1：TSH14", "管板名义厚度") -
                         2 * get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * get_val_by_id_and_name("壳体法兰", "m_ThicknessGasket", "垫片厚度") -
                         2 * tutai_height +
                         get_val_by_id_and_name("管箱法兰", "工况1：FL155", "法兰总高") +
                         get_val_by_id_and_name("壳体法兰", "工况1：FL155", "法兰总高")
                         )
                handle_label_dict["81881"] = round(base_distance + extra, 3)
            else:
                handle_label_dict["81881"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "81886":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("管箱平盖", "法兰名义厚度") +

                            get_val("头盖法兰", "法兰总高") +
                            get_val("壳体封头", "椭圆形封头名义厚度") +
                            get_val("壳体封头", "椭圆形封头外曲面深度") +
                            get_val("壳体封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "77991":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break

            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter1 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '管程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter2 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter3 = float(row["Value"]) / 2 if row else 0.0
            cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程出口接管' 
                      AND Name = '开孔元件外径'
                """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter4 = float(row["Value"]) / 2 if row else 0.0

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n1_len = out_len_map.get("管程入口接管", "")
            n2_len = out_len_map.get("管程出口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            import pymysql
            middle_value = None
            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                            SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND 管口功能 IN ('管程入口', '管程出口','壳程出口','壳程入口')
                        """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                            SELECT 公称尺寸类型, 公称压力类型
                            FROM 产品设计活动表_管口类型选择表
                            WHERE 产品ID = %s
                        """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu5 = None  # 排液口
            gaodu6 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]

                        if func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                        elif func == "壳程入口":
                            gaodu5 = val
                        elif func == "壳程出口":
                            gaodu6 = val
                    break  # 找到一个匹配项就退出

            middle_value = str(float(n1_len) + float(cylinder_inner_diameter1) + float(gaodu3))

            handle_label_dict["831ce"] = f"{middle_value}±3"
            print(f"✅ 管口 N1 → 外伸高度 → handle 831ce = {n1_len}")

            middle_value2 = float(n2_len) + float(cylinder_inner_diameter2) + float(gaodu4)
            handle_label_dict["831cf"] = f"{middle_value2}±3"
            print(f"✅ 管口 N2 → 外伸高度 → handle 831cf = {n2_len}")
            middle_value3 = str(float(n3_len) + float(cylinder_inner_diameter3) + float(gaodu5))

            handle_label_dict["83086"] = f"{middle_value3}±3"
            print(f"✅ 管口 N3 → 外伸高度 → handle 83086 = {n3_len}")

            middle_value4 = float(n4_len) + float(cylinder_inner_diameter4) + float(gaodu6)
            handle_label_dict["83087"] = f"{middle_value4}±3"
            print(f"✅ 管口 N4 → 外伸高度 → handle 83087 = {n4_len}")



            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break

            # === 从数据库中查公称直径（注意：名称可能为“公称直径DN”或类似） ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            nominal_diameter = float(row["Value"]) if row else 0.0
            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0
            handle_label_dict["82fec"] = cylinder_nominal_thickness

            # === 计算最终高度：鞍式支座高度h + 公称直径/2
            handle_label_dict["8188F"] = round(float(support_height) + float(nominal_diameter) / 2 + float(cylinder_nominal_thickness), 3)
            print(f"✅ 8188F → {support_height} + {nominal_diameter / 2} = {handle_label_dict['8188F']}")
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            handle_label_dict["819E9"] = support_height
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81888"] = float(l1_val) - 10
            handle_label_dict["81592"] = float(l1_val) - 10
            handle_label_dict["81596"] = l1_val

            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["81593"] = fuban_val
            handle_label_dict["815C3"] = f"2-{fuban_val}"
            l9_val=None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["81881"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81882"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["81595"] = f"{l2_val}±2"
            handle_label_dict["81887"] = f"{l2_val}±2"
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["81883"] = b5_val
            handle_label_dict["81592"] = b5_val
            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["815C1"] = int(b1_val) / 2
            handle_label_dict["815C2"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["8158E"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["8158F"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["817F3"] = str(l3_val) + "±2"

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["81594"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "818BB": "管程入口接管",
                "81A03": "管程出口接管",
                "81905": "壳程入口接管",
                "819E5": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

                if gt_value:
                    handle_label_dict["8188B"] = f"∅{gt_value}"
                    print(f"✅ 管程公称直径 → handle 8188B = {gt_value}")
                if kt_value:
                    handle_label_dict["82feb"] = f"∅{kt_value}"
                    print(f"✅ 壳程公称直径 → handle 82feb = {kt_value}")

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["82b99"] = yuantong_thickness
            yuantong_thickness = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            handle_label_dict["82b9a"] = yuantong_thickness
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")

            conn, cursor = get_db_connection()
            tube_pass=None
            shell_pass=None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "BES" and fenchengxingshi == "2":

            twoDgeneration_BES_2(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""
            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"
                juli1 = 0
                juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度")+
                         get_val("管箱封头", "椭圆形封头直边高度") +
                         get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                         )
                handle_label_dict["815ca"] = juli1

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = None
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "BES" and fenchengxingshi == "4.1":

            twoDgeneration_BES_4_1(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = None
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "BES" and fenchengxingshi == "4.2":

            twoDgeneration_BES_4_2(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = None
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")

            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1

            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = ""
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = ""
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "BES" and fenchengxingshi == "4.3":

            twoDgeneration_BES_4_3(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                                        # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = ""
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值

            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = ""
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = ""
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "BES" and fenchengxingshi == "6.1":

            twoDgeneration_BES_6_1(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = None
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1

            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = ""
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "BES" and fenchengxingshi == "6.2":

            twoDgeneration_BES_6_2(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头名义厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("管箱法兰", "法兰总高") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = ""
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1

            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = ""
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "AES" and fenchengxingshi == "2":

            twoDgeneration_AES_2(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱平盖", "法兰名义厚度") +
                            get_val("管箱平盖", "垫片厚度") +
                            get_val("头盖法兰", "法兰总高") +

                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = ""
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1

            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = ""
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)


        if product_type == "AES" and fenchengxingshi == "4.1":

            twoDgeneration_AES_4_1(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱平盖", "法兰名义厚度") +
                            get_val("管箱平盖", "垫片厚度") +
                            get_val("头盖法兰", "法兰总高") +

                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = ""
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "AES" and fenchengxingshi == "4.2":

            twoDgeneration_AES_4_2(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',

                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱平盖", "法兰名义厚度") +
                            get_val("管箱平盖", "垫片厚度") +
                            get_val("头盖法兰", "法兰总高") +

                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                                        # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = None
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = ""
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "AES" and fenchengxingshi == "4.3":

            twoDgeneration_AES_4_3(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱平盖", "法兰名义厚度") +
                            get_val("管箱平盖", "垫片厚度") +
                            get_val("头盖法兰", "法兰总高") +

                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                                        # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = ""
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "AES" and fenchengxingshi == "6.1":

            twoDgeneration_AES_6_1(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱平盖", "法兰名义厚度") +
                            get_val("管箱平盖", "垫片厚度") +
                            get_val("头盖法兰", "法兰总高") +

                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                                        # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = None
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)

        if product_type == "AES" and fenchengxingshi == "6.2":

            twoDgeneration_AES_6_2(product_id)
            handle_label_dict = {
                "81815": '',
                '817F8': '7036',
                '81811': '6500',
                '7786A': '滑动鞍座至固定鞍座距离',
                '77854': '滑动鞍座至固定鞍座距离',
                "818BB": "管程入口接管",
                "81905": "管程出口接管",
                "819E5": "壳程入口接管",
                "81A03": "壳程出口接管",
                '81886': '7036',
                '77994': '6500',
                '81592': '滑动鞍座至固定鞍座距离',
                '81883': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '81889': '1000',
                '8188B': '1000',
                '779A3': '封头覆层厚度',
                '81881': '1，2号管口距离',
                '81890': '1000',
                '8188E': '1000',
                '81710': '',
                "819E9": "支座高度",
                "81700": "",
                "8161B": "1",
                "815DC": "",
                "815DD": "",
                '81619': '',
                '8161A': '',
                '779E6': '',
                '816E9': '',
                '816F0': '',
                '817F0': '',
                '815CE': '默认',
                '81711': '1000',
                '81756': '1000',
                '77988': '封头覆层厚度',
                '77989': '1，2号管口距离',
                '77997': '1000',
                '815DF': '1000',
                '815E5': '管口和底座差值',
                "816EC": '封头到管箱距离',
                "817F1": "支座高度",
                "816C3": '封头到管箱距离',
                "816ED": "管程连接厚度",
                "815E1": "支座高度",
                '815E6': '底座高度+500',
                '815E0': '管口和底座差值',
                '816FD': "",
                "815DA": ""

            }

            with open("jisuan_output_new.json", "r", encoding="utf-8") as f:
                json_data = json.load(f)

            dict_out = json_data.get("DictOutDatas", {})
            data_by_module = {
                module: datas["Datas"]
                for module, datas in dict_out.items()
                if datas.get("IsSuccess")
            }

            def get_val(module, name):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            def get_val_by_id_and_name(module, id_str, name_str):
                for entry in data_by_module.get(module, []):
                    if entry.get("Name") == name_str and entry.get("Id") == id_str:
                        try:
                            return float(entry.get("Value", 0))
                        except:
                            return 0
                return 0

            import pymysql

            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            cursor.execute("""
                            SELECT 管口所属元件, 轴向定位距离
                            FROM 产品设计活动表_管口表
                            WHERE 产品ID = %s AND `周向方位（°）` = 0
                            LIMIT 2
                        """, (product_id,))
            ports = cursor.fetchall()

            def parse_axis_position(raw, module):
                raw = str(raw).strip()
                if module == "管箱圆筒":
                    if raw == "默认":
                        return get_val("管箱圆筒", "圆筒长度")
                    elif raw == "居中":
                        return get_val("管箱圆筒", "圆筒长度") / 2
                elif module == "壳体圆筒":
                    if raw == "默认":
                        return 0
                    elif raw == "居中":
                        return get_val("壳体圆筒", "圆筒长度") / 2
                try:
                    return float(raw)
                except:
                    return 0

            tutai_height = "0"  # 默认值
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_元件附加参数表
                            WHERE 产品ID = %s AND 元件名称 = '固定管板' AND 参数名称 = '管板凸台高度'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                try:
                    val = str(row.get("参数值", "")).strip()
                    if val not in ("", "None"):
                        tutai_height = float(val)
                except (ValueError, TypeError):
                    tutai_height = 10  # 或保留默认值

            print(f"✅ 管板凸台高度 = {tutai_height}")

            if len(ports) == 2:
                print("ports:", ports)
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                print("固定管板厚度 =", get_val("固定管板", "管板名义厚度"))
                print("管箱法兰垫片厚度 =", get_val("管箱法兰", "垫片厚度"))
                print("壳体法兰垫片厚度 =", get_val("壳体法兰", "垫片厚度"))
                print("tutai_height =", tutai_height)

                extra = (get_val("固定管板", "管板名义厚度") -
                         2 * get_val("管箱法兰", "垫片厚度") -
                         2 * get_val("壳体法兰", "垫片厚度") -
                         2 * tutai_height +
                         get_val("管箱法兰", "法兰总高") +
                         get_val("壳体法兰", "法兰总高")
                         )
                handle_label_dict["815EA"] = str(round(base_distance, 3)) + "±6"

                # 读取圆筒内径
                cursor.execute("""
                    SELECT Value
                    FROM 产品设计活动表_元件计算结果表
                    WHERE 产品ID = %s 
                      AND 元件名称 = '壳程入口接管' 
                      AND Name = '接管中心线到圆筒边缘距离'
                """, (product_id,))
                row = cursor.fetchone()
                rukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳程出口接管' 
                              AND Name = '接管中心线到圆筒边缘距离'
                        """, (product_id,))
                row = cursor.fetchone()
                chukoujieguan_juli = float(row["Value"])
                cursor.execute("""
                            SELECT Value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s 
                              AND 元件名称 = '壳体圆筒' 
                              AND Name = '圆筒长度'
                        """, (product_id,))
                row = cursor.fetchone()
                yuantongchangdu = float(row["Value"])

                handle_label_dict["8161B"] = int(yuantongchangdu) - int(chukoujieguan_juli) - int(rukoujieguan_juli)


            else:
                handle_label_dict["8161B"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "815DA":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱平盖", "法兰名义厚度") +
                            get_val("管箱平盖", "垫片厚度") +
                            get_val("头盖法兰", "法兰总高") +

                            get_val("管箱法兰", "法兰总高") +
                            get_val("管箱法兰", "垫片厚度") +
                            get_val("固定管板", "管板名义厚度") +
                            get_val("壳体法兰", "垫片厚度") +
                            get_val("壳体法兰", "法兰总高") +
                            get_val("外头盖侧法兰", "法兰总高") +
                            get_val("外头盖法兰", "垫片厚度") +
                            get_val("外头盖法兰", "法兰总高") +
                            get_val("外头盖圆筒", "圆筒长度") +

                            get_val("外头盖封头", "椭圆形封头有效厚度") +
                            get_val("外头盖封头", "椭圆形封头外曲面深度") +
                            get_val("外头盖封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
                    # 刷新消息队列，防止 COM 超时
                    pythoncom.PumpWaitingMessages()

                    # 短暂延时，让 AutoCAD 处理内部消息
                    time.sleep(0.1)  # 50ms，可根据情况调整
                elif handle != "8161B":
                    found = False
                    for module_name, entries in data_by_module.items():
                        for entry in entries:
                            if entry.get("Name") == label:
                                handle_label_dict[handle] = entry.get("Value", "")
                                found = True
                                break
                        if found:
                            break
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )

            cursor = conn.cursor()

            # 读取圆筒内径
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒内径'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_inner_diameter = float(row["Value"]) / 2 if row else 0.0

            # 读取圆筒名义厚度
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '壳体圆筒' 
                  AND Name = '圆筒名义厚度'
            """, (product_id,))
            row = cursor.fetchone()
            cylinder_nominal_thickness = float(row["Value"]) if row else 0.0

            # 读取鞍式支座高度 h
            cursor.execute("""
                SELECT Value
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s 
                  AND 元件名称 = '鞍座' 
                  AND Name = '鞍式支座高度h'
            """, (product_id,))
            row = cursor.fetchone()
            saddle_height = float(row["Value"]) if row else 0.0

            # 三者求和
            total_value = cylinder_inner_diameter + cylinder_nominal_thickness + saddle_height

            # 填入 handle_label_dict
            handle_label_dict["81710"] = f"{total_value}_{{0}}^{{-5}}"
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管大端外径'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_len = out_len_map.get("管程出口接管", "")
            n1_len = out_len_map.get("管程入口接管", "")
            n3_len = out_len_map.get("壳程入口接管", "")
            n4_len = out_len_map.get("壳程出口接管", "")
            n5_len = out_len_map.get("排气口接管", "")
            n6_len = out_len_map.get("排液口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('管程入口接管', '管程出口接管','壳程入口接管', '壳程出口接管','排气口接管', '排液口接管') AND Name = '接管名义厚度'
                            """, (product_id,))
            rows = cursor.fetchall()
            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            n2_houdu = out_len_map.get("管程出口接管", "")
            n1_houdu = out_len_map.get("管程入口接管", "")
            n3_houdu = out_len_map.get("壳程入口接管", "")
            n4_houdu = out_len_map.get("壳程出口接管", "")
            n5_houdu = out_len_map.get("排气口接管", "")
            n6_houdu = out_len_map.get("排液口接管", "")
            handle_label_dict["815DC"] = f"∅{n1_len}x{n1_houdu}"
            handle_label_dict["815DD"] = f"∅{n2_len}x{n2_houdu}"
            handle_label_dict["81619"] = f"∅{n3_len}x{n3_houdu}"
            handle_label_dict["8161A"] = f"∅{n4_len}x{n4_houdu}"
            handle_label_dict["817EC"] = f"∅{n5_len}x{n5_houdu}"
            handle_label_dict["817ED"] = f"∅{n6_len}x{n6_houdu}"

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                            SELECT 元件名称, value
                            FROM 产品设计活动表_元件计算结果表
                            WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管') AND Name = '接管实际外伸长度'
                        """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("排气口接管", "")
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")
            kt_value = None
            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                kt_value = str(row.get("壳程数值", "")).strip()

            # === N4 → handle 779EA
            n4_len = out_len_map.get("排液口接管", "")
            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '开孔元件外径'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            waijing1 = out_len_map.get("排液口接管", "")
            waijing2 = out_len_map.get("排气口接管", "")
            waijing3 = out_len_map.get("管程入口接管", "")
            waijing4 = out_len_map.get("管程出口接管", "")
            cursor.execute("""
                                SELECT 元件名称, value
                                FROM 产品设计活动表_元件计算结果表
                                WHERE 产品ID = %s AND 元件名称 IN ('排气口接管', '排液口接管','管程入口接管', '管程出口接管') AND Name = '接管实际外伸长度'
                            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["元件名称"]: str(row.get("value", "")).strip()
                for row in rows if row.get("元件名称")
            }
            changdu1 = out_len_map.get("排液口接管", "")
            changdu2 = out_len_map.get("排气口接管", "")
            changdu3 = out_len_map.get("管程入口接管", "")
            changdu4 = out_len_map.get("管程出口接管", "")
            import pymysql

            # === 数据库连接 ===
            conn_product = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="产品设计活动库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_material = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="材料库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )
            conn_component = pymysql.connect(
                host="localhost", user="root", password="123456",
                database="元件库", charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor
            )

            cur = conn_product.cursor()
            cur2 = conn_material.cursor()
            cur3 = conn_component.cursor()

            # === 1. 获取管口表数据（排气口、排液口）===
            cur.execute("""
                SELECT 管口代号, 管口功能, 法兰标准, 公称尺寸, 压力等级, 法兰型式, 密封面型式
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口功能 IN ('排气口', '排液口','管程入口', '管程出口')
            """, (product_id,))
            ports = cur.fetchall()

            # === 2. 获取管口类型选择表 (尺寸/压力类型) ===
            cur.execute("""
                SELECT 公称尺寸类型, 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
            """, (product_id,))
            type_info = cur.fetchone()  # 一个产品只会有一行配置

            # 默认类型（防止为空）
            size_type = type_info["公称尺寸类型"] if type_info else "DN"
            press_type = type_info["公称压力类型"] if type_info else "PN"

            # === 3. 获取公称尺寸 NPS → DN 对照表 ===
            cur3.execute("SELECT NPS, DN FROM 公称尺寸表")
            nps_rows = cur3.fetchall()
            nps_map = {str(r["NPS"]).strip(): str(r["DN"]).strip() for r in nps_rows}

            # === 4. 获取管法兰质量表数据 ===
            cur2.execute("SELECT * FROM 管法兰质量表")
            flange_rows = cur2.fetchall()

            # === 5. 匹配逻辑 ===
            gaodu1 = None  # 排液口
            gaodu2 = None  # 排气口
            gaodu3 = None  # 排液口
            gaodu4 = None  # 排气口
            for port in ports:
                code = port["管口代号"]
                func = port["管口功能"]  # 排气口 or
                # 排液口
                std = port["法兰标准"]
                size = str(port["公称尺寸"]).strip()
                pressure = str(port["压力等级"]).strip()

                # --- 公称尺寸处理 ---
                if size_type.upper() == "NPS":
                    size = nps_map.get(size, size)  # NPS → DN

                # --- 遍历管法兰质量表匹配 ---
                for row in flange_rows:
                    # 标准匹配（包含关系）
                    if std and row["标准"] not in std:
                        continue
                    # 公称尺寸匹配（DN）
                    if str(row["DN"]).strip() != size:
                        continue
                    # 压力等级匹配
                    if press_type.upper() == "PN":
                        if str(row["PN"]).strip() != pressure:
                            continue
                    elif press_type.upper() == "CLASS":
                        if str(row["Class"]).strip() != pressure:
                            continue
                    # 法兰型式匹配
                    flange_type = port["法兰型式"]
                    if flange_type and str(row["法兰型式代号"]).strip() != str(flange_type).strip():
                        continue

                    # ✅ 只取 H+密封面型式 对应的值
                    face_type = port["密封面型式"]
                    face_col = f"H{face_type}" if face_type else None
                    if face_col and face_col in row:
                        val = row[face_col]
                        if func == "排液口":
                            gaodu1 = val
                        elif func == "排气口":
                            gaodu2 = val
                        elif func == "管程入口":
                            gaodu3 = val
                        elif func == "管程出口":
                            gaodu4 = val
                    break  # 找到一个匹配项就退出

            print("排液口对应值:", gaodu1)
            print("排气口对应值:", gaodu2)

            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")
            handle_label_dict["816E9"] = str(int(waijing1) / 2 + int(changdu1) + int(gaodu1)) + "±3"
            handle_label_dict["816F0"] = str(int(waijing2) / 2 + int(changdu2) + int(gaodu2)) + "±3"

            handle_label_dict["81711"] = str(int(waijing3) / 2 + int(changdu3) + int(gaodu3)) + "±3"
            handle_label_dict["81756"] = str(int(waijing4) / 2 + int(changdu4) + int(gaodu4)) + "±3"
            # === 从 JSON 中读取鞍式支座高度h ===
            support_height = 0
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "鞍式支座高度h":
                    try:
                        support_height = float(entry.get("Value", 0))
                    except:
                        support_height = 0
                    break
            l1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板长度":
                    l1_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["817F4"] = l1_val
            handle_label_dict["81700"] = l1_val
            l9_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "G":
                    l9_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["8161b"] = l9_val
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l2_val = entry.get("Value", "")
                    break
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l6_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "H":
                    l6_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["815CD"] = l6_val
            # === 更新两个 handle 对应的值
            handle_label_dict["816FD"] = l2_val

            print(f"✅ 间距l2 → handle 817F0, 815CE = {l2_val}")
            juli1 = 0
            juli1 = (get_val("管箱封头", "椭圆形封头外曲面深度") +
                     get_val("管箱封头", "椭圆形封头直边高度") +
                     get_val("管箱入口接管", "接管中心线到圆筒边缘距离")
                     )
            handle_label_dict["815ca"] = juli1
            # === 更新两个 handle 对应的值
            b5_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "D":
                    b5_val = entry.get("Value", "")
                    break
            handle_label_dict["815ce"] = b5_val
            handle_label_dict["817f0"] = b5_val
            b1_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板宽度":
                    b1_val = entry.get("Value", "")
                    break
            handle_label_dict["81813"] = int(b1_val) / 2
            print("81813", int(b1_val) / 2)
            handle_label_dict["81814"] = int(b1_val) / 2
            # === 更新两个 handle 对应的值
            handle_label_dict["817EC"] = int(b1_val)
            print(int(b1_val))
            handle_label_dict["817ED"] = int(b1_val)
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓孔间距1":
                    l3_val = entry.get("Value", "")
                    break
            luoshuan_shuliang = None
            luoshuan_zhijing = None
            handle_label_dict["817F3"] = str(l3_val) + "±2"
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺栓数量":
                    luoshuan_shuliang = entry.get("Value", "")
                if entry.get("Name") == "螺孔直径":
                    luoshuan_zhijing = entry.get("Value", "")
            print("螺栓数量", luoshuan_shuliang)
            handle_label_dict["81815"] = f"{luoshuan_shuliang}-∅{luoshuan_zhijing}"
            s1 = None
            # 底板厚度
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    s1 = entry.get("Value", "")
            print("s1", s1)
            print("Before:", handle_label_dict.get("817F8"))
            handle_label_dict["817F8"] = s1
            print("After:", handle_label_dict.get("817F8"))
            handle_label_dict["81811"] = s1

            print(f"✅ l3 → handle 77992 = {l3_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔长度":
                    b1_val = entry.get("Value", "")
                    break
            # === 更新两个 handle 对应的值
            handle_label_dict["817F2"] = b1_val
            print("b1_val", b1_val)

            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "筋板长度":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = None
            for entry in data_by_module.get("管程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    gp_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("管箱法兰", []):
                if entry.get("Name") == "法兰总高":
                    gp_exit_val1 = entry.get("Value", "")
                    break
            handle_label_dict["77C75"] = float(gp_exit_val) + float(gp_exit_val1)
            print(f"✅ 管程出口接管 → 接管定位距 → handle 77C75 = {gp_exit_val}")

            # === 77990: 壳程出口接管 → 接管定位距
            shell_exit_val = None
            for entry in data_by_module.get("壳程出口接管", []):
                if entry.get("Name") == "接管定位距":
                    shell_exit_val = entry.get("Value", "")
                    break
            for entry in data_by_module.get("壳体法兰", []):
                if entry.get("Name") == "法兰总高":
                    shell_exit_val2 = entry.get("Value", "")
                    break
            handle_label_dict["77990"] = float(shell_exit_val) + float(shell_exit_val2)
            print(f"✅ 壳程出口接管 → 接管定位距 → handle 77990 = {shell_exit_val}")
            # === 定义新的映射关系：handle → 模块名
            handle_to_module = {
                "77988": "管程入口接管",
                "779A4": "管程出口接管",
                "77989": "壳程入口接管",
                "77997": "壳程出口接管"
            }

            # === 构造值并写入 handle_label_dict
            for handle, module in handle_to_module.items():
                entries = data_by_module.get(module, [])

                def get_entry_val(param_name):
                    for entry in entries:
                        if entry.get("Name") == param_name:
                            return entry.get("Value")
                    return None

                od = get_entry_val("接管大端外径")
                thick = get_entry_val("接管大端壁厚")
                l1 = get_entry_val("接管实际外伸长度") or 0
                l2 = get_entry_val("接管实际内伸长度") or 0

                try:
                    if None not in (od, thick):
                        od = float(od)
                        thick = float(thick)
                        l1 = float(l1)
                        l2 = float(l2)
                        value = f"∅{od}×{thick};L={l1 + l2}"
                    else:
                        value = None
                except Exception as e:
                    print(f"❌ 处理 {module} 时出错: {e}")
                    value = ""

                handle_label_dict[handle] = value
                print(f"✅ {module} → handle {handle} = {value}")

            # === 连接数据库，查找管程和壳程公称直径 ===
            conn = pymysql.connect(
                host="localhost",
                user="root",
                password="123456",
                database="产品设计活动库",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()
            # 读取圆筒名义厚度
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '外头盖圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '管箱圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing2 = float(row["Value"]) if row else 0.0
            cursor.execute("""
                   SELECT Value
                   FROM 产品设计活动表_元件计算结果表
                   WHERE 产品ID = %s 
                     AND 元件名称 = '壳体圆筒' 
                     AND Name = '圆筒内径'
               """, (product_id,))
            row = cursor.fetchone()
            yuantong_neijing3 = float(row["Value"]) if row else 0.0

            handle_label_dict["815DF"] = f"∅{yuantong_neijing2}"
            handle_label_dict["815E5"] = f"∅{yuantong_neijing3}"
            handle_label_dict["816EC"] = f"∅{yuantong_neijing}"

            # === 查询管程和壳程公称直径 ===
            cursor.execute("""
                            SELECT 参数名称, 管程数值, 壳程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID = %s AND 参数名称 LIKE '公称直径%%'
                        """, (product_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            # === 提取参数值并写入 handle_label_dict ===
            for row in rows:
                name = row.get("参数名称", "")
                gt_value = str(row.get("管程数值", "")).strip()
                kt_value = str(row.get("壳程数值", "")).strip()

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = None
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "底板厚度":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "螺孔直径":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["817F1"] = fuban_val
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = None
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("浮头法兰", []):
                if entry.get("Name") == "球冠形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            # min_thickness = None
            # for entry in data_by_module.get("浮头法兰", []):
            #     if entry.get("Name") == "腐蚀前壳程球冠形封头有效厚度":
            #         min_thickness = entry.get("Value", "")
            #         break
            handle_label_dict["816C3"] = nominal_thickness
            print(f"✅ 球冠形封头 → handle 816C3 = {nominal_thickness}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("外头盖封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["816ED"] = nominal_thickness
            handle_label_dict["815E1"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E1 = {nominal_thickness}")
            nominal_thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break
            yuantong_thickness = None
            for entry in data_by_module.get("壳体圆筒", []):
                if entry.get("Name") == "圆筒名义厚度":
                    yuantong_thickness = entry.get("Value", "")
                    break
            thickness = None
            for entry in data_by_module.get("管箱封头", []):
                if entry.get("Name") == "椭圆形封头最小成型厚度":
                    thickness = entry.get("Value", "")
                    break
            handle_label_dict["815E6"] = yuantong_thickness
            handle_label_dict["815E0"] = f"{nominal_thickness}(min{thickness})"
            print(f"✅ 外头盖封头 → handle 815E0 = {nominal_thickness}")
            conn, cursor = get_db_connection()
            tube_pass = None
            shell_pass = None
            cursor.execute("""
                            SELECT 参数值
                            FROM 产品设计活动表_布管参数表
                            WHERE 产品ID = %s AND 参数名 = '管程程数'
                            LIMIT 1
                        """, (product_id,))
            row = cursor.fetchone()
            if row:
                tube_pass = str(row["参数值"]).strip()
            cursor.execute("""
                                        SELECT 参数值
                                        FROM 产品设计活动表_布管参数表
                                        WHERE 产品ID = %s AND 参数名 = '壳程程数'
                                        LIMIT 1
                                    """, (product_id,))
            row = cursor.fetchone()
            if row:
                shell_pass = str(row["参数值"]).strip()
            handle_label_dict["7786A"] = tube_pass
            handle_label_dict["77854"] = shell_pass
            apply_dimension_labels(handle_label_dict)
        generate_and_save_flange(product_id, flange_info)
        self.generate_button.setComplete()
