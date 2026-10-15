from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


class DatabaseError(Exception):
    """A user-facing database error."""


class DriverMissingError(DatabaseError):
    pass


class ConnectionLostError(DatabaseError):
    pass


@dataclass
class ConnectionProfile:
    name: str
    kind: str = "sqlite"
    database: str = ""
    host: str = "localhost"
    port: int = 0
    user: str = ""
    password: str = ""
    remember_password: bool = False
    profile_id: str = ""

    def __post_init__(self) -> None:
        self.kind = (self.kind or "sqlite").lower()
        if not self.profile_id:
            self.profile_id = uuid.uuid4().hex
        if not self.port:
            if self.kind == "mysql":
                self.port = 3306
            elif self.kind in {"postgres", "postgresql"}:
                self.port = 5432

    def public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("password", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConnectionProfile":
        allowed = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in allowed})


@dataclass
class NamespaceInfo:
    name: str
    system: bool = False


@dataclass
class TableObject:
    name: str
    kind: str = "table"
    schema: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.schema}.{self.name}" if self.schema else self.name


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool = True
    default: Any = None
    primary_key: bool = False
    position: int = 0
    auto_increment: bool = False


@dataclass
class EditableColumn:
    name: str
    data_type: str = "TEXT"
    nullable: bool = True
    default: Any = None
    primary_key: bool = False
    auto_increment: bool = False
    original_name: str = ""

    @classmethod
    def from_column(cls, column: ColumnInfo) -> "EditableColumn":
        return cls(column.name, column.data_type, column.nullable, column.default,
                   column.primary_key, column.auto_increment, column.name)


@dataclass
class IndexInfo:
    name: str
    unique: bool = False
    columns: List[str] = None

    def __post_init__(self) -> None:
        if self.columns is None:
            self.columns = []


@dataclass
class ForeignKeyInfo:
    name: str = ""
    columns: List[str] = None
    referenced_table: str = ""
    referenced_columns: List[str] = None
    referenced_schema: str = ""
    on_update: str = ""
    on_delete: str = ""
    inferred: bool = False

    def __post_init__(self) -> None:
        if self.columns is None:
            self.columns = []
        if self.referenced_columns is None:
            self.referenced_columns = []


@dataclass
class FilterCondition:
    column: str
    operator: str = "eq"
    value: str = ""
    connector: str = "AND"


@dataclass
class SortCondition:
    column: str
    direction: str = "ASC"


@dataclass
class QueryResult:
    columns: List[str] = None
    rows: List[Tuple[Any, ...]] = None
    rowcount: int = 0
    elapsed_ms: float = 0.0
    message: str = ""
    sql: str = ""
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.columns is None:
            self.columns = []
        if self.rows is None:
            self.rows = []
        if not self.rowcount and self.rows:
            self.rowcount = len(self.rows)


def secure_password_storage_available() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32crypt  # type: ignore
        return bool(win32crypt)
    except Exception:
        return False


def _protect_password(value: str) -> str:
    import base64
    import win32crypt  # type: ignore
    encrypted = win32crypt.CryptProtectData(value.encode("utf-8"), "DogiCat", None, None, None, 0)
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect_password(value: str) -> str:
    import base64
    import win32crypt  # type: ignore
    raw = base64.b64decode(value.encode("ascii"))
    return win32crypt.CryptUnprotectData(raw, None, None, None, 0)[1].decode("utf-8")


class ConfigStore:
    def __init__(self, root: Path):
        root = Path(root)
        self.root = root / ".dogicat" if root.name != ".dogicat" else root
        self.root.mkdir(parents=True, exist_ok=True)
        self.profiles_path = self.root / "connections.json"
        self.credentials_path = self.root / "credentials.json"
        self.history_path = self.root / "query_history.json"
        self.settings_path = self.root / "settings.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def _atomic_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
            os.replace(temp_name, path)
        finally:
            try:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            except OSError:
                pass

    def load_profiles(self) -> List[ConnectionProfile]:
        items = self._read_json(self.profiles_path, [])
        credentials = self._read_json(self.credentials_path, {})
        profiles: List[ConnectionProfile] = []
        for raw in items if isinstance(items, list) else []:
            try:
                profile = ConnectionProfile.from_dict(raw)
                if profile.remember_password and secure_password_storage_available():
                    token = credentials.get(profile.profile_id, "") if isinstance(credentials, dict) else ""
                    if token:
                        try:
                            profile.password = _unprotect_password(token)
                        except Exception:
                            profile.password = ""
                else:
                    profile.password = ""
                profiles.append(profile)
            except Exception:
                continue
        return profiles

    def save_profiles(self, profiles: Sequence[ConnectionProfile]) -> None:
        public = [profile.public_dict() for profile in profiles]
        self._atomic_json(self.profiles_path, public)
        credentials: Dict[str, str] = {}
        if secure_password_storage_available():
            for profile in profiles:
                if profile.remember_password and profile.password:
                    try:
                        credentials[profile.profile_id] = _protect_password(profile.password)
                    except Exception:
                        pass
        self._atomic_json(self.credentials_path, credentials)

    def load_history(self) -> List[Dict[str, Any]]:
        value = self._read_json(self.history_path, [])
        return value if isinstance(value, list) else []

    def add_history(self, database: str, sql: str, elapsed_ms: float, success: bool) -> None:
        items = self.load_history()
        items.insert(0, {
            "database": database,
            "sql": sql,
            "elapsed_ms": elapsed_ms,
            "success": bool(success),
            "time": _dt.datetime.now().isoformat(timespec="seconds"),
        })
        self._atomic_json(self.history_path, items[:500])

    def load_settings(self) -> Dict[str, Any]:
        value = self._read_json(self.settings_path, {})
        return value if isinstance(value, dict) else {}

    def save_settings(self, settings: Dict[str, Any]) -> None:
        self._atomic_json(self.settings_path, dict(settings))


def split_sql_statements(sql: str) -> List[str]:
    statements: List[str] = []
    buf: List[str] = []
    quote: Optional[str] = None
    line_comment = False
    block_comment = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < len(sql) else ""
        if line_comment:
            buf.append(ch)
            if ch == "\n":
                line_comment = False
            i += 1
            continue
        if block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt); i += 2; block_comment = False
            else:
                i += 1
            continue
        if quote:
            buf.append(ch)
            if ch == quote:
                if nxt == quote:  # SQL doubled quote
                    buf.append(nxt); i += 2; continue
                # backslash escaped quote
                slashes = 0; j = i - 1
                while j >= 0 and sql[j] == "\\":
                    slashes += 1; j -= 1
                if slashes % 2 == 0:
                    quote = None
            i += 1
            continue
        if ch in ("'", '"', '`'):
            quote = ch; buf.append(ch); i += 1; continue
        if ch == "-" and nxt == "-":
            line_comment = True; buf.extend((ch, nxt)); i += 2; continue
        if ch == "/" and nxt == "*":
            block_comment = True; buf.extend((ch, nxt)); i += 2; continue
        if ch == ";":
            text = "".join(buf).strip()
            if text:
                statements.append(text)
            buf = []; i += 1; continue
        buf.append(ch); i += 1
    text = "".join(buf).strip()
    if text:
        statements.append(text)
    return statements


class DatabaseAdapter:
    placeholder = "?"

    def __init__(self, profile: ConnectionProfile):
        self.profile = profile
        self.connection: Any = None

    def connect(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

    def is_connection_alive(self) -> bool:
        if self.connection is None:
            return False
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT 1")
            try: cursor.fetchone()
            except Exception: pass
            try: cursor.close()
            except Exception: pass
            return True
        except Exception:
            return False

    def ensure_connected(self) -> None:
        if not self.is_connection_alive():
            raise ConnectionLostError("数据库连接已断开，请重新连接")

    def quote_identifier(self, name: str) -> str:
        return '"' + str(name).replace('"', '""') + '"'

    def qualified_name(self, table: str, schema: str = "") -> str:
        if schema:
            return f"{self.quote_identifier(schema)}.{self.quote_identifier(table)}"
        return self.quote_identifier(table)

    def list_namespaces(self) -> List[NamespaceInfo]:
        return []

    def open_namespace(self, namespace: str) -> "DatabaseAdapter":
        return self

    def list_objects(self, namespace: str = "") -> List[TableObject]:
        raise NotImplementedError

    def get_columns(self, table: str, schema: str = "") -> List[ColumnInfo]:
        raise NotImplementedError

    def get_indexes(self, table: str, schema: str = "") -> List[IndexInfo]:
        return []

    def get_foreign_keys(self, table: str, schema: str = "") -> List[ForeignKeyInfo]:
        return []

    def get_ddl(self, table: str, schema: str = "") -> str:
        return ""

    def get_additional_ddl(self, table: str, schema: str = "") -> List[str]:
        return []

    def clear_database_for_import(self) -> int:
        raise DatabaseError("此数据库类型暂不支持覆盖导入")

    def drop_database(self, database: str) -> None:
        raise DatabaseError("此数据库类型暂不支持删除数据库")

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None,
                max_rows: Optional[int] = 2000) -> QueryResult:
        if self.connection is None:
            raise ConnectionLostError("数据库尚未连接")
        start = time.perf_counter()
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, tuple(params or ()))
            columns: List[str] = []
            rows: List[Tuple[Any, ...]] = []
            truncated = False
            if getattr(cursor, "description", None):
                columns = [item[0] for item in cursor.description]
                if max_rows is None:
                    rows = [tuple(row) for row in cursor.fetchall()]
                else:
                    fetched = cursor.fetchmany(max_rows + 1)
                    truncated = len(fetched) > max_rows
                    rows = [tuple(row) for row in fetched[:max_rows]]
                rowcount = len(rows)
            else:
                try:
                    self.connection.commit()
                except Exception:
                    pass
                rowcount = max(0, int(getattr(cursor, "rowcount", 0) or 0))
            try: cursor.close()
            except Exception: pass
            elapsed = (time.perf_counter() - start) * 1000
            return QueryResult(columns, rows, rowcount, elapsed, f"{rowcount} 行", sql, truncated)
        except Exception as exc:
            try:
                self.connection.rollback()
            except Exception:
                pass
            raise DatabaseError(str(exc)) from exc

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> int:
        if self.connection is None:
            raise ConnectionLostError("数据库尚未连接")
        try:
            cursor = self.connection.cursor()
            cursor.executemany(sql, rows)
            count = cursor.rowcount if getattr(cursor, "rowcount", -1) >= 0 else len(rows)
            self.connection.commit()
            try: cursor.close()
            except Exception: pass
            return int(count)
        except Exception as exc:
            try: self.connection.rollback()
            except Exception: pass
            raise DatabaseError(str(exc)) from exc

    def execute_script(self, sql: str) -> List[QueryResult]:
        return [self.execute(stmt) for stmt in split_sql_statements(sql)]

    def execute_copy(self, sql: str, data: Any) -> int:
        raise DatabaseError("当前数据库驱动不支持 COPY")

    def iter_table_rows(self, table: str, schema: str = "", batch_size: int = 200) -> Iterator[Tuple[Any, ...]]:
        result = self.execute(f"SELECT * FROM {self.qualified_name(table, schema)}", max_rows=None)
        yield from result.rows

    def text_search_expression(self, column: str) -> str:
        return f"LOWER(CAST({self.quote_identifier(column)} AS TEXT))"

    def iter_matching_rows(
        self, table: str, columns: Sequence[ColumnInfo], search_text: str,
        schema: str = "", batch_size: int = 100,
    ) -> Iterator[Tuple[Any, ...]]:
        searchable = self.searchable_columns(columns)
        if not searchable:
            return
        pattern = "%" + self._like_literal(search_text.casefold()) + "%"
        selected = ", ".join(self.quote_identifier(c.name) for c in searchable)
        conditions = []
        params: List[Any] = []
        for column in searchable:
            conditions.append(
                f"{self.text_search_expression(column.name)} LIKE {self.placeholder} ESCAPE '='"
            )
            params.append(pattern)
        sql = (
            f"SELECT {selected} FROM {self.qualified_name(table, schema)} "
            f"WHERE " + " OR ".join(conditions)
        )
        result = self.execute(sql, params, max_rows=None)
        for row in result.rows:
            yield row

    @staticmethod
    def _like_literal(value: str) -> str:
        return str(value).replace("=", "==").replace("%", "=%").replace("_", "=_")

    def searchable_columns(self, columns: Sequence[ColumnInfo]) -> List[ColumnInfo]:
        excluded = ("blob", "binary", "bytea", "image", "varbinary")
        return [c for c in columns if not any(token in c.data_type.lower() for token in excluded)]

    def build_table_query(self, table: str, columns: Sequence[ColumnInfo], schema: str = "",
                          quick_search: str = "", filters: Sequence[FilterCondition] = (),
                          sorts: Sequence[SortCondition] = (), limit: Optional[int] = 2000) -> Tuple[str, List[Any]]:
        names = {c.name for c in columns}
        params: List[Any] = []
        groups: List[str] = []
        if quick_search:
            needle = "%" + self._like_literal(quick_search.lower()) + "%"
            search_parts = []
            for col in self.searchable_columns(columns):
                search_parts.append(f"{self.text_search_expression(col.name)} LIKE {self.placeholder} ESCAPE '='")
                params.append(needle)
            if search_parts:
                groups.append("(" + " OR ".join(search_parts) + ")")
        op_map = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        filter_sql = ""
        for idx, condition in enumerate(filters):
            if condition.column not in names:
                raise DatabaseError(f"筛选字段不存在：{condition.column}")
            q = self.quote_identifier(condition.column)
            op = condition.operator.lower()
            value = condition.value
            part = ""
            if op in op_map:
                part = f"{q} {op_map[op]} {self.placeholder}"; params.append(value)
            elif op in {"contains", "not_contains", "starts_with", "ends_with"}:
                escaped = self._like_literal(value)
                pattern = {"contains": f"%{escaped}%", "not_contains": f"%{escaped}%",
                           "starts_with": f"{escaped}%", "ends_with": f"%{escaped}"}[op]
                not_kw = " NOT" if op == "not_contains" else ""
                part = f"{self.text_search_expression(condition.column)}{not_kw} LIKE {self.placeholder} ESCAPE '='"
                params.append(pattern.lower())
            elif op == "is_null":
                part = f"{q} IS NULL"
            elif op in {"not_null", "is_not_null"}:
                part = f"{q} IS NOT NULL"
            elif op in {"in", "not_in"}:
                values = [x.strip() for x in re.split(r"[,\r\n]+", str(value)) if x.strip()]
                if not values:
                    part = "1=0" if op == "in" else "1=1"
                else:
                    marks = ", ".join([self.placeholder] * len(values))
                    part = f"{q} {'NOT IN' if op == 'not_in' else 'IN'} ({marks})"
                    params.extend(values)
            elif op in {"between", "not_between"}:
                values = [x.strip() for x in re.split(r"[,\r\n]+", str(value), maxsplit=1) if x.strip()]
                if len(values) != 2:
                    raise DatabaseError("BETWEEN 需要两个值")
                part = f"{q} {'NOT BETWEEN' if op == 'not_between' else 'BETWEEN'} {self.placeholder} AND {self.placeholder}"
                params.extend(values)
            else:
                raise DatabaseError(f"不支持的筛选条件：{condition.operator}")
            connector = (condition.connector or "AND").upper()
            if connector not in {"AND", "OR"}: connector = "AND"
            if idx == 0:
                filter_sql = part
            else:
                filter_sql += f" {connector} {part}"
        if filter_sql:
            groups.append("(" + filter_sql + ")")
        sql = f"SELECT * FROM {self.qualified_name(table, schema)}"
        if groups:
            sql += " WHERE " + " AND ".join(groups)
        order_parts: List[str] = []
        seen = set()
        for sort in sorts:
            if sort.column not in names:
                raise DatabaseError(f"排序字段不存在：{sort.column}")
            if sort.column in seen: continue
            seen.add(sort.column)
            direction = "DESC" if str(sort.direction).upper() == "DESC" else "ASC"
            order_parts.append(f"{self.quote_identifier(sort.column)} {direction}")
        if order_parts:
            sql += " ORDER BY " + ", ".join(order_parts)
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return sql, params

    def insert_row(self, table: str, values: Dict[str, Any], schema: str = "") -> int:
        if not values:
            sql = f"INSERT INTO {self.qualified_name(table, schema)} DEFAULT VALUES"
            return self.execute(sql).rowcount
        cols = list(values)
        sql = (f"INSERT INTO {self.qualified_name(table, schema)} (" +
               ", ".join(self.quote_identifier(c) for c in cols) + ") VALUES (" +
               ", ".join([self.placeholder] * len(cols)) + ")")
        return self.execute(sql, [values[c] for c in cols]).rowcount

    def update_row(self, table: str, values: Dict[str, Any], keys: Dict[str, Any], schema: str = "") -> int:
        return self.update_rows(table, [(values, keys)], schema)

    def update_rows(self, table: str, updates: Sequence[Tuple[Dict[str, Any], Dict[str, Any]]], schema: str = "") -> int:
        if self.connection is None:
            raise ConnectionLostError("数据库尚未连接")
        if not updates:
            return 0
        affected = 0
        try:
            cursor = self.connection.cursor()
            for values, keys in updates:
                if not values or not keys:
                    continue
                sets = ", ".join(f"{self.quote_identifier(k)} = {self.placeholder}" for k in values)
                wheres = []
                params: List[Any] = list(values.values())
                for key, value in keys.items():
                    if value is None:
                        wheres.append(f"{self.quote_identifier(key)} IS NULL")
                    else:
                        wheres.append(f"{self.quote_identifier(key)} = {self.placeholder}")
                        params.append(value)
                sql = f"UPDATE {self.qualified_name(table, schema)} SET {sets} WHERE " + " AND ".join(wheres)
                cursor.execute(sql, tuple(params))
                rc = getattr(cursor, "rowcount", 0)
                if rc and rc > 0: affected += int(rc)
            self.connection.commit()
            try: cursor.close()
            except Exception: pass
            return affected
        except Exception as exc:
            try: self.connection.rollback()
            except Exception: pass
            raise DatabaseError(str(exc)) from exc

    def delete_row(self, table: str, keys: Dict[str, Any], schema: str = "") -> int:
        if not keys:
            raise DatabaseError("删除记录必须提供主键")
        parts=[]; params=[]
        for key, value in keys.items():
            if value is None: parts.append(f"{self.quote_identifier(key)} IS NULL")
            else: parts.append(f"{self.quote_identifier(key)} = {self.placeholder}"); params.append(value)
        sql = f"DELETE FROM {self.qualified_name(table, schema)} WHERE " + " AND ".join(parts)
        return self.execute(sql, params).rowcount

    def validate_table_design(self, columns: Sequence[EditableColumn]) -> None:
        if not columns:
            raise DatabaseError("表至少需要一个字段")
        names=[]
        for c in columns:
            name=c.name.strip()
            if not name: raise DatabaseError("字段名不能为空")
            if name.lower() in [x.lower() for x in names]: raise DatabaseError(f"字段名重复：{name}")
            if not c.data_type.strip(): raise DatabaseError(f"字段 {name} 的数据类型不能为空")
            names.append(name)

    def format_default(self, value: Any, data_type: str = "") -> str:
        if value is None or str(value).strip() == "": return ""
        text = str(value).strip()
        upper = text.upper()
        if upper in {"NULL", "CURRENT_TIMESTAMP", "CURRENT_DATE", "CURRENT_TIME", "NOW()", "TRUE", "FALSE"}:
            return upper
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text): return text
        if (len(text)>=2 and text[0]==text[-1] and text[0] in "'\""):
            return text if text[0]=="'" else "'"+text[1:-1].replace("'","''")+"'"
        return "'" + text.replace("'", "''") + "'"

    def apply_table_design(self, table: str, columns: Sequence[EditableColumn], schema: str = "") -> None:
        raise DatabaseError("当前数据库类型暂不支持直接修改表结构")


class SQLiteAdapter(DatabaseAdapter):
    def connect(self) -> None:
        try:
            path = self.profile.database or ":memory:"
            if path != ":memory:": Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, check_same_thread=False)
            self.connection.execute("PRAGMA foreign_keys=ON")
            self.connection.execute("PRAGMA busy_timeout=5000")
        except Exception as exc:
            raise DatabaseError(f"SQLite 连接失败：{exc}") from exc

    def is_connection_alive(self) -> bool:
        if self.connection is None: return False
        try:
            self.connection.execute("SELECT 1").fetchone(); return True
        except Exception: return False

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None,
                max_rows: Optional[int] = 2000) -> QueryResult:
        if self.connection is None: raise ConnectionLostError("数据库尚未连接")
        start=time.perf_counter()
        try:
            cur=self.connection.cursor(); cur.execute(sql, tuple(params or ()))
            if cur.description:
                columns=[d[0] for d in cur.description]
                if max_rows is None:
                    rows=[tuple(r) for r in cur.fetchall()]; truncated=False
                else:
                    raw=cur.fetchmany(max_rows+1); truncated=len(raw)>max_rows; rows=[tuple(r) for r in raw[:max_rows]]
                rc=len(rows)
            else:
                self.connection.commit(); columns=[]; rows=[]; truncated=False; rc=max(0, cur.rowcount if cur.rowcount!=-1 else 0)
            elapsed=(time.perf_counter()-start)*1000
            return QueryResult(columns,rows,rc,elapsed,f"{rc} 行",sql,truncated)
        except Exception as exc:
            try: self.connection.rollback()
            except Exception: pass
            raise DatabaseError(str(exc)) from exc

    def execute_script(self, sql: str) -> List[QueryResult]:
        # Keep individual results while supporting SQLite trigger bodies.
        try:
            from .sql_import import SQLStreamParser
            import io
            commands=[c for c in SQLStreamParser(io.StringIO(sql), "sqlite") if c.kind=="sql"]
            if commands:
                return [self.execute(c.sql) for c in commands]
        except Exception:
            pass
        return super().execute_script(sql)

    def backup_to(self, target: Path) -> None:
        if self.connection is None: raise ConnectionLostError("数据库尚未连接")
        target=Path(target); target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with sqlite3.connect(str(target)) as dest:
                self.connection.backup(dest)
        except Exception as exc: raise DatabaseError(str(exc)) from exc

    def list_objects(self, namespace: str = "") -> List[TableObject]:
        result=self.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name", max_rows=None)
        return [TableObject(name, "view" if kind=="view" else "table") for name,kind in result.rows]

    def get_columns(self, table: str, schema: str = "") -> List[ColumnInfo]:
        q=self.quote_identifier(table)
        rows=self.execute(f"PRAGMA table_info({q})", max_rows=None).rows
        ddl=self.get_ddl(table)
        auto_names=set()
        if "AUTOINCREMENT" in ddl.upper():
            # SQLite allows AUTOINCREMENT only on integer PK. Identify the PK column before token.
            m=re.search(r'(?is)(?:["`\[]?([A-Za-z_][\w$]*)["`\]]?)\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT', ddl)
            if m: auto_names.add(m.group(1))
        return [ColumnInfo(str(name), str(dtype or ""), not bool(notnull), default, bool(pk), int(cid)+1, str(name) in auto_names)
                for cid,name,dtype,notnull,default,pk in rows]

    def get_indexes(self, table: str, schema: str = "") -> List[IndexInfo]:
        rows=self.execute(f"PRAGMA index_list({self.quote_identifier(table)})", max_rows=None).rows
        result=[]
        for row in rows:
            # seq,name,unique,origin,partial
            name=str(row[1]); unique=bool(row[2])
            cols=[r[2] for r in self.execute(f"PRAGMA index_info({self.quote_identifier(name)})", max_rows=None).rows]
            result.append(IndexInfo(name, unique, [str(x) for x in cols if x is not None]))
        return result

    def get_foreign_keys(self, table: str, schema: str = "") -> List[ForeignKeyInfo]:
        rows=self.execute(f"PRAGMA foreign_key_list({self.quote_identifier(table)})", max_rows=None).rows
        grouped: Dict[Any, Dict[str,Any]]={}
        for row in rows:
            # id,seq,table,from,to,on_update,on_delete,match
            fid,seq,ref_table,src,dst,on_update,on_delete,*_=row
            item=grouped.setdefault(fid,{"table":ref_table,"cols":[],"refs":[],"update":on_update,"delete":on_delete})
            item["cols"].append((seq,src)); item["refs"].append((seq,dst))
        result=[]
        for fid,item in sorted(grouped.items(), key=lambda kv: kv[0]):
            result.append(ForeignKeyInfo(f"fk_{table}_{fid}", [x[1] for x in sorted(item['cols'])], str(item['table']),
                                         [x[1] for x in sorted(item['refs'])], "", str(item['update']), str(item['delete'])))
        return result

    def get_ddl(self, table: str, schema: str = "") -> str:
        row=self.execute("SELECT sql FROM sqlite_master WHERE name = ? AND type IN ('table','view')", [table], max_rows=None).rows
        return str(row[0][0] or "") if row else ""

    def get_additional_ddl(self, table: str, schema: str = "") -> List[str]:
        rows=self.execute("SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('index','trigger') AND sql IS NOT NULL ORDER BY type, name", [table], max_rows=None).rows
        return [str(r[0]) for r in rows if r[0]]

    def clear_database_for_import(self) -> int:
        if self.connection is None: raise ConnectionLostError("数据库尚未连接")
        objects=self.execute("SELECT name,type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND type IN ('trigger','view','table') ORDER BY CASE type WHEN 'trigger' THEN 0 WHEN 'view' THEN 1 ELSE 2 END", max_rows=None).rows
        try:
            self.connection.execute("PRAGMA foreign_keys=OFF")
            for name,kind in objects:
                kw={"trigger":"TRIGGER","view":"VIEW","table":"TABLE"}[kind]
                self.connection.execute(f"DROP {kw} IF EXISTS {self.quote_identifier(name)}")
            self.connection.commit()
        finally:
            self.connection.execute("PRAGMA foreign_keys=ON")
        return len(objects)

    def apply_table_design(self, table: str, columns: Sequence[EditableColumn], schema: str = "") -> None:
        self.validate_table_design(columns)
        if self.connection is None: raise ConnectionLostError("数据库尚未连接")
        old_cols=self.get_columns(table)
        old_names={c.name for c in old_cols}
        rename={c.original_name:c.name for c in columns if c.original_name and c.original_name in old_names}
        fks=self.get_foreign_keys(table)
        indexes=[x for x in self.get_indexes(table) if not x.name.startswith("sqlite_autoindex_")]
        additional=self.get_additional_ddl(table)
        triggers=[x for x in additional if re.match(r"(?is)^\s*CREATE\s+TRIGGER", x)]
        # Rebuild index statements ourselves so renamed columns survive.
        temp=f"__dogicat_{table}_{uuid.uuid4().hex[:8]}"
        defs=[]
        for c in columns:
            part=f"{self.quote_identifier(c.name)} {c.data_type.strip() or 'TEXT'}"
            if c.primary_key:
                part += " PRIMARY KEY"
                if c.auto_increment and "INT" in c.data_type.upper(): part += " AUTOINCREMENT"
            if not c.nullable and not c.primary_key: part += " NOT NULL"
            if c.default not in (None, ""):
                formatted=self.format_default(c.default,c.data_type)
                if formatted: part += f" DEFAULT {formatted}"
            defs.append(part)
        for fk in fks:
            mapped=[rename.get(n,n) for n in fk.columns]
            # retain only keys whose source columns survived
            if not all(any(c.name==m for c in columns) for m in mapped): continue
            clause=("FOREIGN KEY ("+", ".join(self.quote_identifier(n) for n in mapped)+") REFERENCES "+
                    self.quote_identifier(fk.referenced_table)+" ("+", ".join(self.quote_identifier(n) for n in fk.referenced_columns)+")")
            if fk.on_update and fk.on_update.upper() not in {"NO ACTION",""}: clause += f" ON UPDATE {fk.on_update}"
            if fk.on_delete and fk.on_delete.upper() not in {"NO ACTION",""}: clause += f" ON DELETE {fk.on_delete}"
            defs.append(clause)
        create=f"CREATE TABLE {self.quote_identifier(temp)} ("+", ".join(defs)+")"
        dest=[]; src=[]
        for c in columns:
            if c.original_name and c.original_name in old_names:
                dest.append(self.quote_identifier(c.name)); src.append(self.quote_identifier(c.original_name))
        try:
            self.connection.execute("PRAGMA foreign_keys=OFF")
            self.connection.execute("BEGIN")
            self.connection.execute(create)
            if dest:
                self.connection.execute(f"INSERT INTO {self.quote_identifier(temp)} ({', '.join(dest)}) SELECT {', '.join(src)} FROM {self.quote_identifier(table)}")
            self.connection.execute(f"DROP TABLE {self.quote_identifier(table)}")
            self.connection.execute(f"ALTER TABLE {self.quote_identifier(temp)} RENAME TO {self.quote_identifier(table)}")
            for idx in indexes:
                mapped=[rename.get(n,n) for n in idx.columns]
                if not mapped or not all(any(c.name==m for c in columns) for m in mapped): continue
                unique="UNIQUE " if idx.unique else ""
                self.connection.execute(f"CREATE {unique}INDEX {self.quote_identifier(idx.name)} ON {self.quote_identifier(table)} ({', '.join(self.quote_identifier(n) for n in mapped)})")
            for trigger in triggers:
                updated=trigger
                for old,new in rename.items():
                    if old!=new:
                        updated=re.sub(rf'(?<![\w$]){re.escape(old)}(?![\w$])', new, updated)
                self.connection.execute(updated)
            self.connection.commit()
        except Exception as exc:
            try: self.connection.rollback()
            except Exception: pass
            raise DatabaseError(str(exc)) from exc
        finally:
            try: self.connection.execute("PRAGMA foreign_keys=ON")
            except Exception: pass


class MySQLAdapter(DatabaseAdapter):
    placeholder="%s"
    SYSTEM_DATABASES={"information_schema","mysql","performance_schema","sys"}

    def quote_identifier(self,name:str)->str:
        return "`"+str(name).replace("`","``")+"`"

    def text_search_expression(self,column:str)->str:
        return f"LOWER(CAST({self.quote_identifier(column)} AS CHAR))"

    def connect(self)->None:
        try:
            import mysql.connector  # type: ignore
        except Exception as exc:
            raise DriverMissingError("缺少 MySQL 驱动 mysql-connector-python") from exc
        options={"host":self.profile.host or "localhost","port":int(self.profile.port or 3306),"user":self.profile.user,
                 "password":self.profile.password,"connection_timeout":8,"use_pure":True}
        if self.profile.database: options["database"]=self.profile.database
        try:
            self.connection=mysql.connector.connect(**options)
        except Exception as exc:
            if getattr(exc,"errno",None)==1045:
                raise DatabaseError("MySQL 拒绝登录：请检查用户名或密码") from exc
            raise DatabaseError(f"MySQL 连接失败：{exc}") from exc

    def is_connection_alive(self)->bool:
        if self.connection is None:return False
        try:
            if hasattr(self.connection,"is_connected"): return bool(self.connection.is_connected())
            return super().is_connection_alive()
        except Exception:return False

    def list_namespaces(self)->List[NamespaceInfo]:
        rows=self.execute("SELECT schema_name FROM information_schema.schemata ORDER BY schema_name",max_rows=None).rows
        return [NamespaceInfo(str(r[0]),str(r[0]).lower() in self.SYSTEM_DATABASES) for r in rows]

    def open_namespace(self,namespace:str)->"MySQLAdapter":
        data=asdict(self.profile); data["database"]=namespace; data["profile_id"]=self.profile.profile_id
        adapter=MySQLAdapter(ConnectionProfile(**data)); adapter.connect(); return adapter

    def list_objects(self,namespace:str="")->List[TableObject]:
        schema=namespace or self.profile.database
        if not schema:return []
        rows=self.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name",[schema],max_rows=None).rows
        return [TableObject(str(n),"view" if str(t).upper()=="VIEW" else "table",schema) for n,t in rows]

    def get_columns(self,table:str,schema:str="")->List[ColumnInfo]:
        schema=schema or self.profile.database
        rows=self.execute("SELECT column_name,column_type,is_nullable,column_default,column_key,ordinal_position,extra FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",[schema,table],max_rows=None).rows
        return [ColumnInfo(str(n),str(t),str(nullable).upper()=="YES",default,str(key).upper()=="PRI",int(pos),"auto_increment" in str(extra).lower()) for n,t,nullable,default,key,pos,extra in rows]

    def get_indexes(self,table:str,schema:str="")->List[IndexInfo]:
        schema=schema or self.profile.database
        rows=self.execute("SELECT index_name, non_unique, column_name, seq_in_index FROM information_schema.statistics WHERE table_schema=%s AND table_name=%s ORDER BY index_name,seq_in_index",[schema,table],max_rows=None).rows
        grouped={}
        for name,non_unique,col,seq in rows:
            item=grouped.setdefault(name,{"unique":not bool(non_unique),"cols":[]}); item["cols"].append((seq,col))
        return [IndexInfo(str(name),data["unique"],[str(c) for _,c in sorted(data["cols"])]) for name,data in grouped.items()]

    def get_foreign_keys(self,table:str,schema:str="")->List[ForeignKeyInfo]:
        schema=schema or self.profile.database
        sql=("SELECT k.constraint_name,k.column_name,k.referenced_table_name,k.referenced_column_name,k.referenced_table_schema,k.ordinal_position,"
             "r.update_rule,r.delete_rule FROM information_schema.key_column_usage k LEFT JOIN information_schema.referential_constraints r "
             "ON r.constraint_schema=k.constraint_schema AND r.constraint_name=k.constraint_name WHERE k.table_schema=%s AND k.table_name=%s AND k.referenced_table_name IS NOT NULL ORDER BY k.constraint_name,k.ordinal_position")
        rows=self.execute(sql,[schema,table],max_rows=None).rows
        grouped={}
        for name,col,rt,rc,rs,pos,up,dele in rows:
            item=grouped.setdefault(name,{"cols":[],"refs":[],"table":rt,"schema":rs,"up":up,"del":dele}); item["cols"].append((pos,col));item["refs"].append((pos,rc))
        return [ForeignKeyInfo(str(n),[str(c) for _,c in sorted(d['cols'])],str(d['table']),[str(c) for _,c in sorted(d['refs'])],str(d['schema'] or ''),str(d['up'] or ''),str(d['del'] or '')) for n,d in grouped.items()]

    def get_ddl(self,table:str,schema:str="")->str:
        row=self.execute(f"SHOW CREATE TABLE {self.qualified_name(table,schema or self.profile.database)}",max_rows=None).rows
        return str(row[0][1]) if row and len(row[0])>1 else ""

    def get_additional_ddl(self,table:str,schema:str="")->List[str]:
        return []

    def clear_database_for_import(self)->int:
        db=self.profile.database
        if not db or db.lower() in self.SYSTEM_DATABASES: raise DatabaseError("不能覆盖 MySQL 系统数据库")
        views=self.execute("SELECT table_name FROM information_schema.views WHERE table_schema=%s",[db],max_rows=None).rows
        tables=self.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE'",[db],max_rows=None).rows
        routines=self.execute("SELECT routine_name,routine_type FROM information_schema.routines WHERE routine_schema=%s",[db],max_rows=None).rows
        events=self.execute("SELECT event_name FROM information_schema.events WHERE event_schema=%s",[db],max_rows=None).rows
        self.execute("SET FOREIGN_KEY_CHECKS = 0")
        try:
            for (name,) in views:self.execute(f"DROP VIEW IF EXISTS {self.qualified_name(name,db)}")
            for (name,) in tables:self.execute(f"DROP TABLE IF EXISTS {self.qualified_name(name,db)}")
            for name,kind in routines:self.execute(f"DROP {str(kind).upper()} IF EXISTS {self.qualified_name(name,db)}")
            for (name,) in events:self.execute(f"DROP EVENT IF EXISTS {self.qualified_name(name,db)}")
        finally:self.execute("SET FOREIGN_KEY_CHECKS = 1")
        return len(views)+len(tables)+len(routines)+len(events)

    def drop_database(self,database:str)->None:
        try: import mysql.connector  # type: ignore
        except Exception as exc: raise DriverMissingError("缺少 MySQL 驱动") from exc
        opts={"host":self.profile.host or "localhost","port":int(self.profile.port or 3306),"user":self.profile.user,"password":self.profile.password,"connection_timeout":8,"use_pure":True}
        conn=mysql.connector.connect(**opts); cur=conn.cursor()
        try: cur.execute(f"DROP DATABASE {self.quote_identifier(database)}"); conn.commit()
        finally:
            try:cur.close()
            except Exception:pass
            try:conn.close()
            except Exception:pass

    def apply_table_design(self,table:str,columns:Sequence[EditableColumn],schema:str="")->None:
        self.validate_table_design(columns); old=self.get_columns(table,schema); old_by={c.name:c for c in old}; retained={c.original_name for c in columns if c.original_name}
        clauses=[]
        for name in old_by:
            if name not in retained:clauses.append(f"DROP COLUMN {self.quote_identifier(name)}")
        old_pk=[c.name for c in old if c.primary_key]; new_pk=[c.name for c in columns if c.primary_key]
        if old_pk and old_pk != [c.original_name or c.name for c in columns if c.primary_key]: clauses.append("DROP PRIMARY KEY")
        for c in columns:
            definition=f"{c.data_type.strip()}" + (" NULL" if c.nullable else " NOT NULL")
            if c.default not in (None,""):
                formatted=self.format_default(c.default,c.data_type)
                if formatted: definition+=f" DEFAULT {formatted}"
            if c.auto_increment:definition+=" AUTO_INCREMENT"
            if c.original_name and c.original_name in old_by:
                oldc=old_by[c.original_name]
                changed=(c.name!=c.original_name or c.data_type.strip().lower()!=oldc.data_type.strip().lower() or c.nullable!=oldc.nullable or str(c.default or "")!=str(oldc.default or "") or c.auto_increment!=oldc.auto_increment)
                if changed:clauses.append(f"CHANGE COLUMN {self.quote_identifier(c.original_name)} {self.quote_identifier(c.name)} {definition}")
            else:clauses.append(f"ADD COLUMN {self.quote_identifier(c.name)} {definition}")
        # Match the original implementation's explicit PK clause, even if same PK remains.
        if new_pk: clauses.append("ADD PRIMARY KEY ("+", ".join(self.quote_identifier(n) for n in new_pk)+")")
        if clauses:self.execute(f"ALTER TABLE {self.qualified_name(table,schema or self.profile.database)}\n  "+",\n  ".join(clauses))


class PostgreSQLAdapter(DatabaseAdapter):
    placeholder="%s"
    def connect(self)->None:
        try: import psycopg2  # type: ignore
        except Exception as exc: raise DriverMissingError("缺少 PostgreSQL 驱动 psycopg2") from exc
        try:self.connection=psycopg2.connect(host=self.profile.host or "localhost",port=int(self.profile.port or 5432),user=self.profile.user,password=self.profile.password,dbname=self.profile.database or "postgres",connect_timeout=8)
        except Exception as exc:raise DatabaseError(f"PostgreSQL 连接失败：{exc}") from exc
    def list_namespaces(self)->List[NamespaceInfo]:
        rows=self.execute("SELECT datname FROM pg_database WHERE datallowconn ORDER BY datname",max_rows=None).rows
        return [NamespaceInfo(str(r[0]),str(r[0]) in {"postgres","template0","template1"}) for r in rows]
    def open_namespace(self,namespace:str)->"PostgreSQLAdapter":
        data=asdict(self.profile);data["database"]=namespace;data["profile_id"]=self.profile.profile_id;adapter=PostgreSQLAdapter(ConnectionProfile(**data));adapter.connect();return adapter
    def list_objects(self,namespace:str="")->List[TableObject]:
        rows=self.execute("SELECT table_schema,table_name,table_type FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY table_schema,table_name",max_rows=None).rows
        return [TableObject(str(n),"view" if str(t).upper()=="VIEW" else "table",str(s)) for s,n,t in rows]
    def get_columns(self,table:str,schema:str="")->List[ColumnInfo]:
        schema=schema or "public"
        sql=("SELECT c.column_name,c.data_type,c.is_nullable,c.column_default,c.ordinal_position,c.is_identity "
             "FROM information_schema.columns c WHERE c.table_schema=%s AND c.table_name=%s ORDER BY c.ordinal_position")
        rows=self.execute(sql,[schema,table],max_rows=None).rows
        pk=set()
        try:
            pr=self.execute("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey) WHERE i.indrelid=%s::regclass AND i.indisprimary",[f"{schema}.{table}"],max_rows=None).rows;pk={r[0] for r in pr}
        except Exception:pass
        result=[]
        for n,t,null,default,pos,identity in rows:
            auto=str(identity).upper()=="YES" or (default and "nextval(" in str(default))
            result.append(ColumnInfo(str(n),str(t),str(null).upper()=="YES",default,str(n) in pk,int(pos),bool(auto)))
        return result
    def get_indexes(self,table:str,schema:str="")->List[IndexInfo]:
        schema=schema or "public"; rows=self.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname=%s AND tablename=%s",[schema,table],max_rows=None).rows;out=[]
        for name,ddl in rows:
            m=re.search(r"\((.*)\)",str(ddl));cols=[x.strip().strip('"') for x in m.group(1).split(',')] if m else []
            out.append(IndexInfo(str(name),"UNIQUE INDEX" in str(ddl).upper(),cols))
        return out
    def get_foreign_keys(self,table:str,schema:str="")->List[ForeignKeyInfo]:
        schema=schema or "public"
        sql=("SELECT tc.constraint_name,kcu.column_name,ccu.table_schema,ccu.table_name,ccu.column_name,rc.update_rule,rc.delete_rule,kcu.ordinal_position "
             "FROM information_schema.table_constraints tc JOIN information_schema.key_column_usage kcu ON tc.constraint_name=kcu.constraint_name AND tc.constraint_schema=kcu.constraint_schema "
             "JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name=tc.constraint_name AND ccu.constraint_schema=tc.constraint_schema "
             "LEFT JOIN information_schema.referential_constraints rc ON rc.constraint_name=tc.constraint_name AND rc.constraint_schema=tc.constraint_schema "
             "WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema=%s AND tc.table_name=%s ORDER BY tc.constraint_name,kcu.ordinal_position")
        rows=self.execute(sql,[schema,table],max_rows=None).rows;group={}
        for name,col,rs,rt,rc,up,dele,pos in rows:
            d=group.setdefault(name,{"cols":[],"refs":[],"rs":rs,"rt":rt,"up":up,"del":dele});d["cols"].append((pos,col));d["refs"].append((pos,rc))
        return [ForeignKeyInfo(str(n),[str(c) for _,c in sorted(d['cols'])],str(d['rt']),[str(c) for _,c in sorted(d['refs'])],str(d['rs']),str(d['up'] or ''),str(d['del'] or '')) for n,d in group.items()]
    def get_ddl(self,table:str,schema:str="")->str:
        schema=schema or "public"; cols=self.get_columns(table,schema)
        # view/materialized handling expected by exporter
        try:
            kind=self.execute("SELECT c.relkind, pg_get_viewdef(c.oid, true) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s",[schema,table],max_rows=None).rows
            if kind and kind[0][0] in {"v","m"} and kind[0][1]: return f"CREATE VIEW {self.qualified_name(table,schema)} AS {kind[0][1]}"
        except Exception:pass
        identity={}
        try:
            rows=self.execute("SELECT column_name, identity_generation FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND is_identity='YES'",[schema,table],max_rows=None).rows;identity={r[0]:r[1] for r in rows}
        except Exception:pass
        defs=[]
        for c in cols:
            dtype=c.data_type
            default=c.default
            if c.name in identity:
                part=f"{self.quote_identifier(c.name)} {dtype} GENERATED {str(identity[c.name]).upper()} AS IDENTITY"
            elif default and "nextval(" in str(default):
                serial="bigserial" if "bigint" in dtype.lower() else "smallserial" if "smallint" in dtype.lower() else "serial"
                part=f"{self.quote_identifier(c.name)} {serial}"
            else:
                part=f"{self.quote_identifier(c.name)} {dtype}"
                if default not in (None,""):part+=f" DEFAULT {default}"
            if not c.nullable:part+=" NOT NULL"
            defs.append(part)
        pks=[c.name for c in cols if c.primary_key]
        if pks:defs.append("PRIMARY KEY ("+", ".join(self.quote_identifier(x) for x in pks)+")")
        return f"CREATE TABLE {self.qualified_name(table,schema)} (\n  "+",\n  ".join(defs)+"\n)"
    def get_additional_ddl(self,table:str,schema:str="")->List[str]:
        schema=schema or "public"; out=[]
        for c in self.get_columns(table,schema):
            if c.auto_increment:
                qtable=self.qualified_name(table,schema); qcol=self.quote_identifier(c.name)
                out.append(f"SELECT setval(pg_get_serial_sequence('{schema}.{table}', '{c.name}'), COALESCE((SELECT MAX({qcol}) FROM {qtable}), 1), true)")
        try:
            out.extend(str(r[0]) for r in self.execute("SELECT indexdef FROM pg_indexes WHERE schemaname=%s AND tablename=%s AND indexname NOT IN (SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass)",[schema,table,f"{schema}.{table}"],max_rows=None).rows)
        except Exception:pass
        try:
            out.extend(str(r[0]) for r in self.execute("SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s AND NOT t.tgisinternal",[schema,table],max_rows=None).rows)
        except Exception:pass
        return out
    def execute_copy(self,sql:str,data:Any)->int:
        if self.connection is None:raise ConnectionLostError("数据库尚未连接")
        try:
            cur=self.connection.cursor();cur.copy_expert(sql,data);count=getattr(cur,"rowcount",0);self.connection.commit();cur.close();return max(0,int(count or 0))
        except Exception as exc:
            try:self.connection.rollback()
            except Exception:pass
            raise DatabaseError(str(exc)) from exc
    def clear_database_for_import(self)->int:
        rows=self.execute("SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema'",max_rows=None).rows
        for (name,) in rows:self.execute(f"DROP SCHEMA {self.quote_identifier(name)} CASCADE")
        self.execute("CREATE SCHEMA public");self.execute("GRANT ALL ON SCHEMA public TO PUBLIC")
        return len(rows)
    def drop_database(self,database:str)->None:
        try:import psycopg2  # type: ignore
        except Exception as exc:raise DriverMissingError("缺少 PostgreSQL 驱动") from exc
        conn=psycopg2.connect(host=self.profile.host or "localhost",port=int(self.profile.port or 5432),user=self.profile.user,password=self.profile.password,dbname="postgres",connect_timeout=8);conn.autocommit=True;cur=conn.cursor()
        try:cur.execute(f"DROP DATABASE {self.quote_identifier(database)}")
        finally:
            try:cur.close()
            except Exception:pass
            try:conn.close()
            except Exception:pass
    def apply_table_design(self,table:str,columns:Sequence[EditableColumn],schema:str="")->None:
        self.validate_table_design(columns);old=self.get_columns(table,schema);old_by={c.name:c for c in old};retained={c.original_name for c in columns if c.original_name};q=self.qualified_name(table,schema or "public")
        clauses=[]
        for name in old_by:
            if name not in retained:clauses.append(f"DROP COLUMN {self.quote_identifier(name)}")
        for c in columns:
            if c.original_name and c.original_name in old_by:
                if c.name!=c.original_name:clauses.append(f"RENAME COLUMN {self.quote_identifier(c.original_name)} TO {self.quote_identifier(c.name)}")
                # PostgreSQL ALTER TYPE/NULL/default are separate operations; execute sequentially below.
            else:
                part=f"ADD COLUMN {self.quote_identifier(c.name)} {c.data_type}"
                if not c.nullable:part+=" NOT NULL"
                if c.default not in (None,""):part+=f" DEFAULT {self.format_default(c.default,c.data_type)}"
                clauses.append(part)
        for clause in clauses:self.execute(f"ALTER TABLE {q} {clause}")


def create_adapter(profile: ConnectionProfile) -> DatabaseAdapter:
    kind=(profile.kind or "sqlite").lower()
    if kind=="sqlite": return SQLiteAdapter(profile)
    if kind=="mysql": return MySQLAdapter(profile)
    if kind in {"postgres","postgresql"}: return PostgreSQLAdapter(profile)
    raise DatabaseError(f"不支持的数据库类型：{profile.kind}")


def infer_sqlite_type(values: Sequence[str]) -> str:
    clean=[v.strip() for v in values if v is not None and str(v).strip()!=""]
    if not clean:return "TEXT"
    try:
        for v in clean:int(v)
        return "INTEGER"
    except Exception:pass
    try:
        for v in clean:float(v)
        return "REAL"
    except Exception:return "TEXT"


def read_csv_preview(path: Path) -> Tuple[List[str], List[List[str]], str, str]:
    raw=Path(path).read_bytes(); text=None; encoding="utf-8-sig"
    for enc in ("utf-8-sig","gb18030","utf-8"):
        try:text=raw.decode(enc);encoding=enc;break
        except UnicodeDecodeError:continue
    if text is None:text=raw.decode("utf-8",errors="replace")
    sample=text[:8192]
    try:delimiter=csv.Sniffer().sniff(sample,delimiters=",;\t|").delimiter
    except Exception:delimiter=","
    rows=list(csv.reader(text.splitlines(),delimiter=delimiter))
    if not rows:return [],[],encoding,delimiter
    width=max(len(r) for r in rows);headers=[(x.strip() or f"column_{i+1}") for i,x in enumerate(rows[0])]
    if len(headers)<width:headers += [f"column_{i+1}" for i in range(len(headers),width)]
    data=[r+[""]*(width-len(r)) for r in rows[1:]]
    return headers,data,encoding,delimiter


def import_csv(adapter: DatabaseAdapter, path: Path, table: str, schema: str = "") -> Tuple[int,List[ColumnInfo]]:
    headers,rows,_enc,_delim=read_csv_preview(path)
    if not headers:raise DatabaseError("CSV 文件为空")
    types=[infer_sqlite_type([r[i] for r in rows]) for i in range(len(headers))]
    definitions=", ".join(f"{adapter.quote_identifier(name)} {dtype}" for name,dtype in zip(headers,types))
    adapter.execute(f"CREATE TABLE {adapter.qualified_name(table,schema)} ({definitions})")
    converted=[]
    for row in rows:
        vals=[]
        for value,dtype in zip(row,types):
            if value=="":vals.append(None)
            elif dtype=="INTEGER":vals.append(int(value))
            elif dtype=="REAL":vals.append(float(value))
            else:vals.append(value)
        converted.append(vals)
    sql=f"INSERT INTO {adapter.qualified_name(table,schema)} ({', '.join(adapter.quote_identifier(h) for h in headers)}) VALUES ({', '.join([adapter.placeholder]*len(headers))})"
    if converted:adapter.executemany(sql,converted)
    return len(rows),[ColumnInfo(h,t,True,None,False,i+1,False) for i,(h,t) in enumerate(zip(headers,types))]


def export_csv(path: Path, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    with Path(path).open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.writer(stream);writer.writerow(list(columns));writer.writerows(rows)
