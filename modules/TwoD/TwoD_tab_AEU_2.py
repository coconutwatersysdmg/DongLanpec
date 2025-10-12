import json

from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QPushButton, QLabel,
                             QMessageBox, QHBoxLayout, QSpacerItem, QSizePolicy)
from PyQt5.QtCore import Qt, QPropertyAnimation, QPoint, QEasingCurve
from PyQt5.QtGui import (QPalette, QColor, QPainter, QBrush,
                         QPainterPath, QLinearGradient, QFont, QPen)

from modules.TwoD.toubiaotu_biaozhu_AEU import extract_dimensions
from modules.chanpinguanli.chanpinguanli_main import product_manager

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
        import pymysql

        from modules.TwoD.toubiaotu_wenziduixiang import twoDgeneration
        from modules.TwoD.toubiaotu_biaozhu import apply_dimension_labels
        try:
            twoDgeneration()
            # extract_dimensions()
            handle_label_dict = {
                '77988': '100',
                '779A4': '100',
                '77989': '100',
                '77997': '100',
                '77996': '7036',
                '77994': '6500',
                '77993': '滑动鞍座至固定鞍座距离',
                '77C15': '滑动鞍座至固定鞍座距离',
                '77992': '固定鞍座至壳程圆筒左端距离+8',
                '77990': '默认',
                '77C75': '默认',
                '77983': '1000',
                '7799D': '1000',
                '779A3': '封头覆层厚度',
                '77991': '1，2号管口距离',
                '779E6': '1000',
                '779EA': '1000',
                '779E9': '底座高度+500',
                '779ED': '管口和底座差值',
                "77995": '封头到管箱距离',
                "77C78":"管程连接厚度"
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
                d1 = parse_axis_position(ports[0]["轴向定位距离"], ports[0]["管口所属元件"])
                d2 = parse_axis_position(ports[1]["轴向定位距离"], ports[1]["管口所属元件"])
                base_distance = abs(d1 - d2)
                extra =  (get_val_by_id_and_name("固定管板", "工况1：TSH14", "管板名义厚度")-
                          2*get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket", "垫片厚度") -
                        2*get_val_by_id_and_name("壳体法兰", "m_ThicknessGasket", "垫片厚度")-
                          2*tutai_height+
                        get_val_by_id_and_name("管箱法兰", "工况1：FL155", "法兰总高")+
                        get_val_by_id_and_name("壳体法兰", "工况1：FL155", "法兰总高")
                )
                handle_label_dict["77991"] = round(base_distance + extra, 3)
            else:
                handle_label_dict["77991"] = "[未找到2个管口]"

            for handle, label in handle_label_dict.items():
                if handle == "77996":
                    total_length = (
                            get_val("壳体圆筒", "圆筒长度") +
                            get_val("管箱圆筒", "圆筒长度") +
                            get_val("管箱封头", "椭圆形封头有效厚度") +
                            get_val("管箱封头", "椭圆形封头外曲面深度") +
                            get_val("管箱圆筒", "与圆筒连接的椭圆形封头直边段长度") +
                            get_val_by_id_and_name("管箱法兰", "m_Se", "法兰有效厚度") +
                            get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket2", "垫片厚度") +
                            get_val_by_id_and_name("固定管板", "工况1：TSH30", "设计厚度") +
                            get_val_by_id_and_name("管箱法兰", "m_ThicknessGasket", "垫片厚度") +
                            get_val_by_id_and_name("管箱法兰", "m_Se2", "法兰有效厚度") +
                            get_val("壳体封头", "椭圆形封头有效厚度") +
                            get_val("壳体封头", "椭圆形封头外曲面深度") +
                            get_val("壳体封头", "椭圆形封头直边高度")
                    )
                    handle_label_dict[handle] = round(total_length, 3)
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

            # === 查询数据库：N2 和 N4 的 外伸高度
            cursor.execute("""
                SELECT 管口代号, 外伸高度
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s AND 管口代号 IN ('N2', 'N4')
            """, (product_id,))
            rows = cursor.fetchall()

            # 构建管口代号 → 外伸高度 映射
            out_len_map = {
                row["管口代号"]: str(row.get("外伸高度", "")).strip()
                for row in rows if row.get("管口代号")
            }

            # === N2 → handle 779E6
            n2_len = out_len_map.get("N2", "")
            if n2_len == "默认":
                n2_len = "600"
            handle_label_dict["779E6"] = n2_len
            print(f"✅ 管口 N2 → 外伸高度 → handle 779E6 = {n2_len}")

            # === N4 → handle 779EA
            n4_len = out_len_map.get("N4", "")
            if n4_len == "默认":
                n4_len = "600"
            handle_label_dict["779EA"] = n4_len
            print(f"✅ 管口 N4 → 外伸高度 → handle 779EA = {n4_len}")

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
                SELECT 管程数值 
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s AND 参数名称 = '公称直径*'
                LIMIT 1
            """, (product_id,))
            row = cursor.fetchone()

            conn.close()

            nominal_diameter = 0
            if row and row.get("管程数值"):
                try:
                    nominal_diameter = float(row["管程数值"])
                except:
                    nominal_diameter = 0

            # === 计算最终高度：鞍式支座高度h + 公称直径/2
            handle_label_dict["779E9"] = round(support_height + nominal_diameter / 2, 3)
            print(f"✅ 779E9 → {support_height} + {nominal_diameter / 2} = {handle_label_dict['779E9']}")
            # === 从 JSON 中提取 鞍座 → 间距l2 的值 ===
            l2_val = ""
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "间距l2":
                    l2_val = entry.get("Value", "")
                    break

            # === 更新两个 handle 对应的值
            handle_label_dict["77993"] = l2_val  + "±3"
            handle_label_dict["77C15"] = l2_val + "±3"
            print(f"✅ 间距l2 → handle 77993, 77C15 = {l2_val}")
            # === 从 JSON 中提取 鞍座 → l3 的值 ===
            l3_val = ""
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "l3":
                    l3_val = entry.get("Value", "")
                    break

            handle_label_dict["77992"] = l3_val
            print(f"✅ l3 → handle 77992 = {l3_val}")
            # === 77C75: 管程出口接管 → 接管定位距
            gp_exit_val = ""
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
            shell_exit_val = ""
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
                    handle_label_dict["77983"] = gt_value
                    print(f"✅ 管程公称直径 → handle 77983 = {gt_value}")
                if kt_value:
                    handle_label_dict["7799D"] = kt_value
                    print(f"✅ 壳程公称直径 → handle 7799D = {kt_value}")

            # === 从 JSON 中提取 鞍座 → 腹板 的值 ===
            fuban_val = ""
            for entry in data_by_module.get("鞍座", []):
                if entry.get("Name") == "s1":
                    fuban_val = entry.get("Value", "")
                    break

            handle_label_dict["779ED"] = fuban_val
            print(f"✅ 鞍座 → 腹板 → handle 779ED = {fuban_val}")
            # === 从 JSON 中提取 管箱圆筒 → 圆筒长度 的值
            guanxiang_length = ""
            for entry in data_by_module.get("管箱圆筒", []):
                if entry.get("Name") == "圆筒长度":
                    guanxiang_length = entry.get("Value", "")
                    break

            handle_label_dict["77995"] = guanxiang_length
            print(f"✅ 管箱圆筒 → 圆筒长度 → handle 77995 = {guanxiang_length}")
            # === 从 JSON 中提取 固定管板 → 管板名义厚度 的值
            nominal_thickness = ""
            for entry in data_by_module.get("固定管板", []):
                if entry.get("Name") == "管板名义厚度":
                    nominal_thickness = entry.get("Value", "")
                    break

            handle_label_dict["77C78"] = nominal_thickness
            print(f"✅ 固定管板 → 管板名义厚度 → handle 77C78 = {nominal_thickness}")

            apply_dimension_labels(handle_label_dict)
            self.generate_button.setComplete()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成过程中发生错误: {e}")
