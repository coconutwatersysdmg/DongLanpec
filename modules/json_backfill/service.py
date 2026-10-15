from __future__ import annotations

import datetime as dt
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import pymysql


PRODUCT_TYPE = "管壳式热交换器"

DB_PROJECT = "项目需求库"
DB_PRODUCT = "产品需求库"
DB_ACTIVITY = "产品设计活动库"
DB_CONDITION = "产品条件库"
DB_MATERIAL = "材料库"
DB_ELEMENT = "元件库"
DB_DEFINITION = "产品定义库"


@dataclass(frozen=True)
class ProjectMetadata:
    owner: str
    name: str
    save_path: str
    number: str = ""
    department: str = ""
    contractor: str = ""


@dataclass(frozen=True)
class ProductMetadata:
    serial: str
    name: str
    number: str
    device_tag: str = ""
    design_stage: str = ""
    design_revision: str = ""


@dataclass
class ImportResult:
    project_id: str
    product_id: str
    project_folder: str
    product_folder: str
    initialized_rows: int = 0
    updated_rows: int = 0
    warnings: List[str] = field(default_factory=list)
    simulated: bool = False

    def summary(self) -> str:
        state = "模拟成功（已回滚）" if self.simulated else "导入成功"
        lines = [
            state,
            f"项目ID：{self.project_id}",
            f"产品ID：{self.product_id}",
            f"项目目录：{self.project_folder}",
            f"产品目录：{self.product_folder}",
            f"初始化记录：{self.initialized_rows}",
            f"反填记录：{self.updated_rows}",
        ]
        if self.warnings:
            lines.append(f"警告：{len(self.warnings)} 项")
        return "\n".join(lines)


class JsonBackfillError(RuntimeError):
    pass


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _sanitize_folder_part(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", _text(value))


def build_product_folder_name(meta: ProductMetadata) -> str:
    serial = _text(meta.serial)
    if serial.isdigit():
        serial = serial.zfill(3)
    parts = (
        serial,
        meta.name,
        meta.device_tag,
        meta.number,
    )
    return "_".join(
        safe for safe in (_sanitize_folder_part(part) for part in parts) if safe
    )


def component_side(component_name: str) -> Optional[str]:
    name = _text(component_name)
    if any(token in name for token in ("管箱", "管程")):
        return "管程数值"
    if any(token in name for token in ("壳体", "壳程", "外头盖", "浮头")):
        return "壳程数值"
    return None


def nozzle_category(component_name: str, attachment: str = "") -> str:
    side = component_side(component_name) or component_side(attachment)
    return "管口材料分类-管程" if side == "管程数值" else "管口材料分类-壳程"


def reverse_material_type(value: str) -> str:
    return {
        "钢板": "板材",
        "钢锻件": "锻件",
    }.get(_text(value), _text(value))


class JsonBackfillService:
    """创建项目/产品并将计算输入 JSON 反填至业务数据库。

    所有数据库写入使用同一连接跨库事务。文件先构建在同盘临时目录，
    数据准备完成后再原子移动至正式项目目录；任何异常都会回滚数据库
    并清理本次创建的目录。
    """

    CONDITION_TABLES: Tuple[Tuple[str, str, bool], ...] = (
        ("产品标准数据模板表", "产品设计活动表_产品标准数据表", False),
        ("设计数据模板表", "产品设计活动表_设计数据表", True),
        ("通用数据模板表", "产品设计活动表_通用数据表", False),
        ("无损检测数据模板表", "产品设计活动表_无损检测数据表", False),
        ("涂漆数据模板表", "产品设计活动表_涂漆数据表", False),
    )

    COMPONENT_ALIASES: Mapping[str, Tuple[str, ...]] = {
        "管箱分程隔板": ("管箱分程隔板", "分程隔板"),
        "鞍座": ("固定鞍座", "滑动鞍座"),
        "管束": ("U形换热管", "换热管"),
    }

    ELEMENT_PARAM_ALIASES: Mapping[str, Tuple[str, ...]] = {
        "是否覆层": ("是否添加覆层",),
        "覆层复合方式": ("覆层成型工艺",),
        "带覆层时的焊接凹槽深度": ("存在覆层时的焊接凹槽深度",),
        "圆筒带覆层时的焊接凹槽深度": ("存在覆层时的焊接凹槽深度",),
        "椭圆形封头覆层厚度": ("覆层厚度",),
        "圆筒覆层厚度": ("覆层厚度",),
        "法兰材料类型": ("材料类型",),
        "法兰材料牌号": ("材料牌号",),
        "法兰类型": ("法兰类型",),
        "法兰密封面": ("法兰密封面",),
        "轴向外力": ("轴向拉伸载荷",),
        "外力矩": ("附加弯矩",),
    }

    def __init__(
        self,
        db_config: Optional[Mapping[str, Any]] = None,
        template_dir: Optional[str | Path] = None,
    ):
        self.db_config = {
            "host": "localhost",
            "port": 3306,
            "user": "root",
            "password": "123456",
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
            "autocommit": False,
        }
        if db_config:
            self.db_config.update(dict(db_config))

        default_template_dir = Path(__file__).resolve().parents[1] / "chanpinguanli"
        self.template_dir = Path(template_dir or default_template_dir)

    def import_product(
        self,
        data: Mapping[str, Any],
        project: ProjectMetadata,
        product: ProductMetadata,
        *,
        simulate: bool = False,
    ) -> ImportResult:
        exchanger_type = _text(data.get("ExchangerType")).upper()
        if not exchanger_type:
            raise JsonBackfillError("JSON 缺少 ExchangerType。")
        self._validate_metadata(project, product)

        parent = Path(project.save_path).expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        project_folder = parent / f"{project.owner}_{project.name}"
        if project_folder.exists():
            raise JsonBackfillError(f"项目目录已经存在：{project_folder}")

        product_folder_name = build_product_folder_name(product)
        if not product_folder_name:
            raise JsonBackfillError("无法根据产品信息生成产品目录名称。")
        product_folder = project_folder / product_folder_name

        staging_folder: Optional[Path] = None
        moved_folder: Optional[Path] = None
        conn = None
        committed = False

        try:
            conn = pymysql.connect(**self.db_config)
            conn.begin()
            with conn.cursor() as cursor:
                project_id = self._next_id(cursor, DB_PROJECT, "项目需求表", "项目ID", "P")
                product_id = self._next_id(cursor, DB_PRODUCT, "产品需求表", "产品ID", "PD")

                staging_folder = Path(
                    tempfile.mkdtemp(prefix=".json_backfill_", dir=str(parent))
                )
                staged_product_folder = staging_folder / product_folder_name
                self._build_local_files(
                    staging_folder, staged_product_folder, project_id, product_id
                )

                result = ImportResult(
                    project_id=project_id,
                    product_id=product_id,
                    project_folder=str(project_folder),
                    product_folder=str(product_folder),
                    simulated=simulate,
                )

                self._insert_master_rows(
                    cursor,
                    project_id,
                    product_id,
                    exchanger_type,
                    project,
                    product,
                    str(product_folder),
                )
                result.initialized_rows += 3
                result.initialized_rows += self._initialize_condition_tables(
                    cursor, product_id, exchanger_type
                )
                template_id, template_name = self._initialize_material_tables(
                    cursor, product_id, exchanger_type
                )
                result.initialized_rows += self._last_row_count
                result.initialized_rows += self._initialize_tube_layout(
                    cursor, product_id, exchanger_type
                )
                result.updated_rows += self._write_nozzles(
                    cursor, product_id, data.get("TTDict") or {}
                )
                result.updated_rows += self._apply_working_conditions(
                    cursor, product_id, data.get("WSList") or []
                )
                result.updated_rows += self._apply_design_params(
                    cursor, product_id, data.get("DesignParams") or {}
                )
                element_updates, warnings = self._apply_component_data(
                    cursor,
                    product_id,
                    data.get("DictDatas") or {},
                    data.get("TTDict") or {},
                )
                result.updated_rows += element_updates
                result.warnings.extend(warnings)

                if simulate:
                    conn.rollback()
                    return result

                # 数据库事务尚未提交时先把完整的暂存目录移动到最终位置。
                staging_folder.replace(project_folder)
                moved_folder = project_folder
                staging_folder = None
                conn.commit()
                committed = True
                return result

        except Exception as exc:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            if isinstance(exc, JsonBackfillError):
                raise
            raise JsonBackfillError(f"JSON 反填失败：{exc}") from exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            if staging_folder and staging_folder.exists():
                shutil.rmtree(staging_folder, ignore_errors=True)
            if moved_folder and moved_folder.exists() and not committed:
                shutil.rmtree(moved_folder, ignore_errors=True)

    @staticmethod
    def _validate_metadata(project: ProjectMetadata, product: ProductMetadata) -> None:
        required = {
            "业主名称": project.owner,
            "项目名称": project.name,
            "项目保存路径": project.save_path,
            "序号": product.serial,
            "产品名称": product.name,
            "产品编号": product.number,
        }
        missing = [name for name, value in required.items() if not _text(value)]
        if missing:
            raise JsonBackfillError("缺少必填信息：" + "、".join(missing))
        invalid_project_parts = [
            name
            for name, value in (
                ("业主名称", project.owner),
                ("项目名称", project.name),
            )
            if re.search(r'[\\/:*?"<>|]', _text(value))
        ]
        if invalid_project_parts:
            raise JsonBackfillError(
                "以下信息包含 Windows 文件名非法字符："
                + "、".join(invalid_project_parts)
            )

    @staticmethod
    def _next_id(cursor, database: str, table: str, column: str, prefix: str) -> str:
        timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        base = f"{prefix}{timestamp}"
        cursor.execute(
            f"SELECT `{column}` FROM `{database}`.`{table}` "
            f"WHERE `{column}` LIKE %s ORDER BY `{column}` DESC LIMIT 1",
            (f"{base}%",),
        )
        row = cursor.fetchone()
        last = _text(row.get(column)) if row else ""
        try:
            number = int(last[-2:]) + 1 if last.startswith(base) else 1
        except ValueError:
            number = 1
        return f"{base}{number:02d}"

    def _build_local_files(
        self,
        project_folder: Path,
        product_folder: Path,
        project_id: str,
        product_id: str,
    ) -> None:
        product_folder.mkdir(parents=True, exist_ok=False)
        (project_folder / "id.csv").write_text(project_id, encoding="utf-8")
        (product_folder / "pro_id.csv").write_text(product_id, encoding="utf-8")
        for filename in ("条件输入数据表.xlsx", "管口导入模板.xlsx"):
            source = self.template_dir / filename
            if not source.is_file():
                raise JsonBackfillError(f"缺少本地模板文件：{source}")
            shutil.copy2(source, product_folder / filename)

    @staticmethod
    def _insert_master_rows(
        cursor,
        project_id: str,
        product_id: str,
        exchanger_type: str,
        project: ProjectMetadata,
        product: ProductMetadata,
        product_folder: str,
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO `{DB_PROJECT}`.`项目需求表`
              (`项目ID`, `业主名称`, `项目编号`, `项目名称`, `所属部门`,
               `工程总包方`, `建立日期`, `项目保存路径`)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                project_id,
                project.owner,
                project.number,
                project.name,
                project.department,
                project.contractor,
                dt.date.today(),
                str(Path(project.save_path).resolve()),
            ),
        )

        cursor.execute(
            f"""
            SELECT `产品示意图`
            FROM `{DB_DEFINITION}`.`产品类型型式表`
            WHERE `产品类型`=%s AND `产品型式`=%s
            LIMIT 1
            """,
            (PRODUCT_TYPE, exchanger_type),
        )
        definition = cursor.fetchone()
        if not definition:
            raise JsonBackfillError(f"产品定义库中没有产品型式 {exchanger_type}。")

        cursor.execute(
            f"""
            INSERT INTO `{DB_PRODUCT}`.`产品需求表`
              (`项目ID`, `产品ID`, `产品编号`, `产品名称`, `产品型号`, `设备位号`,
               `产品类型`, `产品型式`, `设计阶段`, `设计版次`, `产品示意图`)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                project_id,
                product_id,
                product.number,
                product.name,
                "",
                product.device_tag,
                PRODUCT_TYPE,
                exchanger_type,
                product.design_stage,
                product.design_revision,
                definition["产品示意图"],
            ),
        )
        cursor.execute(
            f"""
            INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表`
              (`项目ID`, `产品ID`, `产品类型`, `产品型式`, `产品文件夹绝对路径`)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, product_id, PRODUCT_TYPE, exchanger_type, product_folder),
        )

    @staticmethod
    def _columns(cursor, database: str, table: str) -> List[str]:
        cursor.execute(
            """
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s
            ORDER BY ORDINAL_POSITION
            """,
            (database, table),
        )
        return [row["COLUMN_NAME"] for row in cursor.fetchall()]

    def _initialize_condition_tables(
        self, cursor, product_id: str, exchanger_type: str
    ) -> int:
        total = 0
        for source, target, form_dependent in self.CONDITION_TABLES:
            source_cols = self._columns(cursor, DB_CONDITION, source)
            target_cols = self._columns(cursor, DB_ACTIVITY, target)
            excluded = {"所属类型", "所属型式", "产品ID"}
            common = [
                col
                for col in source_cols
                if col in target_cols and col not in excluded
            ]
            if not common:
                raise JsonBackfillError(f"模板表 {source} 与活动表 {target} 没有公共字段。")

            insert_cols = ", ".join(f"`{col}`" for col in ("产品ID", *common))
            select_cols = ", ".join(f"`{col}`" for col in common)
            sql = (
                f"INSERT INTO `{DB_ACTIVITY}`.`{target}` ({insert_cols}) "
                f"SELECT %s, {select_cols} FROM `{DB_CONDITION}`.`{source}`"
            )
            params: List[Any] = [product_id]
            if form_dependent:
                sql += " WHERE `所属型式`=%s OR FIND_IN_SET(%s, `所属型式`)"
                params.extend(("all", exchanger_type))
            cursor.execute(sql, tuple(params))
            total += max(cursor.rowcount, 0)
        return total

    def _initialize_material_tables(
        self, cursor, product_id: str, exchanger_type: str
    ) -> Tuple[int, str]:
        self._last_row_count = 0
        cursor.execute(
            f"""
            SELECT `模板ID`, `模板名称`
            FROM `{DB_MATERIAL}`.`元件材料模板表`
            WHERE `模板名称`='None' AND `所属类型`=%s AND `所属形式`=%s
            ORDER BY `模板ID`
            LIMIT 1
            """,
            (PRODUCT_TYPE, exchanger_type),
        )
        template = cursor.fetchone()
        if not template:
            raise JsonBackfillError(f"材料库中没有 {exchanger_type} 的 None 模板。")
        template_id = template["模板ID"]
        template_name = template["模板名称"]

        cursor.execute(
            f"""
            INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_元件材料表`
              (`元件ID`, `产品ID`, `模板名称`, `元件名称`, `定义状态`, `所处部件`,
               `材料类型`, `元件示意图`, `材料牌号`, `供货状态`, `材料标准`, `有无覆层`)
            SELECT `元件ID`, %s, `模板名称`, `元件名称`, `定义状态`, `所处部件`,
                   `材料类型`, `元件示意图`, `材料牌号`, `供货状态`, `材料标准`, `有无覆层`
            FROM `{DB_MATERIAL}`.`元件材料模板表`
            WHERE `模板ID`=%s
            """,
            (product_id, template_id),
        )
        self._last_row_count += max(cursor.rowcount, 0)

        cursor.execute(
            f"""
            INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_元件附加参数表`
              (`元件附加参数ID`, `产品ID`, `元件ID`, `元件名称`,
               `参数名称`, `参数值`, `参数单位`)
            SELECT `元件附加参数ID`, %s, `元件ID`, `元件名称`,
                   `参数名称`, `参数数值`, `参数单位`
            FROM `{DB_MATERIAL}`.`元件附加参数表`
            WHERE `模板ID`=%s
            """,
            (product_id, template_id),
        )
        self._last_row_count += max(cursor.rowcount, 0)

        cursor.execute(
            f"""
            INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_元件附加参数合并表`
              (`产品ID`, `元件ID`, `参数名称`, `参数值`, `参数单位`,
               `Tab分类`, `模板名称`, `模板ID`)
            SELECT %s, `元件ID`, `参数名称`, `参数值`, `参数单位`,
                   `Tab分类`, %s, `模板ID`
            FROM `{DB_MATERIAL}`.`元件附加参数合并表`
            WHERE `模板ID`=%s
            """,
            (product_id, template_name, template_id),
        )
        self._last_row_count += max(cursor.rowcount, 0)

        cursor.execute(
            f"""
            INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_管口附加参数表`
              (`管口零件参数ID`, `产品ID`, `参数名称`, `参数值`,
               `参数单位`, `类别`, `模板名称`, `模板ID`)
            SELECT `管口附加参数ID`, %s, `参数名称`, `参数数值`,
                   `参数单位`, `所属分类`, %s, `模板ID`
            FROM `{DB_MATERIAL}`.`管口附加参数表`
            WHERE `模板ID`=%s
            """,
            (product_id, template_name, template_id),
        )
        self._last_row_count += max(cursor.rowcount, 0)
        return template_id, template_name

    @staticmethod
    def _initialize_tube_layout(cursor, product_id: str, exchanger_type: str) -> int:
        source = (
            "布管参数默认表_u型管"
            if exchanger_type in {"AEU", "BEU", "AKU", "BKU"}
            else "布管参数默认表_浮头式"
        )
        cursor.execute(
            f"""
            INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_布管参数表`
              (`产品ID`, `参数名`, `参数值`, `单位`)
            SELECT %s, `参数名`, `参数值`, `单位`
            FROM `{DB_ELEMENT}`.`{source}`
            """,
            (product_id,),
        )
        return max(cursor.rowcount, 0)

    @staticmethod
    def _write_nozzles(
        cursor, product_id: str, nozzles: Mapping[str, Any]
    ) -> int:
        updated = 0
        first = next(iter(nozzles.values()), {}) if nozzles else {}
        cursor.execute(
            f"""
            INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_管口类型选择表`
              (`产品ID`, `公称尺寸类型`, `公称压力类型`, `焊端规格类型`)
            VALUES (%s, %s, %s, %s)
            """,
            (
                product_id,
                _text(first.get("ttDType"), "DN"),
                _text(first.get("ttPType"), "PN"),
                "mm",
            ),
        )
        updated += max(cursor.rowcount, 0)

        for index, (dict_code, raw) in enumerate(nozzles.items(), start=1):
            item = raw if isinstance(raw, Mapping) else {}
            code = _text(item.get("ttCode")) or _text(dict_code)
            attachment = _text(item.get("ttAttach"))
            place = {
                "左轮廓线": "左基准线",
                "右轮廓线": "右基准线",
            }.get(_text(item.get("ttPlace")), _text(item.get("ttPlace")))
            location = _text(item.get("ttLoc"))
            if location == "默认":
                location = "程序推荐"
            spec = _text(item.get("ttSpec"))
            if spec == "默认":
                spec = "程序推荐"
            height = _text(item.get("ttH"))
            if height in ("", "0"):
                height = "程序推荐"

            cursor.execute(
                f"""
                INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_管口表`
                  (`管口ID`, `产品ID`, `管口代号`, `管口功能`, `管口用途`,
                   `公称尺寸`, `法兰标准`, `压力等级`, `法兰型式`, `密封面型式`,
                   `焊端规格`, `管口所属元件`, `轴向定位基准`, `轴向定位距离`,
                   `轴向夹角（°）`, `周向方位（°）`, `偏心距`, `外伸高度`)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    index,
                    product_id,
                    code,
                    _text(item.get("ttUse")),
                    "",
                    _text(item.get("ttDN")),
                    _text(item.get("ttMemo")),
                    _text(item.get("ttPClass")),
                    _text(item.get("ttType")),
                    _text(item.get("ttRF")),
                    spec,
                    attachment,
                    place,
                    location,
                    _text(item.get("ttAngel"), "0"),
                    _text(item.get("ttFW"), "0"),
                    _text(item.get("ttThita"), "0"),
                    height,
                ),
            )
            updated += max(cursor.rowcount, 0)
            cursor.execute(
                f"""
                INSERT INTO `{DB_ACTIVITY}`.`产品设计活动表_管口类别表`
                  (`管口ID`, `产品ID`, `管口代号`, `材料分类`, `管口所属元件`)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    index,
                    product_id,
                    code,
                    nozzle_category(_text(item.get("ttUse")), attachment),
                    attachment,
                ),
            )
            updated += max(cursor.rowcount, 0)
        return updated

    @staticmethod
    def _update_design(
        cursor,
        product_id: str,
        parameter_names: Iterable[str],
        shell_value: Optional[str] = None,
        tube_value: Optional[str] = None,
    ) -> int:
        assignments: List[str] = []
        values: List[Any] = []
        if shell_value is not None:
            assignments.append("`壳程数值`=%s")
            values.append(shell_value)
        if tube_value is not None:
            assignments.append("`管程数值`=%s")
            values.append(tube_value)
        if not assignments:
            return 0
        names = tuple(parameter_names)
        placeholders = ",".join(["%s"] * len(names))
        values.extend((product_id, *names))
        cursor.execute(
            f"""
            UPDATE `{DB_ACTIVITY}`.`产品设计活动表_设计数据表`
            SET {", ".join(assignments)}
            WHERE `产品ID`=%s AND `参数名称` IN ({placeholders})
            """,
            tuple(values),
        )
        return max(cursor.rowcount, 0)

    def _apply_working_conditions(
        self, cursor, product_id: str, conditions: List[Mapping[str, Any]]
    ) -> int:
        updated = 0
        if conditions:
            row = conditions[0]
            updated += self._update_design(
                cursor,
                product_id,
                ("设计压力*",),
                _text(row.get("ShellWorkingPressure"), "0"),
                _text(row.get("TubeWorkingPressure"), "0"),
            )
            updated += self._update_design(
                cursor,
                product_id,
                ("设计温度（最高）*",),
                _text(row.get("ShellWorkingTemperature"), "0"),
                _text(row.get("TubeWorkingTemperature"), "0"),
            )
        if len(conditions) > 1:
            row = conditions[1]
            updated += self._update_design(
                cursor,
                product_id,
                ("设计压力*[工况2]", "设计压力2（设计工况2）"),
                _text(row.get("ShellWorkingPressure"), "0"),
                _text(row.get("TubeWorkingPressure"), "0"),
            )
            updated += self._update_design(
                cursor,
                product_id,
                ("设计温度（最高）*[工况2]", "设计温度2（设计工况2）"),
                _text(row.get("ShellWorkingTemperature"), "0"),
                _text(row.get("TubeWorkingTemperature"), "0"),
            )
        return updated

    def _apply_design_params(
        self, cursor, product_id: str, params: Mapping[str, Any]
    ) -> int:
        updated = 0
        diameter = _text(params.get("公称直径"))
        if diameter:
            updated += self._update_design(
                cursor, product_id, ("公称直径*",), diameter, diameter
            )
        insulation = _text(params.get("绝热厚度"))
        if insulation:
            updated += self._update_design(
                cursor,
                product_id,
                ("绝热材料厚度", "绝热层厚度"),
                insulation,
                insulation,
            )
        basis = _text(params.get("是否以外径为基准"))
        if basis:
            cursor.execute(
                f"""
                UPDATE `{DB_ACTIVITY}`.`产品设计活动表_通用数据表`
                SET `数值`=%s
                WHERE `产品ID`=%s AND `参数名称`='是否以外径为基准*'
                """,
                ("是" if basis in ("1", "True", "true", "是") else "否", product_id),
            )
            updated += max(cursor.rowcount, 0)
        tube_form = _text(params.get("管/壳程布置型式"))
        if tube_form:
            cursor.execute(
                f"""
                UPDATE `{DB_ACTIVITY}`.`产品设计活动表_布管参数表`
                SET `参数值`=%s
                WHERE `产品ID`=%s AND `参数名`='管程分程形式'
                """,
                (tube_form, product_id),
            )
            updated += max(cursor.rowcount, 0)
        return updated

    def _component_names(self, json_name: str) -> Tuple[str, ...]:
        return self.COMPONENT_ALIASES.get(json_name, (json_name,))

    @staticmethod
    def _parameter_value(json_name: str, db_name: str, value: Any) -> str:
        text = _text(value)
        if db_name == "是否添加覆层":
            return "是" if text in ("1", "True", "true", "是") else "否"
        if "材料类型" in db_name:
            return reverse_material_type(text)
        return text

    def _apply_component_data(
        self,
        cursor,
        product_id: str,
        components: Mapping[str, Any],
        nozzles: Mapping[str, Any],
    ) -> Tuple[int, List[str]]:
        updated = 0
        warnings: List[str] = []
        nozzle_by_key: Dict[str, Mapping[str, Any]] = {}
        for _, raw in nozzles.items():
            if isinstance(raw, Mapping):
                use = _text(raw.get("ttUse"))
                if use:
                    nozzle_by_key[f"{use}接管"] = raw

        for json_component, raw_params in components.items():
            if not isinstance(raw_params, Mapping):
                continue
            if json_component.endswith("接管"):
                nozzle = nozzle_by_key.get(json_component, {})
                category = nozzle_category(
                    json_component, _text(nozzle.get("ttAttach"))
                )
                missed = 0
                for param_name, value in raw_params.items():
                    cursor.execute(
                        f"""
                        UPDATE `{DB_ACTIVITY}`.`产品设计活动表_管口附加参数表`
                        SET `参数值`=%s
                        WHERE `产品ID`=%s AND `类别`=%s AND `参数名称`=%s
                        """,
                        (
                            self._parameter_value(param_name, param_name, value),
                            product_id,
                            category,
                            param_name,
                        ),
                    )
                    if cursor.rowcount:
                        updated += cursor.rowcount
                    else:
                        missed += 1
                if missed:
                    warnings.append(
                        f"{json_component} 有 {missed} 个计算派生字段无需直接写入管口参数表。"
                    )
                continue

            db_components = self._component_names(json_component)
            missed = 0
            for json_param, value in raw_params.items():
                candidates = (json_param, *self.ELEMENT_PARAM_ALIASES.get(json_param, ()))
                matched = False
                for db_component in db_components:
                    for db_param in candidates:
                        db_value = self._parameter_value(json_param, db_param, value)
                        cursor.execute(
                            f"""
                            UPDATE `{DB_ACTIVITY}`.`产品设计活动表_元件附加参数表`
                            SET `参数值`=%s
                            WHERE `产品ID`=%s AND `元件名称`=%s AND `参数名称`=%s
                            """,
                            (db_value, product_id, db_component, db_param),
                        )
                        if cursor.rowcount:
                            updated += cursor.rowcount
                            matched = True

                        cursor.execute(
                            f"""
                            UPDATE `{DB_ACTIVITY}`.`产品设计活动表_元件附加参数合并表` m
                            JOIN `{DB_ACTIVITY}`.`产品设计活动表_元件材料表` e
                              ON e.`产品ID`=m.`产品ID`
                             AND CAST(e.`元件ID` AS CHAR)=CAST(m.`元件ID` AS CHAR)
                            SET m.`参数值`=%s
                            WHERE m.`产品ID`=%s
                              AND e.`元件名称`=%s
                              AND m.`参数名称`=%s
                            """,
                            (db_value, product_id, db_component, db_param),
                        )
                        if cursor.rowcount:
                            updated += cursor.rowcount
                            matched = True

                        if db_param in ("材料类型", "材料牌号"):
                            cursor.execute(
                                f"""
                                UPDATE `{DB_ACTIVITY}`.`产品设计活动表_元件材料表`
                                SET `{db_param}`=%s
                                WHERE `产品ID`=%s AND `元件名称`=%s
                                """,
                                (db_value, product_id, db_component),
                            )
                            if cursor.rowcount:
                                updated += cursor.rowcount
                                matched = True
                if not matched:
                    missed += 1

                side = component_side(json_component)
                design_map = {
                    "公称直径": "公称直径*",
                    "液柱静压力": "液柱静压力",
                    "腐蚀余量": "腐蚀裕量*",
                    "腐蚀裕量": "腐蚀裕量*",
                    "焊接接头系数": "焊接接头系数*",
                    "耐压试验温度": "耐压试验温度",
                    "压力试验温度": "耐压试验温度",
                }
                if side and json_param in design_map:
                    kwargs = {
                        "shell_value": _text(value) if side == "壳程数值" else None,
                        "tube_value": _text(value) if side == "管程数值" else None,
                    }
                    changed = self._update_design(
                        cursor,
                        product_id,
                        (design_map[json_param],),
                        **kwargs,
                    )
                    updated += changed
                    if changed:
                        missed = max(0, missed - 1)

            if missed:
                warnings.append(
                    f"{json_component} 有 {missed} 个计算派生字段未直接写库。"
                )
        return updated, warnings
