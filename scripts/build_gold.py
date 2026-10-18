"""Run every gold query, verify it, and store its result in data/gold_results/<id>.json.

    uv run python scripts/build_gold.py            # all cases
    uv run python scripts/build_gold.py q001 q007  # some cases

Checks for every answered case:
1. gold_sql and check_sql (written independently, a different way) return the same rows;
2. the gold result is not empty;
3. a top-n question (ORDER BY ... LIMIT n) has no tie between rows n and n+1, or several
   answers would be equally right; and if its order matters, no ties inside the top n.
Runs as the agent's read-only role with its 5 s timeout. Exits 1 if any check fails.
"""

import argparse
import sys
import time

import psycopg

from sql_agent_evals.cases import load_cases
from sql_agent_evals.compare import compare_results
from sql_agent_evals.config import get_settings
from sql_agent_evals.gold import is_ordered, ranking_ties, run_query, write_gold_result

AGENT_VISIBLE_ROWS = 100  # run_sql shows the agent at most this many rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="*", help="case ids (default: all)")
    args = parser.parse_args()

    settings = get_settings()
    cases = load_cases(settings.data_dir / "golden.jsonl")
    if args.ids:
        cases = [c for c in cases if c.id in set(args.ids)]
    failures: dict[str, list[str]] = {}

    with psycopg.connect(
        settings.database_url.get_secret_value(), connect_timeout=10, autocommit=True
    ) as conn:
        for case in cases:
            if case.expected_status != "answered":
                print(f"{case.id}  {case.expected_status:<19} (no SQL)  {case.question}")
                continue
            started = time.perf_counter()
            problems, warnings = [], []
            try:
                gold = run_query(conn, case.gold_sql)
                check = run_query(conn, case.check_sql)
            except psycopg.Error as exc:
                failures[case.id] = [f"query failed: {str(exc).strip().splitlines()[0]}"]
                print(f"{case.id}  FAILED  {failures[case.id][0]}")
                continue
            ordered = (
                case.order_matters if case.order_matters is not None else is_ordered(case.gold_sql)
            )
            comparison = compare_results(gold.rows, check.rows, ordered=ordered)
            if not comparison.match:
                problems.append(f"check_sql disagrees: {comparison.reason}")
            if not gold.rows:
                problems.append("the gold result is empty")
            ties = ranking_ties(conn, case.gold_sql)
            if ties and ties.at_cutoff:
                problems.append("tie at the top-n cut-off: several answers are equally right")
            if ties and ties.inside and ordered:
                problems.append("ties inside the top n while order matters")
            if len(gold.rows) > AGENT_VISIBLE_ROWS:
                warnings.append(f"{len(gold.rows)} rows: the agent sees at most 100")

            write_gold_result(
                settings.data_dir / "gold_results" / f"{case.id}.json",
                case.id,
                case.gold_sql,
                gold,
                ordered,
            )
            status = "FAILED" if problems else "ok"
            seconds = time.perf_counter() - started
            print(
                f"{case.id}  {status:<6} {len(gold.rows):>4} rows  {seconds:4.1f}s  "
                f"{'ordered' if ordered else 'set    '}  {case.question}"
            )
            for message in problems + [f"warning: {w}" for w in warnings]:
                print(f"         - {message}")
            if problems:
                failures[case.id] = problems

    answered = sum(c.expected_status == "answered" for c in cases)
    print(f"\n{len(cases)} cases, {answered} with gold SQL, {len(failures)} failing")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
