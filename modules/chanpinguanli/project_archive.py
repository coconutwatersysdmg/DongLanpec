"""项目级 .dlpec 文件：所选产品的数据库快照和本地文件，跨库单事务恢复。"""
import base64
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
import zipfile

FORMAT = "DongLanpec.project"
VERSION = 1
EXTENSION = ".dlpec"
DATABASES = ("项目需求库", "产品需求库", "产品设计活动库", "产品定义库", "产品条件库")
PROJECT_TABLE = ("项目需求库", "项目需求表")
PRODUCT_TABLE = ("产品需求库", "产品需求表")
ACTIVITY_TABLE = ("产品设计活动库", "产品设计活动表")
CONFIG_TABLE = ("配置库", "user_config_beifen")


class ArchiveError(ValueError):
    pass


def connect():
    # 同一个连接使用完整库名，避免分别 commit 导致部分库导入成功。
    from modules.chanpinguanli.common_usage import get_mysql_connection_project
    return get_mysql_connection_project()


def quote(name):
    return "`" + name.replace("`", "``") + "`"


def table_sql(key):
    return ".".join(quote(part) for part in key)


def _encode(value):
    if isinstance(value, (bytes, bytearray)):
        return {"$type": "bytes", "value": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return {"$type": "decimal", "value": str(value)}
    if isinstance(value, datetime):
        return {"$type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"$type": "date", "value": value.isoformat()}
    if isinstance(value, time):
        return {"$type": "time", "value": value.isoformat()}
    if isinstance(value, timedelta):
        return {"$type": "timedelta", "value": str(value.total_seconds())}
    raise TypeError(f"不支持的数据类型：{type(value).__name__}")


def _decode(value):
    if set(value) == {"$type", "value"}:
        parsers = {"bytes": lambda v: base64.b64decode(v, validate=True),
                   "decimal": Decimal, "datetime": datetime.fromisoformat,
                   "date": date.fromisoformat, "time": time.fromisoformat,
                   "timedelta": lambda v: timedelta(seconds=float(v))}
        if value["$type"] not in parsers:
            raise ArchiveError("文件中存在不支持的数据类型。")
        return parsers[value["$type"]](value["value"])
    return value


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, default=_encode,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def _schema(conn):
    """从实际结构识别作用域；优先产品ID，绝不按项目ID带入未选产品。"""
    placeholders = ",".join(["%s"] * len(DATABASES))
    with conn.cursor() as cur:
        cur.execute(f"SELECT c.TABLE_SCHEMA,c.TABLE_NAME,c.COLUMN_NAME,c.EXTRA,c.COLUMN_KEY,"
                    f"t.ENGINE FROM information_schema.COLUMNS c JOIN information_schema.TABLES t "
                    f"ON c.TABLE_SCHEMA=t.TABLE_SCHEMA AND c.TABLE_NAME=t.TABLE_NAME "
                    f"WHERE c.TABLE_SCHEMA IN ({placeholders}) AND t.TABLE_TYPE='BASE TABLE' "
                    f"ORDER BY c.TABLE_SCHEMA,c.TABLE_NAME,c.ORDINAL_POSITION", DATABASES)
        rows = cur.fetchall()
    tables = defaultdict(lambda: {"columns": [], "auto": [], "primary": [], "engine": None})
    for row in rows:
        meta = tables[(row["TABLE_SCHEMA"], row["TABLE_NAME"])]
        col = row["COLUMN_NAME"]
        # 生成列由 MySQL 计算，不直接写入。
        if "GENERATED" not in row["EXTRA"].upper():
            meta["columns"].append(col)
        if "auto_increment" in row["EXTRA"].lower():
            meta["auto"].append(col)
        if row["COLUMN_KEY"] == "PRI":
            meta["primary"].append(col)
        meta["engine"] = row["ENGINE"]
    return {key: dict(meta, scope="产品ID" if "产品ID" in meta["columns"] else "项目ID")
            for key, meta in tables.items()
            if "产品ID" in meta["columns"] or "项目ID" in meta["columns"]}


def _where(scope, project_id, product_ids):
    if scope == "产品ID":
        return f"`产品ID` IN ({','.join(['%s'] * len(product_ids))})", tuple(product_ids)
    return "`项目ID`=%s", (project_id,)


def project_root(project):
    parent = str(project.get("项目保存路径") or "").strip()
    if not parent:
        raise ArchiveError("项目尚未登记保存路径，请先保存项目信息。")
    return Path(parent).absolute() / folder_component(
        f"{project.get('业主名称') or ''}_{project.get('项目名称') or ''}")


def folder_component(value):
    value = str(value).strip()
    if (not value or value in (".", "..") or re.search(r'[\\/:*?"<>|\x00-\x1f]', value)
            or value.endswith((".", " "))
            or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", value, re.I)):
        raise ArchiveError(f"不合法的目录名称：{value!r}")
    return value


def load_project(project_id, connection_factory=None):
    conn = (connection_factory or connect)()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_sql(PROJECT_TABLE)} WHERE 项目ID=%s", (project_id,))
            project = cur.fetchone()
            if not project:
                raise ArchiveError("当前项目不存在，请先保存项目。")
            cur.execute(f"SELECT * FROM {table_sql(PRODUCT_TABLE)} WHERE 项目ID=%s ORDER BY 产品ID",
                        (project_id,))
            return project, cur.fetchall()
    finally:
        conn.close()


def _product_folder(root, product, activity, serial):
    stored = str(activity.get("产品文件夹绝对路径") or "").strip()
    if stored and Path(stored).is_dir():
        folder = Path(stored).absolute()
    else:
        matches = []
        if root.is_dir():
            for child in root.iterdir():
                marker = child / "pro_id.csv"
                if child.is_dir() and marker.is_file():
                    if marker.read_text(encoding="utf-8-sig").strip() == str(product["产品ID"]):
                        matches.append(child)
        if len(matches) > 1:
            raise ArchiveError(f"产品 {product['产品ID']} 存在多个本地目录，请先核对路径。")
        folder = matches[0] if matches else root / folder_component(
            f"{serial:03d}_{product.get('产品名称') or ''}_{product.get('设备位号') or ''}_"
            f"{product.get('产品编号') or ''}")
    if not folder.is_dir():
        raise ArchiveError(f"产品本地目录不存在，请在项目管理中恢复后保存：\n{folder}")
    marker = folder / "pro_id.csv"
    if marker.is_file() and marker.read_text(encoding="utf-8-sig").strip() != str(product["产品ID"]):
        raise ArchiveError(f"产品目录标识与数据库不一致：\n{folder}")
    folder_component(folder.name)
    return folder


def _skip_file(name):
    return name.startswith("~$") or name.lower().endswith((".dwl", ".dwl2", EXTENSION, ".partial"))


def _walk_files(folder):
    for current, dirs, files in os.walk(folder):
        for name in list(dirs) + files:
            entry = Path(current) / name
            attributes = getattr(entry.lstat(), "st_file_attributes", 0)
            if entry.is_symlink() or attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise ArchiveError(f"本地目录包含链接，不能可靠保存：{entry}")
        dirs[:] = [name for name in dirs if not _skip_file(name)]
        for name in sorted(files):
            if not _skip_file(name):
                path = Path(current) / name
                yield path, path.relative_to(folder).as_posix()


def _strings(value):
    if isinstance(value, str):
        yield value
        if value.lstrip().startswith(("{", "[")):
            try:
                yield from _strings(json.loads(value))
            except (ValueError, TypeError):
                pass
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def export_project(project_id, product_ids, connection_factory=None, progress=None):
    factory = connection_factory or connect
    ids = list(dict.fromkeys(str(v) for v in product_ids))
    if not ids:
        raise ArchiveError("请至少选择一个产品。")
    conn = factory()
    partial = None
    try:
        schema = _schema(conn)
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cur.execute(f"SELECT * FROM {table_sql(PROJECT_TABLE)} WHERE 项目ID=%s", (project_id,))
            project = cur.fetchone()
            if not project:
                raise ArchiveError("项目不存在。")
            cur.execute(f"SELECT * FROM {table_sql(PRODUCT_TABLE)} WHERE 项目ID=%s ORDER BY 产品ID", (project_id,))
            all_products = cur.fetchall()
            products = [r for r in all_products if str(r["产品ID"]) in ids]
            if len(products) != len(ids):
                raise ArchiveError("所选产品不属于当前项目或已被删除，请重新选择。")
            tables = []
            for index, (key, meta) in enumerate(schema.items()):
                if progress:
                    progress(f"读取数据库 {index + 1}/{len(schema)}：{key[1]}")
                where, args = _where(meta["scope"], project_id, ids)
                cur.execute(f"SELECT {','.join(quote(c) for c in meta['columns'])} "
                            f"FROM {table_sql(key)} WHERE {where}", args)
                tables.append(dict(database=key[0], table=key[1], scope=meta["scope"],
                                   columns=meta["columns"], rows=cur.fetchall()))
            activities = {str(r["产品ID"]): r for t in tables
                          if (t["database"], t["table"]) == ACTIVITY_TABLE for r in t["rows"]}
            configurations = []
            for name in sorted({r.get("预定义配置") for r in activities.values() if r.get("预定义配置")}):
                cur.execute(f"SELECT * FROM {table_sql(CONFIG_TABLE)} WHERE BINARY name=BINARY %s ORDER BY id", (name,))
                rows = cur.fetchall()
                if not rows:
                    cur.execute("SELECT * FROM `配置库`.`user_config` WHERE BINARY name=BINARY %s ORDER BY id", (name,))
                    rows = cur.fetchall()
                if not rows:
                    raise ArchiveError(f"产品绑定的预定义配置“{name}”不存在，不能完整保存。")
                configurations.append(dict(name=name, rows=rows))
        conn.rollback()
        root = project_root(project)
        if not root.is_dir():
            raise ArchiveError(f"项目目录不存在：\n{root}")
        selected = []
        sources = []
        path_maps = []
        product_dirs = set()
        for serial, product in enumerate(all_products, 1):
            if str(product["产品ID"]) not in ids:
                continue
            folder = _product_folder(root, product, activities.get(str(product["产品ID"]), {}), serial)
            product_dirs.add(os.path.normcase(str(folder)))
            archive_dir = f"products/{len(selected):03d}"
            selected.append(dict(id=str(product["产品ID"]), folder=folder.name, source=str(folder),
                                 archive_dir=archive_dir))
            path_maps.append(dict(source=str(folder), target=archive_dir))
            for path, rel in _walk_files(folder):
                if rel != "pro_id.csv":
                    sources.append((path, f"{archive_dir}/{rel}"))
            # 产品定义的示意图通常相对项目管理模块保存，将快照随产品携带。
            illustration = str(product.get("产品示意图") or "").strip()
            if illustration:
                image_path = Path(illustration.replace("\\", os.sep))
                if not image_path.is_absolute():
                    image_path = Path(__file__).resolve().parent / image_path
                if not image_path.is_file():
                    raise ArchiveError(f"产品示意图不存在，不能完整保存：\n{image_path}")
                if folder in image_path.parents:
                    rel = f"{archive_dir}/{image_path.relative_to(folder).as_posix()}"
                else:
                    rel = f"{archive_dir}/产品示意图/{folder_component(image_path.name)}"
                    # 产品定义重新选择模板后，目录内可能仍保留上一张快照。
                    # 两者都保留，当前定义指向本次保存的快照。
                    taken = {name.casefold() for _, name in sources}
                    index = 2
                    while rel.casefold() in taken:
                        rel = f"{archive_dir}/产品示意图/{index}_{image_path.name}"
                        index += 1
                    sources.append((image_path, rel))
                path_maps.append(dict(source=illustration, target=rel))
            # 捕获数据库直接/JSON 引用、但放在产品目录之外的图纸及计算文件。
            seen = set()
            for table in tables:
                for row in table["rows"]:
                    if str(row.get("产品ID") or "") != str(product["产品ID"]):
                        continue
                    for value in _strings(row):
                        path = Path(value)
                        try:
                            if not path.is_absolute() or not path.is_file() or _skip_file(path.name):
                                continue
                            if folder in path.parents or root in path.parents or value in seen:
                                continue
                        except OSError:
                            continue
                        seen.add(value)
                        rel = f"{archive_dir}/外部文件/{hashlib.sha256(value.encode('utf8')).hexdigest()[:12]}_{path.name}"
                        sources.append((path, rel))
                        path_maps.append(dict(source=value, target=rel))
        # 项目共享文件；标准产品目录及带 pro_id 的目录均排除，防止带入未选产品。
        for child in root.iterdir():
            if child.name == "id.csv" or _skip_file(child.name):
                continue
            if child.is_dir():
                if (os.path.normcase(str(child)) in product_dirs or (child / "pro_id.csv").exists()
                        or re.match(r"^\d+_", child.name)):
                    continue
                for path, rel in _walk_files(child):
                    sources.append((path, f"project/{child.name}/{rel}"))
            elif child.is_file():
                sources.append((child, f"project/{child.name}"))
        now = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output = root / f"{folder_component(str(project.get('项目名称') or '项目'))}_{len(ids)}个产品_{now}{EXTENSION}"
        partial = output.with_suffix(EXTENSION + ".partial")
        manifest = dict(format=FORMAT, version=VERSION, created_at=datetime.now(timezone.utc).isoformat(),
                        project_id=str(project_id), project=project, source_root=str(root),
                        products=selected, tables=tables, configurations=configurations,
                        path_maps=path_maps, files=[])
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for index, (path, name) in enumerate(sources):
                if progress:
                    progress(f"保存本地文件 {index + 1}/{len(sources)}：{path.name}")
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as source, archive.open(name, "w", force_zip64=True) as dest:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        dest.write(block)
                        digest.update(block)
                        size += len(block)
                manifest["files"].append(dict(path=name, size=size, sha256=digest.hexdigest()))
            _validate_manifest(manifest)
            archive.writestr("manifest.json", _json_bytes(manifest))
        os.replace(partial, output)
        return str(output)
    finally:
        conn.rollback()
        conn.close()
        if partial and partial.exists():
            partial.unlink()


def _safe_member(name):
    if not isinstance(name, str) or "\\" in name:
        raise ArchiveError("文件内路径不合法。")
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or str(path) != name:
        raise ArchiveError("文件内路径不合法。")
    for part in path.parts:
        folder_component(part)
    return path


def read_archive(filename):
    """读取并校验作用域，文件不携带可执行 SQL。"""
    try:
        with zipfile.ZipFile(filename) as archive:
            names = archive.namelist()
            if len(names) != len(set(n.casefold() for n in names)):
                raise ArchiveError("文件包含重复路径。")
            if archive.getinfo("manifest.json").file_size > 256 * 1024 * 1024:
                raise ArchiveError("项目数据清单过大。")
            manifest = json.loads(archive.read("manifest.json"), object_hook=_decode)
            _validate_manifest(manifest)
            expected = {"manifest.json"} | {f["path"] for f in manifest["files"]}
            if set(names) != expected:
                raise ArchiveError("文件清单与包内容不一致。")
            for entry in manifest["files"]:
                info = archive.getinfo(entry["path"])
                if info.file_size != entry["size"] or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ArchiveError("本地文件长度或类型不合法。")
            return manifest
    except ArchiveError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError, TypeError, ValueError) as exc:
        raise ArchiveError(f"无法读取 DongLanpec 项目文件：{exc}") from exc


def _validate_manifest(m):
    if m["format"] != FORMAT or m["version"] != VERSION:
        raise ArchiveError("不是受支持的 DongLanpec 项目文件。")
    project_id = m["project_id"]
    if not project_id or str(m["project"]["项目ID"]) != project_id:
        raise ArchiveError("项目标识不一致。")
    ids = [p["id"] for p in m["products"]]
    if not ids or len(ids) != len(set(ids)) or any(not i for i in ids):
        raise ArchiveError("产品清单不合法。")
    dirs = set()
    folders = set()
    for p in m["products"]:
        folder_component(p["folder"])
        path = _safe_member(p["archive_dir"])
        if len(path.parts) != 2 or path.parts[0] != "products":
            raise ArchiveError("产品目录不合法。")
        if p["archive_dir"] in dirs or p["folder"].casefold() in folders:
            raise ArchiveError("产品目录重复。")
        dirs.add(p["archive_dir"])
        folders.add(p["folder"].casefold())
    keys = set()
    for table in m["tables"]:
        key = (table["database"], table["table"])
        if key in keys or key[0] not in DATABASES:
            raise ArchiveError("数据库表清单不合法。")
        keys.add(key)
        cols = table["columns"]
        scope = "产品ID" if "产品ID" in cols else "项目ID"
        if scope not in cols or table["scope"] != scope or len(cols) != len(set(cols)):
            raise ArchiveError("数据库表作用域不合法。")
        for row in table["rows"]:
            if set(row) != set(cols):
                raise ArchiveError("数据列不完整。")
            if "产品ID" in cols and str(row["产品ID"]) not in ids:
                raise ArchiveError("文件包含未选择产品的数据。")
            if "项目ID" in cols and str(row["项目ID"]) != project_id:
                raise ArchiveError("文件包含其他项目的数据。")
    def main_rows(key):
        return next((t["rows"] for t in m["tables"] if (t["database"], t["table"]) == key), [])
    if main_rows(PROJECT_TABLE) != [m["project"]]:
        raise ArchiveError("缺少项目主记录。")
    products = main_rows(PRODUCT_TABLE)
    if sorted(str(r["产品ID"]) for r in products) != sorted(ids):
        raise ArchiveError("产品主记录与选择清单不一致。")
    files = set()
    for f in m["files"]:
        path = _safe_member(f["path"])
        if f["path"] in files or f["size"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", f["sha256"]):
            raise ArchiveError("本地文件清单不合法。")
        files.add(f["path"])
        prefix = "/".join(path.parts[:2])
        if path.parts[0] == "project" and (len(path.parts) < 2 or
                path.parts[1].casefold() in folders or re.match(r"^\d+_", path.parts[1])):
            raise ArchiveError("项目共享文件不能写入产品目录。")
        if path.parts[0] != "project" and (prefix not in dirs or len(path.parts) < 3):
            raise ArchiveError("本地文件不属于本项目。")
        if f["path"] == "project/id.csv" or (prefix in dirs and len(path.parts) == 3 and path.name == "pro_id.csv"):
            raise ArchiveError("目录标识应由导入程序生成。")
    for mapping in m["path_maps"]:
        path = _safe_member(mapping["target"])
        if mapping["target"] not in dirs and mapping["target"] not in files:
            raise ArchiveError("本地路径映射目标不存在。")
        if not isinstance(mapping["source"], str) or not mapping["source"]:
            raise ArchiveError("本地路径映射来源不合法。")
    names = set()
    for config in m.get("configurations", []):
        if not config["name"] or config["name"] in names or not config["rows"]:
            raise ArchiveError("预定义配置清单不合法。")
        names.add(config["name"])
        if any(r.get("name") != config["name"] for r in config["rows"]):
            raise ArchiveError("预定义配置名称不一致。")
    for row in main_rows(ACTIVITY_TABLE):
        if row.get("预定义配置") and row["预定义配置"] not in names:
            raise ArchiveError("缺少产品绑定的预定义配置。")


def import_destination(manifest, connection_factory=None):
    """已存在项目使用当前本地目录；新项目由 UI 选择父目录。"""
    conn = (connection_factory or connect)()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_sql(PROJECT_TABLE)} WHERE 项目ID=%s", (manifest["project_id"],))
            project = cur.fetchone()
            ids = [p["id"] for p in manifest["products"]]
            cur.execute(f"SELECT 产品ID,项目ID FROM {table_sql(PRODUCT_TABLE)} "
                        f"WHERE 产品ID IN ({','.join(['%s'] * len(ids))})", ids)
            existing = cur.fetchall()
            if any(str(r["项目ID"]) != manifest["project_id"] for r in existing):
                raise ArchiveError("文件中产品ID已属于本机的其他项目，不能覆盖。")
            return (str(project_root(project)) if project else None), len(existing)
    finally:
        conn.close()


def _remap(value, mappings):
    if isinstance(value, str):
        normalized = value.replace("\\", "/")
        for old, new in mappings:
            prefix = old.replace("\\", "/").rstrip("/")
            if normalized.casefold() == prefix.casefold():
                return new
            if normalized.casefold().startswith(prefix.casefold() + "/"):
                return os.path.join(new, *normalized[len(prefix) + 1:].split("/"))
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
                changed = _remap(parsed, mappings)
                if changed != parsed:
                    return json.dumps(changed, ensure_ascii=False)
            except ValueError:
                pass
        return value
    if isinstance(value, dict):
        return {k: _remap(v, mappings) for k, v in value.items()}
    if isinstance(value, list):
        return [_remap(v, mappings) for v in value]
    return value


def _insert(cur, key, rows, meta, upsert=False):
    if not rows:
        return
    if key == ("产品设计活动库", "产品设计活动表_管口附件附加参数表"):
        # 此表参数ID是全库唯一但非自增的行号。现有保存逻辑按 MAX+1 分配，
        # 业务用产品ID/Tab/附件类型/参数名称关联；跨机器恢复需重新分配行号。
        cur.execute(f"SELECT COALESCE(MAX(参数ID),0) AS max_id FROM {table_sql(key)} FOR UPDATE")
        next_id = int(cur.fetchone()["max_id"])
        rows = [dict(row, 参数ID=next_id + index + 1) for index, row in enumerate(rows)]
    drop = set(meta["auto"]) if len(meta["primary"]) <= 1 else set()
    columns = [c for c in rows[0] if c not in drop]
    sql = (f"INSERT INTO {table_sql(key)} ({','.join(quote(c) for c in columns)}) "
           f"VALUES ({','.join(['%s'] * len(columns))})")
    if upsert:
        sql += " ON DUPLICATE KEY UPDATE " + ",".join(f"{quote(c)}=VALUES({quote(c)})" for c in columns
                                                     if c not in meta["primary"])
    cur.executemany(sql, [[r[c] for c in columns] for r in rows])


def _table_order(conn, keys):
    with conn.cursor() as cur:
        cur.execute("SELECT TABLE_SCHEMA,TABLE_NAME,REFERENCED_TABLE_SCHEMA,REFERENCED_TABLE_NAME "
                    "FROM information_schema.KEY_COLUMN_USAGE WHERE REFERENCED_TABLE_NAME IS NOT NULL")
        dependencies = defaultdict(set)
        for row in cur.fetchall():
            key = (row["TABLE_SCHEMA"], row["TABLE_NAME"])
            parent = (row["REFERENCED_TABLE_SCHEMA"], row["REFERENCED_TABLE_NAME"])
            if key in keys and parent in keys and key != parent:
                dependencies[key].add(parent)
    ordered = []
    pending = set(keys)
    while pending:
        ready = sorted(k for k in pending if not dependencies[k] & pending)
        if not ready:
            raise ArchiveError("数据表存在循环外键关系，无法安全导入。")
        ordered.extend(ready)
        pending.difference_update(ready)
    return ordered


def import_project(filename, destination, connection_factory=None, progress=None):
    """全部校验后暂存文件；数据库失败时回滚，并恢复磁盘中被替换的文件。"""
    m = read_archive(filename)
    root = Path(destination).absolute()
    conn = (connection_factory or connect)()
    staging = None
    installed = []
    made_dirs = []
    committed = False
    recovery_failed = False
    try:
        schema = _schema(conn)
        tables = {(t["database"], t["table"]): t for t in m["tables"]}
        for key, table in tables.items():
            if key not in schema or schema[key]["scope"] != table["scope"]:
                raise ArchiveError(f"本机缺少兼容的数据表：{key[0]}.{key[1]}，请使用相同或更新版本软件。")
            if set(table["columns"]) - set(schema[key]["columns"]):
                raise ArchiveError(f"本机表字段不完整：{key[1]}，请更新软件。")
            if schema[key]["engine"] != "InnoDB":
                raise ArchiveError(f"数据表不支持事务：{key[1]}，不能保证完整导入。")
        order = _table_order(conn, tables)
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table_sql(PROJECT_TABLE)} WHERE 项目ID=%s", (m["project_id"],))
            existing_project = cur.fetchone()
            ids = [p["id"] for p in m["products"]]
            cur.execute(f"SELECT 产品ID,项目ID FROM {table_sql(PRODUCT_TABLE)} "
                        f"WHERE 产品ID IN ({','.join(['%s'] * len(ids))})", ids)
            if any(str(r["项目ID"]) != m["project_id"] for r in cur.fetchall()):
                raise ArchiveError("产品ID已属于本机的其他项目。")
        # 同一项目合并时保留本机项目名称/目录，保证未选择产品仍有正确的路径。
        project = dict(existing_project or m["project"])
        expected_name = project_root(dict(project, 项目保存路径=str(root.parent))).name
        if root.name != expected_name:
            raise ArchiveError(f"项目目录名称应为：{expected_name}")
        if existing_project and os.path.normcase(str(project_root(existing_project))) != os.path.normcase(str(root)):
            raise ArchiveError("已存在项目必须导入到当前登记目录，避免破坏其他产品路径。")
        marker = root / "id.csv"
        if root.exists():
            marker_mismatch = marker.exists() and (not marker.is_file() or
                marker.read_text(encoding="utf-8-sig").strip() != m["project_id"])
            if not root.is_dir() or marker_mismatch or (not marker.exists() and not existing_project):
                raise ArchiveError(f"目标目录已存在且不属于本项目：\n{root}")
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".dlpec-import-", dir=root.parent))
        payload = staging / "payload"
        backup = staging / "backup"
        payload.mkdir()
        folder_map = {}
        used = set()
        # 复用已存在产品的目录；新产品避免与未选产品的序号目录冲突。
        with conn.cursor() as cur:
            cur.execute(f"SELECT 产品ID,产品文件夹绝对路径 FROM {table_sql(ACTIVITY_TABLE)} WHERE 项目ID=%s", (m["project_id"],))
            activities = {str(r["产品ID"]): r for r in cur.fetchall()}
        for product in m["products"]:
            name = product["folder"]
            current = str(activities.get(product["id"], {}).get("产品文件夹绝对路径") or "")
            if current and Path(current).absolute().parent == root:
                name = folder_component(Path(current).name)
            candidate = root / name
            if candidate.exists():
                marker = candidate / "pro_id.csv"
                if not marker.is_file() or marker.read_text(encoding="utf-8-sig").strip() != product["id"]:
                    name = folder_component(name + "_导入_" + uuid.uuid4().hex[:8])
            if name.casefold() in used:
                raise ArchiveError("导入产品目录冲突。")
            used.add(name.casefold())
            folder_map[product["archive_dir"]] = name
        def relative_target(name):
            parts = _safe_member(name).parts
            if parts[0] == "project":
                return Path(*parts[1:])
            return Path(folder_map["/".join(parts[:2])], *parts[2:])
        with zipfile.ZipFile(filename) as archive:
            for index, entry in enumerate(m["files"]):
                if progress:
                    progress(f"校验并恢复文件 {index + 1}/{len(m['files'])}：{entry['path']}")
                target = payload / relative_target(entry["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(entry["path"]) as src, target.open("wb") as dst:
                    for block in iter(lambda: src.read(1024 * 1024), b""):
                        digest.update(block)
                        dst.write(block)
                if digest.hexdigest() != entry["sha256"]:
                    raise ArchiveError(f"本地文件校验失败：{entry['path']}")
        (payload / "id.csv").write_text(m["project_id"], encoding="utf-8")
        for product in m["products"]:
            folder = payload / folder_map[product["archive_dir"]]
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "pro_id.csv").write_text(product["id"], encoding="utf-8")
        # 同一张模板图/外部文件可被多个产品引用，映射必须限定到当前产品。
        # 用归档目录确定归属，确保每个产品指向自己目录中的副本。
        mappings_by_product = {}
        for product in m["products"]:
            mappings = [(p["source"], str(root / relative_target(p["target"])))
                        for p in m["path_maps"] if p["target"] == product["archive_dir"]
                        or p["target"].startswith(product["archive_dir"] + "/")]
            mappings.append((m["source_root"], str(root)))
            mappings.sort(key=lambda pair: len(pair[0]), reverse=True)
            mappings_by_product[product["id"]] = mappings
        conn.rollback()
        conn.begin()
        with conn.cursor() as cur:
            # 预定义同名异内容时建立独立名称，不修改其他产品使用的配置。
            config_names = {}
            for config in m.get("configurations", []):
                name = config["name"]
                cur.execute(f"SELECT * FROM {table_sql(CONFIG_TABLE)} WHERE name=%s ORDER BY id FOR UPDATE", (name,))
                current = cur.fetchall()
                rows = config["rows"]
                if current and current != rows:
                    name = name[:225] + "_导入_" + uuid.uuid4().hex[:12]
                if not current or name != config["name"]:
                    cur.execute(f"SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", CONFIG_TABLE)
                    if (cur.fetchone() or {}).get("ENGINE") != "InnoDB":
                        raise ArchiveError("预定义配置表缺失或不支持事务。")
                    cur.execute(f"SHOW COLUMNS FROM {table_sql(CONFIG_TABLE)}")
                    columns = {r["Field"] for r in cur.fetchall()}
                    if any(set(r) - columns for r in rows):
                        raise ArchiveError("本机预定义配置字段不完整。")
                    _insert(cur, CONFIG_TABLE, [dict(r, name=name) for r in rows], dict(auto=[], primary=["id", "name"]))
                config_names[config["name"]] = name
            for key in reversed(order):
                if key == PROJECT_TABLE:
                    continue
                where, args = _where(tables[key]["scope"], m["project_id"], ids)
                cur.execute(f"DELETE FROM {table_sql(key)} WHERE {where}", args)
            # 父项目先落库，再按实际外键顺序插入产品及子表。
            project["项目保存路径"] = str(root.parent)
            _insert(cur, PROJECT_TABLE, [project], schema[PROJECT_TABLE], upsert=True)
            for key in order:
                if key == PROJECT_TABLE:
                    continue
                if progress:
                    progress(f"写入数据库：{key[1]}")
                rows = [_remap(r, mappings_by_product.get(str(r.get("产品ID") or ""),
                               [(m["source_root"], str(root))])) for r in tables[key]["rows"]]
                if key == ACTIVITY_TABLE:
                    for row in rows:
                        product = next(p for p in m["products"] if p["id"] == str(row["产品ID"]))
                        row["产品文件夹绝对路径"] = str(root / folder_map[product["archive_dir"]])
                        if row.get("预定义配置") in config_names:
                            row["预定义配置"] = config_names[row["预定义配置"]]
                _insert(cur, key, rows, schema[key])
            # 防止旧产品尚无活动主记录，导入后本地目录无法被业务模块发现。
            for product in m["products"]:
                cur.execute(f"INSERT INTO {table_sql(ACTIVITY_TABLE)} (产品ID,项目ID,产品文件夹绝对路径) "
                            "VALUES (%s,%s,%s) ON DUPLICATE KEY UPDATE 产品文件夹绝对路径=VALUES(产品文件夹绝对路径)",
                            (product["id"], m["project_id"], str(root / folder_map[product["archive_dir"]])))
            # 替换已有文件前备份，数据库提交失败时原样恢复。
            def ensure_dir(path):
                missing = []
                while not path.exists():
                    missing.append(path)
                    path = path.parent
                for directory in reversed(missing):
                    directory.mkdir()
                    made_dirs.append(directory)
            for source, rel in _walk_files(payload):
                target = root / rel
                ensure_dir(target.parent)
                # resolve 检查父目录链接，避免包内文件落到项目范围之外。
                if os.path.commonpath([str(root.resolve()), str(target.resolve())]) != str(root.resolve()):
                    raise ArchiveError(f"目标路径越出项目目录：{target}")
                saved = None
                if target.exists():
                    if not target.is_file() or target.is_symlink():
                        raise ArchiveError(f"目标文件路径不合法：{target}")
                    saved = backup / rel
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                installed.append((target, saved))
                os.replace(source, target)
        conn.commit()
        committed = True
        return dict(project_id=m["project_id"], product_ids=ids, project_root=str(root),
                    rows=sum(len(t["rows"]) for t in m["tables"]), files=len(m["files"]))
    finally:
        try:
            if not committed:
                conn.rollback()
                failures = []
                for target, saved in reversed(installed):
                    try:
                        if saved:
                            os.replace(saved, target)
                        elif target.exists():
                            target.unlink()
                    except OSError as exc:
                        failures.append(str(exc))
                for directory in reversed(made_dirs):
                    try:
                        directory.rmdir()
                    except OSError as exc:
                        failures.append(str(exc))
                if failures:
                    recovery_failed = True
                    raise ArchiveError(f"导入失败，部分文件无法自动恢复。原文件备份已保留在：\n{staging}\n"
                                       + "\n".join(failures))
        finally:
            conn.close()
            if staging and not recovery_failed:
                shutil.rmtree(staging, ignore_errors=True)
