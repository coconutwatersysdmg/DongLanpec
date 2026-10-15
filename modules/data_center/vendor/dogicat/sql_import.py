"""Streaming SQL dump import with common vendor compatibility rules."""

from __future__ import annotations

import re
import sqlite3
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, TextIO

from .core import DatabaseAdapter, DatabaseError


@dataclass
class SQLCommand:
    sql: str
    start_line: int
    end_line: int
    position: int = 0
    kind: str = "sql"
    copy_data: Optional[TextIO] = None


@dataclass
class SQLImportError:
    line: int
    message: str
    sql_preview: str


@dataclass
class SQLImportProgress:
    position: int
    total_bytes: int
    line: int
    succeeded: int
    failed: int
    skipped: int
    current: str = ""

    @property
    def percent(self) -> float:
        if not self.total_bytes:
            return 0.0
        return max(0.0, min(100.0, self.position * 100.0 / self.total_bytes))


@dataclass
class SQLImportReport:
    path: Path
    encoding: str
    detected_dialect: str
    target_dialect: str
    target_database: str = ""
    overwrite: bool = False
    cleared_objects: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False
    elapsed_seconds: float = 0.0
    errors: List[SQLImportError] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return not self.cancelled and self.failed == 0


def detect_sql_encoding(path: Path) -> str:
    with Path(path).open("rb") as stream:
        sample = stream.read(256 * 1024)
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    if sample[:200].count(b"\x00") > 20:
        return "utf-16-le" if sample[1:100:2].count(b"\x00") > sample[:100:2].count(b"\x00") else "utf-16-be"
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        try:
            sample.decode("gb18030")
            return "gb18030"
        except UnicodeDecodeError:
            return "latin-1"


def detect_sql_dialect(path: Path, encoding: str = "auto") -> str:
    actual = detect_sql_encoding(path) if encoding == "auto" else encoding
    with Path(path).open("r", encoding=actual, errors="replace", newline="") as stream:
        sample = stream.read(256 * 1024).lower()
    if (
        "source server type    : mysql" in sample
        or "set foreign_key_checks" in sample
        or "engine=innodb" in sample
        or "mysql dump" in sample
    ):
        return "mysql"
    if (
        "postgresql database dump" in sample
        or "set statement_timeout" in sample
        or re.search(r"\bcopy\s+.+\s+from\s+stdin\s*;", sample, re.DOTALL)
    ):
        return "postgresql"
    if "pragma foreign_keys" in sample or "sqlite_sequence" in sample or "begin transaction;" in sample:
        return "sqlite"
    if re.search(r"(?m)^\s*go\s*$", sample):
        return "sqlserver"
    if re.search(r"(?m)^\s*delimiter\s+\S+", sample):
        return "mysql"
    return "generic"


def _has_executable_content(text: str) -> bool:
    # Preserve MySQL executable comments (/*! ... */), but discard ordinary
    # headers so they do not interfere with DELIMITER directives.
    text = re.sub(r"/\*(?!\!).*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^\s*(?:--|#).*$", "", text)
    return bool(text.strip())


def _is_postgres_copy(sql: str) -> bool:
    return bool(re.search(r"\bCOPY\s+.+?\s+FROM\s+stdin\s*$", sql, flags=re.IGNORECASE | re.DOTALL))


def _controls_database_scope(sql: str, dialect: str) -> bool:
    """Return whether a statement can escape the explicitly selected target."""
    cleaned = re.sub(
        r"^\s*(?:(?:--|#)[^\r\n]*(?:\r?\n|$)|/\*.*?\*/\s*)*",
        "",
        sql,
        flags=re.DOTALL,
    )
    if dialect == "mysql":
        return bool(re.match(
            r"(?is)^(?:USE\b|(?:CREATE|DROP|ALTER)\s+"
            r"(?:DATABASE|SCHEMA)\b)",
            cleaned,
        ))
    if dialect in {"postgres", "postgresql"}:
        return bool(re.match(
            r"(?is)^(?:CREATE|DROP|ALTER)\s+DATABASE\b",
            cleaned,
        ))
    if dialect == "sqlite":
        return bool(re.match(r"(?is)^(?:ATTACH|DETACH)\b", cleaned))
    return False


def _is_transaction_wrapper(sql: str) -> bool:
    """Identify dump-level wrappers; adapter.execute commits each statement."""
    cleaned = re.sub(
        r"^\s*(?:(?:--|#)[^\r\n]*(?:\r?\n|$)|/\*.*?\*/\s*)*",
        "",
        sql,
        flags=re.DOTALL,
    ).strip().rstrip(";").strip()
    return bool(re.fullmatch(
        r"(?is)(?:BEGIN(?:\s+(?:TRANSACTION|WORK))?|"
        r"START\s+TRANSACTION|COMMIT(?:\s+WORK)?|"
        r"END(?:\s+TRANSACTION)?|ROLLBACK(?:\s+WORK)?)",
        cleaned,
    ))


class SQLStreamParser:
    """Incrementally split a dump without breaking routines or quoted SQL."""

    def __init__(
        self,
        stream: TextIO,
        dialect: str,
        cancel_event: Optional[threading.Event] = None,
        on_read: Optional[Callable[[int, int, str], None]] = None,
    ):
        self.stream = stream
        self.dialect = dialect.lower()
        self.cancel_event = cancel_event or threading.Event()
        self.on_read = on_read
        self.delimiter = ";"
        self.buffer: List[str] = []
        self.start_line = 1
        self.line_number = 0
        self.quote: Optional[str] = None
        self.block_comment = False
        self.dollar_tag: Optional[str] = None

    def __iter__(self):
        if self.dialect == "sqlite":
            yield from self._iter_sqlite()
            return
        while True:
            if self.cancel_event.is_set():
                return
            line = self.stream.readline()
            if not line:
                break
            self.line_number += 1
            stripped = line.strip()
            top_level = not self.quote and not self.block_comment and not self.dollar_tag
            existing = "".join(self.buffer)
            if top_level and not _has_executable_content(existing):
                self.buffer.clear()
                self.start_line = self.line_number
                existing = ""

            delimiter_match = re.match(r"(?i)^\s*DELIMITER\s+(\S+)\s*$", line)
            if top_level and delimiter_match and not _has_executable_content(existing):
                self.buffer.clear()
                self.delimiter = delimiter_match.group(1)
                self.start_line = self.line_number + 1
                yield SQLCommand(line.strip(), self.line_number, self.line_number, self._tell(), "skip")
                continue

            if top_level and stripped.upper() == "GO":
                command = self._flush(self.line_number - 1)
                if command:
                    yield command
                else:
                    yield SQLCommand("GO", self.line_number, self.line_number, self._tell(), "skip")
                self.start_line = self.line_number + 1
                continue

            if top_level and stripped.startswith("\\") and not _has_executable_content(existing):
                self.buffer.clear()
                yield SQLCommand(stripped, self.line_number, self.line_number, self._tell(), "skip")
                self.start_line = self.line_number + 1
                continue

            for command in self._feed(line):
                if _is_postgres_copy(command.sql):
                    command.copy_data = self._read_copy_data()
                    command.end_line = self.line_number
                    command.position = self._tell()
                yield command

            if self.on_read and self.line_number % 500 == 0:
                self.on_read(self.line_number, self._tell(), "正在读取 SQL…")

        command = self._flush(self.line_number)
        if command:
            yield command

    def _iter_sqlite(self):
        """Use SQLite's own completeness parser so trigger bodies stay intact."""
        self.buffer.clear()
        self.start_line = 1
        while True:
            if self.cancel_event.is_set():
                return
            line = self.stream.readline()
            if not line:
                break
            self.line_number += 1
            if not self.buffer or not _has_executable_content("".join(self.buffer)):
                self.start_line = self.line_number
            for char in line:
                self.buffer.append(char)
                if char == ";" and sqlite3.complete_statement("".join(self.buffer)):
                    sql = "".join(self.buffer).strip()
                    self.buffer.clear()
                    if sql.endswith(";"):
                        sql = sql[:-1].rstrip()
                    if _has_executable_content(sql):
                        yield SQLCommand(
                            sql, self.start_line, self.line_number, self._tell()
                        )
                    self.start_line = self.line_number
            if self.on_read and self.line_number % 500 == 0:
                self.on_read(self.line_number, self._tell(), "正在读取 SQLite 转储…")
        sql = "".join(self.buffer).strip()
        self.buffer.clear()
        if _has_executable_content(sql):
            yield SQLCommand(sql, self.start_line, self.line_number, self._tell())

    def _feed(self, text: str) -> List[SQLCommand]:
        commands: List[SQLCommand] = []
        index = 0
        line_comment = False
        while index < len(text):
            char = text[index]
            nxt = text[index + 1] if index + 1 < len(text) else ""

            if line_comment:
                self.buffer.append(char)
                index += 1
                continue
            if self.block_comment:
                self.buffer.append(char)
                if char == "*" and nxt == "/":
                    self.buffer.append(nxt)
                    self.block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if self.dollar_tag:
                if text.startswith(self.dollar_tag, index):
                    self.buffer.append(self.dollar_tag)
                    index += len(self.dollar_tag)
                    self.dollar_tag = None
                else:
                    self.buffer.append(char)
                    index += 1
                continue
            if self.quote:
                self.buffer.append(char)
                if char == self.quote:
                    if nxt == self.quote:
                        self.buffer.append(nxt)
                        index += 2
                        continue
                    self.quote = None
                elif char == "\\" and nxt:
                    self.buffer.append(nxt)
                    index += 2
                    continue
                index += 1
                continue

            if text.startswith(self.delimiter, index):
                command = self._flush(self.line_number)
                if command:
                    commands.append(command)
                index += len(self.delimiter)
                self.start_line = self.line_number
                continue
            if char == "-" and nxt == "-":
                self.buffer.extend((char, nxt))
                line_comment = True
                index += 2
                continue
            if char == "#" and self.dialect == "mysql":
                self.buffer.append(char)
                line_comment = True
                index += 1
                continue
            if char == "/" and nxt == "*":
                self.buffer.extend((char, nxt))
                self.block_comment = True
                index += 2
                continue
            if char in ("'", '"', "`"):
                self.quote = char
                self.buffer.append(char)
                index += 1
                continue
            if char == "$" and self.dialect in {"postgres", "postgresql"}:
                match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", text[index:])
                if match:
                    self.dollar_tag = match.group(0)
                    self.buffer.append(self.dollar_tag)
                    index += len(self.dollar_tag)
                    continue
            self.buffer.append(char)
            index += 1
        return commands

    def _flush(self, end_line: int) -> Optional[SQLCommand]:
        sql = "".join(self.buffer).strip()
        self.buffer.clear()
        if not sql or not _has_executable_content(sql):
            return None
        command = SQLCommand(sql, self.start_line, max(end_line, self.start_line), self._tell())
        self.start_line = self.line_number
        return command

    def _read_copy_data(self) -> TextIO:
        spool = tempfile.SpooledTemporaryFile(
            max_size=8 * 1024 * 1024, mode="w+", encoding="utf-8", newline=""
        )
        while True:
            if self.cancel_event.is_set():
                spool.close()
                return tempfile.SpooledTemporaryFile(mode="w+", encoding="utf-8")
            line = self.stream.readline()
            if not line:
                break
            self.line_number += 1
            if line.rstrip("\r\n") == r"\.":
                break
            spool.write(line)
            if self.on_read and self.line_number % 500 == 0:
                self.on_read(self.line_number, self._tell(), "正在读取 COPY 数据…")
        spool.seek(0)
        return spool

    def _tell(self) -> int:
        try:
            return int(self.stream.tell())
        except (OSError, ValueError):
            return 0


class SQLFileImporter:
    def __init__(self, adapter: DatabaseAdapter):
        self.adapter = adapter

    def import_file(
        self,
        path: Path,
        encoding: str = "auto",
        continue_on_error: bool = False,
        overwrite: bool = False,
        cancel_event: Optional[threading.Event] = None,
        progress: Optional[Callable[[SQLImportProgress], None]] = None,
    ) -> SQLImportReport:
        path = Path(path)
        actual_encoding = detect_sql_encoding(path) if encoding == "auto" else encoding
        detected = detect_sql_dialect(path, actual_encoding)
        target = self.adapter.profile.kind.lower()
        report = SQLImportReport(
            path, actual_encoding, detected, target,
            target_database=self.adapter.profile.database,
            overwrite=overwrite,
        )
        total_bytes = path.stat().st_size
        cancelled = cancel_event or threading.Event()
        started = time.perf_counter()
        last_update = [0.0]

        def notify(line: int, position: int, current: str = "", force: bool = False) -> None:
            if not progress:
                return
            now = time.monotonic()
            if not force and now - last_update[0] < 0.08:
                return
            last_update[0] = now
            progress(SQLImportProgress(
                position, total_bytes, line, report.succeeded, report.failed,
                report.skipped, current,
            ))

        try:
            if overwrite and not cancelled.is_set():
                notify(
                    0, 0,
                    f"正在清空目标数据库 {report.target_database}…",
                    True,
                )
                report.cleared_objects = (
                    self.adapter.clear_database_for_import()
                )
                notify(
                    0, 0,
                    f"已清空 {report.cleared_objects} 个数据库对象",
                    True,
                )
            with path.open("r", encoding=actual_encoding, errors="strict", newline="") as stream:
                parser = SQLStreamParser(stream, target, cancelled, notify)
                for command in parser:
                    if cancelled.is_set():
                        if command.copy_data is not None:
                            command.copy_data.close()
                        report.cancelled = True
                        break
                    if command.kind == "skip":
                        report.skipped += 1
                        notify(command.end_line, command.position, f"跳过客户端指令：{command.sql[:60]}")
                        continue
                    preview = " ".join(command.sql.split())[:120]
                    if (
                        report.target_database
                        and _controls_database_scope(command.sql, target)
                    ):
                        report.skipped += 1
                        notify(
                            command.end_line, command.position,
                            f"已锁定目标库，跳过数据库切换指令：{preview}",
                            True,
                        )
                        continue
                    if _is_transaction_wrapper(command.sql):
                        report.skipped += 1
                        notify(
                            command.end_line, command.position,
                            f"跳过转储事务包装：{preview}",
                            True,
                        )
                        continue
                    notify(command.end_line, command.position, preview)
                    try:
                        if command.copy_data is not None:
                            self.adapter.execute_copy(command.sql, command.copy_data)
                        else:
                            self.adapter.execute(command.sql, max_rows=1)
                    except Exception as exc:
                        report.failed += 1
                        if len(report.errors) < 500:
                            report.errors.append(SQLImportError(
                                command.start_line, str(exc), preview,
                            ))
                        if not continue_on_error:
                            if command.copy_data is not None:
                                command.copy_data.close()
                            break
                    else:
                        report.succeeded += 1
                    finally:
                        if command.copy_data is not None and not command.copy_data.closed:
                            command.copy_data.close()
                    notify(command.end_line, command.position, preview, True)
        except (UnicodeDecodeError, OSError) as exc:
            raise DatabaseError(f"读取 SQL 文件失败：{exc}") from exc
        finally:
            report.elapsed_seconds = time.perf_counter() - started

        report.cancelled = report.cancelled or cancelled.is_set()
        notify(0, total_bytes, "已取消" if report.cancelled else "导入结束", True)
        return report
