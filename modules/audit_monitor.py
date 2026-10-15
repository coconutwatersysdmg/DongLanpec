# -*- coding: utf-8 -*-
"""DongLanpec global audit/data-flow monitor.

The monitor is deliberately implemented at framework boundaries instead of in
individual business functions:

* QApplication event filter -> user operations and edited values
* QMessageBox.exec_         -> prompts and the user's answer
* PyMySQL cursor/connection -> SQL, parameters, returned rows and transactions

Audit failures must never interrupt the application.  Every public hook and
every patched method therefore falls back to the original behaviour.
"""

from __future__ import annotations

import contextlib
import builtins
import datetime as _datetime
import decimal
import hashlib
import json
import logging
import logging.handlers
import os
import platform
import queue
import re
import socket
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import pymysql
from PyQt5 import QtCore, QtWidgets


_MONITOR = None
_INSTALL_LOCK = threading.RLock()
_AUDIT_LOG_FILE_RE = re.compile(
    r"^audit(?:_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_\d{6})?\.jsonl(?:\.\d{4}-\d{2}-\d{2})?$"
)
_SENSITIVE_KEY_RE = re.compile(
    r"password|passwd|pwd|secret|token|authorization|cookie|api[_-]?key|密码|口令|密钥",
    re.IGNORECASE,
)
_WRITE_SQL = {"insert", "update", "delete", "replace", "merge", "call", "load"}
_READ_SQL = {"select", "show", "describe", "desc", "explain", "with"}
_SCHEMA_SQL = {"create", "alter", "drop", "truncate", "rename", "grant", "revoke"}
_SQL_OPERATIONS = {
    "select": ("查询", "R"),
    "show": ("查询", "R"),
    "describe": ("查询", "R"),
    "desc": ("查询", "R"),
    "explain": ("查询", "R"),
    "with": ("查询", "R"),
    "insert": ("新增", "C"),
    "replace": ("新增或替换", "C/U"),
    "update": ("修改", "U"),
    "delete": ("删除", "D"),
    "merge": ("合并", "C/U"),
    "call": ("调用过程", "EXECUTE"),
    "load": ("批量导入", "C"),
    "create": ("创建结构", "DDL"),
    "alter": ("修改结构", "DDL"),
    "drop": ("删除结构", "DDL"),
    "truncate": ("清空表", "D"),
    "rename": ("重命名结构", "DDL"),
}
_INTERFACE_BY_PATH = {
    "modules/chanpinguanli/": "项目管理",
    "modules/condition_input/": "条件输入",
    "modules/cailiaodingyi/": "元件定义",
    "modules/guankoudingyi/": "管口及附件定义",
    "modules/buguan/": "管束设计",
    "modules/qiangdujisuan/": "设计运算",
    "modules/twod/": "图纸绘制",
    "modules/wenbenshengcheng/": "文本说明生成",
    "modules/yudingyi/": "预定义配置",
    "modules/json_backfill/": "计算输入反填",
    "register.py": "用户登录",
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _application_root() -> Path:
    """Return the directory containing the running software, without a fixed drive."""

    if getattr(sys, "frozen", False):
        # PyInstaller onedir/onefile: sys.executable remains the user-facing EXE.
        return Path(sys.executable).resolve().parent
    # Source mode: this module lives at <software root>/modules/audit_monitor.py.
    return Path(__file__).resolve().parent.parent


def _decode(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return repr(value)
    return value


def _compact_sql(sql: Any, limit: int) -> str:
    sql_text = _decode(sql)
    if not isinstance(sql_text, str):
        sql_text = str(sql_text)
    sql_text = re.sub(r"\s+", " ", sql_text).strip()
    if len(sql_text) > limit:
        return sql_text[:limit] + "...<truncated>"
    return sql_text


def _sql_keyword(sql: Any) -> str:
    text = _compact_sql(sql, 500).lstrip("( \t\r\n")
    text = re.sub(r"^(?:/\*.*?\*/\s*|--[^\r\n]*[\r\n]+\s*)+", "", text, flags=re.DOTALL)
    match = re.match(r"([A-Za-z]+)", text)
    keyword = match.group(1).lower() if match else "unknown"
    if keyword == "with":
        # A CTE may ultimately perform SELECT/INSERT/UPDATE/DELETE.  Use the
        # statement following the final CTE closing parenthesis when present.
        cte_operations = re.findall(
            r"\)\s*(select|insert|update|delete|replace|merge)\b",
            text,
            flags=re.IGNORECASE,
        )
        if cte_operations:
            keyword = cte_operations[-1].lower()
    return keyword


def _sql_kind(sql: Any) -> str:
    keyword = _sql_keyword(sql)
    if keyword in _WRITE_SQL:
        return "write"
    if keyword in _READ_SQL:
        return "read"
    if keyword in _SCHEMA_SQL:
        return "schema"
    return "other"


def _extract_tables(sql: Any) -> list:
    """Best-effort table extraction for human-readable audit summaries."""

    text = _compact_sql(sql, 20000)
    patterns = (
        r"\b(?:from|join|update|into)\s+((?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?)",
        r"\b(?:table|truncate)\s+(?:if\s+(?:not\s+)?exists\s+)?((?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?)",
    )
    tables = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            table = re.sub(r"\s*\.\s*", ".", match.group(1)).replace("`", "")
            if table and table.lower() not in {"select", "set", "values"} and table not in tables:
                tables.append(table)
    show_match = re.search(r"\bshow\s+(?:full\s+)?tables\s+from\s+(`[^`]+`|[\w\u4e00-\u9fff$]+)", text, re.I)
    if show_match:
        database_name = show_match.group(1).replace("`", "")
        marker = "%s.*" % database_name
        if database_name in tables:
            tables.remove(database_name)
        if marker not in tables:
            tables.append(marker)
    return tables[:20]


def _parameter_count(args: Any) -> int:
    if args is None:
        return 0
    if isinstance(args, dict):
        return len(args)
    if isinstance(args, (list, tuple, set, frozenset)):
        return len(args)
    return 1


def _split_sql_list(text: str) -> list:
    parts = []
    current = []
    depth = 0
    quote = None
    for char in text:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"', "`"}:
            quote = char
            current.append(char)
        elif char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _clean_identifier(value: str) -> str:
    value = value.strip().replace("`", "")
    value = re.sub(r"\s+as\s+.+$", "", value, flags=re.IGNORECASE).strip()
    if re.match(r"^[\w\u4e00-\u9fff$]+\s+[\w\u4e00-\u9fff$]+$", value):
        value = value.split()[0]
    return re.sub(r"\s*\.\s*", ".", value)


def _extract_sql_fields(sql: Any) -> Dict[str, list]:
    """Best-effort SELECT/write/condition field extraction."""

    text = _compact_sql(sql, 30000)
    keyword = _sql_keyword(text)
    selected = []
    written = []
    conditions = []

    if keyword == "select":
        match = re.search(r"\bselect\s+(.*?)\s+from\s", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            for expression in _split_sql_list(match.group(1)):
                expression = re.sub(r"\s+as\s+.+$", "", expression, flags=re.IGNORECASE).strip()
                if expression == "*" or expression.endswith(".*"):
                    field = _clean_identifier(expression)
                else:
                    identifiers = re.findall(r"`([^`]+)`", expression)
                    field = _clean_identifier(".".join(identifiers)) if identifiers else _clean_identifier(expression)
                if field and field not in selected:
                    selected.append(field)

    insert_match = re.search(
        r"\b(?:insert(?:\s+ignore)?|replace)\s+into\s+(?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?\s*\((.*?)\)\s*(?:values|select|set)\b",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if insert_match:
        written.extend(_clean_identifier(item) for item in _split_sql_list(insert_match.group(1)))

    insert_set_match = re.search(
        r"\b(?:insert(?:\s+ignore)?|replace)\s+into\s+.+?\s+set\s+(.*?)(?:\s+on\s+duplicate\s+key\s+update\s+|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if insert_set_match:
        for assignment in _split_sql_list(insert_set_match.group(1)):
            match = re.match(r"\s*(`[^`]+`|[\w\u4e00-\u9fff$]+)\s*=", assignment)
            if match:
                written.append(_clean_identifier(match.group(1)))

    update_match = re.search(
        r"\bupdate\s+.+?\s+set\s+(.*?)(?:\s+where\s+|\s+order\s+by\s+|\s+limit\s+|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if update_match:
        for assignment in _split_sql_list(update_match.group(1)):
            match = re.match(r"\s*((?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?)\s*=", assignment)
            if match:
                written.append(_clean_identifier(match.group(1)))

    duplicate_match = re.search(r"\bon\s+duplicate\s+key\s+update\s+(.*)$", text, flags=re.I | re.S)
    if duplicate_match:
        for assignment in _split_sql_list(duplicate_match.group(1)):
            match = re.match(r"\s*(`[^`]+`|[\w\u4e00-\u9fff$]+)\s*=", assignment)
            if match:
                written.append(_clean_identifier(match.group(1)))

    where_match = re.search(r"\bwhere\s+(.*?)(?:\s+group\s+by\s+|\s+order\s+by\s+|\s+limit\s+|$)", text, flags=re.I | re.S)
    if where_match:
        condition_pattern = (
            r"((?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?)"
            r"\s*(?:=|<>|!=|<=|>=|<|>|\blike\b|\bin\b|\bis\b|\bbetween\b)"
        )
        for match in re.finditer(condition_pattern, where_match.group(1), flags=re.I):
            conditions.append(_clean_identifier(match.group(1)))

    def unique(items: list) -> list:
        result = []
        for item in items:
            if item and item not in result:
                result.append(item)
        return result[:100]

    selected = unique(selected)
    written = unique(written)
    conditions = unique(conditions)
    all_fields = unique(selected + written + conditions)
    return {
        "fields": all_fields,
        "selected_fields": selected,
        "written_fields": written,
        "condition_fields": conditions,
    }


_SQL_PLACEHOLDER_RE = re.compile(r"(?<!%)%(?:\(([^)]+)\))?s", re.IGNORECASE)


def _extract_parameter_field_values(
    sql: Any,
    args: Any,
    many: bool = False,
    max_rows: int = 20,
    field_context: Optional[Dict[str, list]] = None,
) -> Dict[str, Any]:
    """Map PyMySQL parameters back to write/condition fields, best effort.

    Only a bounded prefix of ``executemany`` input is inspected. This keeps the
    concise audit useful without copying a potentially large import batch.
    """

    if args is None:
        return {}
    text = _compact_sql(sql, 30000)
    placeholders = list(_SQL_PLACEHOLDER_RE.finditer(text))
    if not placeholders:
        return {}

    field_context = field_context or _extract_sql_fields(text)
    placeholder_targets: Dict[int, tuple] = {}

    def target_region(start: int, end: int, kind: str, field: str) -> None:
        cleaned = _clean_identifier(field)
        if not cleaned:
            return
        for index, placeholder in enumerate(placeholders):
            if start <= placeholder.start() and placeholder.end() <= end:
                placeholder_targets[index] = (kind, cleaned)

    # INSERT/REPLACE (...columns...) VALUES (...parameters...)
    insert_match = re.search(
        r"\b(?:insert(?:\s+ignore)?|replace)\s+into\s+"
        r"(?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?"
        r"\s*\((.*?)\)\s*values\s*\((.*?)\)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if insert_match:
        columns = [_clean_identifier(item) for item in _split_sql_list(insert_match.group(1))]
        expressions = _split_sql_list(insert_match.group(2))
        search_at = 0
        values_text = insert_match.group(2)
        values_start = insert_match.start(2)
        for column, expression in zip(columns, expressions):
            relative = values_text.find(expression, search_at)
            if relative < 0:
                continue
            start = values_start + relative
            target_region(start, start + len(expression), "written", column)
            search_at = relative + len(expression)

    def target_assignments(match: Any, kind: str = "written") -> None:
        if not match:
            return
        assignment_text = match.group(1)
        assignment_start = match.start(1)
        search_at = 0
        for assignment in _split_sql_list(assignment_text):
            relative = assignment_text.find(assignment, search_at)
            if relative < 0:
                continue
            field_match = re.match(
                r"\s*((?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?)\s*=",
                assignment,
            )
            if field_match:
                start = assignment_start + relative
                target_region(start, start + len(assignment), kind, field_match.group(1))
            search_at = relative + len(assignment)

    keyword = _sql_keyword(text)
    if keyword == "update":
        target_assignments(
            re.search(
                r"\bupdate\s+.+?\s+set\s+(.*?)(?:\s+where\s+|\s+order\s+by\s+|\s+limit\s+|$)",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
    elif keyword in {"insert", "replace"}:
        target_assignments(
            re.search(
                r"\b(?:insert(?:\s+ignore)?|replace)\s+into\s+.+?\s+set\s+"
                r"(.*?)(?:\s+on\s+duplicate\s+key\s+update\s+|$)",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
        )
    target_assignments(
        re.search(r"\bon\s+duplicate\s+key\s+update\s+(.*)$", text, flags=re.I | re.S)
    )

    # Associate every WHERE placeholder with the closest preceding condition.
    where_match = re.search(
        r"\bwhere\s+(.*?)(?:\s+group\s+by\s+|\s+order\s+by\s+|\s+limit\s+|$)",
        text,
        flags=re.I | re.S,
    )
    if where_match:
        where_text = where_match.group(1)
        where_start = where_match.start(1)
        condition_pattern = re.compile(
            r"((?:`[^`]+`|[\w\u4e00-\u9fff$]+)(?:\s*\.\s*(?:`[^`]+`|[\w\u4e00-\u9fff$]+))?)"
            r"\s*(?:=|<>|!=|<=|>=|<|>|\blike\b|\bin\b|\bis\b|\bbetween\b)",
            flags=re.I,
        )
        for index, placeholder in enumerate(placeholders):
            relative = placeholder.start() - where_start
            if relative < 0 or relative > len(where_text):
                continue
            matches = list(condition_pattern.finditer(where_text, 0, relative + 1))
            if matches:
                placeholder_targets[index] = ("condition", _clean_identifier(matches[-1].group(1)))

    if many and isinstance(args, (list, tuple)):
        parameter_rows = list(args[:max_rows])
        total_rows = len(args)
    elif many:
        # Do not consume an arbitrary iterator after the database driver has
        # already used it. Unknown iterables remain count-only.
        return {}
    else:
        parameter_rows = [args]
        total_rows = 1

    result: Dict[str, Dict[str, list]] = {
        "written_field_values": {},
        "condition_field_values": {},
    }
    for row in parameter_rows:
        if isinstance(row, dict):
            sequence = None
        elif isinstance(row, (list, tuple)):
            sequence = row
        else:
            sequence = (row,)
        for index, placeholder in enumerate(placeholders):
            name = placeholder.group(1)
            found = False
            value = None
            if isinstance(row, dict) and name is not None and name in row:
                value = row[name]
                found = True
            elif sequence is not None and name is None and index < len(sequence):
                value = sequence[index]
                found = True
            if not found:
                continue
            target = placeholder_targets.get(index)
            if target is None and name:
                cleaned_name = _clean_identifier(name)
                if cleaned_name in field_context["written_fields"]:
                    target = ("written", cleaned_name)
                elif cleaned_name in field_context["condition_fields"]:
                    target = ("condition", cleaned_name)
            if target is None:
                continue
            kind, field = target
            mapping_key = "written_field_values" if kind == "written" else "condition_field_values"
            values = result[mapping_key].setdefault(field, [])
            if value not in values and len(values) < max_rows:
                values.append(value)

    output: Dict[str, Any] = {key: value for key, value in result.items() if value}
    if output:
        output["field_value_rows"] = total_rows
        if total_rows > len(parameter_rows):
            output["field_values_truncated"] = True
    return output


def _event_category(event_type: str) -> str:
    if event_type.startswith("database.backup"):
        return "数据库备份"
    if event_type.startswith("database.restore"):
        return "数据库恢复"
    if event_type.startswith("database.sync"):
        return "数据库同步"
    if event_type.startswith("db.") or event_type.startswith("database.operation"):
        return "数据库操作"
    if event_type.startswith("ui.prompt") or event_type.startswith("ui.dialog"):
        return "界面提示"
    if event_type.startswith("ui."):
        return "界面操作"
    if event_type.startswith("application."):
        return "系统异常"
    if event_type.startswith("session."):
        return "程序会话"
    return "业务事件"


class _AuditLogBridge(logging.Handler):
    """Copies existing Python logging records into the audit stream."""

    def __init__(self, monitor: "GlobalAuditMonitor") -> None:
        super().__init__(level=logging.WARNING)
        self.monitor = monitor

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == self.monitor.logger.name:
            return
        try:
            self.monitor.record(
                "application.log",
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
                source={"file": record.pathname, "line": record.lineno, "function": record.funcName},
                exception=self.formatException(record.exc_info) if record.exc_info else None,
            )
        except Exception:
            pass

    @staticmethod
    def formatException(exc_info: Any) -> str:
        return "".join(traceback.format_exception(*exc_info))


class _AuditedJsonFile:
    """Transparent file proxy that reports JSON reads/writes when closed."""

    def __init__(
        self,
        monitor: "GlobalAuditMonitor",
        raw_file: Any,
        path: Path,
        mode: str,
        existed_before: Optional[bool] = None,
        size_before: Optional[int] = None,
    ) -> None:
        self._monitor = monitor
        self._raw_file = raw_file
        self._path = path
        self._mode = mode
        self._existed_before = path.exists() if existed_before is None else existed_before
        self._size_before = (
            (path.stat().st_size if self._existed_before and path.exists() else 0)
            if size_before is None
            else size_before
        )
        self._read = False
        self._written = False
        self._reported = False
        self._error = None
        self._json_shape = None
        self._captured_text = []
        self._captured_chars = 0
        self._capture_complete = True
        self._started = time.perf_counter()
        self._source = monitor._source_context() if monitor.detail_mode else {}
        self._interface = monitor._visible_interface()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw_file, name)

    def __iter__(self) -> Any:
        return self

    def __next__(self) -> Any:
        self._read = True
        return next(self._raw_file)

    def __enter__(self) -> "_AuditedJsonFile":
        self._raw_file.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, exc_tb: Any) -> Any:
        if exc_value is not None:
            self._error = repr(exc_value)
        try:
            return self._raw_file.__exit__(exc_type, exc_value, exc_tb)
        finally:
            self._report()

    def read(self, *args: Any, **kwargs: Any) -> Any:
        self._read = True
        return self._raw_file.read(*args, **kwargs)

    def readline(self, *args: Any, **kwargs: Any) -> Any:
        self._read = True
        return self._raw_file.readline(*args, **kwargs)

    def readlines(self, *args: Any, **kwargs: Any) -> Any:
        self._read = True
        return self._raw_file.readlines(*args, **kwargs)

    def write(self, data: Any) -> Any:
        self._written = True
        self._capture_write(data)
        return self._raw_file.write(data)

    def writelines(self, lines: Any) -> Any:
        self._written = True
        monitor_file = self

        def audited_lines() -> Any:
            for line in lines:
                monitor_file._capture_write(line)
                yield line

        return self._raw_file.writelines(audited_lines())

    def truncate(self, *args: Any, **kwargs: Any) -> Any:
        self._written = True
        return self._raw_file.truncate(*args, **kwargs)

    def close(self) -> None:
        try:
            self._raw_file.close()
        finally:
            self._report()

    def set_json_shape(self, value: Any) -> None:
        self._json_shape = self._monitor._json_shape(value)
        if any(flag in self._mode.lower() for flag in ("w", "a", "x", "+")):
            # json.dump already gave us the structure; stop buffering chunks.
            self._captured_text = []
            self._capture_complete = False

    def _capture_write(self, data: Any) -> None:
        if not self._capture_complete:
            return
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        else:
            text = str(data)
        new_size = self._captured_chars + len(text)
        if new_size > self._monitor.max_json_inspect_chars:
            self._captured_text = []
            self._capture_complete = False
            return
        self._captured_text.append(text)
        self._captured_chars = new_size

    def _operation(self) -> str:
        mode = self._mode.lower()
        if self._read and self._written:
            return "读取并修改"
        if self._written:
            if "a" in mode:
                return "追加写入"
            return "覆盖写入" if self._existed_before else "创建"
        return "读取"

    def _report(self) -> None:
        if self._reported or (not self._read and not self._written):
            return
        self._reported = True
        self._monitor._record_json_file_operation(
            path=self._path,
            operation=self._operation(),
            mode=self._mode,
            existed_before=self._existed_before,
            size_before=self._size_before,
            interface=self._interface,
            source=self._source,
            duration_ms=round((time.perf_counter() - self._started) * 1000, 3),
            error=self._error,
            json_shape=self._json_shape,
            captured_text="".join(self._captured_text) if self._capture_complete else None,
        )


class GlobalAuditMonitor(QtCore.QObject):
    """Structured, rotating, best-effort audit monitor."""

    def __init__(self, app: QtWidgets.QApplication, app_version: str = "") -> None:
        super().__init__(app)
        self.app = app
        self.app_version = app_version
        self.enabled = _env_bool("DONGLANPEC_AUDIT_ENABLED", True)
        self.detail_mode = _env_bool("DONGLANPEC_AUDIT_DETAIL_MODE", False)
        self.capture_db_rows = _env_bool("DONGLANPEC_AUDIT_CAPTURE_DB_ROWS", self.detail_mode)
        self.capture_input_values = _env_bool("DONGLANPEC_AUDIT_CAPTURE_INPUT_VALUES", self.detail_mode)
        self.max_text_chars = _env_int("DONGLANPEC_AUDIT_MAX_TEXT_CHARS", 4000, 200, 100000)
        self.max_result_rows = _env_int("DONGLANPEC_AUDIT_MAX_RESULT_ROWS", 100, 0, 10000)
        self.max_fetch_events = _env_int("DONGLANPEC_AUDIT_MAX_FETCH_EVENTS", 50, 1, 10000)
        self.max_field_values = _env_int("DONGLANPEC_AUDIT_MAX_FIELD_VALUES", 20, 1, 1000)
        self.coalesce_window_ms = _env_int("DONGLANPEC_AUDIT_COALESCE_WINDOW_MS", 300, 0, 5000)
        self.max_json_inspect_chars = _env_int(
            "DONGLANPEC_AUDIT_MAX_JSON_INSPECT_CHARS", 262144, 0, 5000000
        )
        self.session_id = uuid.uuid4().hex
        self.started_at = _datetime.datetime.now(_datetime.timezone.utc)
        self._state = threading.local()
        self._latest_trace_id = None
        self._latest_trace_at = 0.0
        self._trace_lock = threading.RLock()
        self._context_lock = threading.RLock()
        self._event_lock = threading.RLock()
        self._latest_interface = "程序启动"
        # Keep one pending aggregate per table inside the current user action.
        # A regular dict deliberately preserves first-seen table order.
        self._pending_database_events: Dict[Any, Dict[str, Any]] = {}
        self._pending_database_window_key = None
        self._pending_database_updated_at = 0.0
        self._database_flush_stop = threading.Event()
        self._database_flush_thread = None
        self._actor = None
        self._active = True
        self._originals: Dict[str, Any] = {}
        self._root_bridge: Optional[_AuditLogBridge] = None
        self._hooked_actions = set()
        self._hooked_tab_widgets = set()
        self.application_root = _application_root()
        self.log_path = self._resolve_log_path()
        self.logger = self._create_logger()

    def _resolve_log_path(self) -> Path:
        configured = os.environ.get("DONGLANPEC_AUDIT_LOG_DIR")
        if configured:
            log_dir = Path(configured).expanduser()
        else:
            log_dir = _application_root() / "audit_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired_logs(log_dir)
        # One file per application session. Use local time in a Windows-safe
        # format and retain microseconds so even closely started sessions get
        # distinct names.
        started_local = self.started_at.astimezone()
        timestamp = started_local.strftime("%Y-%m-%d_%H-%M-%S_%f")
        return log_dir / ("audit_%s.jsonl" % timestamp)

    def _cleanup_expired_logs(self, log_dir: Path) -> None:
        """Apply retention across timestamped session files, best effort."""
        try:
            retention_days = _env_int("DONGLANPEC_AUDIT_RETENTION_DAYS", 30, 1, 3650)
            cutoff = time.time() - retention_days * 86400
            for candidate in log_dir.iterdir():
                if not _AUDIT_LOG_FILE_RE.fullmatch(candidate.name):
                    continue
                if candidate.is_file() and candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
        except Exception:
            # Retention failure must not prevent application startup or logging.
            pass

    def _create_logger(self) -> logging.Logger:
        logger = logging.getLogger("DongLanpec.audit.%s" % self.session_id)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        file_handler = logging.handlers.TimedRotatingFileHandler(
            str(self.log_path),
            when="midnight",
            interval=1,
            backupCount=_env_int("DONGLANPEC_AUDIT_RETENTION_DAYS", 30, 1, 3650),
            encoding="utf-8",
            delay=True,
        )
        file_handler.suffix = "%Y-%m-%d"
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        log_queue = queue.Queue(-1)
        queue_handler = logging.handlers.QueueHandler(log_queue)
        logger.addHandler(queue_handler)
        self._audit_file_handler = file_handler
        self._audit_log_listener = logging.handlers.QueueListener(log_queue, file_handler)
        self._audit_log_listener.start()
        return logger

    def install(self) -> "GlobalAuditMonitor":
        if not self.enabled:
            return self
        self.app.installEventFilter(self)
        self._patch_message_boxes()
        self._patch_pymysql()
        self._patch_json_files()
        self._install_exception_hooks()
        self._install_logging_bridge()
        self._start_database_flush_worker()
        self.record(
            "session.start",
            app_version=self.app_version,
            audit_log=str(self.log_path),
            process_id=os.getpid(),
            executable=sys.executable,
            frozen=bool(getattr(sys, "frozen", False)),
            host=socket.gethostname(),
            platform=platform.platform(),
            settings={
                "detail_mode": self.detail_mode,
                "capture_db_rows": self.capture_db_rows,
                "capture_input_values": self.capture_input_values,
                "max_result_rows": self.max_result_rows,
                "max_text_chars": self.max_text_chars,
                "max_field_values": self.max_field_values,
                "coalesce_window_ms": self.coalesce_window_ms,
                "max_json_inspect_chars": self.max_json_inspect_chars,
            },
        )
        return self

    def set_user(self, username: Any) -> None:
        old_actor = self._actor
        self._actor = str(username).strip() if username else None
        self.record("session.actor_changed", previous_actor=old_actor, actor=self._actor)

    def new_trace(self, source: str = "application") -> str:
        trace_id = uuid.uuid4().hex
        self._state.trace_id = trace_id
        with self._trace_lock:
            self._latest_trace_id = trace_id
            self._latest_trace_at = time.monotonic()
        return trace_id

    def current_trace(self) -> str:
        local_trace = getattr(self._state, "trace_id", None)
        if local_trace:
            return local_trace
        with self._trace_lock:
            if self._latest_trace_id:
                return self._latest_trace_id
        return self.session_id

    def _business_context(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        try:
            state_module = sys.modules.get("modules.chanpinguanli.bianl")
            if state_module is None:
                return result
            mappings = {
                "current_project_id": "project_id",
                "product_id": "product_id",
                "current_product_id": "current_product_id",
                "project_mode": "project_mode",
                "product_mode": "product_mode",
            }
            for attr, key in mappings.items():
                value = getattr(state_module, attr, None)
                if value not in (None, ""):
                    result[key] = self._jsonable(value)
            if not self._actor:
                username = getattr(state_module, "current_username", None)
                if username:
                    result["actor"] = str(username).strip()
        except Exception:
            pass
        return result

    def _source_context(self) -> Dict[str, Any]:
        """Infer the business module and interface from the nearest app frame."""

        activity = getattr(self._state, "activity", None)
        if activity:
            return dict(activity)

        root = _application_root()
        chosen = None
        try:
            for frame in reversed(traceback.extract_stack(limit=35)[:-2]):
                path = Path(frame.filename).resolve()
                try:
                    relative = path.relative_to(root).as_posix()
                except (ValueError, OSError):
                    continue
                lower = relative.lower()
                if lower == "modules/audit_monitor.py" or "/pymysql/" in lower:
                    continue
                chosen = (relative, frame.name)
                break
        except Exception:
            pass

        result: Dict[str, Any] = {}
        if chosen:
            relative, function_name = chosen
            lower = relative.lower()
            result.update({"source_module": relative, "source_function": function_name})
            if lower.endswith("modules/db_backup.py"):
                result.update({"business_activity": "数据库远程同步", "interface": "数据库同步"})
            elif lower.endswith("modules/db_migration.py"):
                result.update({"business_activity": "用户库同步", "interface": "程序启动"})
            elif lower.endswith("modules/restore_project_remote.py"):
                result.update({"business_activity": "数据库恢复", "interface": "项目管理"})
            elif lower == "main.py" and "backup" in function_name.lower():
                result.update({"business_activity": "数据库备份", "interface": "数据库备份恢复"})
            elif lower == "main.py" and "restore" in function_name.lower():
                result.update({"business_activity": "数据库恢复", "interface": "数据库备份恢复"})
            else:
                for prefix, interface in _INTERFACE_BY_PATH.items():
                    if prefix in lower:
                        result["interface"] = interface
                        break
        return result

    def _visible_interface(self) -> str:
        activity = getattr(self._state, "activity", None)
        if activity and activity.get("interface"):
            return str(activity["interface"])
        with self._context_lock:
            return self._latest_interface

    def _set_latest_interface(self, interface: Any) -> None:
        value = str(interface or "").strip()
        if value:
            with self._context_lock:
                self._latest_interface = value

    def _hook_tab_widget(self, tab_widget: Any) -> None:
        if tab_widget is None or not isinstance(tab_widget, QtWidgets.QTabWidget):
            return
        key = id(tab_widget)
        if key in self._hooked_tab_widgets:
            return
        self._hooked_tab_widgets.add(key)
        monitor = self

        def on_changed(index: int) -> None:
            try:
                if index >= 0:
                    monitor._set_latest_interface(tab_widget.tabText(index))
            except Exception:
                pass

        tab_widget.currentChanged.connect(on_changed)
        on_changed(tab_widget.currentIndex())

    def activity_context(self, **context: Any) -> Any:
        previous = getattr(self._state, "activity", None)
        self._state.activity = {key: value for key, value in context.items() if value is not None}
        return previous

    def restore_activity_context(self, previous: Any) -> None:
        self._state.activity = previous

    def record(self, event_type: str, trace_id: Optional[str] = None, **payload: Any) -> None:
        if not self.enabled or not self._active:
            return
        try:
            now = _datetime.datetime.now(_datetime.timezone.utc)
            event = {
                "timestamp": now.isoformat(timespec="milliseconds"),
                "event_type": event_type,
                "category": payload.pop("category", None) or _event_category(event_type),
                "session_id": self.session_id,
                "trace_id": trace_id or self.current_trace(),
                "actor": self._actor,
                "thread": {"id": threading.get_ident(), "name": threading.current_thread().name},
            }
            event.update(self._business_context())
            event.update({key: self._jsonable(value) for key, value in payload.items() if value is not None})
            self._emit_or_buffer(event)
        except Exception:
            # Audit logging is never allowed to break a business operation.
            pass

    def _write_event(self, event: Dict[str, Any]) -> None:
        self.logger.info(json.dumps(event, ensure_ascii=False, separators=(",", ":")))

    def _database_merge_key(self, event: Dict[str, Any]) -> Any:
        if event.get("event_type") not in {"database.operation", "database.operation.batch"}:
            return None
        tables = tuple(str(table) for table in (event.get("tables") or ["未识别表"]))
        return (
            event.get("trace_id"),
            event.get("category"),
            event.get("interface"),
            event.get("business_activity"),
            event.get("database"),
            tables,
        )

    def _database_window_key(self, event: Dict[str, Any]) -> Any:
        """Identify one business action without tying it to a specific table."""
        if self._database_merge_key(event) is None:
            return None
        return (
            event.get("trace_id"),
            event.get("category"),
            event.get("interface"),
            event.get("business_activity"),
            event.get("actor"),
            event.get("project_id"),
            event.get("product_id"),
            event.get("current_product_id"),
        )

    def _emit_or_buffer(self, event: Dict[str, Any]) -> None:
        if self.detail_mode or self.coalesce_window_ms <= 0:
            with self._event_lock:
                self._flush_pending_database_event_locked()
                self._write_event(event)
            return

        merge_key = self._database_merge_key(event)
        with self._event_lock:
            if merge_key is None:
                self._flush_pending_database_event_locked()
                self._write_event(event)
                return

            window_key = self._database_window_key(event)
            if self._pending_database_events and self._pending_database_window_key != window_key:
                self._flush_pending_database_event_locked()
            self._pending_database_window_key = window_key

            pending = self._pending_database_events.get(merge_key)
            if pending is not None:
                self._pending_database_events[merge_key] = self._merge_database_events(pending, event)
            else:
                self._pending_database_events[merge_key] = event
            self._pending_database_updated_at = time.monotonic()
            self._schedule_database_flush_locked()

    def _merge_database_events(self, pending: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(pending)
        if merged.get("event_type") != "database.operation.batch":
            merged["event_type"] = "database.operation.batch"
            merged["operation_count"] = 1
            merged["operations"] = {str(pending.get("operation", "其他操作")): 1}
            merged["crud_counts"] = {str(pending.get("crud", "OTHER")): 1}
            merged["first_query_id"] = pending.get("query_id")
            merged.pop("query_id", None)
        merged["operation_count"] = int(merged.get("operation_count", 1)) + 1
        operation = str(current.get("operation", "其他操作"))
        crud = str(current.get("crud", "OTHER"))
        merged.setdefault("operations", {})[operation] = merged["operations"].get(operation, 0) + 1
        merged.setdefault("crud_counts", {})[crud] = merged["crud_counts"].get(crud, 0) + 1
        merged["operation"] = operation if len(merged["operations"]) == 1 else "混合操作"
        merged["crud"] = crud if len(merged["crud_counts"]) == 1 else "MIXED"
        merged["last_query_id"] = current.get("query_id")
        merged["last_timestamp"] = current.get("timestamp")
        for key in ("fields", "selected_fields", "written_fields", "condition_fields", "data_fields"):
            values = list(merged.get(key) or [])
            for value in current.get(key) or []:
                if value not in values:
                    values.append(value)
            if values:
                merged[key] = values[:100]
        for key in ("written_field_values", "condition_field_values", "read_field_values"):
            current_mapping = current.get(key) or {}
            if not current_mapping:
                continue
            merged_mapping = dict(merged.get(key) or {})
            for field, current_values in current_mapping.items():
                values = list(merged_mapping.get(field) or [])
                for value in current_values or []:
                    if value not in values:
                        if len(values) < self.max_field_values:
                            values.append(value)
                        else:
                            merged["field_values_truncated"] = True
                if values:
                    merged_mapping[field] = values
            if merged_mapping:
                merged[key] = merged_mapping
        if current.get("field_values_truncated"):
            merged["field_values_truncated"] = True
        for key in (
            "affected_or_returned_rows",
            "parameter_count",
            "field_value_rows",
            "read_value_rows",
            "duration_ms",
        ):
            left = merged.get(key)
            right = current.get(key)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                if key == "affected_or_returned_rows" and (left < 0 or right < 0):
                    merged[key] = None
                else:
                    merged[key] = round(left + right, 3) if key == "duration_ms" else left + right
        return merged

    def _schedule_database_flush_locked(self) -> None:
        # A single daemon worker flushes periodically.  Do not create a timer
        # or thread per SQL operation.
        return

    def _flush_pending_database_event_locked(self) -> None:
        pending_events = tuple(self._pending_database_events.values())
        self._pending_database_events.clear()
        self._pending_database_window_key = None
        self._pending_database_updated_at = 0.0
        for pending in pending_events:
            self._write_event(pending)

    def flush_pending_database_event(self) -> None:
        with self._event_lock:
            self._flush_pending_database_event_locked()

    def _start_database_flush_worker(self) -> None:
        if self.detail_mode or self.coalesce_window_ms <= 0 or self._database_flush_thread is not None:
            return
        interval = self.coalesce_window_ms / 1000.0
        monitor = self

        def worker() -> None:
            while not monitor._database_flush_stop.wait(interval):
                with monitor._event_lock:
                    if (
                        monitor._pending_database_events
                        and time.monotonic() - monitor._pending_database_updated_at >= interval
                    ):
                        monitor._flush_pending_database_event_locked()

        thread = threading.Thread(target=worker, name="AuditBatchFlush", daemon=True)
        self._database_flush_thread = thread
        thread.start()

    def _jsonable(self, value: Any, depth: int = 0, key_hint: str = "") -> Any:
        if _SENSITIVE_KEY_RE.search(str(key_hint)):
            return "***REDACTED***"
        if depth > 6:
            return "<max-depth>"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            if len(value) > self.max_text_chars:
                return value[: self.max_text_chars] + "...<truncated:%d>" % len(value)
            return value
        if isinstance(value, bytes):
            return {
                "type": "bytes",
                "length": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
            }
        if isinstance(value, (decimal.Decimal, _datetime.date, _datetime.time, _datetime.datetime)):
            return str(value)
        if isinstance(value, dict):
            return {
                str(key): self._jsonable(item, depth + 1, str(key))
                for key, item in list(value.items())[: self.max_result_rows or 100]
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            sequence = list(value)
            limit = self.max_result_rows if self.max_result_rows > 0 else 0
            selected = sequence[:limit]
            result = [self._jsonable(item, depth + 1) for item in selected]
            if len(sequence) > len(selected):
                result.append({"truncated_items": len(sequence) - len(selected), "total_items": len(sequence)})
            return result
        try:
            text = str(value)
        except Exception:
            text = "<unserializable:%s>" % type(value).__name__
        return self._jsonable(text, depth + 1)

    def _safe_field_values(
        self,
        sql: Any,
        args: Any,
        many: bool,
        field_context: Optional[Dict[str, list]] = None,
    ) -> Dict[str, Any]:
        extracted = _extract_parameter_field_values(
            sql,
            args,
            many=many,
            max_rows=self.max_field_values,
            field_context=field_context,
        )
        result: Dict[str, Any] = {}
        for mapping_key in ("written_field_values", "condition_field_values"):
            mapping = extracted.get(mapping_key) or {}
            safe_mapping = {}
            for field, values in mapping.items():
                safe_values = []
                for value in values[: self.max_field_values]:
                    safe_value = self._jsonable(value, key_hint=field)
                    if safe_value not in safe_values:
                        safe_values.append(safe_value)
                safe_mapping[field] = safe_values
            if safe_mapping:
                result[mapping_key] = safe_mapping
        for key in ("field_value_rows", "field_values_truncated"):
            if key in extracted:
                result[key] = extracted[key]
        return result

    def _safe_result_field_values(self, cursor: Any) -> Dict[str, Any]:
        """Sample values already buffered by a normal PyMySQL cursor."""
        try:
            rows = getattr(cursor, "_rows", None)
            description = getattr(cursor, "description", None) or []
            if rows is None or not isinstance(rows, (list, tuple)):
                return {}
            total_rows = len(rows)
            sample_rows = rows[: self.max_field_values]
            field_names = [str(item[0]) for item in description[:100] if item]
            values_by_field: Dict[str, list] = {}
            for row in sample_rows:
                if isinstance(row, dict):
                    items = row.items()
                elif isinstance(row, (list, tuple)):
                    items = zip(field_names, row)
                else:
                    continue
                for field_index, (field, value) in enumerate(items):
                    if field_index >= 100:
                        break
                    field_name = str(field)
                    values = values_by_field.setdefault(field_name, [])
                    safe_value = self._jsonable(value, key_hint=field_name)
                    if safe_value not in values and len(values) < self.max_field_values:
                        values.append(safe_value)
            result: Dict[str, Any] = {}
            if values_by_field:
                result["read_field_values"] = values_by_field
                result["read_value_rows"] = total_rows
                if total_rows > len(sample_rows):
                    result["field_values_truncated"] = True
            return result
        except Exception:
            return {}

    def _safe_params(self, args: Any, sql: Any) -> Any:
        if args is None:
            return None
        sql_text = _compact_sql(sql, self.max_text_chars)
        if _SENSITIVE_KEY_RE.search(sql_text):
            return "***REDACTED: sensitive SQL parameters***"
        return self._jsonable(args)

    def _database_context(self, cursor_or_connection: Any) -> Dict[str, Any]:
        connection = getattr(cursor_or_connection, "connection", None)
        if connection is None:
            connection = getattr(cursor_or_connection, "_connection", None)
        if connection is None:
            connection = cursor_or_connection
        result: Dict[str, Any] = {}
        for attr, key in (("host", "host"), ("port", "port"), ("user", "user"), ("db", "database")):
            value = getattr(connection, attr, None)
            if value not in (None, ""):
                result[key] = _decode(value)
        return result

    def _database_operation_context(
        self,
        cursor: Any,
        sql: Any,
        args: Any,
        many: bool = False,
        include_result_values: bool = True,
    ) -> Dict[str, Any]:
        keyword = _sql_keyword(sql)
        operation, crud = _SQL_OPERATIONS.get(keyword, ("其他操作", "OTHER"))
        activity = getattr(self._state, "activity", None)
        source = dict(activity) if activity else (self._source_context() if self.detail_mode else {})
        interface = self._visible_interface()
        business_activity = source.get("business_activity") or "界面数据库增删改查"
        category = "数据库操作"
        if "备份" in str(business_activity):
            category = "数据库备份"
        elif "恢复" in str(business_activity):
            category = "数据库恢复"
        elif "同步" in str(business_activity):
            category = "数据库同步"
        is_special_activity = category in {"数据库备份", "数据库恢复", "数据库同步"}

        connection = self._database_context(cursor)
        field_context = _extract_sql_fields(sql)
        payload: Dict[str, Any] = {
            "category": category,
            "business_activity": business_activity,
            "interface": (source.get("interface") if is_special_activity else interface) or interface,
            "operation": operation,
            "crud": crud,
            "database": connection.get("database"),
            "tables": _extract_tables(sql) or ["未识别表"],
            **field_context,
            "affected_or_returned_rows": getattr(cursor, "rowcount", None),
            "parameter_count": _parameter_count(args),
            **self._safe_field_values(sql, args, many, field_context),
        }
        if include_result_values and keyword in _READ_SQL:
            payload.update(self._safe_result_field_values(cursor))
        if self.detail_mode:
            payload.update(
                {
                    "source_module": source.get("source_module"),
                    "source_function": source.get("source_function"),
                    "connection": connection,
                    "sql": _compact_sql(sql, self.max_text_chars),
                    "parameters": self._safe_params(args, sql),
                }
            )
        else:
            field_source = args
            if isinstance(args, (list, tuple)) and args and isinstance(args[0], dict):
                field_source = args[0]
            if isinstance(field_source, dict):
                payload["data_fields"] = [
                    str(key) for key in field_source.keys() if not _SENSITIVE_KEY_RE.search(str(key))
                ][:50]
        return payload

    def _suppress_nested_database_events(self) -> bool:
        activity = getattr(self._state, "activity", None) or {}
        return bool(activity.get("suppress_database_operations")) and not self.detail_mode

    @staticmethod
    def _is_json_path(path: Any) -> bool:
        try:
            return str(os.fspath(path)).lower().endswith(".json")
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _absolute_path(path: Any) -> Path:
        return Path(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _json_shape(value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return {"json_type": "object", "top_level_fields": [str(key) for key in list(value.keys())[:100]]}
        if isinstance(value, list):
            result: Dict[str, Any] = {"json_type": "array", "item_count": len(value)}
            if value and isinstance(value[0], dict):
                result["item_fields"] = [str(key) for key in list(value[0].keys())[:100]]
            return result
        return {"json_type": type(value).__name__}

    def _display_file_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.application_root).as_posix()
        except (ValueError, OSError):
            return str(path)

    def _record_json_file_operation(
        self,
        *,
        path: Path,
        operation: str,
        mode: str,
        existed_before: bool,
        size_before: int,
        interface: str,
        source: Dict[str, Any],
        duration_ms: float,
        error: Any = None,
        json_shape: Any = None,
        captured_text: Any = None,
    ) -> None:
        if getattr(self._state, "inside_json_audit", False):
            return
        self._state.inside_json_audit = True
        try:
            resolved = path
            exists_after = resolved.exists()
            size_after = resolved.stat().st_size if exists_after else 0
            shape = json_shape
            if shape is None and captured_text and self.max_json_inspect_chars > 0:
                try:
                    shape = self._json_shape(json.loads(captured_text.lstrip("\ufeff")))
                except Exception:
                    shape = None
            if (
                shape is None
                and operation in {"替换写入", "重命名写入"}
                and exists_after
                and 0 < size_after <= self.max_json_inspect_chars
            ):
                try:
                    safe_open = self._originals.get("builtins.open", builtins.open)
                    with safe_open(resolved, "r", encoding="utf-8-sig") as json_file:
                        shape = self._json_shape(json.load(json_file))
                except Exception:
                    shape = None
            payload = {
                "category": "JSON文件",
                "business_activity": "JSON文件流转",
                "interface": interface,
                "operation": operation,
                "file": self._display_file_path(resolved),
                "file_name": resolved.name,
                "status": "失败" if error else "成功",
                "existed_before": existed_before,
                "size_before": size_before,
                "size_after": size_after,
                "duration_ms": duration_ms,
                **(shape or {}),
            }
            if self.detail_mode:
                payload.update(
                    {
                        "mode": mode,
                        "source_module": source.get("source_module"),
                        "source_function": source.get("source_function"),
                    }
                )
            if error:
                payload["error"] = error
            self.record("json.file", **payload)
        finally:
            self._state.inside_json_audit = False

    def _wrap_json_file(
        self,
        raw_file: Any,
        path: Any,
        mode: str,
        existed_before: Optional[bool] = None,
        size_before: Optional[int] = None,
    ) -> Any:
        if not self._is_json_path(path) or getattr(self._state, "inside_json_audit", False):
            return raw_file
        try:
            return _AuditedJsonFile(
                self,
                raw_file,
                self._absolute_path(path),
                str(mode),
                existed_before=existed_before,
                size_before=size_before,
            )
        except Exception:
            return raw_file

    def _patch_json_files(self) -> None:
        monitor = self
        original_open = builtins.open
        original_path_open = Path.open
        original_dump = json.dump
        original_load = json.load
        original_replace = os.replace
        original_rename = os.rename
        self._originals.update(
            {
                "builtins.open": original_open,
                "Path.open": original_path_open,
                "json.dump": original_dump,
                "json.load": original_load,
                "os.replace": original_replace,
                "os.rename": original_rename,
            }
        )

        def audited_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            is_json = monitor._is_json_path(file)
            path = monitor._absolute_path(file) if is_json else None
            existed_before = path.exists() if path is not None else None
            size_before = path.stat().st_size if path is not None and existed_before else 0
            raw_file = original_open(file, mode, *args, **kwargs)
            return monitor._wrap_json_file(raw_file, file, mode, existed_before, size_before)

        def audited_path_open(path_obj: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            is_json = monitor._is_json_path(path_obj)
            resolved = monitor._absolute_path(path_obj) if is_json else None
            existed_before = resolved.exists() if resolved is not None else None
            size_before = resolved.stat().st_size if resolved is not None and existed_before else 0
            raw_file = original_path_open(path_obj, mode, *args, **kwargs)
            return monitor._wrap_json_file(raw_file, path_obj, mode, existed_before, size_before)

        def audited_dump(obj: Any, fp: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(fp, _AuditedJsonFile):
                fp.set_json_shape(obj)
                fp._written = True
                return original_dump(obj, fp._raw_file, *args, **kwargs)
            return original_dump(obj, fp, *args, **kwargs)

        def audited_load(fp: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(fp, _AuditedJsonFile):
                fp._read = True
                result = original_load(fp._raw_file, *args, **kwargs)
                fp.set_json_shape(result)
                return result
            return original_load(fp, *args, **kwargs)

        def record_move(source: Any, destination: Any, operation: str, call: Any, *args: Any, **kwargs: Any) -> Any:
            destination_is_json = monitor._is_json_path(destination)
            existed_before = False
            size_before = 0
            destination_path = None
            if destination_is_json:
                destination_path = monitor._absolute_path(destination)
                existed_before = destination_path.exists()
                size_before = destination_path.stat().st_size if existed_before else 0
                source_context = monitor._source_context() if monitor.detail_mode else {}
                interface = monitor._visible_interface()
                started = time.perf_counter()
            try:
                result = call(source, destination, *args, **kwargs)
            except Exception as exc:
                if destination_is_json and destination_path is not None:
                    monitor._record_json_file_operation(
                        path=destination_path,
                        operation=operation,
                        mode="filesystem",
                        existed_before=existed_before,
                        size_before=size_before,
                        interface=interface,
                        source=source_context,
                        duration_ms=round((time.perf_counter() - started) * 1000, 3),
                        error=repr(exc),
                    )
                raise
            if destination_is_json and destination_path is not None:
                monitor._record_json_file_operation(
                    path=destination_path,
                    operation=operation,
                    mode="filesystem",
                    existed_before=existed_before,
                    size_before=size_before,
                    interface=interface,
                    source=source_context,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            return result

        builtins.open = audited_open
        Path.open = audited_path_open
        json.dump = audited_dump
        json.load = audited_load
        os.replace = lambda source, destination, *args, **kwargs: record_move(
            source, destination, "替换写入", original_replace, *args, **kwargs
        )
        os.rename = lambda source, destination, *args, **kwargs: record_move(
            source, destination, "重命名写入", original_rename, *args, **kwargs
        )

    def _widget_text(self, widget: Any) -> str:
        for getter_name in ("text", "currentText", "title", "windowTitle"):
            getter = getattr(widget, getter_name, None)
            if callable(getter):
                try:
                    value = getter()
                    if value:
                        return str(value)
                except Exception:
                    pass
        return ""

    def _widget_context(self, widget: Any) -> Dict[str, Any]:
        result = {
            "label": self._widget_text(widget),
            "interface": self._visible_interface(),
        }
        if self.detail_mode:
            result.update(
                {
                    "widget_class": type(widget).__name__,
                    "object_name": widget.objectName() if hasattr(widget, "objectName") else "",
                }
            )
        try:
            window = widget.window()
            if window is not None:
                result["window"] = window.windowTitle()
        except Exception:
            pass
        return result

    def _is_sensitive_widget(self, widget: Any) -> bool:
        clues = [
            getattr(widget, "objectName", lambda: "")(),
            getattr(widget, "placeholderText", lambda: "")(),
            self._widget_text(widget),
        ]
        if _SENSITIVE_KEY_RE.search(" ".join(str(item) for item in clues)):
            return True
        try:
            return isinstance(widget, QtWidgets.QLineEdit) and widget.echoMode() != QtWidgets.QLineEdit.Normal
        except Exception:
            return False

    def _input_value(self, widget: Any) -> Any:
        if self._is_sensitive_widget(widget):
            return "***REDACTED***"
        if isinstance(widget, QtWidgets.QLineEdit):
            return widget.text()
        if isinstance(widget, (QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit)):
            return widget.toPlainText()
        if isinstance(widget, QtWidgets.QComboBox):
            return {"index": widget.currentIndex(), "text": widget.currentText()}
        if isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QtWidgets.QDateTimeEdit):
            return widget.dateTime().toString(QtCore.Qt.ISODate)
        return None

    def eventFilter(self, watched: Any, event: Any) -> bool:
        if not self.enabled:
            return False
        try:
            event_type = event.type()
            if event_type == QtCore.QEvent.ChildAdded:
                try:
                    child = event.child()
                    if isinstance(child, QtWidgets.QAction):
                        self._hook_action(child)
                except Exception:
                    pass
            elif event_type == QtCore.QEvent.ActionAdded:
                try:
                    self._hook_action(event.action())
                except Exception:
                    pass
            elif event_type == QtCore.QEvent.Show and isinstance(watched, QtWidgets.QWidget):
                try:
                    if isinstance(watched, QtWidgets.QTabWidget):
                        self._hook_tab_widget(watched)
                    else:
                        self._hook_tab_widget(watched.findChild(QtWidgets.QTabWidget, "tabWidget"))
                    for action in watched.actions():
                        self._hook_action(action)
                    if isinstance(watched, QtWidgets.QMenu):
                        for action in watched.actions():
                            self._hook_action(action)
                except Exception:
                    pass
            if (
                event_type == QtCore.QEvent.Show
                and isinstance(watched, QtWidgets.QDialog)
                and not isinstance(watched, QtWidgets.QMessageBox)
            ):
                self._record_dialog_shown(watched)
            elif (
                event_type in (QtCore.QEvent.Hide, QtCore.QEvent.Close)
                and isinstance(watched, QtWidgets.QDialog)
                and not isinstance(watched, QtWidgets.QMessageBox)
            ):
                self._record_dialog_closed(watched)
            is_button_activation = isinstance(watched, QtWidgets.QAbstractButton) and (
                event_type == QtCore.QEvent.MouseButtonRelease
                or (
                    event_type == QtCore.QEvent.KeyPress
                    and event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space)
                )
            )
            if is_button_activation:
                trace_id = self.new_trace("ui")
                self.record("ui.action", trace_id=trace_id, action="activate", **self._widget_context(watched))
            elif event_type == QtCore.QEvent.MouseButtonRelease and isinstance(
                watched, (QtWidgets.QAbstractItemView, QtWidgets.QTabBar)
            ):
                trace_id = self.new_trace("ui")
                details = self._widget_context(watched)
                try:
                    if isinstance(watched, QtWidgets.QAbstractItemView):
                        index = watched.indexAt(event.pos())
                        if index.isValid():
                            details.update({"row": index.row(), "column": index.column()})
                    elif isinstance(watched, QtWidgets.QTabBar):
                        index = watched.tabAt(event.pos())
                        details.update({"tab_index": index, "tab_text": watched.tabText(index) if index >= 0 else ""})
                        if index >= 0:
                            self._set_latest_interface(watched.tabText(index))
                except Exception:
                    pass
                self.record("ui.action", trace_id=trace_id, action="select", **details)
            elif (
                self.capture_input_values
                and event_type == QtCore.QEvent.FocusOut
                and isinstance(
                    watched,
                    (
                        QtWidgets.QLineEdit,
                        QtWidgets.QTextEdit,
                        QtWidgets.QPlainTextEdit,
                        QtWidgets.QComboBox,
                        QtWidgets.QSpinBox,
                        QtWidgets.QDoubleSpinBox,
                        QtWidgets.QDateTimeEdit,
                    ),
                )
            ):
                self.record(
                    "ui.value",
                    action="focus_out",
                    value=self._input_value(watched),
                    **self._widget_context(watched),
                )
        except Exception:
            pass
        return False

    def _hook_action(self, action: Any) -> None:
        if action is None or not isinstance(action, QtWidgets.QAction):
            return
        action_key = id(action)
        if action_key in self._hooked_actions:
            return
        self._hooked_actions.add(action_key)
        monitor = self

        def on_triggered(checked: bool = False) -> None:
            try:
                trace_id = monitor.new_trace("ui")
                parent = action.parent()
                window_title = ""
                if isinstance(parent, QtWidgets.QWidget):
                    window_title = parent.window().windowTitle()
                monitor.record(
                    "ui.action",
                    trace_id=trace_id,
                    action="trigger",
                    label=action.text(),
                    interface=monitor._visible_interface(),
                    widget_class=type(action).__name__ if monitor.detail_mode else None,
                    object_name=action.objectName() if monitor.detail_mode else None,
                    shortcut=action.shortcut().toString() if monitor.detail_mode else None,
                    checked=bool(checked) if action.isCheckable() else None,
                    window=window_title,
                )
            except Exception:
                pass

        action.triggered.connect(on_triggered)

    def _record_dialog_shown(self, dialog: QtWidgets.QDialog) -> None:
        if getattr(dialog, "_audit_dialog_open", False):
            return
        dialog_id = uuid.uuid4().hex
        dialog._audit_dialog_id = dialog_id
        dialog._audit_dialog_open = True
        dialog._audit_dialog_started = time.perf_counter()
        labels = []
        try:
            for label in dialog.findChildren(QtWidgets.QLabel):
                text = label.text().strip()
                if text and text not in labels:
                    labels.append(text)
        except Exception:
            pass
        dialog._audit_dialog_labels = labels
        dialog._audit_dialog_interface = self._visible_interface()
        if self.detail_mode:
            self.record(
                "ui.dialog.shown",
                dialog_id=dialog_id,
                dialog_class=type(dialog).__name__,
                object_name=dialog.objectName(),
                title=dialog.windowTitle(),
                visible_text=labels,
                interface=dialog._audit_dialog_interface,
                modal=dialog.isModal(),
            )

    def _record_dialog_closed(self, dialog: QtWidgets.QDialog) -> None:
        if not getattr(dialog, "_audit_dialog_open", False):
            return
        dialog._audit_dialog_open = False
        started = getattr(dialog, "_audit_dialog_started", None)
        duration_ms = None
        if started is not None:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
        try:
            result = int(dialog.result())
        except Exception:
            result = None
        self.record(
            "ui.dialog.closed" if self.detail_mode else "ui.dialog",
            dialog_id=getattr(dialog, "_audit_dialog_id", None),
            dialog_class=type(dialog).__name__ if self.detail_mode else None,
            object_name=dialog.objectName() if self.detail_mode else None,
            title=dialog.windowTitle(),
            visible_text=getattr(dialog, "_audit_dialog_labels", None),
            interface=getattr(dialog, "_audit_dialog_interface", None),
            result=result,
            duration_ms=duration_ms,
        )

    def _patch_message_boxes(self) -> None:
        original_exec = QtWidgets.QMessageBox.exec_
        self._originals["messagebox.exec_"] = original_exec
        monitor = self

        def audited_exec(box: QtWidgets.QMessageBox) -> int:
            # Static helpers patched below may create a QMessageBox and call
            # exec_ internally.  The outer helper owns that audit event so the
            # nested call must not create a duplicate pair.
            if getattr(monitor._state, "inside_static_prompt", False):
                return original_exec(box)
            trace_id = monitor.current_trace()
            prompt_id = uuid.uuid4().hex
            details = {
                "prompt_id": prompt_id,
                "title": box.windowTitle(),
                "text": box.text(),
                "informative_text": box.informativeText(),
                "detailed_text": box.detailedText(),
                "icon": int(box.icon()),
                "standard_buttons": int(box.standardButtons()),
                "interface": monitor._visible_interface(),
            }
            if monitor.detail_mode:
                monitor.record("ui.prompt.shown", trace_id=trace_id, **details)
            started = time.perf_counter()
            try:
                result = original_exec(box)
            except Exception as exc:
                monitor.record(
                    "ui.prompt.failed",
                    trace_id=trace_id,
                    prompt_id=prompt_id,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    error=repr(exc),
                )
                raise
            clicked_text = ""
            try:
                clicked = box.clickedButton()
                if clicked is not None:
                    clicked_text = clicked.text()
            except Exception:
                pass
            monitor.record(
                "ui.prompt.answered" if monitor.detail_mode else "ui.prompt",
                trace_id=trace_id,
                **details,
                result=int(result),
                clicked_text=clicked_text,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            return result

        QtWidgets.QMessageBox.exec_ = audited_exec

        static_icons = {
            "information": QtWidgets.QMessageBox.Information,
            "warning": QtWidgets.QMessageBox.Warning,
            "critical": QtWidgets.QMessageBox.Critical,
            "question": QtWidgets.QMessageBox.Question,
        }
        for method_name, icon in static_icons.items():
            original_method = getattr(QtWidgets.QMessageBox, method_name)
            self._originals["messagebox.%s" % method_name] = original_method

            def make_static_wrapper(name: str, prompt_icon: Any, original: Any) -> Any:
                def audited_static(*args: Any, **kwargs: Any) -> Any:
                    trace_id = monitor.current_trace()
                    prompt_id = uuid.uuid4().hex
                    title = args[1] if len(args) > 1 else kwargs.get("title", "")
                    text = args[2] if len(args) > 2 else kwargs.get("text", "")
                    buttons = args[3] if len(args) > 3 else kwargs.get("buttons")
                    details = {
                        "prompt_id": prompt_id,
                        "title": title,
                        "text": text,
                        "icon": int(prompt_icon),
                        "standard_buttons": int(buttons) if buttons is not None else None,
                        "api": name,
                        "interface": monitor._visible_interface(),
                    }
                    if monitor.detail_mode:
                        monitor.record("ui.prompt.shown", trace_id=trace_id, **details)
                    started = time.perf_counter()
                    monitor._state.inside_static_prompt = True
                    try:
                        result = original(*args, **kwargs)
                    except Exception as exc:
                        monitor.record(
                            "ui.prompt.failed",
                            trace_id=trace_id,
                            prompt_id=prompt_id,
                            api=name,
                            duration_ms=round((time.perf_counter() - started) * 1000, 3),
                            error=repr(exc),
                        )
                        raise
                    finally:
                        monitor._state.inside_static_prompt = False
                    monitor.record(
                        "ui.prompt.answered" if monitor.detail_mode else "ui.prompt",
                        trace_id=trace_id,
                        **details,
                        result=int(result),
                        duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    )
                    return result

                return audited_static

            setattr(
                QtWidgets.QMessageBox,
                method_name,
                make_static_wrapper(method_name, icon, original_method),
            )

    def _patch_pymysql(self) -> None:
        monitor = self
        cursor_class = pymysql.cursors.Cursor
        connection_class = pymysql.connections.Connection

        original_connect = pymysql.connect
        original_execute = cursor_class.execute
        original_executemany = cursor_class.executemany
        original_fetchone = cursor_class.fetchone
        original_fetchmany = cursor_class.fetchmany
        original_fetchall = cursor_class.fetchall
        original_commit = connection_class.commit
        original_rollback = connection_class.rollback
        original_close = connection_class.close
        self._originals.update(
            {
                "pymysql.connect": original_connect,
                "cursor.execute": original_execute,
                "cursor.executemany": original_executemany,
                "cursor.fetchone": original_fetchone,
                "cursor.fetchmany": original_fetchmany,
                "cursor.fetchall": original_fetchall,
                "connection.commit": original_commit,
                "connection.rollback": original_rollback,
                "connection.close": original_close,
            }
        )

        def audited_connect(*args: Any, **kwargs: Any) -> Any:
            started = time.perf_counter()
            safe_config = {
                key: value
                for key, value in kwargs.items()
                if key.lower() not in {"password", "passwd", "ssl_key", "ssl_cert"}
            }
            try:
                connection = original_connect(*args, **kwargs)
            except Exception as exc:
                monitor.record(
                    "db.connection.failed",
                    category="数据库连接异常",
                    interface=monitor._visible_interface(),
                    config=safe_config,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    error=repr(exc),
                )
                raise
            try:
                connection._audit_pending_query_ids = []
            except Exception:
                pass
            if monitor.detail_mode:
                monitor.record(
                    "db.connection.opened",
                    connection=monitor._database_context(connection),
                    interface=monitor._visible_interface(),
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            return connection

        def _run_sql(cursor: Any, sql: Any, args: Any, many: bool, call_original: Any) -> Any:
            if getattr(monitor._state, "inside_sql", False):
                return call_original(cursor, sql, args)
            monitor._state.inside_sql = True
            query_id = uuid.uuid4().hex
            trace_id = monitor.current_trace()
            kind = _sql_kind(sql)
            started = time.perf_counter()
            try:
                result = call_original(cursor, sql, args)
            except Exception as exc:
                operation_context = monitor._database_operation_context(
                    cursor, sql, args, many=many, include_result_values=False
                )
                monitor.record(
                    "database.operation.failed",
                    trace_id=trace_id,
                    query_id=query_id,
                    **operation_context,
                    batch=bool(many) if monitor.detail_mode else None,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    error=repr(exc),
                )
                raise
            finally:
                monitor._state.inside_sql = False
            try:
                cursor._audit_query_id = query_id
                cursor._audit_fetch_events = 0
                cursor._audit_fetch_suppressed = False
                connection = getattr(cursor, "connection", None)
                if kind in {"write", "schema"} and connection is not None:
                    is_autocommit = False
                    try:
                        is_autocommit = bool(connection.get_autocommit())
                    except Exception:
                        pass
                    if is_autocommit:
                        if monitor.detail_mode:
                            monitor.record(
                                "db.transaction.autocommitted",
                                trace_id=trace_id,
                                database=monitor._database_context(connection),
                                query_ids=[query_id],
                            )
                    else:
                        pending = getattr(connection, "_audit_pending_query_ids", None)
                        if pending is None:
                            pending = []
                            connection._audit_pending_query_ids = pending
                        pending.append(query_id)
            except Exception:
                pass
            operation_context = monitor._database_operation_context(cursor, sql, args, many=many)
            if not monitor._suppress_nested_database_events() and (kind != "other" or monitor.detail_mode):
                monitor.record(
                    "database.operation",
                    trace_id=trace_id,
                    query_id=query_id,
                    **operation_context,
                    batch=bool(many) if monitor.detail_mode else None,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    lastrowid=getattr(cursor, "lastrowid", None) if monitor.detail_mode else None,
                )
            return result

        def audited_execute(cursor: Any, query: Any, args: Any = None) -> Any:
            return _run_sql(cursor, query, args, False, original_execute)

        def audited_executemany(cursor: Any, query: Any, args: Any) -> Any:
            return _run_sql(cursor, query, args, True, original_executemany)

        def _log_fetch(cursor: Any, method: str, result: Any, started: float) -> None:
            if not monitor.capture_db_rows:
                return
            try:
                count = int(getattr(cursor, "_audit_fetch_events", 0))
                if count >= monitor.max_fetch_events:
                    if not getattr(cursor, "_audit_fetch_suppressed", False):
                        cursor._audit_fetch_suppressed = True
                        monitor.record(
                            "db.read.result_suppressed",
                            query_id=getattr(cursor, "_audit_query_id", None),
                            reason="fetch event limit reached",
                            max_fetch_events=monitor.max_fetch_events,
                        )
                    return
                cursor._audit_fetch_events = count + 1
            except Exception:
                pass
            total_rows = 0
            if result is not None:
                total_rows = len(result) if isinstance(result, (list, tuple)) and method != "fetchone" else 1
            monitor.record(
                "db.read.result",
                category="数据库读取明细",
                query_id=getattr(cursor, "_audit_query_id", None),
                fetch_method=method,
                database=monitor._database_context(cursor),
                returned_rows=total_rows,
                data=result,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )

        def audited_fetchone(cursor: Any) -> Any:
            started = time.perf_counter()
            result = original_fetchone(cursor)
            _log_fetch(cursor, "fetchone", result, started)
            return result

        def audited_fetchmany(cursor: Any, size: Any = None) -> Any:
            started = time.perf_counter()
            result = original_fetchmany(cursor, size)
            _log_fetch(cursor, "fetchmany", result, started)
            return result

        def audited_fetchall(cursor: Any) -> Any:
            started = time.perf_counter()
            result = original_fetchall(cursor)
            _log_fetch(cursor, "fetchall", result, started)
            return result

        def audited_commit(connection: Any) -> Any:
            pending = list(getattr(connection, "_audit_pending_query_ids", []) or [])
            started = time.perf_counter()
            try:
                result = original_commit(connection)
            except Exception as exc:
                monitor.record(
                    "db.transaction.commit_failed",
                    database=monitor._database_context(connection),
                    query_ids=pending,
                    error=repr(exc),
                )
                raise
            try:
                connection._audit_pending_query_ids = []
            except Exception:
                pass
            if (pending or monitor.detail_mode) and not monitor._suppress_nested_database_events():
                monitor.record(
                    "db.transaction.committed",
                    category="数据库事务",
                    interface=monitor._visible_interface(),
                    database=monitor._database_context(connection).get("database"),
                    write_count=len(pending),
                    query_ids=pending if monitor.detail_mode else None,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            return result

        def audited_rollback(connection: Any) -> Any:
            pending = list(getattr(connection, "_audit_pending_query_ids", []) or [])
            started = time.perf_counter()
            try:
                result = original_rollback(connection)
            except Exception as exc:
                monitor.record(
                    "db.transaction.rollback_failed",
                    database=monitor._database_context(connection),
                    query_ids=pending,
                    error=repr(exc),
                )
                raise
            try:
                connection._audit_pending_query_ids = []
            except Exception:
                pass
            if (pending or monitor.detail_mode) and not monitor._suppress_nested_database_events():
                monitor.record(
                    "db.transaction.rolled_back",
                    category="数据库事务",
                    interface=monitor._visible_interface(),
                    database=monitor._database_context(connection).get("database"),
                    write_count=len(pending),
                    query_ids=pending if monitor.detail_mode else None,
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            return result

        def audited_close(connection: Any) -> Any:
            context = monitor._database_context(connection)
            pending = list(getattr(connection, "_audit_pending_query_ids", []) or [])
            try:
                return original_close(connection)
            finally:
                if monitor.detail_mode or pending:
                    monitor.record(
                        "db.connection.closed",
                        database=context if monitor.detail_mode else context.get("database"),
                        uncommitted_write_count=len(pending),
                        uncommitted_query_ids=pending if monitor.detail_mode else None,
                    )

        pymysql.connect = audited_connect
        cursor_class.execute = audited_execute
        cursor_class.executemany = audited_executemany
        cursor_class.fetchone = audited_fetchone
        cursor_class.fetchmany = audited_fetchmany
        cursor_class.fetchall = audited_fetchall
        connection_class.commit = audited_commit
        connection_class.rollback = audited_rollback
        connection_class.close = audited_close

    def _install_exception_hooks(self) -> None:
        original_sys_hook = sys.excepthook
        self._originals["sys.excepthook"] = original_sys_hook
        monitor = self

        def audited_sys_hook(exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
            monitor.record(
                "application.unhandled_exception",
                exception="".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            )
            original_sys_hook(exc_type, exc_value, exc_tb)

        sys.excepthook = audited_sys_hook
        if hasattr(threading, "excepthook"):
            original_thread_hook = threading.excepthook
            self._originals["threading.excepthook"] = original_thread_hook

            def audited_thread_hook(args: Any) -> None:
                monitor.record(
                    "application.thread_exception",
                    thread_name=getattr(args.thread, "name", None),
                    exception="".join(
                        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
                    ),
                )
                original_thread_hook(args)

            threading.excepthook = audited_thread_hook

    def _install_logging_bridge(self) -> None:
        self._root_bridge = _AuditLogBridge(self)
        logging.getLogger().addHandler(self._root_bridge)

    def shutdown(self) -> None:
        if not self._active:
            return
        try:
            self.record(
                "session.end",
                duration_seconds=round(
                    (_datetime.datetime.now(_datetime.timezone.utc) - self.started_at).total_seconds(), 3
                ),
            )
        finally:
            self._database_flush_stop.set()
            if self._database_flush_thread is not None and self._database_flush_thread.is_alive():
                self._database_flush_thread.join(timeout=0.2)
            self.flush_pending_database_event()
            self._active = False
            if self._root_bridge is not None:
                try:
                    logging.getLogger().removeHandler(self._root_bridge)
                except Exception:
                    pass
            try:
                self._audit_log_listener.stop()
            except Exception:
                pass
            try:
                self._audit_file_handler.flush()
                self._audit_file_handler.close()
            except Exception:
                pass
            for handler in list(self.logger.handlers):
                try:
                    handler.flush()
                    handler.close()
                except Exception:
                    pass
                self.logger.removeHandler(handler)


def install_global_monitor(
    app: Optional[QtWidgets.QApplication] = None, app_version: str = ""
) -> GlobalAuditMonitor:
    """Install and return the process-wide monitor (idempotent)."""

    global _MONITOR
    with _INSTALL_LOCK:
        if _MONITOR is not None:
            return _MONITOR
        application = app or QtWidgets.QApplication.instance()
        if application is None:
            raise RuntimeError("QApplication must exist before installing the audit monitor")
        _MONITOR = GlobalAuditMonitor(application, app_version=app_version).install()
        return _MONITOR


def get_global_monitor() -> Optional[GlobalAuditMonitor]:
    return _MONITOR


def set_audit_user(username: Any) -> None:
    monitor = get_global_monitor()
    if monitor is not None:
        monitor.set_user(username)


def audit_event(event_type: str, **payload: Any) -> None:
    """Optional business-layer hook for important semantic operations."""

    monitor = get_global_monitor()
    if monitor is not None:
        monitor.record(event_type, **payload)


@contextlib.contextmanager
def audit_context(**context: Any) -> Any:
    """Temporarily classify all nested database operations as one activity."""

    monitor = get_global_monitor()
    if monitor is None:
        yield
        return
    previous = monitor.activity_context(**context)
    try:
        yield
    finally:
        monitor.restore_activity_context(previous)
