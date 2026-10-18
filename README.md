# sql-agent-evals

**Proves:** "evaluation frameworks" · "evaluation suites" · "evaluation pipelines"

A 100-question golden set over the Olist e-commerce data, with verified gold answers, and the pipeline that scores [sql-agent](https://github.com/Zubariya-Suleka/sql-agent) against it.

> Week 2 (the golden set) is done. Week 3 adds the eval runner, the LLM judge, the HTML report and the CI gate.

## The golden set

[data/golden.jsonl](data/golden.jsonl) holds one case per line. Each answerable case has a verified result in [data/gold_results/](data/gold_results/).

| Bucket | Cases | What it tests |
|---|---|---|
| Single table, filters | 25 | counts, nulls, distinct values, ratios, intervals, top-n |
| Joins (2–4 tables) | 35 | the dataset's traps (below) |
| Aggregations and time windows | 25 | monthly series, GMV, late-delivery rate by state, running totals, median |
| Ambiguous | 8 | expected status `needs_clarification` ("Who is the best seller?") |
| Unanswerable | 7 | expected status `cannot_answer` ("profit margin": there's no cost data) |

Difficulty: 41 easy, 46 medium, 13 hard. The **smoke subset** is 10 fixed cases covering every bucket (tag `smoke`), for cheap runs while developing.

Tags mark the traps a case tests:
- `customer_unique_id`: `customer_id` is per order, the person is `customer_unique_id`.
- `fan_out`: joining orders to their items repeats each order.
- `translation`: English category names, including categories that have none.
- `late_delivery`, `null_handling`, `anti_join`, `seller_vs_customer`.

A case looks like this:

```json
{"id": "q034", "question": "For orders from customers in Roraima (RR), what is the average freight per order (the sum of freight over each order's items), in BRL rounded to 2 decimals?",
 "expected_status": "answered", "gold_sql": "SELECT round(avg(order_freight), 2) FROM (...) AS per_order",
 "check_sql": "SELECT round(sum(i.freight_value) / count(DISTINCT i.order_id), 2) FROM ...",
 "tags": ["join", "fan_out", "smoke"], "difficulty": "hard",
 "notes": "Averaging freight over item rows instead would give the average per item, not per order."}
```

## How the gold answers are verified

The plan called for checking every gold query by hand. Instead, verification is automated and repeatable, so it runs again whenever a query changes (`scripts/build_gold.py`):

1. **Two independent queries.** Every answerable case has a `check_sql` written a different way: a subquery instead of a join, `EXISTS` instead of `IN`, a window function instead of an aggregate, a different date filter. It must return the same rows as `gold_sql`. All 85 agree.
2. **No ties at a top-n cut-off.** For `ORDER BY ... LIMIT n`, the query is re-run with `LIMIT n+1`. If rows n and n+1 rank equally, several answers would be equally right, so the case fails.
3. **Runnable by the agent.** Gold SQL runs as the agent's read-only role with its 5 s timeout, and must return rows.
4. **Answers agree across cases.** Questions asked separately must add up: 2017's months (q061), quarters (q072) and running total (q071) all add up to q002's 45,101 orders. New customers per year (q070) sum to q004's 96,096 people. Known facts hold: 625 canceled orders, Black Friday 2017 as the busiest month, the median payment of 100 BRL.
5. **CI guards it.** A test fails if any gold result is stale (its SQL fingerprint no longer matches) or if the set's shape drifts from the plan.

The limit, stated plainly: each question and both of its queries come from the same author, so a misreading shared by both queries would pass. A human spot-check of a random sample would measure how often that happens.

## How results are compared

[compare.py](src/sql_agent_evals/compare.py) follows the plan. Rows are compared as multisets, and order matters only when the gold answer is ordered. Column names are ignored, and columns may come in any order. Numbers match within 1% relative tolerance, strings are trimmed and lower-cased, and a midnight timestamp equals its date.

Because of those rules, questions follow some rules of their own:
- **Name the timestamp.** For example "orders purchased in 2017", because this data has five timestamps.
- **Name the output.** Say what to return ("each state with its number of sellers") and how to return time ("the month number, 1 to 12"). A correct answer in another format would otherwise be marked wrong.
- **No two same-typed values side by side.** Since column order is ignored, a swapped pair like "late average, on-time average" would wrongly match.
- **Top-n "which" questions compare as sets** (`order_matters: false`). Listing the right 5 states in another order is still right.

## Run it

Needs the Olist Postgres from [sql-agent](https://github.com/Zubariya-Suleka/sql-agent) (`just db up`, `just load` there).

```
git clone https://github.com/Zubariya-Suleka/sql-agent-evals
cd sql-agent-evals
cp .env.example .env
just setup
just build-gold     # re-run and re-verify every gold query
just test           # runs without a database, as in CI
```
