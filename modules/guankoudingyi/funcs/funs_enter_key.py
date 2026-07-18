from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox, QLabel, QComboBox
import pymysql
import time
from modules.guankoudingyi.db_cnt import get_connection, db_config_2,db_config_material
from modules.guankoudingyi.funcs.funcs_pipe_table import (
    ensure_hidden_maps,
    get_next_pipe_id_runtime,
    ensure_hidden_attachment_maps,
    get_next_attachment_id_runtime,
    get_pipe_column_map,
    get_pipe_col,
)
from modules.cailiaodingyi.funcs.funcs_pdf_input import (
    _component_to_material_category,
    query_all_guankou_categories,
)


def save_all_pipe_data(stats_widget):
    """
    保存策略：
    - 对每一行（除最后空行）：
        * 必须有 管口代号
        * 取隐藏 管口ID；若无（极端情况），运行期分配一个
        * 对 产品设计活动表_管口表 做 INSERT ... ON DUPLICATE KEY UPDATE
        * 同步对 产品设计活动表_管口类别表 做 INSERT ... ON DUPLICATE KEY UPDATE
          （产品ID、管口ID、管口代号、管口所属元件、材料分类）
        * 材料分类规则：
          - 换热器：按管口所属元件分配管程/壳程；所属元件未改则保留元件定义侧已有分配
          - 容器：不看所属元件，新增写入第一个材料分类 tab；已有分配则保留（支持元件定义手动改）
    - 对 stats_widget.deleted_pipe_ids ：逐个 DELETE WHERE 产品ID AND 管口ID（同时删除两张表里的对应记录）
    """
    ensure_hidden_maps(stats_widget)
    # 获取表格和产品ID
    table = stats_widget.tableWidget_pipe
    product_id = stats_widget.product_id
    if not product_id:
        QMessageBox.warning(stats_widget, "错误", "产品ID不能为空")
        return

    is_container = getattr(stats_widget, 'is_container_product', False)

    # ===== 保存前校验：“管口功能”必填（仅换热器；容器不校验） =====
    if table is not None and not is_container:
        missing_codes = []
        last_row = table.rowCount() - 1  # 排除最后空行
        for row in range(last_row):
            code_item = table.item(row, 1)  # 管口代号
            func_item = table.item(row, 2)  # 管口功能
            code = code_item.text().strip() if code_item else ""
            func = func_item.text().strip() if func_item else ""
            if code and not func:
                missing_codes.append(code)
        if missing_codes:
            msg = "请输入管口代号为 " + "、".join(missing_codes) + " 的管口功能"
            if hasattr(stats_widget, 'line_tip'):
                stats_widget.line_tip.setText(msg)
                stats_widget.line_tip.setStyleSheet("color: #FFA500;")  # 橘色提示
            return
        # ===== 校验通过，继续原有保存逻辑 =====

    column_map = get_pipe_column_map(is_container)

    conn = None
    cur = None
    try:
        conn = get_connection(**db_config_2)
        cur = conn.cursor(pymysql.cursors.DictCursor)

        # —— 1) 先处理延迟删除 ——
        for hid in list(stats_widget.deleted_pipe_ids):
            # 管口表
            cur.execute("""
                DELETE FROM 产品设计活动表_管口表
                WHERE 产品ID=%s AND 管口ID=%s
            """, (product_id, hid))
            # 管口类别表（新增）
            cur.execute("""
                DELETE FROM 产品设计活动表_管口类别表
                WHERE 产品ID=%s AND 管口ID=%s
            """, (product_id, hid))
            #管口载荷表（补充）
            cur.execute("""
                DELETE FROM 产品设计活动表_管口载荷表
                WHERE 产品ID=%s AND 管口ID=%s
            """, (product_id, hid))
        stats_widget.deleted_pipe_ids.clear()

        # 保存前：旧所属元件（管口表）+ 已有材料分类（类别表）
        cur.execute("""
            SELECT 管口ID, 管口所属元件
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s
        """, (product_id,))
        prev_belong_map = {}
        for r in cur.fetchall() or []:
            pid = r.get("管口ID")
            if pid is None:
                continue
            prev_belong_map[pid] = (r.get("管口所属元件") or "").strip()

        cur.execute("""
            SELECT 管口ID, 材料分类
            FROM 产品设计活动表_管口类别表
            WHERE 产品ID = %s
        """, (product_id,))
        prev_cat_map = {}
        for r in cur.fetchall() or []:
            pid = r.get("管口ID")
            if pid is None:
                continue
            prev_cat_map[pid] = (r.get("材料分类") or "").strip()

        belong_col = get_pipe_col(is_container, "管口所属元件")
        newly_assigned_codes = []

        # 当前产品可用材料分类（按 Tab_ID 顺序）；容器取第一个作为默认页
        try:
            available_categories = [
                str(c).strip() for c in (query_all_guankou_categories(product_id) or [])
                if str(c).strip()
            ]
        except Exception:
            available_categories = []
        default_first_tab = available_categories[0] if available_categories else "管口材料分类1"

        # —— 2) 逐行 Upsert（新增/修改）——
        last_row = table.rowCount() - 1
        display_order_seq = 1
        for row in range(last_row):  # 排除最后空行
            code_item = table.item(row, 1)
            port_code = code_item.text().strip() if code_item else ""
            if not port_code:
                continue

            # 收集行数据
            row_data = {}
            for col, field in column_map.items():
                it = table.item(row, col)
                txt = it.text().strip() if it else ""
                # 对于"管口附件"字段，允许保存空字符串（用户取消所有选择时需要清空数据库中的值）
                # 其他字段保持原有逻辑，空字符串不保存
                if txt != "" or field == "管口附件":
                    row_data[field] = txt

            row_data["界面显示顺序"] = display_order_seq
            stats_widget.row_display_order[row] = display_order_seq
            display_order_seq += 1

            # 获取/兜底分配 管口ID（运行期分配，确认时才落库）
            hid = stats_widget.row_hidden_pipe_id.get(row)
            if not hid:
                hid = get_next_pipe_id_runtime(stats_widget, product_id)
                stats_widget.row_hidden_pipe_id[row] = hid  # 写回运行期映射

            # —— 2.1 写 "产品设计活动表_管口表"
            row_data.pop("管口代号", None)  # ✅ 删除潜在重复字段
            fields = ["产品ID", "管口ID", "管口代号", "管口更改状态"] + list(row_data.keys())
            values = [product_id, hid, port_code, "已更改"] + list(row_data.values())
            placeholders = ", ".join(["%s"] * len(fields))
            set_clause = ", ".join([f"`{k}`=VALUES(`{k}`)" for k in row_data.keys()] + [
                "`管口代号`=VALUES(`管口代号`)", "`管口更改状态`='已更改'"
            ])

            sql = f"""
                    INSERT INTO 产品设计活动表_管口表 (`{'`, `'.join(fields)}`)
                    VALUES ({placeholders})
                    ON DUPLICATE KEY UPDATE {set_clause}
                """
            cur.execute(sql, values)

            # —— 2.2 同步写 "产品设计活动表_管口类别表"（含材料分类）
            if belong_col is not None:
                belong_item = table.item(row, belong_col)
                component = belong_item.text().strip() if belong_item else ""
            else:
                component = (row_data.get("管口所属元件") or "").strip()

            prev_cat = prev_cat_map.get(hid, "")

            if is_container:
                # 容器：不看所属元件；新增写入第一个 tab；已有分配保留（元件定义可手动改）
                if not prev_cat:
                    material_category = default_first_tab
                    newly_assigned_codes.append(port_code)
                else:
                    material_category = prev_cat
            else:
                # 换热器：按所属元件分配管程/壳程；未改所属元件则保留元件定义侧分配
                mapped_cat = (
                    _component_to_material_category(component, available_categories)
                    if component else None
                )
                prev_belong = prev_belong_map.get(hid, "")
                belong_changed = bool(component) and (component != prev_belong)

                if belong_changed and mapped_cat:
                    # 管口定义侧改了所属元件 → 按管口定义重新分配页面
                    material_category = mapped_cat
                    if not prev_cat:
                        newly_assigned_codes.append(port_code)
                elif (not prev_cat) and mapped_cat:
                    # 首次按所属元件分配
                    material_category = mapped_cat
                    newly_assigned_codes.append(port_code)
                else:
                    # 所属元件未改：保留元件定义侧已有分配（允许两边不匹配）
                    material_category = prev_cat or None

            cur.execute("""
                INSERT INTO 产品设计活动表_管口类别表
                    (`产品ID`, `管口ID`, `管口代号`, `管口所属元件`, `材料分类`)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    `管口代号`=VALUES(`管口代号`),
                    `管口所属元件`=VALUES(`管口所属元件`),
                    `材料分类`=VALUES(`材料分类`)
            """, (product_id, hid, port_code, component, material_category))

            # —— 2.3 同步更新 "产品设计活动表_管口载荷表" 的管口代号（按 产品ID+管口ID）
            cur.execute("""
                UPDATE 产品设计活动表_管口载荷表
                SET 管口代号 = %s
                WHERE 产品ID = %s AND 管口ID = %s
            """, (port_code, product_id, hid))

        conn.commit()

        # —— 3) 保存管口附件数据 ——
        save_pipe_attachment_data(product_id, conn, cur)

        # 在line_tip中显示保存成功 / 自动分配提示
        if hasattr(stats_widget, 'line_tip'):
            if newly_assigned_codes:
                tip_text = "新增管口已自动分配至管口材料分类下。"
            else:
                tip_text = "保存成功！"
            stats_widget.line_tip.setText(tip_text)
            stats_widget.line_tip.setStyleSheet("color: black;")
            QTimer.singleShot(5000, lambda: stats_widget.line_tip.setText(""))
    except Exception as e:
        if conn:
            conn.rollback()
        # 在line_tip中显示保存失败信息
        if hasattr(stats_widget, 'line_tip'):
            stats_widget.line_tip.setText(f"保存失败：{e}")
            stats_widget.line_tip.setStyleSheet("color: red;")
            QTimer.singleShot(5000, lambda: stats_widget.line_tip.setText(""))
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def save_all_attachment_define_data(stats_widget):
    """
    保存附件定义表（tableWidget_attachment）到 产品设计活动表_附件表。
    策略对齐 save_all_pipe_data / 管口表：
    - 第0行为表头；最后一行为空白占位行，不参与保存（与管口「排除最后空行」一致）
    - 第0列为序号（不入库）；第1列「元件名称」为空则跳过该行
    - 元件ID：运行期隐藏映射；若无则按 max(db, runtime)+1 分配
    - 不重排/不修改已存在的 元件ID：删除仅删用户删除的 元件ID；新增则使用 max(db, runtime)+1 分配
      （中间断号允许存在，保证 (产品ID, 元件ID) 作为唯一标识稳定不变）
    - 暂不做校验/不写其他表
    """
    ensure_hidden_attachment_maps(stats_widget)
    table = getattr(stats_widget, "tableWidget_attachment", None)
    product_id = getattr(stats_widget, "product_id", None)
    if not product_id or table is None:
        return

    # 附件表列映射（与 UI 表头一致）
    column_map = {
        1: "元件名称",
        2: "元件类型",
        3: "所属元件",
        4: "轴向定位基准",
        5: "轴向定位距离mm",
        6: "数量",
        7: "间距",
        8: "轴向夹角（°）",
        9: "周向方位（°）",
        10: "偏心距",
        11: "外伸高度",
        12: "备注",
    }

    conn = None
    cur = None
    try:
        conn = get_connection(**db_config_2)
        cur = conn.cursor(pymysql.cursors.DictCursor)

        # 1) 处理延迟删除（仅删除用户实际删除的旧ID；不改动其他记录的 元件ID）
        deleted_ids = list(getattr(stats_widget, "deleted_attachment_ids", set()))
        for elem_id in deleted_ids:
            cur.execute("""
                DELETE FROM 产品设计活动表_附件表
                WHERE 产品ID=%s AND 元件ID=%s
            """, (product_id, elem_id))
        if hasattr(stats_widget, "deleted_attachment_ids"):
            stats_widget.deleted_attachment_ids.clear()

        # 2) 与管口相同：最后一行空白占位不保存；第0行为表头
        last_blank_row = table.rowCount() - 1
        for row in range(1, max(1, last_blank_row)):
            name_item = table.item(row, 1)
            elem_name = name_item.text().strip() if name_item else ""
            if not elem_name:
                continue

            elem_id = getattr(stats_widget, "row_hidden_attachment_id", {}).get(row)
            if not elem_id:
                elem_id = get_next_attachment_id_runtime(stats_widget, product_id)
                stats_widget.row_hidden_attachment_id[row] = elem_id

            row_data = {}
            for col, field in column_map.items():
                it = table.item(row, col)
                txt = it.text().strip() if it else ""
                row_data[field] = txt if txt != "" else None

            fields = ["元件ID", "产品ID"] + list(row_data.keys())
            placeholders = ", ".join(["%s"] * len(fields))
            values = [elem_id, product_id] + list(row_data.values())
            set_clause = ", ".join([f"`{k}`=VALUES(`{k}`)" for k in row_data.keys()])

            sql = f"""
                INSERT INTO 产品设计活动表_附件表 (`{'`, `'.join(fields)}`)
                VALUES ({placeholders})
                ON DUPLICATE KEY UPDATE {set_clause}
            """
            cur.execute(sql, values)

        conn.commit()

    except Exception as e:
        if conn:
            conn.rollback()
        # 不做强校验，仅提示保存失败原因
        QMessageBox.critical(stats_widget, "保存失败", f"保存附件定义数据时出错：{str(e)}")
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_type_selections_from_table_header(stats_widget):
    """
    从表头获取类型选择数据
    :param stats_widget: Stats类实例（更改参数类型以便访问comboBox组件）
    :return: 类型选择字典
    """
    type_selections = {}
    
    # ✅ 使用新的组件命名，不再使用findChild方式
    combo_mapping = [
        (stats_widget.combo_nominal_size_type, "公称尺寸类型"),
        (stats_widget.combo_pressure_level_type, "公称压力类型"),
        (stats_widget.combo_weld_end_spec_type, "焊端规格类型")
    ]
    
    for combo, db_field_name in combo_mapping:
        if combo is not None:
            selected_value = combo.currentText()
            type_selections[db_field_name] = selected_value
    
    return type_selections

def save_pipe_type_selection(stats_widget):
    """
    保存选中的公称尺寸类型、公称压力类型、焊端规格类型到数据库
    :param stats_widget: 主窗口实例
    """
    conn = None
    cursor = None
    
    try:
        # 验证产品ID
        product_id = stats_widget.product_id
        if not product_id:
            QMessageBox.warning(stats_widget, "错误", "产品ID不能为空")
            return False

        # 获取类型选择数据
        type_selections = get_type_selections_from_table_header(stats_widget)
        
        # 验证必需字段
        required_fields = ["公称尺寸类型", "公称压力类型", "焊端规格类型"]
        missing_fields = [field for field in required_fields if field not in type_selections]
        if missing_fields:
            QMessageBox.warning(stats_widget, "错误", f"未能获取到以下字段的选择值：{', '.join(missing_fields)}")
            return False

        # 数据库操作
        conn = get_connection(**db_config_2)
        cursor = conn.cursor()

        # 这里使用删除再插入的方式确保数据一致性
        cursor.execute("DELETE FROM 产品设计活动表_管口类型选择表 WHERE 产品ID = %s", (product_id,))
        
        sql = """
            INSERT INTO 产品设计活动表_管口类型选择表 
            (产品ID, 公称尺寸类型, 公称压力类型, 焊端规格类型) 
            VALUES (%s, %s, %s, %s)
        """
        values = (
            product_id,
            type_selections["公称尺寸类型"],
            type_selections["公称压力类型"], 
            type_selections["焊端规格类型"]
        )
        cursor.execute(sql, values)
        conn.commit()
        
        return True

    except Exception as e:
        if conn:
            conn.rollback()
        QMessageBox.critical(stats_widget, "保存失败", f"保存管口类型选择时出错：{str(e)}")
        return False

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def save_all_data_combined(stats_widget):
    """
    保存所有数据的组合方法：先保存管口类型选择，再保存管口数据
    :param stats_widget: 主窗口实例
    """
    # 先保存管口类型选择
    if save_pipe_type_selection(stats_widget):
        # 再保存管口数据
        save_all_pipe_data(stats_widget)
        # 再保存附件定义数据
        save_all_attachment_define_data(stats_widget)

def save_pipe_attachment_data(product_id, conn, cur):
    """
    保存管口附件数据到产品设计活动表_管口附件附加参数表
    1. 从产品设计活动表_管口表统计哪些管口选择了哪些附件类型
    2. 从模板库的管口附件附加参数表获取模板参数结构
    3. 根据附件类型分组，写入到产品活动库
    """
    try:
        # 1. 统计哪些管口选择了哪些附件类型
        cur.execute("""
            SELECT 管口代号, 管口附件
            FROM 产品设计活动表_管口表
            WHERE 产品ID = %s AND 管口附件 IS NOT NULL AND 管口附件 != ''
        """, (product_id,))
        pipe_attachments = cur.fetchall()

        if not pipe_attachments:
            print("[管口附件] 没有管口选择附件类型，清理旧数据后退出")
            cur.execute("""
                DELETE FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s
            """, (product_id,))
            conn.commit()
            return

        # 按附件类型分组管口号
        # 现在“管口附件”字段支持多选，数据库中以";"分隔，如："接管法兰配对法兰;接管拉筋"
        # 因此需要先按";"拆分，再把同一个管口编号添加到多个附件类型分组里
        attachment_groups = {}
        for row in pipe_attachments:
            pipe_code = row.get('管口代号') if isinstance(row, dict) else row[0]
            raw_attachment = row.get('管口附件') if isinstance(row, dict) else row[1]

            if not raw_attachment:
                continue

            # 解析多选附件，和前端下拉框保持一致，使用 ";" 作为分隔符
            # 同时去掉首尾空格，过滤掉空字符串
            attachment_list = [
                a.strip() for a in str(raw_attachment).split(";") if a.strip()
            ]

            for attachment_type in attachment_list:
                if attachment_type not in attachment_groups:
                    attachment_groups[attachment_type] = []
                attachment_groups[attachment_type].append(pipe_code)

        if not attachment_groups:
            print("[管口附件] 没有有效的附件类型分组，清理旧数据后退出")
            cur.execute("""
                DELETE FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s
            """, (product_id,))
            conn.commit()
            return

        # 3. 获取当前最大的参数ID，用于生成新的参数ID
        cur.execute("""
            SELECT COALESCE(MAX(参数ID), 0) as max_id
            FROM 产品设计活动表_管口附件附加参数表
        """)
        max_id_row = cur.fetchone()
        if isinstance(max_id_row, dict):
            max_param_id = max_id_row.get('max_id', 0)
        elif isinstance(max_id_row, (list, tuple)) and max_id_row:
            max_param_id = max_id_row[0] or 0
        else:
            max_param_id = 0
        next_param_id = max_param_id + 1

        # 4. 差异化同步：只处理受影响的附件类型
        # 查询现有各 Tab分类/Tab_ID 的管口号
        cur.execute("""
            SELECT Tab分类, Tab_ID, 参数数值
            FROM 产品设计活动表_管口附件附加参数表
            WHERE 产品ID = %s AND 参数名称 = '管口号'
        """, (product_id,))
        existing_tabs = cur.fetchall() or []

        current_types = set(attachment_groups.keys())


        # # 如果产品设计活动表_管口附件附加参数表里没有任何数据，按模板加载逻辑处理所有附件类型
        # if not existing_tabs:
        #     print("[管口附件] 产品活动库中无管口附件附加参数数据，按模板加载逻辑处理所有附件类型")
        #     # 获取模板名称（来自产品设计活动表_元件材料表）
        #     cur.execute("""
        #         SELECT 模板名称
        #         FROM 产品设计活动表_元件材料表
        #         WHERE 产品ID = %s
        #         LIMIT 1
        #     """, (product_id,))
        #     template_result = cur.fetchone()
        #     template_name = None
        #     if template_result:
        #         template_name = template_result.get('模板名称') if isinstance(template_result, dict) else template_result[0]

        #     if not template_name:
        #         print("[管口附件] 未找到模板名称，无法按模板加载，跳过")
        #     else:
        #         # 从材料库获取模板ID和模板参数结构
        #         conn_material = pymysql.connect(**db_config_material)
        #         try:
        #             cur_material = conn_material.cursor(pymysql.cursors.DictCursor)
        #             cur_material.execute("""
        #                 SELECT 模板ID
        #                 FROM 元件材料模板表
        #                 WHERE 模板名称 = %s
        #                 LIMIT 1
        #             """, (template_name,))
        #             template_id_row = cur_material.fetchone()
        #             if not template_id_row:
        #                 print(f"[管口附件] 未找到模板名称 '{template_name}' 对应的模板ID")
        #             else:
        #                 template_id = template_id_row.get('模板ID') if isinstance(template_id_row, dict) else template_id_row[0]
        #                 # 读取该模板的全部附件参数结构
        #                 cur_material.execute("""
        #                     SELECT Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位
        #                     FROM 管口附件附加参数表
        #                     WHERE 模板ID = %s
        #                     ORDER BY Tab分类, 标题分组, 参数ID
        #                 """, (template_id,))
        #                 template_params = cur_material.fetchall() or []

        #                 if not template_params:
        #                     print(f"[管口附件] 模板ID={template_id} 无参数结构")
        #                 else:
        #                     base_timestamp = int(time.time() * 1000)
        #                     tab_id_counter = 0
        #                     insert_count_all = 0

        #                     # 处理所有附件类型（不只是新增的）
        #                     for attachment_type, pipe_codes in attachment_groups.items():
        #                         if not pipe_codes:
        #                             continue

        #                         tab_id = base_timestamp + tab_id_counter
        #                         tab_id_counter += 1

        #                         # 从模板参数中筛出对应 Tab分类 的行
        #                         type_params = [p for p in template_params if p.get('Tab分类') == attachment_type]
        #                         if not type_params:
        #                             print(f"[管口附件] 附件类型 '{attachment_type}' 在模板中没有找到参数结构")
        #                             continue

        #                         pipe_codes_str = '、'.join(pipe_codes)

        #                         # 插入该附件类型的所有参数行
        #                         for param in type_params:
        #                             param_name = param.get('参数名称')
        #                             title_group = param.get('标题分组', '')
        #                             attachment_type_from_template = param.get('附件类型', '')

        #                             # 管口号字段使用当前管口表的管口号，其他字段使用模板的空值
        #                             if param_name == '管口号':
        #                                 param_value = pipe_codes_str
        #                             else:
        #                                 param_value = param.get('参数数值', '')  # 模板里的值（可能是空）

        #                             cur.execute("""
        #                                 INSERT INTO 产品设计活动表_管口附件附加参数表
        #                                 (参数ID, 产品ID, Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位, 模板名称, 模板ID, Tab_ID)
        #                                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        #                             """, (
        #                                 next_param_id,
        #                                 product_id,
        #                                 attachment_type,
        #                                 attachment_type_from_template,
        #                                 title_group,
        #                                 param_name,
        #                                 param_value,
        #                                 param.get('参数单位'),
        #                                 template_name,
        #                                 template_id,
        #                                 tab_id
        #                             ))
        #                             next_param_id += 1
        #                             insert_count_all += 1

        #                     if insert_count_all > 0:
        #                         print(f"[管口附件] 按模板加载完成，插入了 {insert_count_all} 条参数记录")
        #                     else:
        #                         print(f"[管口附件] 未插入任何数据")
        #         finally:
        #             try:
        #                 conn_material.close()
        #             except Exception:
        #                 pass

        #     # 提交事务并返回（首次加载时不需要执行后续的差异化更新逻辑）
        #     conn.commit()
        #     print(f"[管口附件] 事务已提交")
        #     return



        # 如果产品设计活动表_管口附件附加参数表里没有任何数据，按模板加载逻辑处理所有附件类型
        if not existing_tabs:
            print("[管口附件] 产品活动库中无管口附件附加参数数据，按模板加载逻辑处理所有附件类型（使用模板ID=9）")
            # 模板ID写死为9（因为不进入元件定义时没有模板ID）
            template_id = 9

            # 从材料库获取模板参数结构
            conn_material = pymysql.connect(**db_config_material)
            try:
                cur_material = conn_material.cursor(pymysql.cursors.DictCursor)
                # 读取该模板的全部附件参数结构
                cur_material.execute("""
                    SELECT Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位
                    FROM 管口附件附加参数表
                    WHERE 模板ID = %s
                    ORDER BY Tab分类, 标题分组, 参数ID
                """, (template_id,))
                template_params = cur_material.fetchall() or []

                if not template_params:
                    print(f"[管口附件] 模板ID={template_id} 无参数结构")
                else:
                    base_timestamp = int(time.time() * 1000)
                    tab_id_counter = 0
                    insert_count_all = 0

                    # 处理所有附件类型（不只是新增的）
                    for attachment_type, pipe_codes in attachment_groups.items():
                        if not pipe_codes:
                            continue

                        tab_id = base_timestamp + tab_id_counter
                        tab_id_counter += 1

                        # 从模板参数中筛出对应 Tab分类 的行
                        type_params = [p for p in template_params if p.get('Tab分类') == attachment_type]
                        if not type_params:
                            print(f"[管口附件] 附件类型 '{attachment_type}' 在模板中没有找到参数结构")
                            continue

                        pipe_codes_str = '、'.join(pipe_codes)

                        # 插入该附件类型的所有参数行
                        for param in type_params:
                            param_name = param.get('参数名称')
                            title_group = param.get('标题分组', '')
                            attachment_type_from_template = param.get('附件类型', '')

                            # 管口号字段使用当前管口表的管口号，其他字段使用模板的空值
                            if param_name == '管口号':
                                param_value = pipe_codes_str
                            else:
                                param_value = param.get('参数数值', '')  # 模板里的值（可能是空）

                            cur.execute("""
                                INSERT INTO 产品设计活动表_管口附件附加参数表
                                (参数ID, 产品ID, Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位, 模板名称, 模板ID, Tab_ID)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                next_param_id,
                                product_id,
                                attachment_type,
                                attachment_type_from_template,
                                title_group,
                                param_name,
                                param_value,
                                param.get('参数单位'),
                                '',  # 模板名称为空（因为未进入元件定义）
                                template_id,
                                tab_id
                            ))
                            next_param_id += 1
                            insert_count_all += 1

                    if insert_count_all > 0:
                        print(f"[管口附件] 按模板加载完成，插入了 {insert_count_all} 条参数记录")
                    else:
                        print(f"[管口附件] 未插入任何数据")
            finally:
                try:
                    conn_material.close()
                except Exception:
                    pass

            # 提交事务并返回（首次加载时不需要执行后续的差异化更新逻辑）
            conn.commit()
            print(f"[管口附件] 事务已提交")
            return


        # # 如果已有数据，执行差异化更新逻辑

        # 删除已不存在的附件类型（整类删）
        types_to_remove = [row.get('Tab分类') for row in existing_tabs if row.get('Tab分类') not in current_types]
        if types_to_remove:
            cur.execute(f"""
                DELETE FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s AND Tab分类 IN ({', '.join(['%s']*len(types_to_remove))})
            """, (product_id, *types_to_remove))

        # 对仍存在的类型，更新各 Tab 的管口号；若管口号为空则删除该 Tab
        handled_types = set()
        for row in existing_tabs:
            tab_type = row.get('Tab分类')
            tab_id = row.get('Tab_ID')
            if not tab_type or tab_type not in current_types:
                continue
            handled_types.add(tab_type)

            keep_set = set(attachment_groups.get(tab_type, []))
            current_codes = [c.strip() for c in (row.get('参数数值') or '').split('、') if c.strip()]
            new_codes = [c for c in current_codes if c in keep_set]

            if new_codes:
                new_codes_str = '、'.join(new_codes)
                cur.execute("""
                    UPDATE 产品设计活动表_管口附件附加参数表
                    SET 参数数值 = %s
                    WHERE 产品ID = %s AND Tab分类 = %s AND Tab_ID = %s AND 参数名称 = '管口号'
                """, (new_codes_str, product_id, tab_type, tab_id))
            else:
                cur.execute("""
                    DELETE FROM 产品设计活动表_管口附件附加参数表
                    WHERE 产品ID = %s AND Tab分类 = %s AND Tab_ID = %s
                """, (product_id, tab_type, tab_id))

        # 新增的附件类型：如果该附件类型一个 Tab 都没有，则按模板结构创建一个 Tab
        types_to_add = current_types - handled_types
        if types_to_add:
            try:
                # 获取模板名称（来自产品设计活动表_元件材料表）
                cur.execute("""
                    SELECT 模板名称
                    FROM 产品设计活动表_元件材料表
                    WHERE 产品ID = %s
                    LIMIT 1
                """, (product_id,))
                template_result = cur.fetchone()
                template_name = None
                if template_result:
                    template_name = template_result.get('模板名称') if isinstance(template_result, dict) else template_result[0]
                if not template_name:
                    print("[管口附件] 新增附件类型时未找到模板名称，跳过模板字段填充")
                else:
                    # 从材料库获取模板ID和模板参数结构
                    conn_material = pymysql.connect(**db_config_material)
                    try:
                        cur_material = conn_material.cursor(pymysql.cursors.DictCursor)
                        cur_material.execute("""
                            SELECT 模板ID
                            FROM 元件材料模板表
                            WHERE 模板名称 = %s
                            LIMIT 1
                        """, (template_name,))
                        template_id_row = cur_material.fetchone()
                        if not template_id_row:
                            print(f"[管口附件] 新增附件类型时未找到模板名称 '{template_name}' 对应的模板ID")
                        else:
                            template_id = template_id_row.get('模板ID') if isinstance(template_id_row, dict) else template_id_row[0]
                            # 读取该模板的全部附件参数结构
                            cur_material.execute("""
                                SELECT Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位
                                FROM 管口附件附加参数表
                                WHERE 模板ID = %s
                                ORDER BY Tab分类, 标题分组, 参数ID
                            """, (template_id,))
                            template_params = cur_material.fetchall() or []

                            if not template_params:
                                print(f"[管口附件] 新增附件类型时模板ID={template_id} 无参数结构")
                            else:
                                base_timestamp = int(time.time() * 1000)
                                tab_id_counter = 0
                                insert_count_new = 0

                                for attachment_type in types_to_add:
                                    # 只为完全没有任何 Tab 的附件类型创建一个新的 Tab
                                    # 若该类型在 existing_tabs 中已经有记录，说明前面处理遗漏，则跳过
                                    if any(row.get('Tab分类') == attachment_type for row in existing_tabs):
                                        continue

                                    pipe_codes = attachment_groups.get(attachment_type, [])
                                    if not pipe_codes:
                                        # 虽然类型存在，但没有管口号，跳过
                                        continue

                                    tab_id = base_timestamp + tab_id_counter
                                    tab_id_counter += 1

                                    # 从模板参数中筛出对应 Tab分类 的行
                                    type_params = [p for p in template_params if p.get('Tab分类') == attachment_type]
                                    if not type_params:
                                        print(f"[管口附件] 新增附件类型 '{attachment_type}' 在模板中没有找到参数结构")
                                        continue

                                    pipe_codes_str = '、'.join(pipe_codes)
                                    for param in type_params:
                                        param_name = param.get('参数名称')
                                        title_group = param.get('标题分组', '')
                                        attachment_type_from_template = param.get('附件类型', '')

                                        if param_name == '管口号':
                                            param_value = pipe_codes_str
                                        else:
                                            param_value = param.get('参数数值', '')

                                        cur.execute("""
                                            INSERT INTO 产品设计活动表_管口附件附加参数表
                                            (参数ID, 产品ID, Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位, 模板名称, 模板ID, Tab_ID)
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                        """, (
                                            next_param_id,
                                            product_id,
                                            attachment_type,
                                            attachment_type_from_template,
                                            title_group,
                                            param_name,
                                            param_value,
                                            param.get('参数单位'),
                                            template_name,
                                            template_id,
                                            tab_id
                                        ))
                                        next_param_id += 1
                                        insert_count_new += 1

                                if insert_count_new:
                                    print(f"[管口附件] 为新增附件类型 {types_to_add} 创建了 {insert_count_new} 条参数记录")
                    finally:
                        try:
                            conn_material.close()
                        except Exception:
                            pass
            except Exception as e:
                print(f"[管口附件] 处理新增附件类型时出错: {e}")
                import traceback
                traceback.print_exc()

        print(f"[管口附件] 同步完成：删除类型 {len(types_to_remove)}，更新类型 {len(handled_types)}，待新增类型 {len(types_to_add)}")

        # 提交事务（使用主连接）
        conn.commit()
        print(f"[管口附件] 事务已提交")

    except Exception as e:
        print(f"[管口附件] 保存失败: {e}")
        import traceback
        traceback.print_exc()
        # 回滚事务（使用主连接）
        if conn:
            conn.rollback()
            print(f"[管口附件] 事务已回滚")
        # 不抛出异常，避免影响主保存流程


def connect_save_button(stats_widget):
    """
    连接确认按钮的点击事件
    :param stats_widget: 主窗口实例
    """
    stats_widget.pushButton_affirm.clicked.connect(lambda: save_all_data_combined(stats_widget))
