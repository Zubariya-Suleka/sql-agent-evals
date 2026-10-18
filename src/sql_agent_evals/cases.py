"""The golden set: one JSON object per line in data/golden.jsonl."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Status = Literal["answered", "cannot_answer", "needs_clarification"]

# Every case belongs to exactly one bucket (the plan's distribution: 25/35/25/15).
BUCKETS = ("single_table", "join", "aggregation", "ambiguous", "unanswerable")
SMOKE_TAG = "smoke"  # the 10 fixed cases of the smoke subset


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^q\d{3}$")
    question: str = Field(min_length=10)
    expected_status: Status
    gold_sql: str | None = None
    # A second query written independently, in a different way, that must return the same
    # rows: the check that the gold answer isn't one query's slip.
    check_sql: str | None = None
    tags: list[str]
    difficulty: Literal["easy", "medium", "hard"]
    # Interpretation decisions behind the gold answer, for anyone reviewing it.
    notes: str = ""
    # None: ordered exactly when gold_sql has a top-level ORDER BY. False: compare as a set
    # anyway, e.g. for "which 5 ..." when the gold sorts only to pick the top 5.
    order_matters: bool | None = None

    @property
    def bucket(self) -> str:
        return next(t for t in self.tags if t in BUCKETS)

    @model_validator(mode="after")
    def _consistent(self) -> "Case":
        if self.expected_status == "answered":
            if not (self.gold_sql and self.check_sql):
                raise ValueError("answered cases need gold_sql and check_sql")
        elif self.gold_sql or self.check_sql:
            raise ValueError("only answered cases have SQL")
        buckets = [t for t in self.tags if t in BUCKETS]
        if len(buckets) != 1:
            raise ValueError(f"tags need exactly one bucket of {BUCKETS}, got {buckets}")
        return self


def load_cases(path: Path) -> list[Case]:
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(Case.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"duplicate case id {case.id}")
        seen.add(case.id)
    return cases
