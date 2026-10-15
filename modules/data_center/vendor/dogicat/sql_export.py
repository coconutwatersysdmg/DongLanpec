from __future__ import annotations

import datetime as dt
import math
import numbers
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, TextIO, Tuple

from .core import ColumnInfo, DatabaseAdapter, DatabaseError, TableObject


EXPORT_STYLES = {"navicat", "native", "generic"}


@dataclass
class SQLExportProgress:
    percent: float = 0.0
    completed_steps: int = 0
    total_steps: int = 0
    rows: int = 0
    current: str = ""


@dataclass
class SQLExportReport:
    path: Path
    style: str
    structure_only: bool
    object_count: int
    row_count: int
    bytes_written: int
    elapsed_seconds: float
    cancelled: bool = False


class SQLFileExporter:
    """Stream a database or selected objects into a portable SQL script."""

    def __init__(self, adapter: DatabaseAdapter):
        self.adapter = adapter
        self.kind = self._normalise_kind(adapter.profile.kind)

    @staticmethod
    def _normalise_kind(kind: str) -> str:
        lowered = kind.lower()
        return "postgresql" if lowered in {"postgres", "postgresql"} else lowered

    @property
    def source_name(self) -> str:
        return {
            "mysql": "MySQL",
            "postgresql": "PostgreSQL",
            "sqlite": "SQLite",
        }.get(self.kind, self.kind or "SQL")

    def export_file(
        self,
        path: Path,
        objects: Sequence[TableObject],
        *,
        style: str = "navicat",
        structure_only: bool = False,
        include_drop: bool = True,
        encoding: str = "utf-8",
        cancel_event: Optional[threading.Event] = None,
        progress: Optional[Callable[[SQLExportProgress], None]] = None,
    ) -> SQLExportReport:
        if style not in EXPORT_STYLES:
            raise ValueError(f"不支持的 SQL 导出格式：{style}")
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.dogicat-part-{uuid.uuid4().hex}"
        )
        started = time.perf_counter()
        rows_written = 0
        cancelled = False
        ordered = self._order_objects(objects)
        tables = [item for item in ordered if item.kind == "table"]
        views = [item for item in ordered if item.kind != "table"]
        total_steps = (
            len(views)
            + len(tables) * (2 if structure_only else 3)
        )
        completed_steps = 0

        def notify(current: str, *, rows: Optional[int] = None) -> None:
            if not progress:
                return
            progress(
                SQLExportProgress(
                    percent=(
                        completed_steps / max(total_steps, 1) * 100.0
                    ),
                    completed_steps=completed_steps,
                    total_steps=total_steps,
                    rows=rows_written if rows is None else rows,
                    current=current,
                )
            )

        try:
            with temporary.open("w", encoding=encoding, newline="\n") as stream:
                self._write_header(stream, style)
                if self.kind == "postgresql":
                    for schema in sorted(
                        {item.schema or "public" for item in ordered}
                    ):
                        stream.write(
                            f"CREATE SCHEMA IF NOT EXISTS "
                            f"{self.adapter.quote_identifier(schema)};\n"
                        )
                    stream.write("\n")

                if include_drop:
                    for obj in reversed(views):
                        self._write_drop(stream, obj)
                    for obj in reversed(tables):
                        self._write_drop(stream, obj)
                    stream.write("\n")

                for obj in tables:
                    if self._cancelled(cancel_event):
                        cancelled = True
                        break
                    notify(f"正在导出结构：{obj.display_name}")
                    self._write_object_heading(stream, obj, style)
                    self._write_statement(stream, self.adapter.get_ddl(obj.name, obj.schema))
                    completed_steps += 1
                    notify(f"已导出结构：{obj.display_name}")

                if not cancelled and not structure_only:
                    for obj in tables:
                        if self._cancelled(cancel_event):
                            cancelled = True
                            break
                        notify(f"正在导出数据：{obj.display_name}")
                        count = self._write_table_data(
                            stream, obj, cancel_event, notify
                        )
                        rows_written += count
                        if self._cancelled(cancel_event):
                            cancelled = True
                            break
                        completed_steps += 1
                        notify(f"已导出 {count} 行：{obj.display_name}")

                if not cancelled:
                    for obj in tables:
                        if self._cancelled(cancel_event):
                            cancelled = True
                            break
                        notify(f"正在导出索引和触发器：{obj.display_name}")
                        for ddl in self.adapter.get_additional_ddl(
                            obj.name, obj.schema
                        ):
                            self._write_statement(stream, ddl)
                        completed_steps += 1
                        notify(f"已导出索引和触发器：{obj.display_name}")

                if not cancelled:
                    for obj in views:
                        if self._cancelled(cancel_event):
                            cancelled = True
                            break
                        notify(f"正在导出视图：{obj.display_name}")
                        self._write_object_heading(stream, obj, style)
                        self._write_statement(
                            stream, self.adapter.get_ddl(obj.name, obj.schema)
                        )
                        completed_steps += 1
                        notify(f"已导出视图：{obj.display_name}")

                if not cancelled:
                    self._write_footer(stream, style)

            if cancelled:
                temporary.unlink(missing_ok=True)
            else:
                temporary.replace(destination)
                if progress:
                    progress(
                        SQLExportProgress(
                            percent=100.0,
                            completed_steps=total_steps,
                            total_steps=total_steps,
                            rows=rows_written,
                            current="导出完成",
                        )
                    )
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        elapsed = time.perf_counter() - started
        return SQLExportReport(
            path=destination,
            style=style,
            structure_only=structure_only,
            object_count=len(objects),
            row_count=rows_written,
            bytes_written=(
                destination.stat().st_size
                if not cancelled and destination.exists() else 0
            ),
            elapsed_seconds=elapsed,
            cancelled=cancelled,
        )

    @staticmethod
    def _cancelled(cancel_event: Optional[threading.Event]) -> bool:
        return bool(cancel_event and cancel_event.is_set())

    def _order_objects(
        self, objects: Sequence[TableObject]
    ) -> List[TableObject]:
        tables = [item for item in objects if item.kind == "table"]
        views = [item for item in objects if item.kind != "table"]
        by_key = {
            (item.schema or "", item.name): item for item in tables
        }
        dependencies: Dict[Tuple[str, str], set[Tuple[str, str]]] = {
            key: set() for key in by_key
        }
        for key, item in by_key.items():
            for foreign_key in self.adapter.get_foreign_keys(
                item.name, item.schema
            ):
                parent_key = (
                    foreign_key.referenced_schema or item.schema or "",
                    foreign_key.referenced_table,
                )
                if parent_key in by_key and parent_key != key:
                    dependencies[key].add(parent_key)
        ordered: List[TableObject] = []
        remaining = dict(dependencies)
        while remaining:
            ready = sorted(
                (key for key, parents in remaining.items() if not parents),
                key=lambda value: (value[0].lower(), value[1].lower()),
            )
            if not ready:
                ordered.extend(
                    by_key[key] for key in sorted(
                        remaining,
                        key=lambda value: (
                            value[0].lower(), value[1].lower()
                        ),
                    )
                )
                break
            for key in ready:
                ordered.append(by_key[key])
                remaining.pop(key)
            for parents in remaining.values():
                parents.difference_update(ready)
        return ordered + sorted(
            views, key=lambda item: (
                item.schema.lower(), item.name.lower()
            )
        )

    def _write_header(self, stream: TextIO, style: str) -> None:
        database = self.adapter.profile.database or self.adapter.profile.name
        database = str(database).replace("\r", " ").replace("\n", " ")
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if style == "navicat":
            stream.write(
                "/*\n"
                " DogiCat SQL Export (Navicat-compatible layout)\n\n"
                f" Source Server Type    : {self.source_name}\n"
                f" Source Schema         : {database}\n"
                f" File Encoding         : 65001\n"
                f" Export Time           : {timestamp}\n"
                "*/\n\n"
            )
        elif style == "native":
            marker = {
                "mysql": "MySQL dump compatible SQL",
                "postgresql": "PostgreSQL database dump compatible SQL",
                "sqlite": "SQLite .dump compatible SQL",
            }.get(self.kind, f"{self.source_name} native-tool compatible SQL")
            stream.write(f"-- {marker}\n-- Generated by DogiCat at {timestamp}\n\n")
        else:
            stream.write(
                f"-- Generic SQL export generated by DogiCat\n"
                f"-- Source dialect: {self.source_name}\n"
                f"-- Export time: {timestamp}\n\n"
            )

        if self.kind == "mysql":
            stream.write(
                "SET NAMES utf8mb4;\n"
                "SET FOREIGN_KEY_CHECKS = 0;\n\n"
            )
        elif self.kind == "postgresql":
            stream.write(
                "SET statement_timeout = 0;\n"
                "SET client_encoding = 'UTF8';\n"
                "SET standard_conforming_strings = on;\n"
                "BEGIN;\n\n"
            )
        elif self.kind == "sqlite":
            stream.write(
                "PRAGMA foreign_keys = OFF;\n"
                "BEGIN TRANSACTION;\n\n"
            )

    def _write_footer(self, stream: TextIO, style: str) -> None:
        if self.kind == "mysql":
            stream.write("\nSET FOREIGN_KEY_CHECKS = 1;\n")
        elif self.kind == "postgresql":
            stream.write("\nCOMMIT;\n")
        elif self.kind == "sqlite":
            stream.write("\nCOMMIT;\nPRAGMA foreign_keys = ON;\n")
        if style == "navicat":
            stream.write("\n-- Export finished successfully.\n")

    def _write_object_heading(
        self, stream: TextIO, obj: TableObject, style: str
    ) -> None:
        if style == "navicat":
            stream.write(
                "\n-- ----------------------------\n"
                f"-- {obj.kind.title()} structure for {obj.display_name}\n"
                "-- ----------------------------\n"
            )
        else:
            stream.write(
                f"\n-- {obj.kind.title()}: {obj.display_name}\n"
            )

    def _write_drop(self, stream: TextIO, obj: TableObject) -> None:
        keyword = "VIEW" if obj.kind != "table" else "TABLE"
        suffix = " CASCADE" if self.kind == "postgresql" else ""
        stream.write(
            f"DROP {keyword} IF EXISTS "
            f"{self.adapter.qualified_name(obj.name, obj.schema)}"
            f"{suffix};\n"
        )

    def _write_statement(self, stream: TextIO, ddl: str) -> None:
        text = str(ddl or "").strip()
        if not text:
            return
        is_mysql_trigger = (
            self.kind == "mysql"
            and text.upper().startswith("CREATE")
            and " TRIGGER " in f" {text.upper()} "
        )
        if is_mysql_trigger:
            stream.write("DELIMITER ;;\n")
            stream.write(text.rstrip(";") + ";;\n")
            stream.write("DELIMITER ;\n\n")
            return
        stream.write(text)
        if not text.endswith(";"):
            stream.write(";")
        stream.write("\n\n")

    def _write_table_data(
        self,
        stream: TextIO,
        obj: TableObject,
        cancel_event: Optional[threading.Event],
        notify: Callable[..., None],
        batch_size: int = 200,
    ) -> int:
        columns = self.adapter.get_columns(obj.name, obj.schema)
        if not columns:
            return 0
        qualified = self.adapter.qualified_name(obj.name, obj.schema)
        column_sql = ", ".join(
            self.adapter.quote_identifier(column.name)
            for column in columns
        )
        rows: List[Tuple[Any, ...]] = []
        count = 0
        heading_written = False
        iterator = self.adapter.iter_table_rows(
            obj.name, obj.schema, batch_size=batch_size
        )
        try:
            for row in iterator:
                if self._cancelled(cancel_event):
                    break
                rows.append(row)
                if len(rows) >= batch_size:
                    if not heading_written:
                        stream.write(
                            "\n-- Data for "
                            f"{obj.display_name}\n"
                        )
                        heading_written = True
                    self._write_insert(
                        stream, qualified, column_sql, rows, columns
                    )
                    count += len(rows)
                    rows.clear()
                    notify(
                        f"正在导出数据：{obj.display_name} · {count} 行",
                        rows=count,
                    )
            if rows and not self._cancelled(cancel_event):
                if not heading_written:
                    stream.write(
                        f"\n-- Data for {obj.display_name}\n"
                    )
                self._write_insert(
                    stream, qualified, column_sql, rows, columns
                )
                count += len(rows)
        finally:
            close = getattr(iterator, "close", None)
            if close:
                close()
        if count:
            stream.write("\n")
        return count

    def _write_insert(
        self,
        stream: TextIO,
        qualified: str,
        column_sql: str,
        rows: Iterable[Tuple[Any, ...]],
        columns: Sequence[ColumnInfo],
    ) -> None:
        values = []
        for row in rows:
            if len(row) != len(columns):
                raise DatabaseError(
                    f"导出 {qualified} 时返回的字段数量不一致"
                )
            values.append(
                "(" + ", ".join(self._literal(value) for value in row) + ")"
            )
        override = (
            " OVERRIDING SYSTEM VALUE"
            if self.kind == "postgresql"
            and any(column.auto_increment for column in columns)
            else ""
        )
        stream.write(
            f"INSERT INTO {qualified} ({column_sql}){override} VALUES\n"
            + ",\n".join(values)
            + ";\n"
        )

    def _literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            if self.kind == "postgresql":
                return "TRUE" if value else "FALSE"
            return "1" if value else "0"
        if isinstance(value, numbers.Number):
            if isinstance(value, float) and not math.isfinite(value):
                return self._quote_text(str(value))
            return str(value)
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, (bytes, bytearray)):
            hexadecimal = bytes(value).hex().upper()
            if self.kind == "mysql":
                return f"0x{hexadecimal}"
            if self.kind == "postgresql":
                return f"decode('{hexadecimal}', 'hex')"
            return f"X'{hexadecimal}'"
        if isinstance(value, dt.datetime):
            return self._quote_text(value.isoformat(sep=" "))
        if isinstance(value, (dt.date, dt.time)):
            return self._quote_text(value.isoformat())
        return self._quote_text(str(value))

    def _quote_text(self, value: str) -> str:
        if "\x00" in value and self.kind == "sqlite":
            return f"CAST(X'{value.encode('utf-8').hex().upper()}' AS TEXT)"
        if "\x00" in value:
            raise DatabaseError(
                f"{self.source_name} SQL 文本字面量无法安全表示 NUL 字符"
            )
        escaped = value.replace("'", "''")
        if self.kind == "mysql":
            escaped = (
                escaped.replace("\\", "\\\\")
                .replace("\r", "\\r")
                .replace("\n", "\\n")
                .replace("\x1a", "\\Z")
            )
        return "'" + escaped + "'"
