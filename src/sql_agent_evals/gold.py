"""Running and verifying gold queries."""

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import sqlglot
from sqlglot import exp

from sql_agent_evals.compare import normalize


class Connection(Protocol):
    def execute(self, query: str) -> Any: ...


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]


def run_query(conn: Connection, sql: str) -> QueryResult:
    cursor = conn.execute(sql)
    columns = [d.name for d in cursor.description] if cursor.description else []
    return QueryResult(columns, cursor.fetchall() if cursor.description else [])


def _parse(sql: str) -> exp.Expression:
    return sqlglot.parse_one(sql, dialect="postgres")


def is_ordered(sql: str) -> bool:
    """Whether the query's own result is ordered (a top-level ORDER BY)."""
    return _parse(sql).args.get("order") is not None


def _top_n(tree: exp.Expression) -> int | None:
    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if tree.args.get("order") is None or not (isinstance(value, exp.Literal) and value.is_int):
        return None
    return int(value.this)


def first_order_key_index(tree: exp.Expression) -> int | None:
    """Which result column the first ORDER BY key is, or None if it can't be told."""
    order = tree.args.get("order")
    if order is None or not isinstance(tree, exp.Select):
        return None
    key = order.expressions[0].this
    selects = tree.selects
    if isinstance(key, exp.Literal) and key.is_int:
        return int(key.this) - 1
    names = [s.alias_or_name.lower() for s in selects]
    if isinstance(key, exp.Column) and not key.table and key.name.lower() in names:
        return names.index(key.name.lower())
    target = key.sql(dialect="postgres").lower()  # ORDER BY count(*) with count(*) AS n
    for i, select in enumerate(selects):
        inner = select.this if isinstance(select, exp.Alias) else select
        if inner.sql(dialect="postgres").lower() == target:
            return i
    return None


@dataclass(frozen=True)
class RankingTies:
    at_cutoff: bool  # rows n and n+1 rank equally: several top-n answers are equally right
    inside: bool  # some rows inside the top n rank equally: their order is arbitrary


def ranking_ties(conn: Connection, sql: str) -> RankingTies | None:
    """For a top-n query (ORDER BY ... LIMIT n), ties on the first ORDER BY key.

    None when the query is not top-n or its ranking column can't be located.
    """
    tree = _parse(sql)
    n = _top_n(tree)
    index = first_order_key_index(tree)
    if n is None or index is None:
        return None
    widened = tree.copy().limit(n + 1).sql(dialect="postgres")
    keys = [normalize(row[index]) for row in run_query(conn, widened).rows]
    at_cutoff = len(keys) > n and keys[n - 1] == keys[n]
    inside = any(keys[i] == keys[i + 1] for i in range(min(n, len(keys)) - 1))
    return RankingTies(at_cutoff=at_cutoff, inside=inside)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def sql_fingerprint(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]


def write_gold_result(
    path: Path, case_id: str, gold_sql: str, result: QueryResult, ordered: bool
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": case_id,
        # Lets the scorer notice a gold result that is stale after gold_sql changed.
        "gold_sql_fingerprint": sql_fingerprint(gold_sql),
        "ordered": ordered,
        "columns": result.columns,
        "row_count": len(result.rows),
        "rows": [[_json_value(v) for v in row] for row in result.rows],
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
