"""Pure helpers for Navicat-style cell editing and clipboard operations."""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, List, Sequence


def column_family(data_type: str) -> str:
    value = (data_type or "").lower().strip()
    if any(x in value for x in ("blob", "binary", "bytea", "image", "varbinary")):
        return "binary"
    if "json" in value:
        return "json"
    if re.search(r"\b(bool|boolean|bit)\b", value):
        return "boolean"
    if any(x in value for x in ("date", "time", "timestamp")):
        return "datetime"
    if any(x in value for x in ("int", "real", "float", "double", "decimal", "numeric", "number")):
        return "number"
    if value.startswith("enum"):
        return "enum"
    if value.startswith("set"):
        return "set"
    return "text"


def enum_values(data_type: str) -> List[str]:
    m = re.match(r"(?is)^\s*(?:enum|set)\s*\((.*)\)\s*$", data_type or "")
    if not m:
        return []
    text = m.group(1)
    values = []
    i = 0
    while i < len(text):
        while i < len(text) and (text[i].isspace() or text[i] == ','):
            i += 1
        if i >= len(text):
            break
        if text[i] not in "'\"":
            j = text.find(',', i)
            if j < 0: j = len(text)
            values.append(text[i:j].strip()); i = j + 1; continue
        quote = text[i]; i += 1; buf = []
        while i < len(text):
            ch = text[i]
            if ch == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    buf.append(quote); i += 2; continue
                i += 1; break
            if ch == '\\' and i + 1 < len(text):
                buf.append(text[i + 1]); i += 2; continue
            buf.append(ch); i += 1
        values.append(''.join(buf))
    return values


def clipboard_matrix(text: str) -> List[List[str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return [[""]]
    return [line.split("\t") for line in text.split("\n")]


def sql_literal(value: Any, kind: str = "sqlite") -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if kind in {"postgres", "postgresql"} else ("1" if value else "0")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        h = bytes(value).hex().upper()
        if kind == "mysql": return "0x" + h
        if kind in {"postgres", "postgresql"}: return f"decode('{h}', 'hex')"
        return f"X'{h}'"
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        value = value.isoformat(sep=" ") if isinstance(value, dt.datetime) else value.isoformat()
    return "'" + str(value).replace("'", "''") + "'"


def json_pretty(value: Any) -> str:
    obj = json.loads(value) if isinstance(value, str) else value
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def json_minify(value: Any) -> str:
    obj = json.loads(value) if isinstance(value, str) else value
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def text_transform(value: Any, operation: str, argument: str = "") -> Any:
    if value is None:
        return None
    text = str(value)
    if operation == "trim": return text.strip()
    if operation == "ltrim": return text.lstrip()
    if operation == "rtrim": return text.rstrip()
    if operation == "upper": return text.upper()
    if operation == "lower": return text.lower()
    if operation == "prefix": return argument + text
    if operation == "suffix": return text + argument
    if operation == "replace":
        old, sep, new = argument.partition("\0")
        return text.replace(old, new) if sep else text
    if operation == "regex_replace":
        pattern, sep, replacement = argument.partition("\0")
        return re.sub(pattern, replacement, text) if sep else text
    if operation == "remove_invisible":
        return ''.join(ch for ch in text if ch.isprintable() or ch in "\t\n\r")
    return value


def coerce_text(text: str, family: str) -> Any:
    if family == "number":
        stripped = text.strip()
        if re.fullmatch(r"[-+]?\d+", stripped): return int(stripped)
        try: return float(stripped)
        except ValueError: return text
    if family == "boolean":
        lowered = text.strip().lower()
        if lowered in {"1", "true", "yes", "y", "是"}: return True
        if lowered in {"0", "false", "no", "n", "否"}: return False
    return text
