"""The golden set itself: its shape matches the plan, and every gold result is current.

These run in CI without a database: they read only the committed files.
"""

import json
from collections import Counter
from pathlib import Path

import pytest

from sql_agent_evals.cases import BUCKETS, SMOKE_TAG, load_cases
from sql_agent_evals.gold import sql_fingerprint

DATA = Path(__file__).resolve().parent.parent / "data"
CASES = load_cases(DATA / "golden.jsonl")


def test_bucket_sizes_match_the_plan():
    sizes = Counter(c.bucket for c in CASES)
    assert len(CASES) == 100
    assert (sizes["single_table"], sizes["join"], sizes["aggregation"]) == (25, 35, 25)
    assert sizes["ambiguous"] + sizes["unanswerable"] == 15


def test_ids_run_from_q001_to_q100():
    assert [c.id for c in CASES] == [f"q{n:03d}" for n in range(1, 101)]


def test_smoke_subset_has_10_cases_covering_every_bucket():
    smoke = [c for c in CASES if SMOKE_TAG in c.tags]
    assert len(smoke) == 10
    assert {c.bucket for c in smoke} == set(BUCKETS)


def test_questions_are_unique():
    questions = [c.question.lower() for c in CASES]
    assert len(set(questions)) == len(questions)


@pytest.mark.parametrize("case", [c for c in CASES if c.gold_sql], ids=lambda c: c.id)
def test_every_answered_case_has_a_current_gold_result(case):
    path = DATA / "gold_results" / f"{case.id}.json"
    assert path.exists(), f"run scripts/build_gold.py {case.id}"
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["gold_sql_fingerprint"] == sql_fingerprint(case.gold_sql), (
        f"{case.id}: gold_sql changed since its result was built; run scripts/build_gold.py"
    )
    assert result["row_count"] == len(result["rows"]) > 0


def test_no_stray_gold_results():
    answered = {c.id for c in CASES if c.gold_sql}
    on_disk = {p.stem for p in (DATA / "gold_results").glob("*.json")}
    assert on_disk == answered
