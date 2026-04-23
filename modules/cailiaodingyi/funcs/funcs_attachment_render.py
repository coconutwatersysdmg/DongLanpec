"""
管口附件参数渲染模块
用于渲染管口附件元件的参数到UI界面
固定三列：参数名称、参数值、参数单位
根据管口定义中的附件类型动态创建tab页
"""
from collections import defaultdict
from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtWidgets import QTableWidgetItem, QHeaderView, QAbstractItemView, QTableWidget, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QMessageBox, QComboBox, QMenu
from modules.cailiaodingyi.controllers.add_tab import PlusTabManager

from modules.cailiaodingyi.controllers.checkcombo import CheckComboDelegate
from modules.cailiaodingyi.controllers.combo import ComboPopupEventFilter, MultiSelectRowComboDelegate, ComboDelegate, NonNegativeDoubleDelegate
from modules.cailiaodingyi.funcs.funcs_pdf_input import db_config_1, db_config_2, get_options_for_param
from modules.cailiaodingyi.funcs.funcs_pdf_render import _set_table_tooltips, _install_tooltip_updater
from modules.cailiaodingyi.funcs.funcs_pdf_change import get_filtered_material_options, DEBUG_VERBOSE_DEFINE_UI
from modules.cailiaodingyi.controllers.datamanager import install_material_delegate_linkage, MaterialInstantDelegate, _apply_forging_visibility
import pymysql

# 材料库配置（用于查询管口附件折叠表）
db_config_material = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': '材料库'
}


def _dbg_print(msg: str):
    """统一受 DEBUG_VERBOSE_DEFINE_UI 控制的调试输出。"""
    if DEBUG_VERBOSE_DEFINE_UI:
        print(msg)


def _set_tip(viewer_instance, msg, *, success=True, auto_clear_ms=5000):
    """模仿 datamanager 的提示栏样式：成功黑色、失败红色，默认 5s 清空"""
    try:
        tip = getattr(viewer_instance, "line_tip", None)
        if not tip:
            return
        tip.setStyleSheet("color:black;" if success else "color:red;")
        tip.setText(msg or "")
        if auto_clear_ms and auto_clear_ms > 0:
            QTimer.singleShot(auto_clear_ms, lambda: tip.setText(""))
    except Exception as e:
        print(f"[提示栏写入失败] {e}")


def get_attachment_tab_types_by_product(product_id):
    """
    从产品设计活动表_管口附件附加参数表中查询Tab分类，用于创建tab页
    返回: 去重后的Tab分类列表，按附件类型分组，每个附件类型内按Tab_ID排序
    例如: ["接管法兰配对法兰", "接管法兰配对法兰2", "接管拉筋", "防冲挡板"]
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 查询所有Tab分类及其附件类型和Tab_ID
            cursor.execute("""
                SELECT DISTINCT Tab分类, 附件类型, MIN(Tab_ID) as min_tab_id
                FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s AND Tab分类 IS NOT NULL AND Tab分类 != ''
                GROUP BY Tab分类, 附件类型
                ORDER BY 附件类型, min_tab_id
            """, (product_id,))
            rows = cursor.fetchall()
            
            # 按附件类型分组，每个附件类型内按Tab_ID排序
            fixed_tab_order = ["接管法兰配对法兰", "接管拉筋", "防冲挡板", "破涡器"]
            attachment_type_groups = {}
            for row in rows:
                tab_classification = row.get('Tab分类', '').strip()
                attachment_type = row.get('附件类型', '').strip()
                min_tab_id = row.get('min_tab_id', '')
                
                if attachment_type not in attachment_type_groups:
                    attachment_type_groups[attachment_type] = []
                attachment_type_groups[attachment_type].append((tab_classification, min_tab_id))
            
            # 按固定顺序和Tab_ID排序
            result = []
            for attachment_type in fixed_tab_order:
                if attachment_type in attachment_type_groups:
                    # 按Tab_ID排序
                    groups = sorted(attachment_type_groups[attachment_type], key=lambda x: x[1] or '')
                    result.extend([g[0] for g in groups])
            
            return result
    finally:
        connection.close()


def load_attachment_param_data(product_id, tab_classification):
    """
    加载指定Tab分类的参数数据
    :param product_id: 产品ID
    :param tab_classification: Tab分类（如：接管法兰配对法兰、接管拉筋、防冲挡板、破涡器）
    :return: 参数数据列表，每个元素包含：标题分组、参数名称、参数数值、参数单位、附件类型、Tab_ID等
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位, Tab_ID
                FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s AND Tab分类 = %s
                ORDER BY Tab_ID, 标题分组, 参数ID
            """, (product_id, tab_classification))
            
            rows = cursor.fetchall()
            return rows
    finally:
        connection.close()


def get_attachment_type_options():
    """
    获取管口附件类型下拉框选项
    返回: 附件类型选项列表
    """
    return ["接管法兰配对法兰", "接管拉筋", "防冲挡板", "破涡器"]


def copy_attachment_tab_from_current(product_id, attachment_type, source_tab_name, source_param_values, viewer_instance):
    """
    从当前tab页复制创建新的tab页（复制当前tab页的内容，但管口号不复制）
    :param product_id: 产品ID
    :param attachment_type: 附件类型（如：接管法兰配对法兰、接管拉筋、防冲挡板、破涡器）
    :param source_tab_name: 源tab页名称
    :param source_param_values: 源tab页的参数值字典 {(参数名称, 标题分组): 参数值}（不包含管口号）
    :param viewer_instance: 视图实例
    :return: 新创建的tab分类名称（如："接管法兰配对法兰2"）
    """
    import time
    
    # 1. 查找该附件类型已有的tab分类，确定新tab的名称
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 查询该附件类型的所有tab分类
            cursor.execute("""
                SELECT DISTINCT Tab分类
                FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s AND 附件类型 = %s
                ORDER BY Tab分类
            """, (product_id, attachment_type))
            existing_tabs = cursor.fetchall()
            
            # 确定新tab的名称
            existing_tab_names = [row.get('Tab分类', '').strip() for row in existing_tabs]
            new_tab_name = attachment_type
            counter = 2
            while new_tab_name in existing_tab_names:
                new_tab_name = f"{attachment_type}{counter}"
                counter += 1
            
            # 2. 从源tab页获取参数结构（包括标题分组）
            cursor.execute("""
                SELECT Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位, 模板名称, 模板ID
                FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s AND Tab分类 = %s
                ORDER BY Tab_ID, 标题分组, 参数ID
            """, (product_id, source_tab_name))
            source_params = cursor.fetchall()
            
            if not source_params:
                print(f"[创建新tab] 源tab页 '{source_tab_name}' 没有参数数据")
                return None
            
            # 3. 生成新的Tab_ID（使用时间戳）
            new_tab_id = int(time.time() * 1000)
            
            # 4. 获取当前最大的参数ID
            cursor.execute("""
                SELECT COALESCE(MAX(参数ID), 0) as max_id
                FROM 产品设计活动表_管口附件附加参数表
            """)
            max_id_result = cursor.fetchone()
            max_param_id = max_id_result.get('max_id', 0) if max_id_result else 0
            next_param_id = max_param_id + 1
            
            # 5. 插入新tab的参数数据（复制源tab页的参数值，但管口号设为空）
            insert_count = 0
            for source_param in source_params:
                param_name = source_param.get('参数名称', '') or ''
                param_name = param_name.strip() if param_name else ''
                title_group = source_param.get('标题分组', '') or ''
                title_group = title_group.strip() if title_group else ''
                attachment_type_from_source = source_param.get('附件类型', '') or ''
                template_name = source_param.get('模板名称', '') or ''
                template_id = source_param.get('模板ID')
                
                # 对于"管口号"参数，设为空（不复制）
                if param_name == '管口号':
                    param_value = ''
                else:
                    # 其他参数优先从源tab页的参数值字典中获取（从表格中读取的当前值）
                    # 使用(参数名称, 标题分组)作为key查找
                    key = (param_name, title_group)
                    param_value = source_param_values.get(key, '')
                    # 如果使用分组key找不到，使用源数据库中的值（而不是查找其他分组）
                    if param_value == '' and key not in source_param_values:
                        # 使用源数据库中的参数值
                        param_value = source_param.get('参数数值', '') or ''
                        param_value = param_value.strip() if param_value else ''
                
                cursor.execute("""
                    INSERT INTO 产品设计活动表_管口附件附加参数表
                    (参数ID, 产品ID, Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位, 模板名称, 模板ID, Tab_ID)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    next_param_id,
                    product_id,
                    new_tab_name,  # Tab分类 = 新tab的名称（如"接管法兰配对法兰2"）
                    attachment_type_from_source,  # 附件类型 = 源tab页的附件类型
                    title_group,
                    param_name,
                    param_value,
                    source_param.get('参数单位'),
                    template_name,
                    template_id,
                    new_tab_id
                ))
                next_param_id += 1
                insert_count += 1
            
            connection.commit()
            print(f"[创建新tab] 成功创建tab页 '{new_tab_name}'，从 '{source_tab_name}' 复制了 {insert_count} 条参数记录（管口号未复制）")
            
            return new_tab_name
    finally:
        connection.close()


def create_attachment_tab_from_template(product_id, attachment_type, selected_pipe_codes, viewer_instance):
    """
    从模板创建新的管口附件tab页
    :param product_id: 产品ID
    :param attachment_type: 附件类型（如：接管法兰配对法兰、接管拉筋、防冲挡板、破涡器）
    :param selected_pipe_codes: 选中的管口号列表（如：["N3", "N4"]）
    :param viewer_instance: 视图实例
    :return: 新创建的tab分类名称（如："接管法兰配对法兰2"）
    """
    import time
    
    # 1. 查找该附件类型已有的tab分类，确定新tab的名称
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 查询该附件类型的所有tab分类
            cursor.execute("""
                SELECT DISTINCT Tab分类
                FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s AND 附件类型 = %s
                ORDER BY Tab分类
            """, (product_id, attachment_type))
            existing_tabs = cursor.fetchall()
            
            # 确定新tab的名称
            existing_tab_names = [row.get('Tab分类', '').strip() for row in existing_tabs]
            new_tab_name = attachment_type
            counter = 2
            while new_tab_name in existing_tab_names:
                new_tab_name = f"{attachment_type}{counter}"
                counter += 1
            
            # 2. 获取模板信息
            cursor.execute("""
                SELECT 模板名称
                FROM 产品设计活动表_元件材料表
                WHERE 产品ID = %s
                LIMIT 1
            """, (product_id,))
            template_result = cursor.fetchone()
            if not template_result:
                print(f"[创建新tab] 未找到产品的模板名称")
                return None
            
            template_name = template_result.get('模板名称', '').strip()
            if not template_name:
                print(f"[创建新tab] 产品模板名称为空")
                return None
            
            # 3. 从材料库获取模板ID和参数结构
            conn_material = pymysql.connect(**db_config_material)
            try:
                cur_material = conn_material.cursor(pymysql.cursors.DictCursor)
                
                cur_material.execute("""
                    SELECT 模板ID
                    FROM 元件材料模板表
                    WHERE 模板名称 = %s
                    LIMIT 1
                """, (template_name,))
                template_id_result = cur_material.fetchone()
                if not template_id_result:
                    print(f"[创建新tab] 材料库中没有找到模板名称 '{template_name}' 的模板ID")
                    return None
                
                template_id = template_id_result.get('模板ID')
                
                # 查询模板参数结构（使用附件类型而不是Tab分类）
                cur_material.execute("""
                    SELECT Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位
                    FROM 管口附件附加参数表
                    WHERE 模板ID = %s AND 附件类型 = %s
                    ORDER BY 标题分组, 参数ID
                """, (template_id, attachment_type))
                template_params = cur_material.fetchall()
                
                if not template_params:
                    print(f"[创建新tab] 模板库中没有找到附件类型 '{attachment_type}' 的参数结构")
                    return None
                
                # 4. 生成新的Tab_ID（使用时间戳）
                new_tab_id = int(time.time() * 1000)
                
                # 5. 获取当前最大的参数ID
                cursor.execute("""
                    SELECT COALESCE(MAX(参数ID), 0) as max_id
                    FROM 产品设计活动表_管口附件附加参数表
                """)
                max_id_result = cursor.fetchone()
                max_param_id = max_id_result.get('max_id', 0) if max_id_result else 0
                next_param_id = max_param_id + 1
                
                # 6. 合并管口号
                pipe_codes_str = '、'.join(selected_pipe_codes)
                
                # 7. 插入新tab的参数数据
                insert_count = 0
                for param in template_params:
                    param_name = param.get('参数名称')
                    title_group = param.get('标题分组', '')
                    attachment_type_from_template = param.get('附件类型', '')
                    
                    # 对于"管口号"参数，写入选中的管口号
                    if param_name == '管口号':
                        param_value = pipe_codes_str
                    else:
                        param_value = param.get('参数数值', '')
                    
                    cursor.execute("""
                        INSERT INTO 产品设计活动表_管口附件附加参数表
                        (参数ID, 产品ID, Tab分类, 附件类型, 标题分组, 参数名称, 参数数值, 参数单位, 模板名称, 模板ID, Tab_ID)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        next_param_id,
                        product_id,
                        new_tab_name,  # Tab分类 = 新tab的名称（如"接管法兰配对法兰2"）
                        attachment_type_from_template,  # 附件类型 = 模板中的附件类型
                        title_group,
                        param_name,
                        param_value,
                        param.get('参数单位'),
                        template_name,
                        template_id,
                        new_tab_id
                    ))
                    next_param_id += 1
                    insert_count += 1
                
                connection.commit()
                print(f"[创建新tab] 成功创建tab页 '{new_tab_name}'，插入 {insert_count} 条参数记录")
                
            finally:
                conn_material.close()
            
            return new_tab_name
    finally:
        connection.close()


def query_pipe_codes_by_attachment_type(product_id, attachment_type):
    """
    从管口定义中获取某个附件类型对应的所有管口号（总可选项）
    现在“管口附件”字段支持多选，数据库中以";"分隔，如："接管法兰配对法兰;接管拉筋"
    因此需要先按";"拆分，再按附件类型分组
    :param product_id: 产品ID
    :param attachment_type: 附件类型（如：接管法兰配对法兰、接管拉筋、防冲挡板、破涡器）
    :return: 管口号列表（去重，按管口ID顺序）
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 取出所有有管口附件的管口记录
            cursor.execute("""
                SELECT 管口ID, 管口代号, 管口附件
                FROM 产品设计活动表_管口表
                WHERE 产品ID = %s
                  AND 管口附件 IS NOT NULL
                  AND 管口附件 != ''
                ORDER BY 管口ID
            """, (product_id,))
            rows = cursor.fetchall()

            result = []
            seen = set()
            for row in rows:
                code = (row.get('管口代号') or '').strip()
                raw_attachment = row.get('管口附件') or ''
                if not code or not raw_attachment:
                    continue

                # 按 ";" 拆分多选附件
                attach_list = [a.strip() for a in str(raw_attachment).split(";") if a.strip()]
                if attachment_type in attach_list and code not in seen:
                    seen.add(code)
                    result.append(code)

            return result
    finally:
        connection.close()


def query_selected_pipe_codes_in_other_tabs(product_id, attachment_type, current_tab_name):
    """
    获取其他tab页已选的管口号（已选项）
    :param product_id: 产品ID
    :param attachment_type: 附件类型
    :param current_tab_name: 当前tab页名称
    :return: 其他tab页已选的管口号列表
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            # 查询该附件类型的其他tab页（排除当前tab页）已选的管口号
            cursor.execute("""
                SELECT DISTINCT 参数数值
                FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s 
                  AND 附件类型 = %s 
                  AND Tab分类 != %s
                  AND 参数名称 = '管口号'
                  AND 参数数值 IS NOT NULL 
                  AND 参数数值 != ''
            """, (product_id, attachment_type, current_tab_name))
            rows = cursor.fetchall()
            
            # 合并所有其他tab页的管口号
            selected_codes = set()
            for row in rows:
                pipe_codes_str = row.get('参数数值', '').strip()
                if pipe_codes_str:
                    codes = [code.strip() for code in pipe_codes_str.split('、') if code.strip()]
                    selected_codes.update(codes)
            
            result = list(selected_codes)
            _dbg_print(f"[query_selected_pipe_codes_in_other_tabs] 产品ID={product_id}, 附件类型={attachment_type}, 当前tab={current_tab_name}")
            _dbg_print(f"[query_selected_pipe_codes_in_other_tabs] 查询结果: {result}")
            return result
    finally:
        connection.close()


def get_attachment_folding_structure(attachment_type):
    """
    从管口附件折叠表中获取指定附件类型的小标题信息
    :param attachment_type: 附件类型（如：接管法兰配对法兰、接管拉筋、防冲挡板、破涡器）
    :return: 小标题列表，每个元素包含：小标题、是否默认展开、排序顺序
    例如: [
        {"小标题": "接管法兰配对法兰", "是否默认展开": "1", "排序顺序": "1"},
        {"小标题": "接管法兰垫片", "是否默认展开": "0", "排序顺序": "2"},
        ...
    ]
    """
    connection = pymysql.connect(**db_config_material)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT 小标题, 是否默认展开, 排序顺序
                FROM 管口附件折叠表
                WHERE 附件类型 = %s
                ORDER BY CAST(排序顺序 AS UNSIGNED)
            """, (attachment_type,))
            
            rows = cursor.fetchall()
            return rows
    finally:
        connection.close()


def _get_tab_widget(viewer_instance):
    """获取或创建tabWidget"""
    tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
    if not tab_widget:
        try:
            stacked_widget = getattr(viewer_instance, "stackedWidget", None)
            if stacked_widget:
                page_5 = stacked_widget.widget(4)
                if page_5:
                    tab_widget = page_5.findChild(QTabWidget)
                    if tab_widget:
                        setattr(viewer_instance, "tabWidget_attachment", tab_widget)
        except Exception as e:
            _dbg_print(f"[DBG][attachment_render] 查找tabWidget失败: {e}")
    return tab_widget


def _setup_tab_bar(tab_widget, viewer_instance):
    """设置tabBar属性"""
    bar = tab_widget.tabBar()
    bar.setUsesScrollButtons(True)
    bar.setExpanding(False)
    bar.setElideMode(Qt.ElideNone)
    bar.setContextMenuPolicy(Qt.CustomContextMenu)
    bar.customContextMenuRequested.connect(lambda pos: _on_attachment_tab_right_menu(viewer_instance, pos))
    # 设置左右导航按钮背景为白色（背景色），边框也为白色
    bar.setStyleSheet("""
        QTabBar::scroller {
            background: white;
            border: none;
        }
        QTabBar QAbstractButton {
            background: white;
            border: 1px solid white;
        }
    """)


def _clear_existing_tabs(tab_widget):
    """清空现有tab页（保留+号tab如果有）"""
    has_plus = (tab_widget.count() > 0 and tab_widget.tabText(tab_widget.count() - 1).strip() in {"+", "＋"})
    last_real = tab_widget.count() - (1 if has_plus else 0)
    for i in range(last_real - 1, -1, -1):
        w = tab_widget.widget(i)
        tab_widget.removeTab(i)
        if w:
            w.deleteLater()
    return has_plus


def _create_attachment_tab_page(tab_classification):
    """创建单个tab页的页面和表格"""
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(9, 6, 9, 6)
    layout.setSpacing(6)
    
    table = QTableWidget()
    table.setColumnCount(3)
    table.setHorizontalHeaderLabels(['参数名称', '参数值', '参数单位'])
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(False)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QTableWidget.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.SelectedClicked)
    
    layout.addWidget(table)
    return page, table


def _extract_attachment_info_from_params(param_data):
    """从参数数据中提取附件类型和管口号"""
    attachment_type = None
    pipe_codes_str = ""
    
    if param_data:
        attachment_type = param_data[0].get('附件类型', '').strip()
        for param in param_data:
            if param.get('参数名称') == '管口号':
                pipe_codes_str = param.get('参数数值', '')
                break
    
    guankou_codes = [code.strip() for code in pipe_codes_str.split('、') if code.strip()] if pipe_codes_str else []
    return attachment_type, guankou_codes


def render_empty_attachment_ui(viewer_instance, placeholder_tab_name="管口附件"):
    """
    渲染一个空的管口附件界面：只有空表头，不展示旧内容。
    用于产品活动库无管口附件数据时的占位显示。
    """
    tab_widget = _get_tab_widget(viewer_instance)
    if not tab_widget:
        _dbg_print("[DBG][attachment_render] 未找到tabWidget_attachment，无法渲染空界面")
        return
    
    _setup_tab_bar(tab_widget, viewer_instance)
    _clear_existing_tabs(tab_widget)
    
    page, table = _create_attachment_tab_page(placeholder_tab_name)
    tab_widget.addTab(page, placeholder_tab_name)
    
    # 清空并设置表头
    table.clear()
    table.setRowCount(0)
    table.setColumnCount(3)
    table.setHorizontalHeaderLabels(['参数名称', '参数值', '参数单位'])
    _setup_table_header_style(table)
    
    # 记录到动态字典，避免后续引用空指针
    if not hasattr(viewer_instance, "dynamic_attachment_param_tabs"):
        viewer_instance.dynamic_attachment_param_tabs = {}
    viewer_instance.dynamic_attachment_param_tabs.clear()
    viewer_instance.dynamic_attachment_param_tabs[placeholder_tab_name] = table


def render_attachment_param_to_ui(viewer_instance, element_id, target_tab_name=None):
    """
    渲染管口附件参数到UI
    根据产品设计活动表_管口附件附加参数表中的Tab分类字段创建tab页
    :param viewer_instance: 视图实例
    :param element_id: 元件ID（保留参数以兼容调用，但实际不使用）
    :param target_tab_name: 可选，指定要切换到的tab页名称（如"接管法兰配对法兰2"），如果不提供则默认切换到第一个tab页
    """
    product_id = getattr(viewer_instance, 'product_id', None)
    if not product_id:
        _dbg_print("[DBG][attachment_render] 未找到product_id")
        return
    
    _dbg_print(f"[DBG][attachment_render] 开始渲染管口附件，产品ID={product_id}")
    
    # 获取Tab分类列表
    tab_types = get_attachment_tab_types_by_product(product_id)
    if not tab_types:
        _dbg_print("[DBG][attachment_render] 未找到Tab分类数据")
        return
    
    _dbg_print(f"[DBG][attachment_render] 数据库中的Tab分类列表: {tab_types}")
    
    # 获取或创建tabWidget
    tab_widget = _get_tab_widget(viewer_instance)
    if not tab_widget:
        _dbg_print("[DBG][attachment_render] 未找到tabWidget_attachment")
        return
    
    # 设置tabBar属性
    _setup_tab_bar(tab_widget, viewer_instance)
    
    # 清空现有tab页
    has_plus = _clear_existing_tabs(tab_widget)
    
    # 初始化动态tab字典
    if not hasattr(viewer_instance, "dynamic_attachment_param_tabs"):
        viewer_instance.dynamic_attachment_param_tabs = {}
    viewer_instance.dynamic_attachment_param_tabs.clear()
    
    # 为每个Tab分类创建tab页
    for tab_classification in tab_types:
        page, table = _create_attachment_tab_page(tab_classification)
        
        # 插入tab页
        insert_pos = tab_widget.count() - 1 if has_plus else tab_widget.count()
        tab_widget.insertTab(insert_pos, page, tab_classification)
        viewer_instance.dynamic_attachment_param_tabs[tab_classification] = table
        
        # 加载参数数据
        param_data = load_attachment_param_data(product_id, tab_classification)
        attachment_type, guankou_codes = _extract_attachment_info_from_params(param_data)
        
        if not attachment_type:
            _dbg_print(f"[DBG][attachment_render] Tab分类 '{tab_classification}' 未找到附件类型，跳过渲染")
            continue
        
        # 渲染数据
        _render_attachment_table_data(
            table, 
            attachment_type,
            guankou_codes, 
            param_data, 
            viewer_instance,
            tab_classification,
            product_id
        )
        
        _dbg_print(f"[DBG][attachment_render] 完成渲染 {tab_classification}，共 {table.rowCount()} 行")
    
    # 添加+号tab页管理器和tab切换处理器
    _setup_plus_tab_manager(tab_widget, viewer_instance)
    _setup_tab_change_handler(tab_widget, viewer_instance)
    
    # 切换到指定的tab页或第一个真实的tab页（而不是"+"标签页）
    if tab_widget.count() > 0:
        if target_tab_name:
            # 如果指定了目标tab页名称，尝试切换到该tab页
            found = False
            for i in range(tab_widget.count()):
                if tab_widget.tabText(i).strip() == target_tab_name.strip():
                    tab_widget.setCurrentIndex(i)
                    _dbg_print(f"[DBG][attachment_render] 已切换到指定的tab页: {target_tab_name}")
                    found = True
                    break
            if not found:
                # 如果找不到指定的tab页，切换到第一个tab页
                tab_widget.setCurrentIndex(0)
                _dbg_print(f"[DBG][attachment_render] 未找到指定的tab页 '{target_tab_name}'，切换到第一个tab页")
        else:
            # 如果没有指定目标tab页，默认切换到第一个tab页
            # 从其他元件切换到管口附件时，应该默认显示第一个tab页
            tab_widget.setCurrentIndex(0)


def _read_param_values_from_table(table, param_data):
    """从表格中读取参数值（用于复制到新tab页）"""
    current_param_values = {}
    param_group_map = {}
    
    # 构建标题分组映射
    for param in param_data:
        param_name = param.get('参数名称', '') or ''
        param_name = param_name.strip() if param_name else ''
        title_group = param.get('标题分组', '') or ''
        title_group = title_group.strip() if title_group else ''
        if param_name:
            if param_name not in param_group_map:
                param_group_map[param_name] = []
            if title_group and title_group not in param_group_map[param_name]:
                param_group_map[param_name].append(title_group)
    
    # 遍历表格，读取参数值
    current_group = None
    for r in range(table.rowCount()):
        param_item = table.item(r, 0)
        if not param_item:
            continue
        
        group_info = param_item.data(Qt.UserRole)
        if group_info and group_info.get("is_group_title"):
            current_group = group_info.get("group_name", "")
            continue
        
        param_name = param_item.text().strip()
        if not param_name or param_name == "管口号":
            continue
        
        # 确定当前参数所属的标题分组
        title_group = current_group if current_group else ""
        if not title_group and param_name in param_group_map:
            groups = param_group_map[param_name]
            if groups:
                title_group = groups[0]
        
        if title_group is None:
            title_group = ""
        else:
            title_group = str(title_group).strip()
        
        # 读取参数值
        param_value = ""
        value_item = table.item(r, 1)
        if value_item:
            param_value = value_item.text().strip()
        else:
            widget = table.cellWidget(r, 1)
            if widget and isinstance(widget, QComboBox):
                param_value = widget.currentText().strip()
        
        key = (param_name, title_group)
        current_param_values[key] = param_value
    
    return current_param_values


def _add_attachment_tab_from_current(viewer_instance, src_idx, src_name):
    """从当前tab页创建新的tab页（复制当前tab页的内容，但管口号不复制）"""
    try:
        print(f"[创建新tab] _add_attachment_tab_from_current 被调用: src_idx={src_idx}, src_name={src_name}")
        tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
        if not tab_widget:
            print(f"[创建新tab] 未找到tabWidget_attachment")
            return
        
        if src_idx < 0 or src_idx >= tab_widget.count():
            print(f"[创建新tab] src_idx超出范围: {src_idx}, tab数量: {tab_widget.count()}")
            return
        
        product_id = getattr(viewer_instance, 'product_id', None)
        if not product_id:
            print(f"[创建新tab] 未找到product_id")
            return
        
        # 获取当前tab页的附件类型
        current_tab_name = tab_widget.tabText(src_idx)
        current_table = viewer_instance.dynamic_attachment_param_tabs.get(current_tab_name)
        
        if not current_table:
            print(f"[DBG][attachment_render] 未找到当前tab页 '{current_tab_name}' 的表格")
            return
        
        # 从数据库获取当前tab页的附件类型和参数数据
        param_data = load_attachment_param_data(product_id, current_tab_name)
        if not param_data:
            print(f"[DBG][attachment_render] 未找到当前tab页 '{current_tab_name}' 的参数数据")
            return
        
        attachment_type = param_data[0].get('附件类型', '').strip()
        if not attachment_type:
            print(f"[DBG][attachment_render] 当前tab页 '{current_tab_name}' 未找到附件类型")
            return
        
        # 从当前tab页的表格中读取所有参数值
        current_param_values = _read_param_values_from_table(current_table, param_data)
        print(f"[创建新tab] 从当前tab页读取的参数值（按分组）: {current_param_values}")
        
        # 创建新tab页
        try:
            print(f"[创建新tab] 开始创建新tab页，源tab: {current_tab_name}, 附件类型: {attachment_type}")
            new_tab_name = copy_attachment_tab_from_current(product_id, attachment_type, current_tab_name, current_param_values, viewer_instance)
            if new_tab_name:
                print(f"[创建新tab] 新tab页创建成功: {new_tab_name}")
                # 重新渲染所有tab页，并切换到新创建的tab页
                try:
                    render_attachment_param_to_ui(viewer_instance, None, target_tab_name=new_tab_name)
                    print(f"[创建新tab] 重新渲染完成，已切换到新tab页: {new_tab_name}")
                except Exception as e2:
                    print(f"[创建新tab] 重新渲染或切换tab页失败: {e2}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"[创建新tab] 新tab页创建失败，返回None")
        except Exception as e:
            print(f"[创建新tab] 创建新tab页失败: {e}")
            import traceback
            traceback.print_exc()
            try:
                QMessageBox.warning(viewer_instance, "错误", f"创建新tab页失败：{e}")
            except:
                pass
    except Exception as outer_e:
        print(f"[创建新tab] 外层异常: {outer_e}")
        import traceback
        traceback.print_exc()


def _setup_plus_tab_manager(tab_widget, viewer_instance):
    """设置+号tab页管理器"""
    def _add_callback(src_idx, src_name):
        _add_attachment_tab_from_current(viewer_instance, src_idx, src_name)
    
    if not hasattr(viewer_instance, "attachment_plus_mgr"):
        viewer_instance.attachment_plus_mgr = PlusTabManager(tab_widget, _add_callback)
    else:
        viewer_instance.attachment_plus_mgr.on_add_from_src = _add_callback
        viewer_instance.attachment_plus_mgr.refresh_after_model_change()


def _setup_tab_change_handler(tab_widget, viewer_instance):
    """设置tab切换处理器"""
    try:
        tab_widget.currentChanged.disconnect()
    except:
        pass
    tab_widget.currentChanged.connect(lambda index: _on_attachment_tab_changed(viewer_instance, index))


def _save_table_expand_state(table):
    """保存表格的折叠状态"""
    saved_expand_state = {}
    is_first_render = True
    if hasattr(table, "_group_rows") and table._group_rows:
        is_first_render = False
        for title_row, group_data in table._group_rows.items():
            group_name = group_data.get("group_name", "")
            expanded = group_data.get("expanded", False)
            if group_name:
                saved_expand_state[group_name] = expanded
    return saved_expand_state, is_first_render


def _setup_table_basic_properties(table):
    """设置表格基本属性"""
    table._loading = True
    table.clear()
    table.setRowCount(0)
    table.setColumnCount(3)
    table.setHorizontalHeaderLabels(['参数名称', '参数值', '参数单位'])
    
    # 安装事件过滤器
    flt = ComboPopupEventFilter(table)
    table._popup_filter = flt
    table.viewport().installEventFilter(flt)


def _calculate_pipe_code_options(product_id, attachment_type, tab_classification, guankou_codes):
    """计算管口号的可选项"""
    if not (product_id and attachment_type and tab_classification):
        return guankou_codes if guankou_codes else []
    
    # 获取该附件类型对应的所有管口号（总可选项）
    all_pipe_codes = query_pipe_codes_by_attachment_type(product_id, attachment_type)
    
    # 获取其他tab页已选的管口号（已选项，需要排除）
    selected_in_other_tabs = query_selected_pipe_codes_in_other_tabs(product_id, attachment_type, tab_classification)
    
    # 计算当前tab页的可选项 = 总可选项 - 已选项（但包含当前tab页已选的）
    selected_in_other_tabs_set = set(selected_in_other_tabs)
    pipe_code_options = []
    seen = set()
    # 先添加当前tab已选的（确保它们一定在候选列表中）
    for code in guankou_codes:
        if code and code.strip() and code.strip() not in seen:
            code_stripped = code.strip()
            pipe_code_options.append(code_stripped)
            seen.add(code_stripped)
    # 再添加总可选项中未被其他tab占用的
    for code in all_pipe_codes:
        code_stripped = code.strip() if code else ""
        if code_stripped and code_stripped not in seen and code_stripped not in selected_in_other_tabs_set:
            pipe_code_options.append(code_stripped)
            seen.add(code_stripped)
    
    _dbg_print(f"[管口附件] Tab '{tab_classification}' (附件类型: {attachment_type})")
    _dbg_print(f"[管口附件] 总可选项（从产品设计活动表_管口表获取）: {all_pipe_codes}")
    _dbg_print(f"[管口附件] 其他tab已选: {selected_in_other_tabs}")
    _dbg_print(f"[管口附件] 当前tab已选: {guankou_codes}")
    _dbg_print(f"[管口附件] 当前tab可选项: {pipe_code_options}")
    
    return pipe_code_options if pipe_code_options else (guankou_codes if guankou_codes else [])


def _setup_table_header_style(table):
    """设置表头样式"""
    header = table.horizontalHeader()
    for i in range(table.columnCount()):
        header.setSectionResizeMode(i, QHeaderView.Stretch)
    
    header_qss = """
        QHeaderView::section {
            background-color: #F2F2F2;
            color: black;
            font-weight: bold;
            text-align: center;
            padding: 5px;
            border: 1px solid #CCCCCC;
            border-right: 1px solid #CCCCCC;
            border-bottom: 1px solid #CCCCCC;
        }
        QHeaderView::section:first {
            border-left: 1px solid #CCCCCC;
        }
    """
    table.setStyleSheet(header_qss)
    header.setStyleSheet(header_qss)
    header.setDefaultAlignment(Qt.AlignCenter)
    table.horizontalHeader().setFixedHeight(35)


def _toggle_group_expand(table, title_row):
    """切换分组展开/折叠状态"""
    if not hasattr(table, "_group_rows"):
        return
    
    group_data = table._group_rows.get(title_row)
    if not group_data:
        return
    
    is_expanded = group_data.get("expanded", False)
    new_expanded = not is_expanded
    group_data["expanded"] = new_expanded
    
    # 更新标题符号
    title_item = table.item(title_row, 0)
    if title_item:
        symbol = "▾" if new_expanded else "▸"
        title_text = title_item.text()
        title_name = title_text.split(" ", 1)[-1] if " " in title_text else title_text
        title_item.setText(f"{symbol} {title_name}")
        user_data = title_item.data(Qt.UserRole) or {}
        user_data["expanded"] = new_expanded
        title_item.setData(Qt.UserRole, user_data)
    
    # 显示/隐藏参数行
    # 注意：若某行被业务逻辑（如“是否添加覆层=否”）强制隐藏，则分组展开时不能把它放出来
    forced_hidden_rows = getattr(table, "_attachment_forced_hidden_rows", set()) or set()
    param_rows = group_data.get("param_rows", [])
    for param_row in param_rows:
        should_hide = (not new_expanded) or (param_row in forced_hidden_rows)
        table.setRowHidden(param_row, should_hide)


def _find_all_rows_by_param(table, param_col, name: str):
    """查找所有匹配参数名的行号列表"""
    rows = []
    for r in range(table.rowCount()):
        it = table.item(r, param_col)
        if it and it.text().strip() == name:
            rows.append(r)
    return rows


def _find_material_group_rows(table, param_col, type_row):
    """从材料类型行开始，查找对应的材料牌号、材料标准、供货状态行"""
    brand_row = -1
    std_row = -1
    status_row = -1
    
    # 在"材料类型"行之后查找（最多查找后续20行，避免查找太远）
    for r in range(type_row + 1, min(type_row + 20, table.rowCount())):
        it = table.item(r, param_col)
        if not it:
            continue
        
        # 跳过分组标题行
        group_info = it.data(Qt.UserRole)
        if group_info and group_info.get("is_group_title"):
            # 如果遇到下一个分组标题，停止查找
            break
        
        param_name = it.text().strip()
        if param_name == "材料牌号" and brand_row < 0:
            brand_row = r
        elif param_name == "材料标准" and std_row < 0:
            std_row = r
        elif param_name == "供货状态" and status_row < 0:
            status_row = r
        
        # 如果找到了所有三个字段，提前退出
        if brand_row >= 0 and std_row >= 0 and status_row >= 0:
            break
    
    return brand_row, std_row, status_row


def _install_attachment_material_delegate_linkage(table, param_col, value_col, viewer_instance=None):
    """
    为附件表格安装材料四字段联动逻辑
    处理所有找到的材料组（包括多个分组，如"接管法兰配对法兰"、"螺栓(接管法兰)"、"螺母(接管法兰)"等）
    """
    from PyQt5.QtWidgets import QAbstractItemView, QTableWidgetItem
    from PyQt5.QtCore import Qt
    
    table.setEditTriggers(QAbstractItemView.SelectedClicked)
    
    # 找到所有"材料类型"行
    type_rows = _find_all_rows_by_param(table, param_col, "材料类型")
    if not type_rows:
        _dbg_print(f"[DBG][attachment_material_linkage] 未找到'材料类型'行")
        return
    
    _dbg_print(f"[DBG][attachment_material_linkage] 找到 {len(type_rows)} 个材料类型行: {type_rows}")
    
    # 工具函数
    def _ensure_editable(r: int):
        if r < 0:
            return
        if table.cellWidget(r, value_col):
            table.setCellWidget(r, value_col, None)
        it = table.item(r, value_col)
        if it is None:
            it = QTableWidgetItem("")
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, value_col, it)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
    
    def _get(r: int):
        it = table.item(r, value_col)
        return (it.text().strip() if it else "")
    
    def _set(r: int, txt: str):
        if r < 0:
            return
        it = table.item(r, value_col)
        if it is None:
            it = QTableWidgetItem("")
            it.setTextAlignment(Qt.AlignCenter)
            table.setItem(r, value_col, it)
        it.setText(txt or "")
    
    # 为每个材料组安装联动逻辑
    all_target_rows = set()
    for idx, type_row in enumerate(type_rows):
        brand_row, std_row, status_row = _find_material_group_rows(table, param_col, type_row)
        
        if brand_row < 0 or std_row < 0 or status_row < 0:
            _dbg_print(f"[DBG][attachment_material_linkage] 材料组 {idx+1} (行{type_row}) 不完整，跳过")
            continue
        
        _dbg_print(f"[DBG][attachment_material_linkage] 为材料组 {idx+1} 安装联动: 类型={type_row}, 牌号={brand_row}, 标准={std_row}, 状态={status_row}")
        
        # 确保行可编辑
        for r in [type_row, brand_row, std_row, status_row]:
            _ensure_editable(r)
        
        # 获取当前值
        cur_type = _get(type_row)
        cur_brand = _get(brand_row)
        cur_std = _get(std_row)
        
        # 获取选项
        opts_type = (get_filtered_material_options({}) or {}).get("材料类型", []) or []
        opts_brand = (get_filtered_material_options({"材料类型": cur_type} if cur_type else {}) or {}).get("材料牌号", []) or []
        basis_std = {k: v for k, v in {"材料类型": cur_type, "材料牌号": cur_brand}.items() if v}
        opts_std = (get_filtered_material_options(basis_std) or {}).get("材料标准", []) or []
        basis_stat = {k: v for k, v in {"材料类型": cur_type, "材料牌号": cur_brand, "材料标准": cur_std}.items() if v}
        opts_stat = (get_filtered_material_options(basis_stat) or {}).get("供货状态", []) or []
        
        # 创建独立的on_pick回调（使用闭包捕获当前组的行号）
        def make_on_pick(tr, br, sr, st_row, is_first_group):
            def on_pick(field_name: str, new_text: str, row: int, col: int):
                if field_name not in ["材料类型", "材料牌号", "材料标准", "供货状态"]:
                    return
                
                # 更新当前选择的值
                if field_name == "材料类型":
                    _set(tr, new_text)
                elif field_name == "材料牌号":
                    _set(br, new_text)
                elif field_name == "材料标准":
                    _set(sr, new_text)
                elif field_name == "供货状态":
                    _set(st_row, new_text)
                
                # 获取当前值
                if field_name == "材料类型":
                    cur_t = new_text
                    cur_b = _get(br)
                elif field_name == "材料牌号":
                    cur_t = _get(tr)
                    cur_b = new_text
                else:
                    cur_t = _get(tr)
                    cur_b = _get(br)
                
                # 安装delegate的函数
                def _install_row_delegate(field_name, row_idx, options):
                    if row_idx < 0:
                        return
                    seen, opts = set(), []
                    for o in list(options or []):
                        s = (o or "").strip()
                        if s and s not in seen:
                            seen.add(s)
                            opts.append(s)
                    table.setItemDelegateForRow(row_idx, MaterialInstantDelegate(opts, table, field_name, on_pick))
                
                if field_name == "材料类型":
                    # 材料类型改变，清空后续字段并更新选项
                    _set(br, "")
                    _set(sr, "")
                    _set(st_row, "")
                    b = get_filtered_material_options({"材料类型": new_text}) or {}
                    _install_row_delegate("材料牌号", br, b.get("材料牌号", []))
                    # 参照普通元件逻辑：即使材料牌号为空，只要有材料类型，材料标准和供货状态也应该有选项
                    basis_std = {"材料类型": new_text} if new_text else {}
                    std_opts = (get_filtered_material_options(basis_std) or {}).get("材料标准", []) or []
                    stat_opts = (get_filtered_material_options(basis_std) or {}).get("供货状态", []) or []
                    _install_row_delegate("材料标准", sr, std_opts)
                    _install_row_delegate("供货状态", st_row, stat_opts)
                elif field_name == "材料牌号":
                    # 材料牌号改变，清空标准和状态，更新选项
                    _set(sr, "")
                    _set(st_row, "")
                    f = get_filtered_material_options({"材料类型": cur_t, "材料牌号": new_text}) or {}
                    std_opts = f.get("材料标准", []) or []
                    stat_opts = f.get("供货状态", []) or []
                    _install_row_delegate("材料标准", sr, std_opts)
                    _install_row_delegate("供货状态", st_row, stat_opts)
                    if (not _get(sr)) and len(std_opts) == 1:
                        _set(sr, std_opts[0])
                    if (not _get(st_row)) and len(stat_opts) == 1:
                        _set(st_row, stat_opts[0])
                elif field_name == "材料标准":
                    # 材料标准改变，清空状态，更新选项
                    _set(st_row, "")
                    f = get_filtered_material_options({"材料类型": cur_t, "材料牌号": cur_b, "材料标准": new_text}) or {}
                    stat_opts = f.get("供货状态", []) or []
                    _install_row_delegate("供货状态", st_row, stat_opts)
                    if (not _get(st_row)) and len(stat_opts) == 1:
                        _set(st_row, stat_opts[0])
                
                # 应用锻件级别显隐（仅对第一组）
                if is_first_group and field_name == "材料类型":
                    _apply_forging_visibility(table, param_col, value_col, viewer_instance, new_text, write_db=True)
                
                table.viewport().update()
            return on_pick
        
        # 为当前组创建独立的on_pick回调
        is_first_group = (idx == 0)
        on_pick = make_on_pick(type_row, brand_row, std_row, status_row, is_first_group)
        
        # 安装delegate的函数
        def _install_row_delegate(field_name, row_idx, options):
            if row_idx < 0:
                return
            seen, opts = set(), []
            for o in list(options or []):
                s = (o or "").strip()
                if s and s not in seen:
                    seen.add(s)
                    opts.append(s)
            table.setItemDelegateForRow(row_idx, MaterialInstantDelegate(opts, table, field_name, on_pick))
        
        # 初次安装
        _install_row_delegate("材料类型", type_row, opts_type)
        _install_row_delegate("材料牌号", brand_row, opts_brand)
        _install_row_delegate("材料标准", std_row, opts_std)
        _install_row_delegate("供货状态", status_row, opts_stat)
        
        # 锻件级别显隐（仅对第一组）
        if is_first_group:
            _apply_forging_visibility(table, param_col, value_col, viewer_instance, cur_type, write_db=False)
        
        # 记录所有目标行
        all_target_rows.update([type_row, brand_row, std_row, status_row])
    
    _dbg_print(f"[DBG][attachment_material_linkage] 共安装了 {len(type_rows)} 个材料组的联动逻辑")


def _find_first_row_by_param(table, param_col, name: str):
    rows = _find_all_rows_by_param(table, param_col, name)
    return rows[0] if rows else None


def _ensure_editable_value_cell(table, row: int, value_col: int):
    from PyQt5.QtWidgets import QTableWidgetItem
    from PyQt5.QtCore import Qt
    if row is None or row < 0:
        return
    if table.cellWidget(row, value_col):
        table.setCellWidget(row, value_col, None)
    it = table.item(row, value_col)
    if it is None:
        it = QTableWidgetItem("")
        it.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, value_col, it)
    it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)


def _get_cell_text(table, row: int, value_col: int) -> str:
    it = table.item(row, value_col)
    return (it.text().strip() if it else "")


def _set_cell_text(table, row: int, value_col: int, txt: str):
    from PyQt5.QtWidgets import QTableWidgetItem
    from PyQt5.QtCore import Qt
    if row is None or row < 0:
        return
    it = table.item(row, value_col)
    if it is None:
        it = QTableWidgetItem("")
        it.setTextAlignment(Qt.AlignCenter)
        table.setItem(row, value_col, it)
    it.setText(txt or "")


def _attachment_pressure_series_from_product(product_id) -> str:
    """
    从产品设计活动表_管口类型选择表读取公称压力类型，映射到垫片规则主表的「压力体系」：
    - 包含 class / lb / 磅 等 → CLASS
    - 否则默认 PN
    """
    if not product_id:
        return "PN"
    conn = pymysql.connect(**db_config_1)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                """
                SELECT 公称压力类型
                FROM 产品设计活动表_管口类型选择表
                WHERE 产品ID = %s
                LIMIT 1
                """,
                (product_id,),
            )
            row = cur.fetchone() or {}
            pt = (row.get("公称压力类型") or "").strip()
    except Exception as e:
        print(f"[管口附件垫片] 读取公称压力类型失败: {e}")
        pt = ""
    finally:
        try:
            conn.close()
        except Exception:
            pass
    u = pt.upper().replace(" ", "")
    if "CLASS" in u or u == "CL" or "LB" in u or "磅" in pt:
        return "CLASS"
    return "PN"


def _query_flange_gasket_rules(pressure_series: str):
    """
    读取材料库：管口附件接管法兰垫片联动主表
    返回 list[dict]，按规则ID排序。
    """
    conn = pymysql.connect(**db_config_material)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                """
                SELECT 规则ID, 压力体系, 垫片类型, 垫片标准, 垫片材料, 垫片型式
                FROM 管口附件接管法兰垫片联动主表
                WHERE 压力体系 = %s
                ORDER BY 规则ID
                """,
                (pressure_series,),
            )
            return cur.fetchall() or []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _query_flange_gasket_style_options(rule_id: int):
    """
    读取材料库：管口附件接管法兰垫片型式明细表
    优先按「型式序号」排序；若列不存在则回退按明细ID排序。
    """
    conn = pymysql.connect(**db_config_material)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            try:
                cur.execute(
                    """
                    SELECT 垫片型式
                    FROM 管口附件接管法兰垫片型式明细表
                    WHERE 规则ID = %s
                    ORDER BY 型式序号, 明细ID
                    """,
                    (rule_id,),
                )
            except Exception:
                cur.execute(
                    """
                    SELECT 垫片型式
                    FROM 管口附件接管法兰垫片型式明细表
                    WHERE 规则ID = %s
                    ORDER BY 明细ID
                    """,
                    (rule_id,),
                )
            rows = cur.fetchall() or []
            opts = []
            seen = set()
            for r in rows:
                s = (r.get("垫片型式") or "").strip()
                if s and s not in seen:
                    seen.add(s)
                    opts.append(s)
            return opts
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _remap_gasket_type_between_pn_class(cur_type: str, target_series: str) -> str:
    """
    当用户在管口定义切换公称压力类型（PN/CLASS）后，活动库里可能仍保存旧系列的「垫片类型」文本。
    这里按约定把 (PN系列)/(CLASS系列) 后缀互换到目标压力体系对应文本（同族名称）。
    """
    t = (cur_type or "").strip()
    if not t:
        return ""
    ts = (target_series or "").strip().upper()
    if ts not in ("PN", "CLASS"):
        return t
    low = t.lower()
    if ts == "PN":
        if "(class系列)" in low:
            # 大小写不敏感替换一次（常见：Class系列）
            idx = low.find("(class系列)")
            return t[:idx] + "(PN系列)" + t[idx + len("(class系列)"):]
        if low.endswith("(class)"):
            return t[: -len("(class)")] + "(PN系列)"
    else:
        if "(pn系列)" in low:
            idx = low.find("(pn系列)")
            return t[:idx] + "(CLASS系列)" + t[idx + len("(pn系列)"):]
        if low.endswith("(pn)"):
            return t[: -len("(pn)")] + "(CLASS系列)"
    return t


def _install_attachment_flange_gasket_linkage(
    table,
    *,
    product_id,
    attachment_type: str,
    param_col: int = 0,
    value_col: int = 1,
):
    """
    「接管法兰配对法兰」附件：垫片联动
    - 垫片类型：按压力体系(PN/CLASS)从主表取候选
    - 垫片标准：选类型后给出该类型下全部「垫片标准」候选（下拉）
    - 垫片型式：选标准后按对应规则ID读明细表候选；默认型式以主表「垫片型式」为准
    - 垫片材料：普通文本格，不参与下拉联动；仅在选类型/选标准时写入主表推荐值，用户可任意改
    """
    if not product_id:
        return
    if (attachment_type or "").strip() != "接管法兰配对法兰":
        return

    type_name, std_name, mat_name, style_name = "垫片类型", "垫片标准", "垫片材料", "垫片型式"
    type_row = _find_first_row_by_param(table, param_col, type_name)
    std_row = _find_first_row_by_param(table, param_col, std_name)
    mat_row = _find_first_row_by_param(table, param_col, mat_name)
    style_row = _find_first_row_by_param(table, param_col, style_name)
    if type_row is None or std_row is None or mat_row is None or style_row is None:
        return

    pressure_series = _attachment_pressure_series_from_product(product_id)
    rules = _query_flange_gasket_rules(pressure_series)
    if not rules:
        print(f"[管口附件垫片] 未找到压力体系={pressure_series} 的垫片联动规则")
        return

    # 同一垫片类型可能对应多条主表规则（不同标准）——按规则ID顺序分组
    rules_by_type: dict = {}
    for r in rules:
        t = (r.get("垫片类型") or "").strip()
        if not t:
            continue
        rules_by_type.setdefault(t, []).append(r)
    valid_types = set(rules_by_type.keys())
    type_options = []
    seen_t = set()
    for r in rules:
        t = (r.get("垫片类型") or "").strip()
        if t and t not in seen_t:
            seen_t.add(t)
            type_options.append(t)

    for rr in (type_row, std_row, mat_row, style_row):
        _ensure_editable_value_cell(table, rr, value_col)

    def _distinct_standards_for_rules(rs: list) -> list:
        out, seen = [], set()
        for r in rs or []:
            s = (r.get("垫片标准") or "").strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def _rule_for_type_std(type_key: str, std: str) -> dict:
        rs = rules_by_type.get((type_key or "").strip()) or []
        st = (std or "").strip()
        for r in rs:
            if (r.get("垫片标准") or "").strip() == st:
                return r
        return {}

    def _clear_gasket_dependent_fields_and_delegates():
        """垫片类型为空时：标准/型式清空并锁定空下拉；材料清空为文本格。"""
        for rr in (std_row, style_row):
            if rr is None:
                continue
            _set_cell_text(table, rr, value_col, "")
            table.setItemDelegateForRow(rr, ComboDelegate([""], table))
        if mat_row is not None:
            _set_cell_text(table, mat_row, value_col, "")
            table.setItemDelegateForRow(mat_row, None)

    def _ensure_mat_is_plain_text():
        if mat_row is not None:
            table.setItemDelegateForRow(mat_row, None)

    def _install_style_delegate(options):
        opts = []
        seen = set()
        for o in list(options or []):
            s = (o or "").strip()
            if s and s not in seen:
                seen.add(s)
                opts.append(s)

        if not opts:
            table.setItemDelegateForRow(style_row, ComboDelegate([""], table))
            return

        def on_style_pick(_fn, new_text, _r, _c):
            _set_cell_text(table, style_row, value_col, new_text)
            table.viewport().update()

        table.setItemDelegateForRow(
            style_row, MaterialInstantDelegate(opts, table, style_name, on_style_pick)
        )

    def _apply_style_from_rule(rule: dict, *, reset_style_to_default: bool):
        """仅根据规则刷新型式候选与单元格（不碰标准列、不强制改写材料）。"""
        if not rule:
            _set_cell_text(table, style_row, value_col, "")
            table.setItemDelegateForRow(style_row, ComboDelegate([""], table))
            return
        rid = rule.get("规则ID")
        default_style = (rule.get("垫片型式") or "").strip()
        style_opts = []
        if rid is not None and str(rid).strip() != "":
            try:
                style_opts = _query_flange_gasket_style_options(int(rid))
            except Exception:
                style_opts = []
        if not style_opts and default_style:
            style_opts = [default_style]
        if reset_style_to_default and default_style:
            _set_cell_text(table, style_row, value_col, default_style)
        elif reset_style_to_default and not default_style:
            _set_cell_text(table, style_row, value_col, "")
        cur_style = _get_cell_text(table, style_row, value_col)
        if style_opts:
            if not (cur_style or "").strip():
                if default_style and default_style in style_opts:
                    _set_cell_text(table, style_row, value_col, default_style)
            elif cur_style not in style_opts:
                if default_style and default_style in style_opts:
                    _set_cell_text(table, style_row, value_col, default_style)
        _install_style_delegate(style_opts)

    def on_std_pick(_fn, new_text, _r, _c):
        _set_cell_text(table, std_row, value_col, new_text)
        _ensure_mat_is_plain_text()
        st = (new_text or "").strip()
        t = (_get_cell_text(table, type_row, value_col) or "").strip()
        if not t or not st:
            _set_cell_text(table, style_row, value_col, "")
            table.setItemDelegateForRow(style_row, ComboDelegate([""], table))
            table.viewport().update()
            return
        rule = _rule_for_type_std(t, st)
        if not rule:
            _set_cell_text(table, style_row, value_col, "")
            table.setItemDelegateForRow(style_row, ComboDelegate([""], table))
            table.viewport().update()
            return
        _set_cell_text(table, mat_row, value_col, (rule.get("垫片材料") or "").strip())
        _apply_style_from_rule(rule, reset_style_to_default=True)
        table.viewport().update()

    def _install_std_delegate(type_key: str):
        rs = rules_by_type.get((type_key or "").strip()) or []
        opts = _distinct_standards_for_rules(rs)
        std_opts_ui = [""] + opts
        table.setItemDelegateForRow(
            std_row, MaterialInstantDelegate(std_opts_ui, table, std_name, on_std_pick)
        )

    def on_type_pick(_fn, new_text, _r, _c):
        _set_cell_text(table, type_row, value_col, new_text)
        t = (new_text or "").strip()
        _ensure_mat_is_plain_text()
        if not t:
            _clear_gasket_dependent_fields_and_delegates()
            table.viewport().update()
            return
        rs = rules_by_type.get(t) or []
        std_opts = _distinct_standards_for_rules(rs)
        if len(std_opts) == 1:
            only = std_opts[0]
            _set_cell_text(table, std_row, value_col, only)
            rule = _rule_for_type_std(t, only)
            _set_cell_text(table, mat_row, value_col, (rule.get("垫片材料") or "").strip())
            _apply_style_from_rule(rule, reset_style_to_default=True)
        else:
            _set_cell_text(table, std_row, value_col, "")
            _set_cell_text(table, style_row, value_col, "")
            table.setItemDelegateForRow(style_row, ComboDelegate([""], table))
            if rs:
                _set_cell_text(table, mat_row, value_col, (rs[0].get("垫片材料") or "").strip())
            else:
                _set_cell_text(table, mat_row, value_col, "")
        _install_std_delegate(t)
        table.viewport().update()

    # 垫片类型 delegate
    seen_t2, topts = set(), []
    for o in type_options:
        s = (o or "").strip()
        if s and s not in seen_t2:
            seen_t2.add(s)
            topts.append(s)
    type_opts_ui = [""] + topts

    # 若用户在「管口定义」切换了 PN/CLASS，而活动库里仍保存旧系列垫片类型：自动映射到同族 PN/CLASS 文本
    try:
        cur_type0 = _get_cell_text(table, type_row, value_col)
        if cur_type0 and cur_type0 not in valid_types:
            mapped = _remap_gasket_type_between_pn_class(cur_type0, pressure_series)
            if mapped and mapped != cur_type0 and mapped in valid_types:
                _set_cell_text(table, type_row, value_col, mapped)
                _dbg_print(f"[管口附件垫片] 公称压力体系切换后自动映射垫片类型: {cur_type0} -> {mapped}")
            elif mapped and mapped in valid_types and mapped == cur_type0:
                pass
            else:
                _set_cell_text(table, type_row, value_col, "")
                _clear_gasket_dependent_fields_and_delegates()
                _dbg_print(f"[管口附件垫片] 无法将垫片类型映射到压力体系={pressure_series}，已清空: {cur_type0}")
    except Exception as e:
        print(f"[管口附件垫片] 自动映射垫片类型失败: {e}")

    cur_type = _get_cell_text(table, type_row, value_col)
    if not (cur_type or "").strip():
        _clear_gasket_dependent_fields_and_delegates()
        table.setItemDelegateForRow(
            type_row, MaterialInstantDelegate(type_opts_ui, table, type_name, on_type_pick)
        )
    elif cur_type in valid_types:
        _ensure_mat_is_plain_text()
        rs = rules_by_type.get(cur_type) or []
        std_opts = _distinct_standards_for_rules(rs)
        cur_std = (_get_cell_text(table, std_row, value_col) or "").strip()
        if cur_std not in std_opts:
            if len(std_opts) == 1:
                cur_std = std_opts[0]
                _set_cell_text(table, std_row, value_col, cur_std)
            else:
                cur_std = ""
                _set_cell_text(table, std_row, value_col, "")
                _set_cell_text(table, style_row, value_col, "")
        rule = _rule_for_type_std(cur_type, cur_std) if cur_std else {}
        _install_std_delegate(cur_type)
        if rule:
            _apply_style_from_rule(rule, reset_style_to_default=False)
        else:
            _set_cell_text(table, style_row, value_col, "")
            table.setItemDelegateForRow(style_row, ComboDelegate([""], table))
        table.setItemDelegateForRow(
            type_row, MaterialInstantDelegate(type_opts_ui, table, type_name, on_type_pick)
        )
    else:
        _set_cell_text(table, type_row, value_col, "")
        _clear_gasket_dependent_fields_and_delegates()
        table.setItemDelegateForRow(
            type_row, MaterialInstantDelegate(type_opts_ui, table, type_name, on_type_pick)
        )


def _apply_cladding_type_logic_for_attachment_table(
    table,
    param_col: int,
    value_col: int,
    *,
    has_covering: bool,
    type_value: str,
    level_param: str,
    status_param: str,
    process_param: str,
):
    """
    参照管口元件覆层逻辑：
      - 覆层材料类型=焊材：隐藏「材料级别」「使用状态」，并把「成型工艺」限定为堆焊且赋值
      - 覆层材料类型=板材/钢板：显示上述两项，且「成型工艺」候选为爆炸焊接/轧制复合，默认爆炸焊接
      - 其它：恢复可见，不强制工艺
    """
    v = (type_value or "").strip()
    level_row = _find_first_row_by_param(table, param_col, level_param)
    status_row = _find_first_row_by_param(table, param_col, status_param)
    process_row = _find_first_row_by_param(table, param_col, process_param)

    # 覆层开关优先级最高：未启用覆层时，不在这里“强行展开/显示”任何行
    if not has_covering:
        return

    if v == "焊材":
        if level_row is not None:
            table.setRowHidden(level_row, True)
        if status_row is not None:
            table.setRowHidden(status_row, True)
        if process_row is not None:
            table.setRowHidden(process_row, False)
            _ensure_editable_value_cell(table, process_row, value_col)
            table.setItemDelegateForRow(process_row, ComboDelegate(["堆焊"], table))
            _set_cell_text(table, process_row, value_col, "堆焊")
    elif v in ("板材", "钢板"):
        if level_row is not None:
            table.setRowHidden(level_row, False)
        if status_row is not None:
            table.setRowHidden(status_row, False)
        if process_row is not None:
            table.setRowHidden(process_row, False)
            _ensure_editable_value_cell(table, process_row, value_col)
            table.setItemDelegateForRow(process_row, ComboDelegate(["爆炸焊接", "轧制复合"], table))
            cur = _get_cell_text(table, process_row, value_col)
            if cur not in ("爆炸焊接", "轧制复合"):
                _set_cell_text(table, process_row, value_col, "爆炸焊接")
    else:
        if level_row is not None:
            table.setRowHidden(level_row, False)
        if status_row is not None:
            table.setRowHidden(status_row, False)
        if process_row is not None:
            table.setRowHidden(process_row, False)


def _install_attachment_flange_cladding_linkage(table, param_col: int, value_col: int, viewer_instance=None):
    """
    在“接管法兰配对法兰”附件页中，为“接管法兰覆层”相关字段安装：
      - 是否添加覆层 → 显示/隐藏覆层字段并在隐藏时清空值
      - 覆层材料类型 → 覆层材料牌号/材料标准联动（同材料四字段的过滤逻辑），并驱动成型工艺/级别/使用状态显隐
      - 覆层厚度(mm) → >=0 的数值代理

    注意：管口附件页的写库在“确定”按钮触发，这里只做 UI 级联与候选项联动。
    """
    toggle_name = "接管法兰是否添加覆层"
    type_name = "接管法兰覆层材料类型"
    brand_name = "接管法兰覆层材料牌号"
    std_name = "接管法兰覆层材料标准"
    level_name = "接管法兰覆层材料级别"
    process_name = "接管法兰覆层成型工艺"
    status_name = "接管法兰覆层使用状态"
    thickness_name = "接管法兰覆层厚度(mm)"

    toggle_row = _find_first_row_by_param(table, param_col, toggle_name)
    type_row = _find_first_row_by_param(table, param_col, type_name)
    brand_row = _find_first_row_by_param(table, param_col, brand_name)
    std_row = _find_first_row_by_param(table, param_col, std_name)
    thickness_row = _find_first_row_by_param(table, param_col, thickness_name)

    # 如果这套字段在当前tab不存在，直接跳过
    if toggle_row is None and type_row is None:
        return

    dependent_names = [
        type_name,
        brand_name,
        "接管法兰覆层材料级别",
        std_name,
        process_name,
        status_name,
        thickness_name,
        "接管法兰覆层材料类型",
    ]

    # 统一找出依赖字段行
    dep_rows = []
    for n in dict.fromkeys(dependent_names):
        r = _find_first_row_by_param(table, param_col, n)
        if r is not None:
            dep_rows.append(r)

    def _mark_forced_hidden(rows, hidden: bool):
        """记录/清理被覆层逻辑强制隐藏的行，避免分组展开时被错误展开。"""
        s = getattr(table, "_attachment_forced_hidden_rows", None)
        if s is None:
            s = set()
            setattr(table, "_attachment_forced_hidden_rows", s)
        for rr in rows or []:
            if rr is None:
                continue
            if hidden:
                s.add(rr)
            else:
                s.discard(rr)

    # --- 1) 覆层开关（是/否） ---
    if toggle_row is not None:
        _ensure_editable_value_cell(table, toggle_row, value_col)

        def _on_cover_toggle(_field, new_text, _r, _c):
            v = (new_text or "").strip()
            has_cover = (v == "是")
            # 显隐 + 隐藏时清空值（不写库，等“确定”写回）
            for rr in dep_rows:
                table.setRowHidden(rr, not has_cover)
                if not has_cover:
                    _ensure_editable_value_cell(table, rr, value_col)
                    _set_cell_text(table, rr, value_col, "")
            # 覆层总开关=否时，所有依赖行都强制隐藏；=是时先全部解除，后续再按材料类型二次控制
            _mark_forced_hidden(dep_rows, not has_cover)
            # 打开覆层时，按当前“覆层材料类型”立即应用一次工艺/显隐规则
            if has_cover and type_row is not None:
                cur_type = _get_cell_text(table, type_row, value_col)
                _apply_cladding_type_logic_for_attachment_table(
                    table,
                    param_col,
                    value_col,
                    has_covering=True,
                    type_value=cur_type,
                    level_param=level_name,
                    status_param=status_name,
                    process_param=process_name,
                )
                # 材料类型=焊材时，级别/使用状态仍需保持隐藏，避免被分组展开放出来
                level_row = _find_first_row_by_param(table, param_col, level_name)
                status_row = _find_first_row_by_param(table, param_col, status_name)
                type_hides = []
                if (cur_type or "").strip() == "焊材":
                    type_hides = [level_row, status_row]
                _mark_forced_hidden([level_row, status_row], False)
                _mark_forced_hidden(type_hides, True)
            table.viewport().update()

        table.setItemDelegateForRow(
            toggle_row,
            MaterialInstantDelegate(["是", "否"], table, toggle_name, _on_cover_toggle),
        )

        # 初始化一次显隐（按当前值）
        try:
            cur = _get_cell_text(table, toggle_row, value_col)
            _on_cover_toggle(toggle_name, cur, toggle_row, value_col)
        except Exception:
            pass

    # --- 2) 覆层材料类型 -> 牌号/标准联动 + 工艺/级别/使用状态 ---
    if type_row is not None:
        for rr in [type_row, brand_row, std_row]:
            if rr is not None:
                _ensure_editable_value_cell(table, rr, value_col)

        def _install_delegate_for_row(row_idx, field_name, options, on_pick):
            if row_idx is None:
                return
            seen, opts = set(), []
            for o in list(options or []):
                s = (o or "").strip()
                if s and s not in seen:
                    seen.add(s)
                    opts.append(s)
            table.setItemDelegateForRow(row_idx, MaterialInstantDelegate(opts, table, field_name, on_pick))

        def _opts_for_brand(tval: str):
            return (get_filtered_material_options({"材料类型": tval} if tval else {}) or {}).get("材料牌号", []) or []

        def _opts_for_std(tval: str, bval: str):
            basis = {k: v for k, v in {"材料类型": tval, "材料牌号": bval}.items() if v}
            return (get_filtered_material_options(basis) or {}).get("材料标准", []) or []

        def _on_pick_cladding(field_name: str, new_text: str, row: int, col: int):
            # 覆层是否开启（用于门控后续“展开/强制值”逻辑）
            has_covering = True
            if toggle_row is not None:
                has_covering = (_get_cell_text(table, toggle_row, value_col) == "是")

            # 写回当前格
            if field_name == type_name:
                _set_cell_text(table, type_row, value_col, new_text)
                # 类型变更：清空牌号/标准并刷新候选
                if brand_row is not None:
                    _set_cell_text(table, brand_row, value_col, "")
                if std_row is not None:
                    _set_cell_text(table, std_row, value_col, "")
                b_opts = _opts_for_brand(new_text)
                _install_delegate_for_row(brand_row, brand_name, b_opts, _on_pick_cladding)
                std_opts = _opts_for_std(new_text, "")
                _install_delegate_for_row(std_row, std_name, std_opts, _on_pick_cladding)

                # 覆层类型逻辑（工艺候选 & 级别/使用状态显隐）
                _apply_cladding_type_logic_for_attachment_table(
                    table,
                    param_col,
                    value_col,
                    has_covering=has_covering,
                    type_value=new_text,
                    level_param=level_name,
                    status_param=status_name,
                    process_param=process_name,
                )
                # 材料类型导致的额外隐藏（焊材隐藏级别/使用状态）也要参与“强制隐藏”集合
                level_row = _find_first_row_by_param(table, param_col, level_name)
                status_row = _find_first_row_by_param(table, param_col, status_name)
                _mark_forced_hidden([level_row, status_row], False)
                if has_covering and (new_text or "").strip() == "焊材":
                    _mark_forced_hidden([level_row, status_row], True)
            elif field_name == brand_name:
                if brand_row is not None:
                    _set_cell_text(table, brand_row, value_col, new_text)
                # 牌号变更：清空标准并刷新
                if std_row is not None:
                    _set_cell_text(table, std_row, value_col, "")
                    tval = _get_cell_text(table, type_row, value_col)
                    std_opts = _opts_for_std(tval, new_text)
                    _install_delegate_for_row(std_row, std_name, std_opts, _on_pick_cladding)
            elif field_name == std_name:
                if std_row is not None:
                    _set_cell_text(table, std_row, value_col, new_text)

            table.viewport().update()

        # 初次安装 delegates
        cur_t = _get_cell_text(table, type_row, value_col)
        cur_b = _get_cell_text(table, brand_row, value_col) if brand_row is not None else ""

        type_opts = get_options_for_param(type_name) or (get_filtered_material_options({}) or {}).get("材料类型", []) or []
        _install_delegate_for_row(type_row, type_name, type_opts, _on_pick_cladding)
        _install_delegate_for_row(brand_row, brand_name, _opts_for_brand(cur_t), _on_pick_cladding)
        _install_delegate_for_row(std_row, std_name, _opts_for_std(cur_t, cur_b), _on_pick_cladding)

        # 初始应用一次工艺/显隐
        try:
            has_covering_init = True
            if toggle_row is not None:
                has_covering_init = (_get_cell_text(table, toggle_row, value_col) == "是")
            _apply_cladding_type_logic_for_attachment_table(
                table,
                param_col,
                value_col,
                has_covering=has_covering_init,
                type_value=cur_t,
                level_param=level_name,
                status_param=status_name,
                process_param=process_name,
            )
            # 初始化时同步一次“强制隐藏”集合，避免首次点分组标题时把覆层控制隐藏项展开
            level_row = _find_first_row_by_param(table, param_col, level_name)
            status_row = _find_first_row_by_param(table, param_col, status_name)
            if not has_covering_init:
                _mark_forced_hidden(dep_rows, True)
            else:
                _mark_forced_hidden(dep_rows, False)
                if (cur_t or "").strip() == "焊材":
                    _mark_forced_hidden([level_row, status_row], True)
        except Exception:
            pass

    # --- 3) 覆层厚度(mm) 数值代理（>=0） ---
    if thickness_row is not None:
        _ensure_editable_value_cell(table, thickness_row, value_col)
        table.setItemDelegateForRow(thickness_row, NonNegativeDoubleDelegate(bottom=0.0, parent=table))


def _apply_attachment_param_combobox(table, param_col, value_col):
    """
    为管口附件参数绑定下拉框（从数据库参数表获取选项）
    模仿普通元件的 apply_paramname_combobox 函数
    """
    from modules.cailiaodingyi.funcs.funcs_pdf_input import get_all_param_name
    
    # 材料四字段和管口号已经处理，跳过
    material_fields = {"材料类型", "材料牌号", "材料标准", "供货状态"}
    # 垫片相关参数不使用参数表的下拉框选项绑定（这些参数可能有特殊的联动逻辑或其他处理方式）
    gasket_params = {"垫片类型", "垫片材料", "垫片标准", "垫片型式"}
    excluded_params = {"管口号"} | material_fields | gasket_params
    
    # 获取所有参数名（用于判断参数是否在数据库中）
    try:
        param_names = set(get_all_param_name() or [])
    except Exception:
        param_names = set()
    
    # 工具函数：确保item可编辑
    def ensure_editable_item(r, c, txt=""):
        it = table.item(r, c)
        if it is None:
            it = QTableWidgetItem(txt)
            table.setItem(r, c, it)
        it.setTextAlignment(Qt.AlignCenter)
        it.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
        return it
    
    for row in range(table.rowCount()):
        try:
            param_item = table.item(row, param_col)
            if not param_item:
                continue
            
            # 跳过分组标题行
            group_info = param_item.data(Qt.UserRole)
            if group_info and group_info.get("is_group_title"):
                continue
            
            param_name = param_item.text().strip()
            if not param_name or param_name in excluded_params:
                continue
            
            # 如果已经有delegate（材料四字段、管口号等），跳过
            if table.itemDelegateForRow(row):
                continue
            
            # 如果已经有cellWidget，跳过
            if table.cellWidget(row, value_col):
                continue
            
            # 获取当前值
            value_item = table.item(row, value_col)
            current_value = value_item.text().strip() if value_item else ""
            
            # 从数据库获取选项（模仿 apply_paramname_combobox 的逻辑）
            options = []
            try:
                if param_name in param_names:
                    options = get_options_for_param(param_name) or []
            except Exception:
                options = []
            
            # 确保item可编辑
            ensure_editable_item(row, value_col, current_value)
            
            # 去重去空
            options = [o for o in dict.fromkeys([str(x).strip() for x in options]) if o != ""]
            
            # 如果有选项，设置ComboDelegate；否则设置为None
            if options:
                table.setItemDelegateForRow(row, ComboDelegate(options, table))
                _dbg_print(f"[DBG][attachment_combobox] 为参数 '{param_name}' 绑定下拉框，选项数: {len(options)}")
            else:
                table.setItemDelegateForRow(row, None)
        except Exception as e:
            print(f"[DBG][attachment_combobox] 处理第{row}行参数失败: {e}")
            import traceback
            traceback.print_exc()


def _install_table_event_handlers(table):
    """安装表格事件处理器"""
    def _on_item_changed(item: QTableWidgetItem):
        try:
            if getattr(table, "_loading", False):
                return
            if item.column() == 0:
                return
            
            r = item.row()
            if r < 0 or r >= table.rowCount():
                return
            
            pitem = table.item(r, 0)
            if not pitem:
                return
            
            # 以前这里有大量调试打印，容易刷屏；保持静默，仅做未来扩展
        except Exception as e:
            print(f"[管口附件-参数修改] 处理item变化事件失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _select_row_first(r, c):
        table.selectRow(r)
    
    def _edit_on_click(r, c):
        title_item = table.item(r, 0)
        if title_item:
            group_info = title_item.data(Qt.UserRole)
            if group_info and group_info.get("is_group_title"):
                _toggle_group_expand(table, r)
                return
        
        idx = table.model().index(r, c)
        it = table.item(r, c)
        if idx.isValid() and it and (it.flags() & Qt.ItemIsEditable):
            table.setCurrentIndex(idx)
            table.edit(idx)
    
    try:
        table.itemChanged.disconnect()
    except Exception:
        pass
    table.itemChanged.connect(_on_item_changed)
    
    try:
        table.cellPressed.disconnect()
    except Exception:
        pass
    table.cellPressed.connect(_select_row_first)
    
    try:
        table.cellClicked.disconnect()
    except Exception:
        pass
    table.cellClicked.connect(_edit_on_click)
    
    _set_table_tooltips(table)
    _install_tooltip_updater(table)


def _render_attachment_table_data(table, attachment_type, guankou_codes, param_data_list, viewer_instance=None, tab_classification=None, product_id=None):
    """
    渲染管口附件数据到表格
    :param table: 表格控件
    :param attachment_type: 附件类型
    :param guankou_codes: 该附件类型对应的管口号列表（当前tab页已选的）
    :param param_data_list: 参数数据列表（从数据库加载的完整数据）
    :param viewer_instance: 视图实例
    :param tab_classification: Tab分类名称（用于计算可选项）
    :param product_id: 产品ID（用于查询）
    """
    # 保存折叠状态
    saved_expand_state, is_first_render = _save_table_expand_state(table)
    
    # 设置表格基本属性
    _setup_table_basic_properties(table)
    
    # 获取材料下拉框选项
    material_options = {}
    try:
        # 适配 get_filtered_material_options 的新签名，未选择时传 None
        material_options = get_filtered_material_options(None)
    except Exception as e:
        _dbg_print(f"[DBG][attachment_render] 获取材料选项失败: {e}")
    
    # 计算管口号的可选项
    pipe_code_options = _calculate_pipe_code_options(product_id, attachment_type, tab_classification, guankou_codes)
    table.setProperty("gk_code_candidates", pipe_code_options)
    _dbg_print(f"[管口附件] 已设置table.property('gk_code_candidates'): {pipe_code_options}")
    
    # 根据附件类型渲染不同的参数结构
    folding_structure = get_attachment_folding_structure(attachment_type)
    if folding_structure:
        _render_flange_pairing_params(table, guankou_codes, param_data_list, material_options, viewer_instance, attachment_type, saved_expand_state, is_first_render, pipe_code_options)
    else:
        _render_simple_attachment_params(table, guankou_codes, param_data_list, material_options, viewer_instance, pipe_code_options)
    
    # 安装材料四字段的联动逻辑（处理所有材料组，包括多个分组）
    try:
        _install_attachment_material_delegate_linkage(table, param_col=0, value_col=1, viewer_instance=viewer_instance)
        _dbg_print(f"[DBG][attachment_render] 材料联动逻辑安装完成")
    except Exception as e:
        print(f"[DBG][attachment_render] 安装材料联动逻辑失败: {e}")
        import traceback
        traceback.print_exc()

    # 安装“接管法兰覆层”相关字段的联动逻辑（仅在存在这些行时生效）
    try:
        _install_attachment_flange_cladding_linkage(table, param_col=0, value_col=1, viewer_instance=viewer_instance)
        _dbg_print(f"[DBG][attachment_render] 接管法兰覆层联动逻辑安装完成")
    except Exception as e:
        print(f"[DBG][attachment_render] 安装接管法兰覆层联动逻辑失败: {e}")
        import traceback
        traceback.print_exc()

    # 安装「接管法兰垫片」联动：类型→标准→型式下拉；垫片材料为文本推荐（材料库新表）
    try:
        _install_attachment_flange_gasket_linkage(
            table,
            product_id=product_id,
            attachment_type=attachment_type,
            param_col=0,
            value_col=1,
        )
        _dbg_print(f"[DBG][attachment_render] 接管法兰垫片联动逻辑安装完成")
    except Exception as e:
        print(f"[DBG][attachment_render] 安装接管法兰垫片联动逻辑失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 为其他参数绑定下拉框（从数据库获取选项）
    try:
        _apply_attachment_param_combobox(table, param_col=0, value_col=1)
        _dbg_print(f"[DBG][attachment_render] 参数下拉框绑定完成")
    except Exception as e:
        print(f"[DBG][attachment_render] 绑定参数下拉框失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 清除加载标志
    table._loading = False
    
    # 设置表头样式
    _setup_table_header_style(table)
    
    # 安装事件处理器
    _install_table_event_handlers(table)


def _render_flange_pairing_params(table, guankou_codes, param_data_list, material_options, viewer_instance, attachment_type="接管法兰配对法兰", saved_expand_state=None, is_first_render=True, pipe_code_options=None):
    """
    渲染"接管法兰配对法兰"的参数（带折叠分组）
    从数据库加载的数据中解析标题分组和参数项
    :param attachment_type: 附件类型，用于从管口附件折叠表查询小标题信息
    :param saved_expand_state: 保存的折叠状态字典 {group_name: expanded}
    :param is_first_render: 是否是第一次渲染
    """
    # 存储分组信息到表格属性中
    if not hasattr(table, "_group_rows"):
        table._group_rows = {}  # {title_row: {"group_name": str, "param_rows": [row1, row2, ...], "expanded": bool}}
    
    # 如果没有传递保存的状态，初始化为空字典
    if saved_expand_state is None:
        saved_expand_state = {}
    
    # 首先添加"管口号"行（如果存在）
    pipe_code_param = None
    for param in param_data_list:
        if param.get('参数名称') == '管口号':
            pipe_code_param = param
            break
    
    if pipe_code_param:
        pipe_codes_str = pipe_code_param.get('参数数值', '')
        pipe_codes_list = [code.strip() for code in pipe_codes_str.split('、') if code.strip()] if pipe_codes_str else []
        # 使用计算好的可选项（如果提供了），否则使用当前已选的管口号
        options_for_combo = pipe_code_options if pipe_code_options is not None else pipe_codes_list
        _add_param_row(table, "管口号", pipe_codes_list, {"管口号": pipe_codes_str}, material_options, is_combo=True, pipe_code_options=options_for_combo)
    
    # 按标题分组组织数据
    groups_data = defaultdict(list)
    for row in param_data_list:
        # 跳过"管口号"参数，已经单独处理
        if row.get('参数名称') == '管口号':
            continue
        title_group = row.get('标题分组', '').strip() or 'default'
        groups_data[title_group].append(row)
    
    # 从管口附件折叠表获取小标题信息（包括顺序和是否默认展开）
    folding_structure = get_attachment_folding_structure(attachment_type)
    
    if not folding_structure:
        _dbg_print(f"[DBG][attachment_render] 附件类型 '{attachment_type}' 在管口附件折叠表中没有找到小标题信息，跳过渲染")
        return
    
    # 按照折叠表中的排序顺序渲染每个分组
    for folding_info in folding_structure:
        group_name = folding_info.get('小标题', '').strip()
        if not group_name or group_name not in groups_data:
            continue  # 如果数据库中没有该分组的数据，跳过
        
        group_rows = groups_data[group_name]
        
        # 添加分组标题行
        title_row = table.rowCount()
        table.insertRow(title_row)
        
        # 决定是否展开：
        # - 如果是第一次渲染，使用默认状态（从管口附件折叠表获取）
        # - 如果不是第一次渲染，使用保存的状态（如果存在），否则使用默认状态
        if is_first_render:
            # 第一次渲染，使用默认状态
            is_default_expanded = folding_info.get('是否默认展开', '0') == '1'
        else:
            # 不是第一次渲染，优先使用保存的状态
            if group_name in saved_expand_state:
                is_default_expanded = saved_expand_state[group_name]
            else:
                # 如果保存的状态中没有该分组（可能是新增的分组），使用默认状态
                is_default_expanded = folding_info.get('是否默认展开', '0') == '1'
        
        symbol = "▾" if is_default_expanded else "▸"  # 使用更小的三角形符号
        title_item = QTableWidgetItem(f"{symbol} {group_name}")
        title_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        # 设置灰色背景（移除加粗字体）
        title_item.setBackground(QColor("#E0E0E0"))  # 浅灰色背景
        title_item.setData(Qt.UserRole, {"is_group_title": True, "group_name": group_name, "expanded": is_default_expanded})
        table.setItem(title_row, 0, title_item)
        
        # 占位（同样设置灰色背景）
        placeholder_item_1 = QTableWidgetItem()
        placeholder_item_1.setBackground(QColor("#E0E0E0"))
        placeholder_item_1.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table.setItem(title_row, 1, placeholder_item_1)
        
        placeholder_item_2 = QTableWidgetItem()
        placeholder_item_2.setBackground(QColor("#E0E0E0"))
        placeholder_item_2.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        table.setItem(title_row, 2, placeholder_item_2)
        
        # 记录参数行
        param_rows = []
        
        # 添加参数行
        for param_row_data in group_rows:
            param_row = table.rowCount()
            param_name = param_row_data.get('参数名称', '')
            param_value = param_row_data.get('参数数值', '')
            param_unit = param_row_data.get('参数单位', '')
            
            # 构建参数数据字典
            param_dict = {param_name: param_value}
            if param_unit:
                param_dict[f"{param_name}_单位"] = param_unit
            
            _add_param_row(table, param_name, guankou_codes, param_dict, material_options, 
                         material_fields=["材料类型", "材料牌号", "材料标准", "供货状态"])
            param_rows.append(param_row)
            
            # 如果分组折叠，隐藏参数行
            if not is_default_expanded:
                table.setRowHidden(param_row, True)
        
        # 存储分组信息
        table._group_rows[title_row] = {
            "group_name": group_name,
            "param_rows": param_rows,
            "expanded": is_default_expanded
        }


def _render_simple_attachment_params(table, guankou_codes, param_data_list, material_options, viewer_instance, pipe_code_options=None):
    """
    渲染简单附件类型的参数（接管拉筋、防冲挡板、破涡器）
    从数据库加载的数据中解析参数项
    """
    # 首先添加"管口号"行（如果存在）
    pipe_code_param = None
    for param in param_data_list:
        if param.get('参数名称') == '管口号':
            pipe_code_param = param
            break
    
    if pipe_code_param:
        pipe_codes_str = pipe_code_param.get('参数数值', '')
        pipe_codes_list = [code.strip() for code in pipe_codes_str.split('、') if code.strip()] if pipe_codes_str else []
        # 使用计算好的可选项（如果提供了），否则使用当前已选的管口号
        options_for_combo = pipe_code_options if pipe_code_options is not None else pipe_codes_list
        _add_param_row(table, "管口号", pipe_codes_list, {"管口号": pipe_codes_str}, material_options, is_combo=True, pipe_code_options=options_for_combo)
    
    # 过滤出参数项（排除"管口号"，已经单独处理）
    param_rows_data = [row for row in param_data_list if row.get('参数名称') != '管口号']
    
    # 渲染参数行
    for param_row_data in param_rows_data:
        param_name = param_row_data.get('参数名称', '')
        param_value = param_row_data.get('参数数值', '')
        param_unit = param_row_data.get('参数单位', '')
        
        # 构建参数数据字典
        param_dict = {param_name: param_value}
        if param_unit:
            param_dict[f"{param_name}_单位"] = param_unit
        
        _add_param_row(table, param_name, guankou_codes, param_dict, material_options,
                     material_fields=["材料类型", "材料牌号", "材料标准", "供货状态"])


def _add_param_row(table, param_name, guankou_codes, param_data, material_options, 
                   is_combo=False, material_fields=None, pipe_code_options=None):
    """
    添加一个参数行
    :param table: 表格
    :param param_name: 参数名称
    :param guankou_codes: 管口号列表
    :param param_data: 参数数据字典
    :param material_options: 材料选项字典
    :param is_combo: 是否为下拉框
    :param material_fields: 材料字段列表（用于材料联动）
    """
    row = table.rowCount()
    table.insertRow(row)
    
    # 参数名称列
    name_item = QTableWidgetItem(param_name)
    name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    name_item.setTextAlignment(Qt.AlignCenter)  # 居中显示，模仿普通元件
    table.setItem(row, 0, name_item)
    
    # 参数值列
    value_item = QTableWidgetItem("")
    value_item.setTextAlignment(Qt.AlignCenter)
    value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
    
    # 从param_data中获取值（如果有多个管口，可能需要特殊处理）
    if param_name == "管口号":
        # 管口号显示所有对应的管口号，用顿号分隔；允许使用多选下拉进行修改
        value_item.setText("、".join(guankou_codes))
        value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsEditable)
    else:
        # 其他参数从param_data中获取
        value = param_data.get(param_name, "")
        value_item.setText(str(value) if value else "")
    
    table.setItem(row, 1, value_item)
    
    # 参数单位列（从param_data中获取）
    unit_value = param_data.get(f"{param_name}_单位", "") or param_data.get("参数单位", "")
    unit_item = QTableWidgetItem(str(unit_value) if unit_value else "")
    unit_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
    table.setItem(row, 2, unit_item)
    
    # 设置下拉框代理
    if is_combo and param_name == "管口号":
        # 优先使用传入的可选项，如果没有则从表格属性中获取，最后使用当前已选的管口号
        if pipe_code_options is not None:
            options = pipe_code_options
        else:
            # 尝试从表格属性中获取（在渲染时设置的）
            options = table.property("gk_code_candidates")
            if not options:
                options = guankou_codes
        
        # 确保options是列表类型
        if not isinstance(options, list):
            options = list(options) if options else []
        
        if options:
            _dbg_print(f"[管口附件] _add_param_row: 为管口号行设置delegate，可选项: {options}")
            # 使用计算好的可选项（总可选项 - 已选项，但包含当前tab页已选的）
            # 注意：CheckComboDelegate会优先从table.property('gk_code_candidates')读取，所以这里传入的options作为兜底
            table.setItemDelegateForRow(row, CheckComboDelegate(options, table, enable_select_all=True))
    # 注意：材料四字段（材料类型、材料牌号、材料标准、供货状态）的代理
    # 将在渲染完成后通过 install_material_delegate_linkage 统一安装，这里不单独设置


def on_clear_attachment_param_update(viewer_instance):
    """
    清空管口附件参数数值列，写库并刷新界面（不清空"管口号"和参数名称、参数单位）
    """
    # 1) 询问确认
    tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
    if tab_widget is None:
        return
    
    cur_idx = tab_widget.currentIndex()
    if cur_idx < 0:
        return
    
    tab_name = tab_widget.tabText(cur_idx).strip()
    table = viewer_instance.dynamic_attachment_param_tabs.get(tab_name)
    if table is None:
        return
    
    box = QMessageBox(QMessageBox.Information, "清空确认",
                      "清空后不可撤销，是否继续？",
                      QMessageBox.NoButton, table)
    btn_ok = box.addButton("确认", QMessageBox.YesRole)
    btn_cancel = box.addButton("取消", QMessageBox.NoRole)
    box.setDefaultButton(btn_cancel)
    box.exec_()
    if box.clickedButton() is not btn_ok:
        print("[清空] 用户取消操作")
        return
    
    # 2) UI 清空（只清空参数数值列，保留参数名称和参数单位）
    product_id = getattr(viewer_instance, "product_id", None)
    if not product_id:
        print("[清空] 未找到product_id")
        return
    
    table.blockSignals(True)
    try:
        for r in range(table.rowCount()):
            # 跳过分组标题行
            name_item = table.item(r, 0)
            if not name_item:
                continue
            
            # 检查是否是分组标题行
            group_info = name_item.data(Qt.UserRole)
            if group_info and group_info.get("is_group_title"):
                continue
            
            param_name = name_item.text().strip()
            if not param_name or param_name == "管口号":
                # 跳过"管口号"参数，不清空
                continue
            
            # 清空参数数值列（列1）
            value_item = table.item(r, 1)
            if value_item:
                value_item.setText("")
            else:
                table.setItem(r, 1, QTableWidgetItem(""))
            
            # 如果有下拉框控件，也清空
            widget = table.cellWidget(r, 1)
            if widget:
                if isinstance(widget, QComboBox):
                    widget.setCurrentIndex(0)
                elif hasattr(widget, 'clear'):
                    widget.clear()
    finally:
        table.blockSignals(False)
    
    # 3) 写库：更新参数数值为空
    try:
        connection = pymysql.connect(**db_config_1)
        try:
            with connection.cursor() as cursor:
                # 获取当前tab的所有参数记录
                cursor.execute("""
                    SELECT 参数ID, 参数名称, 标题分组
                    FROM 产品设计活动表_管口附件附加参数表
                    WHERE 产品ID = %s AND Tab分类 = %s
                """, (product_id, tab_name))
                records = cursor.fetchall()
                
                # 更新参数数值为空（保留参数名称和参数单位）
                for record in records:
                    cursor.execute("""
                        UPDATE 产品设计活动表_管口附件附加参数表
                        SET 参数数值 = ''
                        WHERE 产品ID = %s AND Tab分类 = %s AND 参数ID = %s
                    """, (product_id, tab_name, record[0]))
                
                connection.commit()
                print(f"[清空] 已清空 {len(records)} 条参数记录的数值")
        finally:
            connection.close()
    except Exception as e:
        print(f"[数据库错误] 清空管口附件参数失败：{e}")
        import traceback
        traceback.print_exc()
    
    # 4) 刷新当前Tab页的UI（重新加载数据，确保下拉框代理正确绑定）
    try:
        # 重新加载参数数据
        param_data = load_attachment_param_data(product_id, tab_name)

        if not param_data:
            print(f"[清空] 未找到 {tab_name} 的参数数据，跳过刷新")
            return

        # 从参数数据中获取附件类型（attachment_type），而不是使用tab_name
        attachment_type = param_data[0].get('附件类型', '').strip()
        if not attachment_type:
            print(f"[清空] Tab分类 '{tab_name}' 未找到附件类型，跳过刷新")
            return

        # 从参数数据中解析当前tab的管口号（使用'、'分隔）
        pipe_codes_str = ""
        for param in param_data:
            if param.get('参数名称') == '管口号':
                pipe_codes_str = param.get('参数数值', '')
                break
        guankou_codes = [code.strip() for code in pipe_codes_str.split('、') if code.strip()] if pipe_codes_str else []
        
        # 重新渲染表格（这样会重新绑定所有代理，包括管口号的下拉框）
        _render_attachment_table_data(
            table,
            attachment_type,
            guankou_codes,
            param_data,
            viewer_instance,
            tab_classification=tab_name,
            product_id=product_id
        )
        
        print(f"[清空] 已刷新 {tab_name} 的UI (附件类型: {attachment_type})")
    except Exception as e:
        print(f"[清空] 刷新UI失败：{e}")
        import traceback
        traceback.print_exc()
    
    # 5) 提示栏：清空成功
    _set_tip(viewer_instance, "清空成功", success=True)


def on_confirm_attachment_param_update(viewer_instance):
    """
    确定按钮：将管口附件参数表格中的数据写回数据库
    """
    # 1) 获取当前tab
    tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
    if tab_widget is None:
        box = QMessageBox(QMessageBox.Warning, "错误", "未找到管口附件Tab控件", QMessageBox.NoButton, viewer_instance)
        box.addButton("确认", QMessageBox.AcceptRole)
        box.exec_()
        return
    
    cur_idx = tab_widget.currentIndex()
    if cur_idx < 0:
        box = QMessageBox(QMessageBox.Warning, "错误", "未选择Tab页", QMessageBox.NoButton, viewer_instance)
        box.addButton("确认", QMessageBox.AcceptRole)
        box.exec_()
        return
    
    tab_name = tab_widget.tabText(cur_idx).strip()
    table = viewer_instance.dynamic_attachment_param_tabs.get(tab_name)
    if table is None:
        box = QMessageBox(QMessageBox.Warning, "错误", f"未找到 {tab_name} 的参数表", QMessageBox.NoButton, viewer_instance)
        box.addButton("确认", QMessageBox.AcceptRole)
        box.exec_()
        return
    
    product_id = getattr(viewer_instance, "product_id", None)
    if not product_id:
        box = QMessageBox(QMessageBox.Warning, "错误", "未找到产品ID", QMessageBox.NoButton, viewer_instance)
        box.addButton("确认", QMessageBox.AcceptRole)
        box.exec_()
        return
    
    # 2) 从表格中读取数据并更新到数据库
    try:
        connection = pymysql.connect(**db_config_1)
        try:
            with connection.cursor() as cursor:
                # 获取当前tab的所有参数记录（用于匹配参数ID）
                cursor.execute("""
                    SELECT 参数ID, 参数名称, 标题分组
                    FROM 产品设计活动表_管口附件附加参数表
                    WHERE 产品ID = %s AND Tab分类 = %s
                """, (product_id, tab_name))
                records = cursor.fetchall()
                
                # 创建参数名称+标题分组 -> 参数ID的映射
                param_map = {}
                for record in records:
                    param_id = record[0]
                    param_name = record[1]
                    title_group = record[2] if len(record) > 2 else ''
                    key = (param_name, title_group or '')
                    param_map[key] = param_id
                
                # 遍历表格，更新参数数值
                update_count = 0
                for r in range(table.rowCount()):
                    # 跳过分组标题行
                    name_item = table.item(r, 0)
                    if not name_item:
                        continue
                    
                    # 检查是否是分组标题行
                    group_info = name_item.data(Qt.UserRole)
                    if group_info and group_info.get("is_group_title"):
                        continue
                    
                    param_name = name_item.text().strip()
                    if not param_name:
                        continue
                    
                    # 获取参数值（从item或widget）
                    param_value = ""
                    value_item = table.item(r, 1)
                    if value_item:
                        param_value = value_item.text().strip()
                    else:
                        widget = table.cellWidget(r, 1)
                        if widget:
                            if isinstance(widget, QComboBox):
                                param_value = widget.currentText().strip()
                            elif hasattr(widget, 'text'):
                                param_value = widget.text().strip()
                    
                    # 获取标题分组（从当前行的上下文或数据中获取）
                    # 需要向上查找分组标题行
                    title_group = ''
                    for i in range(r, -1, -1):
                        check_item = table.item(i, 0)
                        if check_item:
                            check_group_info = check_item.data(Qt.UserRole)
                            if check_group_info and check_group_info.get("is_group_title"):
                                title_group = check_group_info.get("group_name", "")
                                break
                    
                    # 查找对应的参数ID
                    key = (param_name, title_group or '')
                    param_id = param_map.get(key)
                    
                    if param_id:
                        # 更新参数数值
                        cursor.execute("""
                            UPDATE 产品设计活动表_管口附件附加参数表
                            SET 参数数值 = %s
                            WHERE 产品ID = %s AND Tab分类 = %s AND 参数ID = %s
                        """, (param_value, product_id, tab_name, param_id))
                        update_count += 1
                
                connection.commit()
                print(f"[确定] 已更新 {update_count} 条参数记录")
                
                # 显示保存成功提示（左下角 line_tip 如有，样式对齐 datamanager）
                _set_tip(viewer_instance, "保存成功", success=True)
                
               
                
                # 3) 刷新当前Tab页的UI（重新加载数据）
                param_data = load_attachment_param_data(product_id, tab_name)
                
                # 从参数数据中获取附件类型（attachment_type），而不是使用tab_name
                attachment_type = None
                if param_data:
                    attachment_type = param_data[0].get('附件类型', '').strip()
                
                if not attachment_type:
                    print(f"[确定] Tab分类 '{tab_name}' 未找到附件类型，跳过刷新")
                    return
                
                pipe_codes_str = ""
                for param in param_data:
                    if param.get('参数名称') == '管口号':
                        pipe_codes_str = param.get('参数数值', '')
                        break
                guankou_codes = [code.strip() for code in pipe_codes_str.split('、') if code.strip()] if pipe_codes_str else []
                
                print(f"[确定按钮刷新] Tab '{tab_name}' (附件类型: {attachment_type})")
                print(f"[确定按钮刷新] 当前tab已选的管口号: {guankou_codes}")
                
                # 传递正确的参数：attachment_type、tab_classification、product_id
                _render_attachment_table_data(table, attachment_type, guankou_codes, param_data, viewer_instance, tab_classification=tab_name, product_id=product_id)
                
                # 4) 刷新其他tab页的管口号可选项（因为当前tab页的管口号可能已经改变）
                # 获取所有同附件类型的其他tab页
                tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
                if tab_widget:
                    for i in range(tab_widget.count()):
                        other_tab_name = tab_widget.tabText(i).strip()
                        if other_tab_name != tab_name and other_tab_name not in {"+", "＋"}:
                            other_table = viewer_instance.dynamic_attachment_param_tabs.get(other_tab_name)
                            if other_table:
                                # 检查是否是同一个附件类型
                                other_param_data = load_attachment_param_data(product_id, other_tab_name)
                                if other_param_data:
                                    other_attachment_type = other_param_data[0].get('附件类型', '').strip()
                                    if other_attachment_type == attachment_type:
                                        # 刷新这个tab页的管口号可选项
                                        try:
                                            _refresh_attachment_tab_pipe_code_options(viewer_instance, other_table, other_tab_name)
                                        except Exception as e:
                                            print(f"[确定] 刷新其他tab页 '{other_tab_name}' 失败: {e}")
                
        finally:
            connection.close()
    except Exception as e:
        print(f"[数据库错误] 保存管口附件参数失败：{e}")
        import traceback
        traceback.print_exc()
        box = QMessageBox(QMessageBox.Warning, "错误", f"保存失败：{e}", QMessageBox.NoButton, viewer_instance)
        box.addButton("确认", QMessageBox.AcceptRole)
        box.exec_()
        _set_tip(viewer_instance, f"保存失败：{e}", success=False)


def _on_attachment_tab_right_menu(viewer_instance, pos):
    """管口附件tab页右键菜单处理"""
    tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
    if not tab_widget:
        return
    
    # 防止删除过程中再次触发右键菜单
    if hasattr(viewer_instance, '_is_removing_attachment_tab'):
        if viewer_instance._is_removing_attachment_tab:
            return
    
    bar = tab_widget.tabBar()
    index = bar.tabAt(pos)
    if index < 0:
        return
    
    text = tab_widget.tabText(index).strip()
    if text in {"+", "＋"}:
        return
    
    total = tab_widget.count()
    has_plus = total > 0 and tab_widget.tabText(total - 1).strip() in {"+", "＋"}
    real_count = total - (1 if has_plus else 0)
    
    menu = QMenu(tab_widget)
    act_delete = menu.addAction("删除此分类")
    act = menu.exec_(bar.mapToGlobal(pos))
    
    if act is act_delete:
        _remove_attachment_tab(viewer_instance, index)


def _remove_attachment_tab(viewer_instance, index):
    """删除管口附件tab页"""
    from PyQt5.QtCore import QTimer
    
    tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
    if not tab_widget:
        return
    
    # 设置删除标志，防止删除过程中再次触发右键菜单
    viewer_instance._is_removing_attachment_tab = True
    
    # 防止删除"+"
    tab_text = tab_widget.tabText(index).strip()
    if tab_text in {"+", "＋"}:
        def clear_removing_flag_after_plus():
            viewer_instance._is_removing_attachment_tab = False
        QTimer.singleShot(200, clear_removing_flag_after_plus)
        return
    
    # 至少保留一个（排除"+"）
    total = tab_widget.count()
    has_plus = total > 0 and tab_widget.tabText(total - 1).strip() in {"+", "＋"}
    real_count = total - (1 if has_plus else 0)
    if real_count <= 1:
        box = QMessageBox(QMessageBox.Information, "提示", "至少保留一个管口附件分类，不能删除最后一个 tab", QMessageBox.NoButton, tab_widget)
        box.addButton("确认", QMessageBox.AcceptRole)
        box.exec_()
        def clear_removing_flag_after_dialog():
            viewer_instance._is_removing_attachment_tab = False
        QTimer.singleShot(200, clear_removing_flag_after_dialog)
        return
    
    tab_name = tab_widget.tabText(index)
    print(f"[管口附件] 正在删除 tab: {tab_name}")
    
    # 删库
    product_id = getattr(viewer_instance, "product_id", None)
    if product_id:
        _delete_attachment_tab_data_from_db(product_id, tab_name)
    else:
        print("[管口附件] 当前 product_id 不存在，无法删除数据库记录")
    
    # 从映射字典中移除
    if hasattr(viewer_instance, 'dynamic_attachment_param_tabs'):
        viewer_instance.dynamic_attachment_param_tabs.pop(tab_name, None)
    
    # UI 移除
    tab_widget.removeTab(index)
    
    # 选中一个合理的 tab
    cnt = tab_widget.count()
    if cnt:
        sel = min(index, cnt - 1)
        if tab_widget.tabText(sel).strip() in {"+", "＋"} and sel > 0:
            sel -= 1
        tab_widget.setCurrentIndex(sel)
    
    # 让 PlusTabManager 重新判断"+"用页签还是右上角按钮
    if hasattr(viewer_instance, "attachment_plus_mgr") and viewer_instance.attachment_plus_mgr:
        viewer_instance.attachment_plus_mgr.refresh_after_model_change()
    
    # 延迟清除删除标志，确保菜单关闭事件不会再次触发右键菜单
    def clear_removing_flag():
        viewer_instance._is_removing_attachment_tab = False
    
    QTimer.singleShot(200, clear_removing_flag)


def _delete_attachment_tab_data_from_db(product_id, tab_name):
    """
    从数据库中删除指定tab页的所有参数数据
    :param product_id: 产品ID
    :param tab_name: Tab分类名称
    """
    connection = pymysql.connect(**db_config_1)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM 产品设计活动表_管口附件附加参数表
                WHERE 产品ID = %s AND Tab分类 = %s
            """, (product_id, tab_name))
            connection.commit()
            print(f"[管口附件] 已从数据库删除tab页 '{tab_name}' 的所有参数数据")
    except Exception as e:
        print(f"[管口附件] 删除数据库记录失败: {e}")
        connection.rollback()
    finally:
        connection.close()


def _on_attachment_tab_changed(viewer_instance, index: int):
    """
    附件Tab页切换时的数据刷新逻辑（模仿管口元件的_on_guankou_tab_changed）
    在切换tab页时，刷新当前tab页的管口号可选项
    """
    tab_widget = getattr(viewer_instance, "tabWidget_attachment", None)
    if not tab_widget or index < 0 or index >= tab_widget.count():
        return
    
    tab_name = tab_widget.tabText(index).strip()
    if tab_name in {"+", "＋"}:
        # 点击 + 标签，跳回上一页
        tab_widget.setCurrentIndex(max(0, index - 1))
        return
    
    _dbg_print(f"[管口附件] Tab页切换: {tab_name}")
    
    # 获取当前Tab页对应的表格
    table = viewer_instance.dynamic_attachment_param_tabs.get(tab_name)
    if table is None:
        _dbg_print(f"[管口附件] 未找到 {tab_name} 的参数表，跳过刷新")
        return
    
    # 刷新当前Tab页的管口号可选项
    try:
        _refresh_attachment_tab_pipe_code_options(viewer_instance, table, tab_name)
    except Exception as e:
        print(f"[管口附件] Tab页数据刷新失败: {e}")
        import traceback
        traceback.print_exc()


def _refresh_attachment_tab_pipe_code_options(viewer_instance, table, tab_name):
    """
    刷新附件tab页的管口号可选项（模仿管口元件的patch_codes_for_current_tab）
    :param viewer_instance: 视图实例
    :param table: 表格控件
    :param tab_name: Tab分类名称
    """
    product_id = getattr(viewer_instance, 'product_id', None)
    if not product_id:
        _dbg_print(f"[管口附件] 未找到product_id，跳过刷新")
        return
    
    # 找到"管口号"这一行
    pipe_code_row = None
    for r in range(table.rowCount()):
        param_item = table.item(r, 0)
        if not param_item:
            continue
        # 跳过分组标题行
        group_info = param_item.data(Qt.UserRole)
        if group_info and group_info.get("is_group_title"):
            continue
        if param_item.text().strip() == "管口号":
            pipe_code_row = r
            break
    
    if pipe_code_row is None:
        _dbg_print(f"[管口附件] 未找到'管口号'行，跳过刷新")
        return
    
    # 从数据库加载最新的参数数据
    param_data = load_attachment_param_data(product_id, tab_name)
    if not param_data:
        _dbg_print(f"[管口附件] 未找到 {tab_name} 的参数数据，跳过刷新")
        return
    
    # 获取附件类型
    attachment_type = None
    if param_data:
        attachment_type = param_data[0].get('附件类型', '').strip()
    
    if not attachment_type:
        _dbg_print(f"[管口附件] Tab分类 '{tab_name}' 未找到附件类型，跳过刷新")
        return
    
    # 获取当前tab页已选的管口号
    pipe_codes_str = ""
    for param in param_data:
        if param.get('参数名称') == '管口号':
            pipe_codes_str = param.get('参数数值', '')
            break
    guankou_codes = [code.strip() for code in pipe_codes_str.split('、') if code.strip()] if pipe_codes_str else []
    
    # 重新计算可选项
    all_pipe_codes = query_pipe_codes_by_attachment_type(product_id, attachment_type)
    selected_in_other_tabs = query_selected_pipe_codes_in_other_tabs(product_id, attachment_type, tab_name)
    
    # 计算当前tab页的可选项 = 总可选项 - 已选项（但包含当前tab页已选的）
    selected_in_other_tabs_set = set(selected_in_other_tabs)
    pipe_code_options = []
    seen = set()
    # 先添加当前tab已选的（确保它们一定在候选列表中）
    for code in guankou_codes:
        if code and code.strip() and code.strip() not in seen:
            code_stripped = code.strip()
            pipe_code_options.append(code_stripped)
            seen.add(code_stripped)
    # 再添加总可选项中未被其他tab占用的
    for code in all_pipe_codes:
        code_stripped = code.strip() if code else ""
        if code_stripped and code_stripped not in seen and code_stripped not in selected_in_other_tabs_set:
            pipe_code_options.append(code_stripped)
            seen.add(code_stripped)
    
    _dbg_print(f"[管口附件] Tab切换刷新 '{tab_name}' (附件类型: {attachment_type})")
    _dbg_print(f"[管口附件] 总可选项: {all_pipe_codes}")
    _dbg_print(f"[管口附件] 其他tab已选: {selected_in_other_tabs}")
    _dbg_print(f"[管口附件] 当前tab已选: {guankou_codes}")
    _dbg_print(f"[管口附件] 刷新后的可选项: {pipe_code_options}")
    
    # 更新表格属性
    table.setProperty("gk_code_candidates", pipe_code_options)
    
    # 重新设置delegate（先清掉可能存在的旧代理，避免悬空引用）
    table.setItemDelegateForRow(pipe_code_row, None)
    if pipe_code_options:
        from modules.cailiaodingyi.controllers.checkcombo import CheckComboDelegate
        table.setItemDelegateForRow(pipe_code_row, CheckComboDelegate(options=pipe_code_options, table=table, enable_select_all=True))
        _dbg_print(f"[管口附件] 已重新设置管口号行的delegate，可选项: {pipe_code_options}")
