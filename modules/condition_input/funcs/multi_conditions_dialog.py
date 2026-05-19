# modules/condition_input/funcs/multi_conditions_dialog.py
import os
from PyQt5.QtCore import Qt, QEvent
from PyQt5 import uic
from PyQt5.QtWidgets import (
    QDialog,
    QMessageBox,
    QTableWidgetItem,
    QAbstractItemView,
    QPushButton,
    QToolButton,
    QSizePolicy,
    QHeaderView,
)
from modules.condition_input.funcs.ctrl_helper import enable_full_undo

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
    # 不再硬编码固定起点；改为按产品动态计算起点（见 _compute_multi_id_base）

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
        # 动态ID基准：避免与常规设计参数ID冲突，也避免影响已有高位工况ID
        self._multi_id_base = None
        self._multi_id_safe_threshold = 0
        self._multi_id_legacy_high = False

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
        # 禁用鼠标滚轮切换工况
        self.combo_gongkuang.installEventFilter(self)

        # 初始化表格
        self.tableWidget.setRowCount(len(self.PARAM_NAMES))
        self.tableWidget.setColumnCount(3)
        self.tableWidget.setHorizontalHeaderLabels(["参数单位","壳程数值", "管程数值"])

        # 1107新修改
        self.tableWidget.horizontalHeader().setStyleSheet("""
            QHeaderView::section {
                border-top: 0px;
                border-left: 0px;
                border-right: 1px solid #D3D3D3;
                border-bottom: 1px solid #D3D3D3;
                background-color: white;
            }
        """)

        for r, name in enumerate(self.PARAM_NAMES):
            self.tableWidget.setVerticalHeaderItem(r, QTableWidgetItem(name))

        # ✅ 安装 undo + 校核代理（本地文件未恢复只读时不安装，避免代理下拉仍可编辑）
        parent_viewer = self.parent()
        try:
            import modules.chanpinguanli.bianl as bianl
            self._readonly_local_files = bool(
                getattr(bianl, "product_local_files_missing_readonly", False)
            )
        except Exception:
            self._readonly_local_files = False

        if parent_viewer and not self._readonly_local_files:
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

        if self._readonly_local_files:
            self._apply_readonly_for_missing_local_files()

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

    def _apply_table_readonly_only(self):
        """仅锁定表格与单元格内嵌控件（切换工况重新 fill 后需再调用）。"""
        self.tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r in range(self.tableWidget.rowCount()):
            for c in range(self.tableWidget.columnCount()):
                it = self.tableWidget.item(r, c)
                if it:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                cw = self.tableWidget.cellWidget(r, c)
                if cw is not None:
                    cw.setEnabled(False)

    def _apply_readonly_for_missing_local_files(self):
        """产品本地文件夹未恢复时：禁止编辑表格与保存按钮；工况下拉可切换以浏览各工况数据。"""
        try:
            self._apply_table_readonly_only()
            for btn in self.findChildren(QPushButton):
                btn.setEnabled(False)
            for btn in self.findChildren(QToolButton):
                btn.setEnabled(False)
        except Exception as e:
            print(f"[多工况] 只读应用失败: {e}")

    def _make_param_field(self, param_name, gongkuang_no):
        if gongkuang_no == 1:
            return param_name
        else:
            return f"{param_name}[工况{gongkuang_no}]"

    def _get_param_unit_for_multi(self, row_index, param_name):
        """优先使用多工况弹窗表格第0列单位，缺失时回退主界面设计数据表单位。"""
        try:
            unit_item = self.tableWidget.item(row_index, 0)
            if unit_item and unit_item.text() and unit_item.text().strip():
                return unit_item.text().strip()
        except Exception:
            pass

        # 回退：从主界面设计数据表读取单位
        parent = self.parent()
        if not parent or not hasattr(parent, "tableWidget_design_data"):
            return ""
        table = parent.tableWidget_design_data
        for row in range(table.rowCount()):
            name_item = table.item(row, 1)
            if name_item and name_item.text().strip() == param_name:
                unit_item = table.item(row, 2)
                return unit_item.text().strip() if unit_item and unit_item.text() else ""
        return ""

    def _compute_multi_id_base(self):
        """
        计算多工况参数ID的动态起点（不硬编码900000）：
        - normal_max：当前产品常规参数（不含[工况]）最大ID
        - template_max：模板表（按产品型式过滤）最大ID
        - multi_max：当前产品已有多工况参数最大ID（若历史已写入高位，则沿用高位区间，避免回迁）
        “整齐化”策略：
        - 对新产品/低位多工况：固定以 safe_threshold 作为基准（即 max(normal_max, template_max)），
          从而保证工况2/3的ID区间稳定、连续，不会因导入了部分参数导致后续 base 被 multi_max 抬高。
        - 对历史已存在明显高位工况ID（例如 900xxx 或远高于常规区间）：视为 legacy_high，
          为避免扰动历史数据，继续沿用原先“跟随 multi_max”策略。
        返回 (base, safe_threshold, legacy_high)。
        同时返回 safe_threshold=max(normal_max, template_max)，用于判断是否需要把“落在常规区间”的历史工况ID迁移走。
        """
        normal_max = 0
        template_max = 0
        multi_max = 0
        try:
            from modules.condition_input.funcs.funcs_cdt_input import get_connection
            from main import get_product_form_from_db
            product_form = get_product_form_from_db(self.product_id) or "all"

            conn = get_connection(**db_config_1)
            try:
                with conn.cursor() as cur:
                    # 常规参数最大ID（排除[工况]）
                    cur.execute(
                        """
                        SELECT MAX(设计数据参数ID) AS max_id
                        FROM 产品设计活动表_设计数据表
                        WHERE 产品ID=%s
                          AND (参数名称 IS NULL OR 参数名称 NOT LIKE %s)
                        """,
                        (self.product_id, "%[工况%")
                    )
                    r = cur.fetchone() or {}
                    normal_max = int(r.get("max_id") or 0)

                    # 现有多工况最大ID（若历史已高位，沿用）
                    cur.execute(
                        """
                        SELECT MAX(设计数据参数ID) AS max_id
                        FROM 产品设计活动表_设计数据表
                        WHERE 产品ID=%s AND 参数名称 LIKE %s
                        """,
                        (self.product_id, "%[工况%")
                    )
                    r2 = cur.fetchone() or {}
                    multi_max = int(r2.get("max_id") or 0)

                    # 模板最大ID（按产品型式：NEN/AEM/BEM 额外包含 'NEN,AEM,BEM' 行；其余仅'all'）
                    if product_form in ("NEN", "AEM", "BEM","NEN(Head)"):
                        cur.execute(
                            """
                            SELECT MAX(设计数据参数ID) AS max_id
                            FROM 产品条件库.设计数据模板表
                            WHERE 所属型式 = %s OR 所属型式 LIKE %s
                            """,
                            ("all", f"%{product_form}%")
                        )
                    else:
                        cur.execute(
                            """
                            SELECT MAX(设计数据参数ID) AS max_id
                            FROM 产品条件库.设计数据模板表
                            WHERE 所属型式 = %s
                            """,
                            ("all",)
                        )
                    r3 = cur.fetchone() or {}
                    template_max = int(r3.get("max_id") or 0)
            finally:
                conn.close()
        except Exception as e:
            print(f"[多工况] 计算动态ID起点失败: {e}")

        safe_threshold = max(normal_max, template_max)
        # 判断是否存在“明显高位”的历史工况ID：这类产品不做整齐化回迁，避免影响既有数据
        legacy_high = False
        try:
            # 900xxx 是你们历史方案的典型区间；或 multi_max 远超 safe_threshold 也视为高位
            if int(multi_max or 0) >= 900000:
                legacy_high = True
            elif int(multi_max or 0) > int(safe_threshold or 0) + (len(self.PARAM_NAMES) * 2) + 50:
                legacy_high = True
        except Exception:
            legacy_high = False

        # 整齐化：新产品/低位工况固定基准为 safe_threshold；高位历史产品沿用 multi_max
        base = int(safe_threshold or 0) if not legacy_high else max(int(safe_threshold or 0), int(multi_max or 0))
        return base, safe_threshold, legacy_high

    def _get_multi_condition_param_id(self, gongkuang_no, param_name):
        """
        生成不与常规设计参数冲突的“动态”参数ID（不再硬编码900000）。
        规则：base + (工况号-2)*len(PARAM_NAMES) + 参数序号（1-based）
        """
        if self._multi_id_base is None:
            self._multi_id_base, self._multi_id_safe_threshold, self._multi_id_legacy_high = self._compute_multi_id_base()
        try:
            param_index = self.PARAM_NAMES.index(param_name) + 1
        except ValueError:
            param_index = 99
        # base是当前最大ID；为确保新ID>base，需要再顺延
        offset = (gongkuang_no - 2) * len(self.PARAM_NAMES) + param_index
        return int(self._multi_id_base or 0) + offset

    def eventFilter(self, obj, event):
        # 屏蔽工况下拉框的滚轮，避免误切换
        try:
            if obj is getattr(self, "combo_gongkuang", None) and event.type() == QEvent.Wheel:
                return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

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
        if getattr(self, "_readonly_local_files", False):
            return
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
                for row_idx, pname in enumerate(self.PARAM_NAMES):
                    kc_val, gc_val = self._data_cache[gongkuang_no][pname]
                    db_field = self._make_param_field(pname, gongkuang_no)
                    reserved_param_id = self._get_multi_condition_param_id(gongkuang_no, pname)
                    param_unit = self._get_param_unit_for_multi(row_idx, pname)

                    # 查询是否已存在
                    cur.execute("""
                        SELECT 设计数据参数ID FROM 产品设计活动表_设计数据表
                        WHERE 产品ID=%s AND 参数名称=%s
                    """, (self.product_id, db_field))
                    row = cur.fetchone()
                    exists = row is not None

                    if exists:
                        # 已存在 → 更新；若历史ID为低位冲突段，先迁移到保留高位ID
                        existing_param_id = row.get("设计数据参数ID")
                        # 只在“落在常规区间”时迁移，避免把已经是高位的历史工况ID回迁/扰动
                        if (
                            not getattr(self, "_multi_id_legacy_high", False)
                            and existing_param_id != reserved_param_id
                            and int(existing_param_id or 0) <= int(self._multi_id_safe_threshold or 0) + (len(self.PARAM_NAMES) * 2) + 50
                        ):
                            try:
                                cur.execute("""
                                    UPDATE 产品设计活动表_设计数据表
                                    SET 设计数据参数ID=%s
                                    WHERE 产品ID=%s AND 参数名称=%s
                                """, (reserved_param_id, self.product_id, db_field))
                            except Exception as migrate_err:
                                # 若高位ID已被占用，保底按参数名称更新数值，避免流程中断
                                print(f"[多工况] 参数ID迁移失败({db_field}): {migrate_err}")
                        cur.execute("""
                            UPDATE 产品设计活动表_设计数据表
                            SET 参数单位=%s, 壳程数值=%s, 管程数值=%s
                            WHERE 产品ID=%s AND 参数名称=%s
                        """, (param_unit, kc_val, gc_val, self.product_id, db_field))
                    else:
                        # 不存在 → 插入，使用高位保留ID，避免与主界面常规参数ID冲突
                        cur.execute("""
                            INSERT INTO 产品设计活动表_设计数据表
                                (设计数据参数ID, 产品ID, 参数名称, 参数单位, 壳程数值, 管程数值)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (reserved_param_id, self.product_id, db_field, param_unit, kc_val, gc_val))

            conn.commit()
            conn.close()
            # ❌ 不再 self.accept()，保持窗口打开
            QMessageBox.information(self, "保存成功", f"工况{gongkuang_no} 已保存")
            
            # 0209新修改-多工况输入标识显示
            # ✅ 通知父窗口更新多工况状态并刷新显示
            parent = self.parent()
            if parent and hasattr(parent, "update_multi_conditions_status"):
                parent.update_multi_conditions_status()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"保存工况{gongkuang_no} 数据失败：{e}")

    def _auto_save_current_gongkuang(self, gongkuang_no):
        """静默保存当前工况（无弹窗）"""
        if getattr(self, "_readonly_local_files", False):
            return
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
                for row_idx, pname in enumerate(self.PARAM_NAMES):
                    kc_val, gc_val = self._data_cache[gongkuang_no][pname]
                    db_field = self._make_param_field(pname, gongkuang_no)
                    reserved_param_id = self._get_multi_condition_param_id(gongkuang_no, pname)
                    param_unit = self._get_param_unit_for_multi(row_idx, pname)

                    cur.execute("""
                        SELECT 设计数据参数ID FROM 产品设计活动表_设计数据表
                        WHERE 产品ID=%s AND 参数名称=%s
                    """, (self.product_id, db_field))
                    row = cur.fetchone()
                    exists = row is not None

                    if exists:
                        existing_param_id = row.get("设计数据参数ID")
                        if (
                            not getattr(self, "_multi_id_legacy_high", False)
                            and existing_param_id != reserved_param_id
                            and int(existing_param_id or 0) <= int(self._multi_id_safe_threshold or 0) + (len(self.PARAM_NAMES) * 2) + 50
                        ):
                            try:
                                cur.execute("""
                                    UPDATE 产品设计活动表_设计数据表
                                    SET 设计数据参数ID=%s
                                    WHERE 产品ID=%s AND 参数名称=%s
                                """, (reserved_param_id, self.product_id, db_field))
                            except Exception as migrate_err:
                                print(f"[多工况][AutoSave] 参数ID迁移失败({db_field}): {migrate_err}")
                        cur.execute("""
                            UPDATE 产品设计活动表_设计数据表
                            SET 参数单位=%s, 壳程数值=%s, 管程数值=%s
                            WHERE 产品ID=%s AND 参数名称=%s
                        """, (param_unit, kc_val, gc_val, self.product_id, db_field))
                    else:
                        cur.execute("""
                            INSERT INTO 产品设计活动表_设计数据表
                                (设计数据参数ID, 产品ID, 参数名称, 参数单位, 壳程数值, 管程数值)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (reserved_param_id, self.product_id, db_field, param_unit, kc_val, gc_val))
            conn.commit()
            conn.close()
            
            # 0209新修改-多工况输入标识显示
            # ✅ 自动保存后也更新父窗口的多工况状态（静默更新，不弹窗）
            if gongkuang_no in [2, 3]:  # 只有工况2/3才需要更新状态
                parent = self.parent()
                if parent and hasattr(parent, "update_multi_conditions_status"):
                    parent.update_multi_conditions_status()
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

        if getattr(self, "_readonly_local_files", False):
            self._apply_table_readonly_only()

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
