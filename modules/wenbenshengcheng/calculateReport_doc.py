import datetime
import json
import re
from pathlib import Path

import pymysql
from docx import Document

def _normalize_case_label(text):
    """
    将 工况1 / 工况2 / 工况3 / 工况一 / 工况二 / 工况三
    统一成：
      工况1 / 工况2 / 工况3
    """
    text = str(text or "").strip()
    text = (
        text.replace("１", "1")
            .replace("２", "2")
            .replace("３", "3")
    )

    m = re.search(r"工况\s*([123一二三])", text)
    if not m:
        return None

    mapping = {
        "1": "工况1",
        "2": "工况2",
        "3": "工况3",
        "一": "工况1",
        "二": "工况2",
        "三": "工况3",
    }
    return mapping.get(m.group(1))


def _case_label_to_chinese(case_label):
    """
    工况1 -> 工况一
    工况2 -> 工况二
    工况3 -> 工况三
    """
    case_label = _normalize_case_label(case_label)
    mapping = {
        "工况1": "工况一",
        "工况2": "工况二",
        "工况3": "工况三",
    }
    return mapping.get(case_label)


def _extract_case_label_from_id(result_id):
    """
    从计算结果 id 中提取外层工况。

    例如：
      工况1：锥壳(α1-工况三)207 -> 工况1
      工况2：吊耳001              -> 工况2
      锥壳001                    -> None

    注意：
    这里提取的是最前面的外层工况，不是 α1 里的工况。
    """
    text = str(result_id or "").strip()
    if not text:
        return None

    m = re.match(r"^工况\s*([123一二三])\s*[：:]", text)
    if not m:
        return None

    return _normalize_case_label(m.group(0))


def _strip_case_prefix(result_id):
    """
    去掉 id 前面的 工况1：/ 工况2：/ 工况3：
    """
    text = str(result_id or "").strip()
    return re.sub(r"^工况\s*[123一二三]\s*[：:]\s*", "", text)


def _get_case_param_name(case_label):
    """
    当前工况对应的设计压力参数名。
    和 Excel 逻辑保持一致。
    """
    case_label = _normalize_case_label(case_label) or "工况1"

    mapping = {
        "工况1": "设计压力*",
        "工况2": "设计压力*[工况2]",
        "工况3": "设计压力*[工况3]",
    }
    return mapping.get(case_label, "设计压力*")


def _find_case_labels_from_rows(rows, row_get_func, get_result_id_func, target_component_name=None):
    """
    从 产品设计活动表_元件计算结果表 的 id 中识别工况。
    如果没有任何工况前缀，默认只有 工况1。
    """
    found = []
    seen = set()

    has_target_component = False

    for row in rows:
        component_name = str(row_get_func(row, "元件名称", 0, "") or "").strip()
        result_id = get_result_id_func(row)

        if target_component_name:
            if component_name != target_component_name and target_component_name not in str(result_id or ""):
                continue

        has_target_component = True

        case_label = _extract_case_label_from_id(result_id)
        if case_label and case_label not in seen:
            seen.add(case_label)
            found.append(case_label)

    if not found and has_target_component:
        found.append("工况1")

    order = ["工况1", "工况2", "工况3"]
    return [c for c in order if c in found]


def _find_case_labels_from_design_pressure(cursor, product_id):
    """
    从 产品设计活动表_设计数据表 中识别设计压力工况。
    支持：
      设计压力*
      设计压力*[工况2]
      设计压力*[工况3]
    """
    cursor.execute(
        """
        SELECT 参数名称
        FROM 产品设计活动表_设计数据表
        WHERE 产品ID = %s
          AND 参数名称 LIKE %s
        """,
        (product_id, "设计压力%")
    )

    rows = cursor.fetchall()

    found = []
    seen = set()

    for row in rows:
        if isinstance(row, dict):
            param_name = str(row.get("参数名称") or "").strip()
        else:
            param_name = str(row[0] or "").strip()

        if param_name in ("设计压力", "设计压力*"):
            case_label = "工况1"
        else:
            case_label = _normalize_case_label(param_name)

        if case_label and case_label not in seen:
            seen.add(case_label)
            found.append(case_label)

    if not found:
        found.append("工况1")

    order = ["工况1", "工况2", "工况3"]
    return [c for c in order if c in found]


def _merge_case_labels(*case_label_lists):
    """
    合并多个来源识别到的工况，并按 工况1、工况2、工况3 排序。
    """
    seen = set()
    for labels in case_label_lists:
        for label in labels or []:
            norm = _normalize_case_label(label)
            if norm:
                seen.add(norm)

    if not seen:
        seen.add("工况1")

    order = ["工况1", "工况2", "工况3"]
    return [c for c in order if c in seen]
def export_diaoer_calculation_doc(product_id, save_dir, db_config=None, project_root=None):
    """
    独立生成“吊耳”Word计算书。

    功能：
    1. 查 产品设计活动表_元件计算结果表 中当前产品ID是否存在 元件名称='吊耳'
    2. 若不存在，则不输出Word
    3. 若存在，则根据 Name='吊耳名称' 的 Value 选择模板：
       - 卧式设备板式吊耳 -> 卧式设备板式吊耳-计算书模板.docx
       - 顶部板式吊耳     -> 顶部板式吊耳-计算书模板.docx
    4. 模板占位符支持：
       - 材料类型（吊耳）
       - 材料类型（壳体圆筒）
       - 系揽环板厚度（吊耳）（隐）
    5. 替换规则：
       - 括号外 = Name
       - 第一层括号内 = 元件名称
       - （隐）缺失时替换为 "-"
    6. 返回生成后的 docx 路径；若无吊耳则返回 None
    """

    if db_config is None:
        db_config = {
            "host": "localhost",
            "user": "root",
            "password": "123456",
            "database": "产品设计活动库",
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if project_root is None:
        project_root = _find_project_root_with_templates(Path(__file__).resolve())
    else:
        project_root = Path(project_root).resolve()

    template_dir = project_root / "templates" / "calculation_docs" / "吊耳"
    if not template_dir.exists():
        raise FileNotFoundError(f"吊耳模板目录不存在：{template_dir}")

    conn = None
    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()

        # 一次性读取当前产品ID所有元件计算结果
        cursor.execute(
            """
            SELECT *
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s
            """,
            (product_id,),
        )
        rows = cursor.fetchall()

        if not rows:
            print(f"[吊耳计算书] 产品ID={product_id} 未找到任何元件计算结果，不生成计算书。")
            return None

        def _build_diaoer_component_map(rows, case_label="工况1"):
            """
            吊耳计算书按外层工况构造 component_map。

            - 无工况前缀的数据作为公共基础数据
            - 有 工况1/2/3 前缀的数据只进入对应工况
            - 当前工况数据覆盖公共数据
            """
            case_label = _normalize_case_label(case_label) or "工况1"
            component_map = {}

            # 1. 公共数据
            for row in rows:
                component_name = str(row.get("元件名称") or "").strip()
                name = str(row.get("Name") or "").strip()
                value = "" if row.get("Value") is None else str(row.get("Value"))

                if not component_name or not name:
                    continue

                result_id = ""
                for key in ("id", "Id", "ID", "计算结果ID", "元件计算结果ID"):
                    if key in row and row.get(key) is not None:
                        result_id = str(row.get(key)).strip()
                        break

                row_case_label = _extract_case_label_from_id(result_id)

                # 有工况前缀的先不作为公共数据
                if row_case_label:
                    continue

                component_map.setdefault(component_name, {})
                component_map[component_name][name] = value

            # 2. 当前工况数据覆盖公共数据
            for row in rows:
                component_name = str(row.get("元件名称") or "").strip()
                name = str(row.get("Name") or "").strip()
                value = "" if row.get("Value") is None else str(row.get("Value"))

                if not component_name or not name:
                    continue

                result_id = ""
                for key in ("id", "Id", "ID", "计算结果ID", "元件计算结果ID"):
                    if key in row and row.get(key) is not None:
                        result_id = str(row.get(key)).strip()
                        break

                row_case_label = _extract_case_label_from_id(result_id)

                if row_case_label != case_label:
                    continue

                component_map.setdefault(component_name, {})
                component_map[component_name][name] = value

            return component_map

        # ================================
        # 识别吊耳外层工况
        # ================================
        def _get_diaoer_result_id(row):
            for key in ("id", "Id", "ID", "计算结果ID", "元件计算结果ID"):
                if key in row and row.get(key) is not None:
                    return str(row.get(key)).strip()
            return ""

        def _row_get_diaoer(row, key, index=0, default=""):
            if not row:
                return default
            if isinstance(row, dict):
                return row.get(key, default)
            try:
                return row[index]
            except Exception:
                return default

        case_labels = _find_case_labels_from_rows(
            rows=rows,
            row_get_func=_row_get_diaoer,
            get_result_id_func=_get_diaoer_result_id,
            target_component_name="吊耳"
        )

        print(f"[吊耳计算书] 识别到工况：{case_labels}")

        generated_paths = []

        for case_label in case_labels:
            component_map = _build_diaoer_component_map(
                rows=rows,
                case_label=case_label
            )

            if "吊耳" not in component_map:
                print(f"[吊耳计算书] 产品ID={product_id}，{case_label} 不存在元件名称“吊耳”，跳过。")
                continue

            lug_type = str(component_map["吊耳"].get("与吊耳连接元件", "")).strip()
            if not lug_type:
                raise ValueError(
                    f"产品ID={product_id}，{case_label} 的吊耳记录中缺少 Name='与吊耳连接元件' 对应的 Value。"
                )

            top_lug_component_set = {
                "管箱圆筒",
                "外头盖圆筒",
                "管箱平盖",
                "浮头法兰",
                "球冠形封头",
            }

            if lug_type in top_lug_component_set:
                template_filename = "顶部板式吊耳-计算书模板.docx"
            else:
                template_filename = "卧式设备板式吊耳-计算书模板.docx"

            template_path = template_dir / template_filename
            if not template_path.exists():
                raise FileNotFoundError(f"模板不存在：{template_path}")

            doc = Document(str(template_path))

            for p in _iter_all_paragraphs(doc):
                _replace_placeholders_in_paragraph_by_component_map(
                    paragraph=p,
                    component_map=component_map,
                )

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_name = f"吊耳计算书_{case_label}_{lug_type}_{timestamp}.docx"
            output_path = save_dir / out_name

            doc.save(str(output_path))
            print(f"[吊耳计算书] 生成成功：{output_path}")

            generated_paths.append(str(output_path))

        if not generated_paths:
            print(f"[吊耳计算书] 产品ID={product_id} 未生成任何吊耳计算书。")
            return None

        if len(generated_paths) == 1:
            return generated_paths[0]

        return generated_paths

    finally:
        if conn:
            conn.close()


def export_zhuiqiao_calculation_doc(product_id, save_dir, db_config=None, project_root=None):
    """
    独立生成“锥壳”Word计算书。

    逻辑：
    1. 读取 产品设计活动表_元件计算结果表 当前产品ID的计算结果
    2. 判断是否存在锥壳；不存在则不生成
    3. 读取 产品设计活动表_设计数据表 中 参数名称 LIKE '设计压力%' 的 壳程数值
       - 壳程设计压力 >= 0：按内压生成
       - 壳程设计压力 < 0：按外压生成
    4. 外压生成规则：
       - 必须先生成对应折边形式的内压计算书
       - 再生成对应折边形式的外压基础计算书
       - 如果计算结果 id 中存在 (α1-工况一)/(α1-工况二)/(α1-工况三)
         则分别生成对应 α1 工况计算书
    """

    if db_config is None:
        db_config = {
            "host": "localhost",
            "user": "root",
            "password": "123456",
            "database": "产品设计活动库",
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    if project_root is None:
        project_root = _find_project_root_with_templates(Path(__file__).resolve())
    else:
        project_root = Path(project_root).resolve()

    template_dir = project_root / "templates" / "calculation_docs" / "锥壳"
    if not template_dir.exists():
        raise FileNotFoundError(f"锥壳模板目录不存在：{template_dir}")

    def _row_get(row, key, index=0, default=""):
        """兼容 DictCursor 和普通 Cursor"""
        if not row:
            return default
        if isinstance(row, dict):
            return row.get(key, default)
        try:
            return row[index]
        except Exception:
            return default

    def _get_param_value(row):
        """兼容 DictCursor 和普通 Cursor 的取值方式"""
        if not row:
            return ""
        if isinstance(row, dict):
            return str(row.get("参数值") or "").strip()
        return str(row[0] or "").strip()

    def _normalize_yes_no(value):
        value = str(value or "").strip()
        if value in ("是", "有", "1", "true", "True", "YES", "Yes", "yes"):
            return "是"
        if value in ("否", "无", "0", "false", "False", "NO", "No", "no"):
            return "否"
        return value

    def _to_float(value):
        """
        将数据库中的压力值转为 float。
        支持：
          - -1.6
          - −1.6
          - -1.6MPa
          - 1.6 MPa
        """
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        text = (
            text.replace("−", "-")
                .replace("－", "-")
                .replace("—", "-")
                .replace(",", "")
                .replace(" ", "")
        )

        try:
            return float(text)
        except Exception:
            pass

        m = re.search(r'[-+]?\d+(?:\.\d+)?', text)
        if not m:
            return None

        try:
            return float(m.group(0))
        except Exception:
            return None

    def _normalize_work_condition(text):
        """
        工况1 / 工况2 / 工况3 / 工况一 / 工况二 / 工况三
        统一为：
          工况一 / 工况二 / 工况三
        """
        text = str(text or "").strip()
        text = (
            text.replace("１", "1")
                .replace("２", "2")
                .replace("３", "3")
        )

        m = re.search(r'工况\s*([123一二三])', text)
        if not m:
            return None

        mapping = {
            "1": "工况一",
            "2": "工况二",
            "3": "工况三",
            "一": "工况一",
            "二": "工况二",
            "三": "工况三",
        }
        return mapping.get(m.group(1))

    def _extract_alpha1_condition_from_id(result_id):
        """
        从计算结果 id 中提取 α1 工况。

        关键：
        如果 id 是：
          工况1：锥壳(α1-工况三)207

        这里必须取括号中的：
          α1-工况三

        而不是前面的：
          工况1
        """
        text = str(result_id or "").strip()
        if not text:
            return None

        # 优先从括号中提取 α1 工况
        paren_contents = re.findall(r'[（(]([^（）()]*)[）)]', text)
        for content in paren_contents:
            if "α1" in content or "a1" in content.lower():
                cond = _normalize_work_condition(content)
                if cond:
                    return cond

        return None

    def _get_result_id(row):
        """
        兼容不同字段名。
        你的表里如果字段就叫 id，这里会优先读取 id。
        """
        if not isinstance(row, dict):
            return ""

        for key in ("id", "Id", "ID", "计算结果ID", "元件计算结果ID"):
            if key in row and row.get(key) is not None:
                return str(row.get(key)).strip()

        return ""

    def _make_component_key(result_id, component_name):
        """
        构造 component_map 的 key。
        如果 result_id 本身已经包含锥壳等元件名，就直接用 result_id；
        否则拼上元件名称。
        """
        result_id = str(result_id or "").strip()
        component_name = str(component_name or "").strip()

        if not result_id:
            return component_name

        if component_name and component_name in result_id:
            return result_id

        return f"{result_id}：{component_name}"

    def _build_component_map(rows, case_label="工况1", wanted_condition=None):
        """
        构造 component_map。

        多工况逻辑：
        - 没有 id 工况前缀的数据，作为公共基础数据，每个工况都可用
        - id 前缀为 工况1/工况2/工况3 的数据，只进入对应工况
        - α1 工况数据不直接污染普通锥壳数据
        - 如果 wanted_condition=工况一/二/三，则再用对应 α1 数据覆盖普通“锥壳”字段
        """
        case_label = _normalize_case_label(case_label) or "工况1"
        component_map = {}

        # =========================
        # 1. 先写入公共数据
        # =========================
        for row in rows:
            component_name = str(_row_get(row, "元件名称", 0, "") or "").strip()
            name = str(_row_get(row, "Name", 1, "") or "").strip()
            value_raw = _row_get(row, "Value", 2, "")
            value = "" if value_raw is None else str(value_raw)

            if not component_name or not name:
                continue

            result_id = _get_result_id(row)
            row_case_label = _extract_case_label_from_id(result_id)
            alpha1_condition = _extract_alpha1_condition_from_id(result_id)

            # 有外层工况前缀的，先不作为公共数据
            if row_case_label:
                continue

            # α1 工况数据先只保存带 id 的 key，不覆盖普通 component_name
            if alpha1_condition:
                key = _make_component_key(result_id, component_name)
                component_map.setdefault(key, {})
                component_map[key][name] = value
                continue

            component_map.setdefault(component_name, {})
            component_map[component_name][name] = value

            if result_id:
                key = _make_component_key(result_id, component_name)
                component_map.setdefault(key, {})
                component_map[key][name] = value

        # =========================
        # 2. 再写入当前外层工况数据，覆盖公共数据
        # =========================
        for row in rows:
            component_name = str(_row_get(row, "元件名称", 0, "") or "").strip()
            name = str(_row_get(row, "Name", 1, "") or "").strip()
            value_raw = _row_get(row, "Value", 2, "")
            value = "" if value_raw is None else str(value_raw)

            if not component_name or not name:
                continue

            result_id = _get_result_id(row)
            row_case_label = _extract_case_label_from_id(result_id)
            alpha1_condition = _extract_alpha1_condition_from_id(result_id)

            # 只处理当前外层工况
            if row_case_label != case_label:
                continue

            # α1 数据先不覆盖普通 component_name
            if alpha1_condition:
                key = _make_component_key(result_id, component_name)
                component_map.setdefault(key, {})
                component_map[key][name] = value
                continue

            component_map.setdefault(component_name, {})
            component_map[component_name][name] = value

            key = _make_component_key(result_id, component_name)
            component_map.setdefault(key, {})
            component_map[key][name] = value

        # =========================
        # 3. 如果是 α1 工况计算书，则用当前 α1 工况覆盖普通“锥壳”字段
        # =========================
        if wanted_condition:
            for row in rows:
                component_name = str(_row_get(row, "元件名称", 0, "") or "").strip()
                name = str(_row_get(row, "Name", 1, "") or "").strip()
                value_raw = _row_get(row, "Value", 2, "")
                value = "" if value_raw is None else str(value_raw)

                if not component_name or not name:
                    continue

                result_id = _get_result_id(row)
                row_case_label = _extract_case_label_from_id(result_id)
                alpha1_condition = _extract_alpha1_condition_from_id(result_id)

                # α1 也必须属于当前外层工况
                # 如果没有外层工况前缀，则默认它属于工况1
                actual_case_label = row_case_label or "工况1"

                if actual_case_label != case_label:
                    continue

                if alpha1_condition != wanted_condition:
                    continue

                component_map.setdefault(component_name, {})
                component_map[component_name][name] = value

                key = _make_component_key(result_id, component_name)
                component_map.setdefault(key, {})
                component_map[key][name] = value

        return component_map

    def _find_alpha1_conditions(rows, case_label="工况1"):
        """
        查找当前外层工况下，需要生成 α1 工况计算书的 α1 工况。

        例如：
          工况1：锥壳(α1-工况三)207
        只有当当前 case_label=工况1 时才使用。
        """
        case_label = _normalize_case_label(case_label) or "工况1"
        found = set()

        for row in rows:
            name = str(_row_get(row, "Name", 1, "") or "").strip()
            result_id = _get_result_id(row)

            if "设计压力" not in name:
                continue

            row_case_label = _extract_case_label_from_id(result_id)
            actual_case_label = row_case_label or "工况1"

            if actual_case_label != case_label:
                continue

            cond = _extract_alpha1_condition_from_id(result_id)
            if cond:
                found.add(cond)

        order = ["工况一", "工况二", "工况三"]
        return [cond for cond in order if cond in found]
    def _save_doc_by_template(template_filename, component_map, output_tag):
        """
        根据模板生成一个 Word。
        """
        template_path = template_dir / template_filename
        if not template_path.exists():
            raise FileNotFoundError(f"模板不存在：{template_path}")

        doc = Document(str(template_path))

        for p in _iter_all_paragraphs(doc):
            _replace_placeholders_in_paragraph_by_component_map(
                paragraph=p,
                component_map=component_map,
            )

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        safe_tag = str(output_tag).replace("/", "_").replace("\\", "_").replace(":", "_")
        out_name = f"锥壳计算书_{safe_tag}_{timestamp}.docx"
        output_path = save_dir / out_name

        doc.save(str(output_path))
        print(f"[锥壳计算书] 生成成功：{output_path}")

        return str(output_path)

    conn = None

    try:
        conn = pymysql.connect(**db_config)
        cursor = conn.cursor()

        # 一次性读取当前产品ID所有元件计算结果
        # 这里用 SELECT *，是因为后面需要读取 id / Id / ID 字段判断 α1 工况
        cursor.execute(
            """
            SELECT *
            FROM 产品设计活动表_元件计算结果表
            WHERE 产品ID = %s
            """,
            (product_id,),
        )
        rows = cursor.fetchall()

        if not rows:
            print(f"[锥壳计算书] 产品ID={product_id} 未找到任何元件计算结果，不生成计算书。")
            return None

        # 判断是否存在锥壳
        has_zhuiqiao = False
        for row in rows:
            component_name = str(_row_get(row, "元件名称", 0, "") or "").strip()
            result_id = _get_result_id(row)

            if component_name == "锥壳" or "锥壳" in result_id:
                has_zhuiqiao = True
                break

        if not has_zhuiqiao:
            print(f"[锥壳计算书] 产品ID={product_id} 不存在元件名称“锥壳”，不生成计算书。")
            return None

        # 查询锥壳大端是否带折边
        cursor.execute(
            """
            SELECT 参数值 
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s 
              AND 元件名称 = '锥壳' 
              AND 参数名称 = '锥壳大端是否带折边'
            """,
            (product_id,)
        )
        big_end_row = cursor.fetchone()

        # 查询锥壳小端是否带折边
        cursor.execute(
            """
            SELECT 参数值 
            FROM 产品设计活动表_元件附加参数表
            WHERE 产品ID = %s 
              AND 元件名称 = '锥壳' 
              AND 参数名称 = '锥壳小端是否带折边'
            """,
            (product_id,)
        )
        small_end_row = cursor.fetchone()

        big_end_has_flange = _normalize_yes_no(_get_param_value(big_end_row))
        small_end_has_flange = _normalize_yes_no(_get_param_value(small_end_row))

        flange_key = (big_end_has_flange, small_end_has_flange)

        # 查询设计压力* 的壳程数值
        cursor.execute(
            """
            SELECT 参数名称, 壳程数值
            FROM 产品设计活动表_设计数据表
            WHERE 产品ID = %s
              AND 参数名称 LIKE %s
            ORDER BY 
              CASE 
                WHEN 参数名称 = '设计压力*' THEN 0
                WHEN 参数名称 LIKE '设计压力%%' THEN 1
                ELSE 2
              END
            LIMIT 1
            """,
            (product_id, "设计压力%"),
        )
        pressure_row = cursor.fetchone()

        shell_design_pressure = None
        if pressure_row:
            if isinstance(pressure_row, dict):
                shell_design_pressure = _to_float(pressure_row.get("壳程数值"))
            else:
                shell_design_pressure = _to_float(pressure_row[1])

        if shell_design_pressure is None:
            print(
                f"[锥壳计算书] 产品ID={product_id} 未读取到“设计压力*”壳程数值，"
                f"默认按内压计算书处理。"
            )
            is_external_pressure = False
        else:
            is_external_pressure = shell_design_pressure < 0

        print(
            f"[锥壳计算书] 产品ID={product_id}，"
            f"壳程设计压力={shell_design_pressure}，"
            f"判断为：{'外压' if is_external_pressure else '内压'}"
        )

        # 内压模板
        inner_template_map = {
            ("是", "是"): "19.11、偏心锥壳-内径-内压-两端折边-计算书模板.docx",
            ("否", "是"): "19.15、偏心锥壳-内径-内压-大端无折边-小端折边-计算书模板.docx",
            ("是", "否"): "19.13、偏心锥壳-内径-内压-大端折边-小端无折边-计算书模板.docx",
            ("否", "否"): "19.9、偏心锥壳-内径-内压-无折边-计算书模板.docx",
        }

        # 外压基础模板：外压计算必须先出内压计算书
        outer_base_template_map = {
            ("是", "是"): "19.12-1、偏心锥壳-内径-外压-两端折边-计算书模板（外压计算必须先出内压计算书）.docx",
            ("否", "是"): "19.16-1、偏心锥壳-内径-外压-大端无折边-小端折边-计算书模板（外压计算必须先出内压计算书）.docx",
            ("是", "否"): "19.14-1、偏心锥壳-内径-外压-大端折边-小端无折边-计算书模板（外压计算必须先出内压计算书）.docx",
            ("否", "否"): "19.10-1、偏心锥壳-内径-外压-无折边-计算书模板（外压计算必须先出内压计算书）.docx",
        }

        # 外压 α1 夹角工况模板：三种工况分别调用一次
        outer_alpha1_template_map = {
            ("是", "是"): "19.12-2、偏心锥壳-内径-外压-两端折边-计算书模板-α1夹角工况（三种工况分别调用一次）.docx",
            ("否", "是"): "19.16-2、偏心锥壳-内径-外压-大端无折边-小端折边-计算书模板-α1夹角工况（三种工况分别调用一次）.docx",
            ("是", "否"): "19.14-2、偏心锥壳-内径-外压-大端折边-小端无折边-计算书模板-α1夹角工况（三种工况分别调用一次）.docx",
            ("否", "否"): "19.10-2、偏心锥壳-内径-外压-无折边-计算书模板-α1夹角工况（三种工况分别调用一次）.docx",
        }

        if flange_key not in inner_template_map:
            raise ValueError(
                f"无法判断锥壳折边形式："
                f"大端={big_end_has_flange}，小端={small_end_has_flange}"
            )

        # ================================
        # 识别需要输出的外层工况
        # ================================
        case_labels_from_rows = _find_case_labels_from_rows(
            rows=rows,
            row_get_func=_row_get,
            get_result_id_func=_get_result_id,
            target_component_name="锥壳"
        )

        case_labels_from_pressure = _find_case_labels_from_design_pressure(
            cursor=cursor,
            product_id=product_id
        )

        case_labels = _merge_case_labels(case_labels_from_rows, case_labels_from_pressure)

        print(f"[锥壳计算书] 识别到工况：{case_labels}")

        generated_paths = []

        # =========================================================
        # 按外层工况循环生成 Word
        # =========================================================
        for case_label in case_labels:
            current_param_name = _get_case_param_name(case_label)

            cursor.execute(
                """
                SELECT 参数名称, 壳程数值
                FROM 产品设计活动表_设计数据表
                WHERE 产品ID = %s
                  AND 参数名称 = %s
                LIMIT 1
                """,
                (product_id, current_param_name),
            )
            pressure_row = cursor.fetchone()

            shell_design_pressure = None
            if pressure_row:
                if isinstance(pressure_row, dict):
                    shell_design_pressure = _to_float(pressure_row.get("壳程数值"))
                else:
                    shell_design_pressure = _to_float(pressure_row[1])

            if shell_design_pressure is None:
                print(
                    f"[锥壳计算书] 产品ID={product_id}，{case_label} 未读取到 {current_param_name} 的壳程数值，"
                    f"默认按内压计算书处理。"
                )
                is_external_pressure = False
            else:
                is_external_pressure = shell_design_pressure < 0

            print(
                f"[锥壳计算书] 产品ID={product_id}，{case_label}，"
                f"{current_param_name} 壳程设计压力={shell_design_pressure}，"
                f"判断为：{'外压' if is_external_pressure else '内压'}"
            )

            normal_component_map = _build_component_map(
                rows=rows,
                case_label=case_label,
                wanted_condition=None
            )

            # =========================
            # 当前工况：内压
            # =========================
            if not is_external_pressure:
                inner_template = inner_template_map[flange_key]

                path = _save_doc_by_template(
                    template_filename=inner_template,
                    component_map=normal_component_map,
                    output_tag=f"{case_label}_内压"
                )
                generated_paths.append(path)

            # =========================
            # 当前工况：外压
            # =========================
            else:
                # 1. 外压前置内压计算书
                inner_template = inner_template_map[flange_key]

                inner_path = _save_doc_by_template(
                    template_filename=inner_template,
                    component_map=normal_component_map,
                    output_tag=f"{case_label}_外压前置_内压"
                )
                generated_paths.append(inner_path)

                # 2. 外压基础计算书
                outer_base_template = outer_base_template_map[flange_key]

                outer_base_path = _save_doc_by_template(
                    template_filename=outer_base_template,
                    component_map=normal_component_map,
                    output_tag=f"{case_label}_外压_基础"
                )
                generated_paths.append(outer_base_path)

                # 3. 当前外层工况下的 α1 工况计算书
                alpha1_conditions = _find_alpha1_conditions(
                    rows=rows,
                    case_label=case_label
                )

                if not alpha1_conditions:
                    print(f"[锥壳计算书] {case_label} 未发现 id 中包含 α1 工况的设计压力结果，不生成 α1 工况计算书。")
                else:
                    alpha1_template = outer_alpha1_template_map[flange_key]

                    for cond in alpha1_conditions:
                        condition_component_map = _build_component_map(
                            rows=rows,
                            case_label=case_label,
                            wanted_condition=cond,
                        )

                        condition_path = _save_doc_by_template(
                            template_filename=alpha1_template,
                            component_map=condition_component_map,
                            output_tag=f"{case_label}_外压_α1_{cond}"
                        )
                        generated_paths.append(condition_path)

        if not generated_paths:
            return None

        if len(generated_paths) == 1:
            return generated_paths[0]

        return generated_paths

    finally:
        if conn:
            conn.close()


_HEAD_TYPE_CONFIG = {
    "EHA": ("椭圆形", "封头-椭圆形"),
    "THA": ("碟形", "封头-碟形"),
    "HHA": ("半球形", "封头-半球形"),
}

_HEAD_CYLINDER_COMPONENTS = {
    "管箱封头": ("管箱圆筒",),
    "后端管箱封头": ("后端管箱圆筒",),
    "外头盖封头": ("外头盖圆筒",),
    "壳体封头": ("壳体圆筒",),
    "前端封头": ("容器圆筒",),
    "后端封头": ("容器圆筒",),

}


def _calculation_row_get(row, key, index=0, default=""):
    """兼容计算结果的字典行和简单元组行。"""
    if not row:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[index]
    except Exception:
        return default


def _calculation_result_id(row):
    if not isinstance(row, dict):
        return ""
    for key in ("id", "Id", "ID", "计算结果ID", "元件计算结果ID"):
        if row.get(key) is not None:
            return str(row.get(key)).strip()
    return ""


def _to_number(value):
    if value is None:
        return None
    text = (
        str(value).strip()
        .replace("−", "-")
        .replace("－", "-")
        .replace("—", "-")
        .replace(",", "")
        .replace(" ", "")
    )
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
        return float(match.group(0)) if match else None


def _load_calculation_rows_from_json(json_path):
    """将强度计算 JSON 的 DictOutDatas 展平成数据库计算结果行。"""
    with Path(json_path).open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)

    component_results = payload.get("DictOutDatas") or {}
    rows = []
    for component_name, result_group in component_results.items():
        if not isinstance(result_group, dict):
            continue
        for item in result_group.get("Datas") or []:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["元件名称"] = component_name
            rows.append(row)
    return rows


def _component_fields_for_case(rows, component_name, case_label):
    """
    取得指定元件、指定外层工况的数据；无工况前缀的数据作为公共值。
    当前工况值在最后写入，因此会覆盖公共值。
    """
    case_label = _normalize_case_label(case_label) or "工况1"
    common = {}
    current = {}
    for row in rows:
        row_component = str(
            _calculation_row_get(row, "元件名称", 0, "") or ""
        ).strip()
        if row_component != component_name:
            continue

        name = str(_calculation_row_get(row, "Name", 1, "") or "").strip()
        if not name:
            continue
        raw_value = _calculation_row_get(row, "Value", 2, "")
        value = "" if raw_value is None else str(raw_value)
        row_case = _extract_case_label_from_id(_calculation_result_id(row))
        if row_case is None:
            common[name] = value
        elif row_case == case_label:
            current[name] = value

    common.update(current)
    return common


def _find_head_case_labels(rows, head_component_name):
    labels = []
    seen = set()
    has_common_data = False
    for row in rows:
        component_name = str(
            _calculation_row_get(row, "元件名称", 0, "") or ""
        ).strip()
        if component_name != head_component_name:
            continue
        label = _extract_case_label_from_id(_calculation_result_id(row))
        if label:
            if label not in seen:
                seen.add(label)
                labels.append(label)
        else:
            has_common_data = True

    if not labels and has_common_data:
        labels.append("工况1")
    order = ("工况1", "工况2", "工况3")
    return [label for label in order if label in labels]


def _head_cylinder_candidates(head_component_name):
    """返回与当前封头配套的圆筒名称，精确名称优先。"""
    candidates = list(_HEAD_CYLINDER_COMPONENTS.get(head_component_name, ()))
    if head_component_name.endswith("封头"):
        inferred = f"{head_component_name[:-2]}圆筒"
        if inferred not in candidates:
            candidates.append(inferred)
    return candidates


def _find_head_template(template_dir, fragment):
    """模板带编号，因此按“形状-口径基准-压力-计算书”片段匹配。"""
    matches = [
        path for path in Path(template_dir).iterdir()
        if path.is_file()
        and path.suffix.lower() == ".docx"
        and fragment in path.name
        and "直边段" not in path.name
    ]
    if not matches:
        raise FileNotFoundError(
            f"在模板目录 {template_dir} 中未找到名称包含“{fragment}”的 docx 模板"
        )
    if len(matches) > 1:
        names = "、".join(path.name for path in matches)
        raise ValueError(f"名称片段“{fragment}”匹配到多个模板：{names}")
    return matches[0]


def _build_head_component_map(rows, head_component_name, case_label):
    """
    为一份封头计算书构造专属映射。

    模板只写（封头）/（圆筒），这里将它们分别绑定到当前真实封头及其
    配套圆筒，防止同一产品存在多个封头时串用其它封头的结果。
    """
    component_names = {
        str(_calculation_row_get(row, "元件名称", 0, "") or "").strip()
        for row in rows
    }
    head_fields = _component_fields_for_case(rows, head_component_name, case_label)
    component_map = {
        "封头": head_fields,
        head_component_name: head_fields,
    }

    cylinder_name = next(
        (
            candidate for candidate in _head_cylinder_candidates(head_component_name)
            if candidate in component_names
        ),
        None,
    )
    if cylinder_name:
        cylinder_fields = _component_fields_for_case(rows, cylinder_name, case_label)
        component_map["圆筒"] = cylinder_fields
        component_map[cylinder_name] = cylinder_fields
    else:
        component_map["圆筒"] = {}
        print(
            f"[封头计算书] {head_component_name} 未找到配套圆筒，"
            f"已尝试：{_head_cylinder_candidates(head_component_name)}"
        )
    return component_map


def _head_structural_value(rows, head_component_name, case_labels, field_name):
    """结构型字段若未在当前工况重复输出，则从该封头其它工况补取。"""
    for case_label in case_labels:
        fields = _component_fields_for_case(rows, head_component_name, case_label)
        value = str(fields.get(field_name) or "").strip()
        if value:
            return value
    return ""


def export_fengtou_calculation_doc(
        product_id, save_dir, db_config=None, project_root=None, json_path=None):
    """
    为产品中的每个封头、每个外层工况分别生成 Word 计算书。

    - 封头类型代号：EHA=椭圆形、THA=碟形、HHA=半球形
    - 是否以外径为基准：是=外径、否=内径
    - 当前封头的设计压力 < 0 为外压，否则为内压
    - 模板中的（封头）和（圆筒）只使用当前封头及其配套圆筒的数据
    """
    if db_config is None:
        db_config = {
            "host": "localhost",
            "user": "root",
            "password": "123456",
            "database": "产品设计活动库",
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    project_root = (
        _find_project_root_with_templates(Path(__file__).resolve())
        if project_root is None
        else Path(project_root).resolve()
    )

    conn = None
    try:
        if json_path is not None:
            rows = _load_calculation_rows_from_json(json_path)
        else:
            conn = pymysql.connect(**db_config)
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT *
                FROM 产品设计活动表_元件计算结果表
                WHERE 产品ID = %s
                """,
                (product_id,),
            )
            rows = cursor.fetchall()

        head_components = []
        for row in rows:
            component_name = str(
                _calculation_row_get(row, "元件名称", 0, "") or ""
            ).strip()
            name = str(_calculation_row_get(row, "Name", 1, "") or "").strip()
            if name == "封头类型代号" and component_name not in head_components:
                head_components.append(component_name)

        if not head_components:
            print(f"[封头计算书] 产品ID={product_id} 未找到封头计算结果，不生成计算书。")
            return None

        generated_paths = []
        for head_component_name in head_components:
            case_labels = _find_head_case_labels(rows, head_component_name) or ["工况1"]
            for case_label in case_labels:
                component_map = _build_head_component_map(
                    rows, head_component_name, case_label
                )
                head_fields = component_map["封头"]

                type_code = str(head_fields.get("封头类型代号") or "").strip().upper()
                if not type_code:
                    # 少数旧结果只在首个工况保存结构型参数。
                    type_code = _head_structural_value(
                        rows, head_component_name, case_labels, "封头类型代号"
                    ).upper()
                if type_code not in _HEAD_TYPE_CONFIG:
                    print(
                        f"[封头计算书] 跳过 {head_component_name}/{case_label}："
                        f"不支持的封头类型代号“{type_code}”"
                    )
                    continue

                basis_value = str(
                    head_fields.get("是否以外径为基准") or ""
                ).strip()
                if not basis_value:
                    basis_value = _head_structural_value(
                        rows, head_component_name, case_labels, "是否以外径为基准"
                    )
                if basis_value in ("是", "1", "true", "True", "YES", "Yes", "yes"):
                    diameter_basis = "外径"
                elif basis_value in ("否", "0", "false", "False", "NO", "No", "no"):
                    diameter_basis = "内径"
                else:
                    print(
                        f"[封头计算书] 跳过 {head_component_name}/{case_label}："
                        f"无法根据“是否以外径为基准={basis_value}”判断内径/外径"
                    )
                    continue

                design_pressure = _to_number(head_fields.get("设计压力"))
                pressure_kind = (
                    "外压" if design_pressure is not None and design_pressure < 0 else "内压"
                )
                if design_pressure is None:
                    print(
                        f"[封头计算书] {head_component_name}/{case_label} "
                        f"未读取到设计压力，默认选择内压模板。"
                    )

                shape_name, folder_name = _HEAD_TYPE_CONFIG[type_code]
                template_dir = project_root / "templates" / "calculation_docs" / folder_name
                if not template_dir.exists():
                    raise FileNotFoundError(f"封头模板目录不存在：{template_dir}")
                fragment = f"{shape_name}封头-{diameter_basis}-{pressure_kind}-计算书"
                template_path = _find_head_template(template_dir, fragment)

                doc = Document(str(template_path))
                for paragraph in _iter_all_paragraphs(doc):
                    _replace_placeholders_in_paragraph_by_component_map(
                        paragraph=paragraph,
                        component_map=component_map,
                    )

                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                safe_component_name = re.sub(
                    r'[<>:"/\\|?*]+', "_", head_component_name
                )
                output_path = save_dir / (
                    f"封头计算书_{safe_component_name}_{case_label}_"
                    f"{shape_name}_{diameter_basis}_{pressure_kind}_{timestamp}.docx"
                )
                doc.save(str(output_path))
                generated_paths.append(str(output_path))
                print(
                    f"[封头计算书] {head_component_name}/{case_label}："
                    f"类型={type_code}，口径={diameter_basis}，压力={pressure_kind}，"
                    f"生成成功：{output_path}"
                )

        if not generated_paths:
            return None
        return generated_paths[0] if len(generated_paths) == 1 else generated_paths
    finally:
        if conn:
            conn.close()

def _find_project_root_with_templates(start_path: Path) -> Path:
    start_path = start_path.resolve()
    candidates = [start_path.parent] + list(start_path.parents)

    for p in candidates:
        if (p / "templates" / "calculation_docs").exists():
            return p

    raise FileNotFoundError("未能自动定位项目根目录，请手动传入 project_root。")


def _iter_all_paragraphs(doc: Document):
    for p in doc.paragraphs:
        yield p

    def walk_table(table):
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    yield p
                for nested in cell.tables:
                    yield from walk_table(nested)

    for table in doc.tables:
        yield from walk_table(table)

    for section in doc.sections:
        for p in section.header.paragraphs:
            yield p
        for table in section.header.tables:
            yield from walk_table(table)

        for p in section.footer.paragraphs:
            yield p
        for table in section.footer.tables:
            yield from walk_table(table)



import re


import re


def _replace_placeholders_in_paragraph_by_component_map(paragraph, component_map):
    """
    支持替换：
      材料类型（吊耳）
      材料类型（壳体圆筒）
      系揽环板厚度（吊耳）（隐）
      参数A（带括号说明）（壳体圆筒）
      参数名（锥壳）【工况2】（隐）

    规则：
    - 如果最后一个括号是（隐），则：
        倒数第二个括号 = 元件名称
        前面的全部内容 = 参数名
    - 如果最后一个括号不是（隐），则：
        最后一个括号 = 元件名称
        前面的全部内容 = 参数名
    - 参数名中允许自带括号
    - 支持 【工况1】/【工况2】/【工况3】
    - 带有“计算报告”的标题不替换
    """

    if not paragraph.runs:
        return

    runs = paragraph.runs
    full_text = "".join(run.text or "" for run in runs)
    if not full_text:
        return

    # 匹配：
    #   字段名（元件）
    #   字段名（元件）（隐）
    #   字段名（元件）【工况2】
    #   字段名（元件）【工况2】（隐）
    #   参数A（带括号说明）（壳体圆筒）【工况2】（隐）
    whole_pattern = re.compile(
        r'[^\r\n]+?(?=(?:（[^（）]+）)+)'
        r'(?:（[^（）]+）)+'
        r'(?:【[^】]+】)?'
        r'(?:（隐）)?'
    )

    group_pattern = re.compile(r'（([^（）]+)）')
    condition_pattern = re.compile(r'【([^】]+)】')

    def normalize_work_condition(text):
        """
        将 工况1 / 工况2 / 工况3 / 工况一 / 工况二 / 工况三
        统一为 工况一 / 工况二 / 工况三
        """
        text = str(text or "").strip()
        text = (
            text.replace("１", "1")
                .replace("２", "2")
                .replace("３", "3")
        )

        m = re.search(r'工况\s*([123一二三])', text)
        if not m:
            return None

        flag = m.group(1)
        mapping = {
            "1": "工况一",
            "2": "工况二",
            "3": "工况三",
            "一": "工况一",
            "二": "工况二",
            "三": "工况三",
        }
        return mapping.get(flag)

    def extract_placeholder_condition(raw_text):
        """
        从占位符中的 【工况2】 提取工况。
        例如：
          厚度（锥壳）【工况2】（隐） -> 工况二
        """
        for bm in condition_pattern.finditer(raw_text):
            cond = normalize_work_condition(bm.group(1))
            if cond:
                return cond
        return None

    def extract_condition_from_component_id(component_id):
        """
        从 component_map 的 key/id 中提取真实工况。

        重要规则：
        1. 如果 key 里有括号，例如：
             工况1：锥壳(α1-工况一)131
             工况1：锥壳(正压)124

           那么真实工况只能从括号内容中提取。

           - (α1-工况一) -> 工况一
           - (正压)      -> None，不能回退到前面的 工况1

        2. 只有当 key 中完全没有括号/书名号工况标识时，
           才允许从全文中提取工况。
        """
        text = str(component_id or "").strip()
        if not text:
            return None

        # 1. 优先检查中文/英文括号
        paren_contents = re.findall(r'[（(]([^（）()]*)[）)]', text)
        if paren_contents:
            for content in paren_contents:
                cond = normalize_work_condition(content)
                if cond:
                    return cond

            # 关键：有括号，但括号里不是工况，例如 (正压)
            # 此时不能再从全文开头的“工况1”提取，否则会误匹配
            return None

        # 2. 再检查【】
        bracket_contents = re.findall(r'【([^】]+)】', text)
        if bracket_contents:
            for content in bracket_contents:
                cond = normalize_work_condition(content)
                if cond:
                    return cond

            # 有【】但里面不是工况，也不回退全文
            return None

        # 3. 只有完全没有括号/【】时，才允许从全文提取
        return normalize_work_condition(text)

    def get_component_candidates(component_name):
        """
        返回用于匹配 component_map 的候选元件名称列表
        """
        component_name = (component_name or "").strip()

        if component_name == "壳体圆筒":
            return ["壳体圆筒", "大端壳体圆筒"]

        return [component_name]

    def component_key_matches(component_key, candidate_name):
        """
        判断 component_map 中的 key 是否属于目标元件。

        支持：
          锥壳
          工况1：锥壳(α1-工况三)207

        避免：
          锥壳 匹配到 锥壳大端加强圈、锥壳小端加强圈、锥壳大端圆筒加强段等其它 key
        """
        component_key = str(component_key or "").strip()
        candidate_name = str(candidate_name or "").strip()

        if not component_key or not candidate_name:
            return False

        if component_key == candidate_name:
            return True

        # 去掉前面的 “工况1：”
        pure_key = re.sub(r'^工况\s*[123一二三]\s*[:：]\s*', '', component_key)

        # 去掉尾部编号，例如 207、208
        pure_key = re.sub(r'\d+$', '', pure_key).strip()

        # 取括号前面的主体元件名
        # 例如：
        # 工况1：锥壳(α1-工况三)207 -> 锥壳
        # 锥壳大端加强圈 -> 锥壳大端加强圈
        main_name = re.split(r'[（(【]', pure_key)[0].strip()

        return main_name == candidate_name

    def condition_matches(component_key, wanted_condition):
        """
        判断 component_map 的 key 是否匹配目标工况。
        如果占位符没有写【工况】，则不限制工况。
        如果占位符写了【工况一】，但 key 不能提取出真实工况，则不匹配。
        """
        if not wanted_condition:
            return True

        actual_condition = extract_condition_from_component_id(component_key)

        if not actual_condition:
            return False

        return actual_condition == wanted_condition

    def get_field_value_from_component_data(component_data, field_name, wanted_condition=None):
        """
        从某个元件的数据字典中取字段值。
        支持普通结构：
            component_data[field_name]

        也兼容这种结构：
            component_data[field_name][工况二]
        """
        if not isinstance(component_data, dict):
            return None

        # 1. 普通字段名直接匹配
        if field_name in component_data:
            value = component_data[field_name]

            # 如果 value 本身是按工况分组的 dict
            if wanted_condition and isinstance(value, dict):
                if wanted_condition in value:
                    return value[wanted_condition]

                # 兼容 工况2 / 工况二 混写
                for k, v in value.items():
                    if normalize_work_condition(k) == wanted_condition:
                        return v

            return value

        # 2. 兼容字段名里带工况的情况
        if wanted_condition:
            possible_field_names = [
                f"{field_name}【{wanted_condition}】",
                f"{field_name}（{wanted_condition}）",
                f"{field_name}({wanted_condition})",
            ]

            # 再补充阿拉伯数字形式
            reverse_mapping = {
                "工况一": "工况1",
                "工况二": "工况2",
                "工况三": "工况3",
            }
            num_condition = reverse_mapping.get(wanted_condition)
            if num_condition:
                possible_field_names.extend([
                    f"{field_name}【{num_condition}】",
                    f"{field_name}（{num_condition}）",
                    f"{field_name}({num_condition})",
                ])

            for key in possible_field_names:
                if key in component_data:
                    return component_data[key]

        return None

    matches = list(whole_pattern.finditer(full_text))
    if not matches:
        return

    # 倒序替换，避免索引错位
    for m in reversed(matches):
        raw = m.group(0)

        groups = []
        for gm in group_pattern.finditer(raw):
            g = (gm.group(1) or "").strip()
            groups.append({
                "text": g,
                "start": gm.start(),
                "end": gm.end(),
            })

        if not groups:
            continue

        is_hidden = groups[-1]["text"] == "隐"

        if is_hidden:
            if len(groups) < 2:
                continue

            component_name = groups[-2]["text"]
            field_name = raw[:groups[-2]["start"]].strip()
        else:
            component_name = groups[-1]["text"]
            field_name = raw[:groups[-1]["start"]].strip()

        # 去掉 field_name 末尾可能残留的空格
        field_name = field_name.strip()

        # 提取占位符中的 【工况2】
        wanted_condition = extract_placeholder_condition(raw)

        # ===============================
        # 计算报告标题不参与占位符替换
        # 例如：
        #   偏心锥壳校核计算报告（无折边）
        #   锥壳计算报告（有折边）
        # ===============================
        if "计算报告" in field_name:
            continue

        if "(锥壳大端加强圈)" in field_name:
            continue

        value = None
        component_candidates = get_component_candidates(component_name)

        # 先精确匹配，再模糊匹配
        matched_keys = []

        for candidate_name in component_candidates:
            if candidate_name in component_map:
                if condition_matches(candidate_name, wanted_condition):
                    matched_keys.append(candidate_name)

        for key in component_map.keys():
            for candidate_name in component_candidates:
                if component_key_matches(key, candidate_name):
                    if condition_matches(key, wanted_condition):
                        if key not in matched_keys:
                            matched_keys.append(key)

        for key in matched_keys:
            component_data = component_map.get(key)
            value = get_field_value_from_component_data(
                component_data=component_data,
                field_name=field_name,
                wanted_condition=wanted_condition
            )
            if value is not None:
                break

        if value is None:
            replacement = "-" if is_hidden else ""
        else:
            replacement = str(value)

        _replace_text_range_in_runs(
            runs=runs,
            start=m.start(),
            end=m.end(),
            replacement=replacement,
        )


def _replace_text_range_in_runs(runs, start, end, replacement):
    """
    将拼接后的段落文本中 [start:end) 对应区域替换为 replacement。
    不重建整段，只改对应 run，尽量兼容 Word / WPS。
    """
    char_map = []
    for run_idx, run in enumerate(runs):
        text = run.text or ""
        for char_idx, _ in enumerate(text):
            char_map.append((run_idx, char_idx))

    if not char_map:
        return

    if start < 0 or end > len(char_map) or start >= end:
        return

    start_run_idx, start_char_idx = char_map[start]
    end_run_idx, end_char_idx = char_map[end - 1]

    start_text = runs[start_run_idx].text or ""
    end_text = runs[end_run_idx].text or ""

    prefix = start_text[:start_char_idx]
    suffix = end_text[end_char_idx + 1:]

    if start_run_idx == end_run_idx:
        runs[start_run_idx].text = prefix + replacement + suffix
        return

    runs[start_run_idx].text = prefix + replacement

    for i in range(start_run_idx + 1, end_run_idx):
        runs[i].text = ""

    runs[end_run_idx].text = suffix
