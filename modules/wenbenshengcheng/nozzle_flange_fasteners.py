"""从工程自带的 LiteDB 标准表读取管法兰配用螺柱尺寸。"""
import json
from pathlib import Path
import re
import sys

from modules.wenbenshengcheng.nozzle_flange_materials import _NPS_TO_DN


_CLASS_SMALL = "_20634_DNLess600法兰配用螺柱长度和质量CLASS"
_CLASS_LARGE_A = "_20634_DNAbove600A系列法兰配用螺柱长度和质量CLASS"
_CLASS_LARGE_B = "_20634_DNAbove600B系列法兰配用螺柱长度和质量CLASS"
_PN_PL = "_20613_螺柱的长度和近似质量_板式平焊法兰PN"
_PN_IF = "_20613_螺柱的长度和近似质量_整体法兰PN"
_PN_NECK = "_20613_螺柱的长度和近似质量_带颈平焊_带颈对焊_螺纹以及承插焊法兰PN"
_PN_HIGH = "_20613_螺柱的长度和近似质量_带颈对焊以及承插焊法兰PN"


def _key(value):
    text = str(value or "").strip()
    try:
        return format(float(text), "g")
    except ValueError:
        return text


def _tables_for_nozzle(nozzle):
    standard = re.sub(r"\s+", "", str(nozzle.get("法兰标准") or "")).upper()
    if "HG/T20615" in standard:
        return (_CLASS_SMALL,)
    if "HG/T20623" in standard:
        if re.search(r"[（(]A[）)]", standard):
            return (_CLASS_LARGE_A,)
        if re.search(r"[（(]B[）)]", standard):
            return (_CLASS_LARGE_B,)
        return ()
    if "HG/T20592" not in standard:
        return ()
    flange = str(nozzle.get("法兰型式") or "").strip().upper()
    return {
        "PL": (_PN_PL,), "IF": (_PN_IF,), "SO": (_PN_NECK,), "TH": (_PN_NECK,),
        "WN": (_PN_NECK, _PN_HIGH), "SW": (_PN_NECK, _PN_HIGH),
    }.get(flange, ())


def resolve_nozzle_fastener_dimensions(nozzle, unit_config, tables):
    """精确匹配单位体系和密封面；不把其它压力/尺寸的首条记录当作兜底。"""
    table_names = _tables_for_nozzle(nozzle)
    if not table_names:
        return {}
    size_col = "NPS" if str(unit_config.get("公称尺寸类型") or "DN").upper() == "NPS" else "DN"
    pressure_type = str(unit_config.get("公称压力类型") or (
        "PN" if "20592" in str(nozzle.get("法兰标准")) else "Class"
    )).upper()
    pressure_col = "CLASS" if pressure_type == "CLASS" else "PN"
    face = str(nozzle.get("密封面型式") or "").strip().upper()
    length_col = {"RF": "LZR", "M": "LZM", "FM": "LZM", "MFM": "LZM", "RJ": "LZJ"}.get(face)
    if length_col is None:
        return {}
    for table in table_names:
        for row in tables.get(table, []):
            size_value = _key(nozzle.get("公称尺寸"))
            row_size = _key(row.get(size_col))
            if size_col == "NPS" and "NPS" not in row:
                size_value = _NPS_TO_DN.get(size_value, "")
                row_size = _key(row.get("DN"))
            if (not size_value or not _key(nozzle.get("压力等级"))
                    or row_size != size_value
                    or _key(row.get(pressure_col)) != _key(nozzle.get("压力等级"))):
                continue
            diameter = re.fullmatch(r"M\s*(\d+(?:\.\d+)?)", str(row.get("螺纹") or ""), re.I)
            try:
                length = float(row.get(length_col) or 0)
                quantity = float(row.get("数量") or 0)
            except (ValueError, TypeError):
                continue
            if diameter and length > 0:
                return {"diameter": _key(diameter.group(1)), "length": _key(length),
                        "quantity": quantity if quantity > 0 else None,
                        "nut_quantity": 2 * quantity if quantity > 0 else None}
    return {}


def load_nozzle_fastener_dimensions(nozzle_rows, unit_config=None):
    """每次生成只打开一次标准库，读取后立即释放；产品数据库不发生写入。"""
    needed = {table for nozzle in nozzle_rows for table in _tables_for_nozzle(nozzle)}
    if not needed:
        return {}
    roots = [Path(sys.executable).resolve().parent] if getattr(sys, "frozen", False) else []
    roots.append(Path(__file__).resolve().parents[2])
    if getattr(sys, "_MEIPASS", None):
        roots.append(Path(sys._MEIPASS))
    database_path = next((root / "MyDatabase9.db" for root in roots if (root / "MyDatabase9.db").is_file()), None)
    dll_path = next((root / "LiteDB.dll" for root in roots if (root / "LiteDB.dll").is_file()), None)
    if database_path is None or dll_path is None:
        print("⚠️ 管口紧固件标准库 MyDatabase9.db 或 LiteDB.dll 缺失")
        return {}
    database = None
    try:
        import clr
        from System.Reflection import Assembly
        Assembly.LoadFrom(str(dll_path))
        from LiteDB import BsonDocument, JsonSerializer, LiteDatabase
        database = LiteDatabase(f"Filename={database_path};ReadOnly=true;Connection=shared")
        existing = {str(name) for name in database.GetCollectionNames()}
        tables = {
            name: [json.loads(str(JsonSerializer.Serialize(doc)))
                   for doc in database.GetCollection[BsonDocument](name).FindAll()]
            for name in needed if name in existing
        }
        config = unit_config if isinstance(unit_config, dict) else {}
        return {str(nozzle.get("管口代号") or "").strip(): dimensions
                for nozzle in nozzle_rows
                if (dimensions := resolve_nozzle_fastener_dimensions(nozzle, config, tables))}
    except Exception as exc:
        print(f"⚠️ 读取管口紧固件标准尺寸失败: {exc}")
        return {}
    finally:
        if database is not None:
            database.Dispose()
