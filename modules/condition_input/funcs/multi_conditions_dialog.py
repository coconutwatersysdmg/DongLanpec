# modules/condition_input/funcs/multi_conditions_dialog.py
import os
from PyQt5.QtCore import Qt
from PyQt5 import uic
from PyQt5.QtWidgets import QDialog, QMessageBox, QTableWidgetItem
from modules.condition_input.funcs.ctrl_helper import enable_full_undo
from PyQt5.QtWidgets import QSizePolicy, QHeaderView

# PARAM_UNITS = ["MPa", "℃", "MPa", "℃", "℃", "MPa"]  # 按参数名称顺序给单位

db_config_1 = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '产品设计活动库'
}
class MultiConditionsDialog(QDialog):
    PARAM_NAMES = [
        "设计压力*",
        "设计温度（最高）*",
        "工作压力",
        "工作温度（入口）",
        "工作温度（出口）",
        "最高允许工作压力"
    ]

# 已改
    def fill_table(self, gongkuang_no):
        data_map = self._data_cache.get(gongkuang_no, {})
        for r, pname in enumerate(self.PARAM_NAMES):
            kc_val, gc_val = data_map.get(pname, ("", ""))
            kc_item = QTableWidgetItem(str(kc_val))
            kc_item.setTextAlignment(Qt.AlignCenter)  # 设置居zhong
            self.tableWidget.setItem(r, 1, kc_item)

            gc_item = QTableWidgetItem(str(gc_val))
            gc_item.setTextAlignment(Qt.AlignCenter)  # 设置居中
            self.tableWidget.setItem(r, 2, gc_item)

            # self.tableWidget.setItem(r, 2, QTableWidgetItem(self.PARAM_UNITS[r]))
            # 获取参数单位列（0列）的单元格
            unit_item = self.tableWidget.item(r, 0)
            if unit_item:
                # 移除可编辑标志，保留其他默认标志（如选中、启用等）
                unit_item.setFlags(unit_item.flags() & ~Qt.ItemIsEditable)

    def __init__(self, parent=None, product_id=None):
        super().__init__(parent)
        self.product_id = product_id
        self.current_gongkuang = 1
        self._data_cache = {}

        # 加载 UI
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(os.path.dirname(base_dir), "mutigongkuang.ui")
        if not os.path.exists(ui_path):
            ui_path = os.path.join(base_dir, "mutigongkuang.ui")
        uic.loadUi(ui_path, self)

        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowMinMaxButtonsHint)

        # 初始化工况下拉
        if not hasattr(self, "combo_gongkuang"):
            raise AttributeError("UI 中找不到 combo_gongkuang 下拉框，请检查对象名")
        self.combo_gongkuang.clear()
        for i in range(1, 4):  # 工况1~3
            self.combo_gongkuang.addItem(f"工况{i}", i)

        # 初始化表格
        self.tableWidget.setRowCount(len(self.PARAM_NAMES))
        self.tableWidget.setColumnCount(3)
        self.tableWidget.setHorizontalHeaderLabels(["参数单位","壳程数值", "管程数值"])
        for r, name in enumerate(self.PARAM_NAMES):
            self.tableWidget.setVerticalHeaderItem(r, QTableWidgetItem(name))

        # ✅ 安装 undo + 校核代理
        parent_viewer = self.parent()
        if parent_viewer:
            try:
                enable_full_undo(self.tableWidget, parent_viewer, mode="design")
            except Exception as e:
                print(f"[多工况] 安装校核代理异常: {e}")

        # 绑定事件
        self.combo_gongkuang.currentIndexChanged.connect(self.on_gongkuang_changed)
        if hasattr(self, "btnok"):
            self.btnok.clicked.connect(self.save_current_gongkuang)
        else:
            print("[多工况] 警告：UI 中找不到 btnok 按钮")

        # 默认加载工况1数据
        self.load_gongkuang_data(1)
        self.fill_table(1)

        # ✅ 根据表格内容动态设置初始大小（高度正好能显示所有行）
        vh = self.tableWidget.verticalHeader()
        total_height = vh.length()  # 所有行高度之和
        header_height = self.tableWidget.horizontalHeader().height()
        frame = self.tableWidget.frameWidth() * 2
        margin = 100  # 预留额外空间给下拉框、按钮

        total_height = total_height + header_height + frame + margin

        # 表格宽度
        total_width = sum(self.tableWidget.columnWidth(c) for c in range(self.tableWidget.columnCount()))
        total_width += self.tableWidget.verticalHeader().width() + frame + 50  # 适当留点余量

        self.resize(total_width, total_height)

        # ✅ 允许用户继续拖动缩放
        self.setSizeGripEnabled(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ✅ 表格自适应窗口
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tableWidget.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tableWidget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


    def _make_param_field(self, param_name, gongkuang_no):
        if gongkuang_no == 1:
            return param_name
        else:
            return f"{param_name}[工况{gongkuang_no}]"

    def load_gongkuang_data(self, gongkuang_no):
        if gongkuang_no in self._data_cache:
            print(f"[多工况] 工况 {gongkuang_no} 已缓存，跳过加载")
            return

        data_map = {}
        if gongkuang_no == 1:
            # ✅ 工况1：直接从主界面表格抓取
            parent = self.parent()
            if parent and hasattr(parent, "tableWidget_design_data"):
                table = parent.tableWidget_design_data
                for pname in self.PARAM_NAMES:
                    val_kc, val_gc = "", ""
                    for row in range(table.rowCount()):
                        name_item = table.item(row, 1)  # 第1列: 参数名称
                        if name_item and name_item.text().strip() == pname:
                            kc_item = table.item(row, 3)  # 第2列: 壳程数值
                            gc_item = table.item(row, 4)  # 第3列: 管程数值
                            val_kc = kc_item.text() if kc_item else ""
                            val_gc = gc_item.text() if gc_item else ""
                            break
                    data_map[pname] = (val_kc, val_gc)
        else:
            # ✅ 工况2/3…：从数据库读取
            try:
                from modules.condition_input.funcs.funcs_cdt_input import get_connection
                conn = get_connection(**db_config_1)
                with conn.cursor() as cur:
                    for pname in self.PARAM_NAMES:
                        db_field = self._make_param_field(pname, gongkuang_no)
                        sql = """
                            SELECT 壳程数值, 管程数值
                            FROM 产品设计活动表_设计数据表
                            WHERE 产品ID=%s AND 参数名称=%s
                        """
                        cur.execute(sql, (self.product_id, db_field))
                        row = cur.fetchone()
                        if row:
                            data_map[pname] = (row.get("壳程数值") or "", row.get("管程数值") or "")
                        else:
                            data_map[pname] = ("", "")
                conn.close()
            except Exception as e:
                print(f"[多工况] 数据库读取异常: {e}")
                for pname in self.PARAM_NAMES:
                    data_map.setdefault(pname, ("", ""))

        # 缓存
        self._data_cache[gongkuang_no] = data_map

    # def fill_table(self, gongkuang_no):
    #     data_map = self._data_cache.get(gongkuang_no, {})
    #     for r, pname in enumerate(self.PARAM_NAMES):
    #         kc_val, gc_val = data_map.get(pname, ("", ""))
    #         # self.tableWidget.setItem(r, 0, QTableWidgetItem(PARAM_UNITS[r]))
    #         self.tableWidget.setItem(r, 1, QTableWidgetItem(str(kc_val)))
    #         self.tableWidget.setItem(r, 2, QTableWidgetItem(str(gc_val)))


    def save_current_gongkuang(self):
        gongkuang_no = self.current_gongkuang
        self._save_to_cache(gongkuang_no)
        if gongkuang_no == 1:
            # ✅ 工况1：只回填界面，不写数据库
            parent = self.parent()
            if parent and hasattr(parent, "tableWidget_design_data"):
                table = parent.tableWidget_design_data
                for pname in self.PARAM_NAMES:
                    kc_val, gc_val = self._data_cache[gongkuang_no][pname]
                    # 找到界面上对应行
                    for row in range(table.rowCount()):
                        name_item = table.item(row, 1)
                        if name_item and name_item.text().strip() == pname:
                            # ✅ 居中显示
                            item_kc = QTableWidgetItem(kc_val)
                            item_kc.setTextAlignment(Qt.AlignCenter)
                            table.setItem(row, 3, item_kc)

                            item_gc = QTableWidgetItem(gc_val)
                            item_gc.setTextAlignment(Qt.AlignCenter)
                            table.setItem(row, 4, item_gc)
            QMessageBox.information(self, "保存成功", f"工况{gongkuang_no} 已保存")
            return

        # ✅ 工况2/3 及以后：写数据库
        try:
            from modules.condition_input.funcs.funcs_cdt_input import get_connection
            conn = get_connection(**db_config_1)
            with conn.cursor() as cur:
                # 获取当前最大序号
                cur.execute("""
                    SELECT MAX(设计数据参数ID) AS max_sn
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID=%s
                """, (self.product_id,))
                row = cur.fetchone()
                max_sn = row["max_sn"] or 31
                for pname in self.PARAM_NAMES:
                    kc_val, gc_val = self._data_cache[gongkuang_no][pname]
                    db_field = self._make_param_field(pname, gongkuang_no)

                    # 查询是否已存在
                    cur.execute("""
                        SELECT 设计数据参数ID FROM 产品设计活动表_设计数据表
                        WHERE 产品ID=%s AND 参数名称=%s
                    """, (self.product_id, db_field))
                    row = cur.fetchone()
                    exists = row is not None

                    if exists:
                        # 已存在 → 更新
                        cur.execute("""
                            UPDATE 产品设计活动表_设计数据表
                            SET 壳程数值=%s, 管程数值=%s
                            WHERE 产品ID=%s AND 参数名称=%s
                        """, (kc_val, gc_val, self.product_id, db_field))
                    else:
                        # 不存在 → 插入，每个参数单独递增序号
                        max_sn += 1
                        cur.execute("""
                            INSERT INTO 产品设计活动表_设计数据表
                                (设计数据参数ID, 产品ID, 参数名称, 壳程数值, 管程数值)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (max_sn, self.product_id, db_field, kc_val, gc_val))

            conn.commit()
            conn.close()
            # ❌ 不再 self.accept()，保持窗口打开
            QMessageBox.information(self, "保存成功", f"工况{gongkuang_no} 已保存")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存工况{gongkuang_no} 数据失败：{e}")

    def _auto_save_current_gongkuang(self, gongkuang_no):
        """静默保存当前工况（无弹窗）"""
        self._save_to_cache(gongkuang_no)

        if gongkuang_no == 1:
            # 工况1：回填界面，不写数据库
            parent = self.parent()
            if parent and hasattr(parent, "tableWidget_design_data"):
                table = parent.tableWidget_design_data
                for pname in self.PARAM_NAMES:
                    kc_val, gc_val = self._data_cache[gongkuang_no][pname]
                    for row in range(table.rowCount()):
                        name_item = table.item(row, 1)
                        if name_item and name_item.text().strip() == pname:
                            item_kc = QTableWidgetItem(kc_val)
                            item_kc.setTextAlignment(Qt.AlignCenter)
                            table.setItem(row, 3, item_kc)

                            item_gc = QTableWidgetItem(gc_val)
                            item_gc.setTextAlignment(Qt.AlignCenter)
                            table.setItem(row, 4, item_gc)
            return

        # 工况2/3：写数据库
        try:
            from modules.condition_input.funcs.funcs_cdt_input import get_connection
            conn = get_connection(**db_config_1)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT MAX(设计数据参数ID) AS max_sn
                    FROM 产品设计活动表_设计数据表
                    WHERE 产品ID=%s
                """, (self.product_id,))
                row = cur.fetchone()
                max_sn = row["max_sn"] or 31
                for pname in self.PARAM_NAMES:
                    kc_val, gc_val = self._data_cache[gongkuang_no][pname]
                    db_field = self._make_param_field(pname, gongkuang_no)

                    cur.execute("""
                        SELECT 设计数据参数ID FROM 产品设计活动表_设计数据表
                        WHERE 产品ID=%s AND 参数名称=%s
                    """, (self.product_id, db_field))
                    exists = cur.fetchone() is not None

                    if exists:
                        cur.execute("""
                            UPDATE 产品设计活动表_设计数据表
                            SET 壳程数值=%s, 管程数值=%s
                            WHERE 产品ID=%s AND 参数名称=%s
                        """, (kc_val, gc_val, self.product_id, db_field))
                    else:
                        max_sn += 1
                        cur.execute("""
                            INSERT INTO 产品设计活动表_设计数据表
                                (设计数据参数ID, 产品ID, 参数名称, 壳程数值, 管程数值)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (max_sn, self.product_id, db_field, kc_val, gc_val))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[多工况][AutoSave] 工况{gongkuang_no} 自动保存失败: {e}")

    def on_gongkuang_changed(self, idx):
        text = self.combo_gongkuang.currentText().strip()

        if not text.startswith("工况"):
            print("[多工况] 工况文本格式不正确，跳过")
            return

        try:
            gongkuang_no = int(text.replace("工况", ""))
        except ValueError:
            print("[多工况] 无法解析工况号")
            return


        # 保存当前工况数据到缓存
        self._auto_save_current_gongkuang(self.current_gongkuang)

        # 加载新工况数据
        self.load_gongkuang_data(gongkuang_no)

        # 填充表格
        self.fill_table(gongkuang_no)

        self.current_gongkuang = gongkuang_no

# 已改
    def _save_to_cache(self, gongkuang_no):
        data_map = {}
        for r, pname in enumerate(self.PARAM_NAMES):
            kc_item = self.tableWidget.item(r, 1)
            gc_item = self.tableWidget.item(r, 2)

            kc_val = kc_item.text().strip() if kc_item else ""
            gc_val = gc_item.text().strip() if gc_item else ""
            data_map[pname] = (kc_val, gc_val)
            kc_item.setTextAlignment(Qt.AlignCenter)
            gc_item.setTextAlignment(Qt.AlignCenter)
        self._data_cache[gongkuang_no] = data_map
