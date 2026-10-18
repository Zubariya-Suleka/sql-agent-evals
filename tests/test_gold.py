import json

import pytest
import sqlglot

from sql_agent_evals.cases import Case, load_cases
from sql_agent_evals.gold import first_order_key_index, is_ordered, ranking_ties


def tree(sql):
    return sqlglot.parse_one(sql, dialect="postgres")


@pytest.mark.parametrize(
    ("sql", "index"),
    [
        ("SELECT state, count(*) AS n FROM c GROUP BY 1 ORDER BY n DESC LIMIT 5", 1),
        ("SELECT state, count(*) AS n FROM c GROUP BY 1 ORDER BY 2 DESC LIMIT 5", 1),
        ("SELECT state, count(*) AS n FROM c GROUP BY 1 ORDER BY count(*) DESC LIMIT 5", 1),
        ("SELECT state, n FROM t ORDER BY state LIMIT 5", 0),
        ("SELECT state FROM t ORDER BY length(state) LIMIT 5", None),  # not a result column
    ],
)
def test_first_order_key_is_located_in_the_result(sql, index):
    assert first_order_key_index(tree(sql)) == index


def test_ordered_means_a_top_level_order_by():
    assert is_ordered("SELECT a FROM t ORDER BY a")
    assert not is_ordered("SELECT a FROM (SELECT a FROM t ORDER BY a) s")


class FakeConnection:
    """Answers every query with fixed rows; records the SQL it was sent."""

    def __init__(self, rows):
        self.rows, self.sent = rows, []

    def execute(self, sql):
        self.sent.append(sql)
        conn = self

        class Cursor:
            description = [type("D", (), {"name": "c"})()] * len(conn.rows[0])

            def fetchall(self):
                return conn.rows

        return Cursor()


SQL = "SELECT state, count(*) AS n FROM c GROUP BY 1 ORDER BY n DESC LIMIT 3"


def test_tie_at_the_cut_off_is_detected_with_one_extra_row():
    conn = FakeConnection([("SP", 10), ("RJ", 8), ("MG", 5), ("RS", 5)])
    ties = ranking_ties(conn, SQL)
    assert ties.at_cutoff and not ties.inside
    assert conn.sent[0].endswith("LIMIT 4")


def test_ties_inside_the_top_n_are_reported_separately():
    ties = ranking_ties(FakeConnection([("SP", 10), ("RJ", 10), ("MG", 5), ("RS", 4)]), SQL)
    assert ties.inside and not ties.at_cutoff


def test_queries_that_are_not_top_n_are_not_checked():
    assert ranking_ties(FakeConnection([("x", 1)]), "SELECT a, b FROM t ORDER BY b") is None


CASE = {
    "id": "q001",
    "question": "How many orders were canceled?",
    "expected_status": "answered",
    "gold_sql": "SELECT count(*) FROM orders WHERE order_status = 'canceled'",
    "check_sql": "SELECT sum(1) FROM orders WHERE order_status IN ('canceled')",
    "tags": ["single_table"],
    "difficulty": "easy",
}


def test_answered_cases_need_both_queries():
    with pytest.raises(ValueError, match="gold_sql and check_sql"):
        Case(**(CASE | {"check_sql": None}))


def test_unanswerable_cases_have_no_sql():
    with pytest.raises(ValueError, match="only answered cases"):
        Case(**(CASE | {"expected_status": "cannot_answer", "tags": ["unanswerable"]}))


def test_every_case_has_exactly_one_bucket():
    with pytest.raises(ValueError, match="exactly one bucket"):
        Case(**(CASE | {"tags": ["single_table", "join"]}))


def test_duplicate_ids_are_rejected(tmp_path):
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps(CASE) + "\n" + json.dumps(CASE) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate case id q001"):
        load_cases(path)
