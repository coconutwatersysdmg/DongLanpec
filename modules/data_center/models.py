from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

ACTIVITY_DB = "产品设计活动库"
META_DB = "数据中心配置库"


class DataCenterError(ValueError):
    pass


def _encode(value):
    if isinstance(value, Decimal):
        return {"$decimal": str(value.normalize())}
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return {"$" + type(value).__name__: value.isoformat()}
    if isinstance(value, dt.timedelta):
        return {"$timedelta": value.total_seconds()}
    raise TypeError(type(value).__name__)


def _decode(value):
    if len(value) == 1:
        for key, factory in (("$decimal", Decimal), ("$bytes", base64.b64decode),
                             ("$datetime", dt.datetime.fromisoformat),
                             ("$date", dt.date.fromisoformat), ("$time", dt.time.fromisoformat)):
            if key in value:
                return factory(value[key])
        if "$timedelta" in value:
            return dt.timedelta(seconds=value["$timedelta"])
    return value


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_encode, separators=(",", ":"))


def loads(value):
    return json.loads(value, object_hook=_decode)


def display(value):
    if value is None:
        return "NULL"
    if value == '':
        return "（空文本）"
    if isinstance(value, bytes):
        return "二进制 · %s 字节" % len(value)
    return str(value)


@dataclass(frozen=True)
class CellRef:
    database: str
    table: str
    keys: Tuple[Tuple[str, Any], ...]
    column: str

    @classmethod
    def make(cls, database, table, keys, column):
        if not database or not table or not column or not keys:
            raise DataCenterError("字段必须包含库、表、完整记录定位条件和字段名。")
        return cls(database, table, tuple(sorted(keys.items())), column)

    @property
    def id(self):
        return hashlib.sha256(dumps(self.to_dict()).encode("utf-8")).hexdigest()

    @property
    def label(self):
        return "%s.%s.%s [%s]" % (self.database, self.table, self.column,
                                   ", ".join("%s=%s" % (k, display(v)) for k, v in self.keys))

    def to_dict(self):
        return dict(database=self.database, table=self.table, keys=dict(self.keys), column=self.column)

    @classmethod
    def from_dict(cls, value):
        return cls.make(**value)


@dataclass(frozen=True)
class Edge:
    source: CellRef
    target: CellRef
    evidence: str = "用户确认的直接取值"
    candidate: bool = False

    def to_dict(self):
        return dict(source=self.source.to_dict(), target=self.target.to_dict(),
                    evidence=self.evidence, candidate=self.candidate)

    @classmethod
    def from_dict(cls, value):
        return cls(CellRef.from_dict(value['source']), CellRef.from_dict(value['target']),
                   value.get('evidence', ''), value.get('candidate', False))


@dataclass
class Change:
    ref: CellRef
    before: Any
    after: Any
    reason: str

    def to_dict(self):
        return dict(ref=self.ref.to_dict(), before=self.before, after=self.after, reason=self.reason)


@dataclass
class Plan:
    revision: int
    changes: List[Change]
    observed: Dict[CellRef, Any]
    edges_before: Dict[CellRef, Edge]
    edges_after: Dict[CellRef, Edge]
    action: str = "编辑字段与取值链路"
    actor: str = ""
    undo_of: Optional[int] = None

    @property
    def databases(self):
        return sorted({c.ref.database for c in self.changes})

    def to_dict(self):
        return dict(revision=self.revision, changes=[c.to_dict() for c in self.changes],
                    observed=[dict(ref=r.to_dict(), value=v) for r, v in self.observed.items()],
                    edges_before=[e.to_dict() for e in self.edges_before.values()],
                    edges_after=[e.to_dict() for e in self.edges_after.values()],
                    action=self.action, actor=self.actor, undo_of=self.undo_of)


def topological(edges):
    """One incoming value source per field; reject cycles before reading/writing data."""
    children, indegree = {}, {}
    for target, edge in edges.items():
        source = edge.source
        if target != edge.target or edge.candidate:
            raise DataCenterError("候选来源必须明确确认后才能联动。")
        children.setdefault(source, []).append(target)
        indegree.setdefault(source, 0)
        indegree[target] = indegree.get(target, 0) + 1
    queue = sorted((r for r, n in indegree.items() if n == 0), key=lambda r: r.id)
    result = []
    while queue:
        ref = queue.pop(0)
        result.append(ref)
        for target in children.get(ref, []):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(result) != len(indegree):
        raise DataCenterError("该连线会形成循环依赖，请选择其他来源。")
    return result, children
