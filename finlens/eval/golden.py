"""Loading and validating the golden set.

A case declares only what can be checked without re-deciding the answer by hand
every time the corpus updates. That is why numeric expectations carry a
tolerance and a metric/period rather than a literal figure where possible: a
hard-coded "$383.3B" goes stale the moment a company restates, and a stale
golden set is worse than no golden set, because it fails on correct behaviour
and trains you to ignore it.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from finlens.agent.types import Route

GOLDEN_DIR = Path(__file__).parent / "golden"


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class NumericExpectation(BaseModel):
    """An expected figure, with the tolerance that makes it durable."""

    value: float
    tolerance_pct: float = Field(
        default=0.01,
        description="Fractional tolerance. 0.01 allows 1% drift from restatements.",
    )
    unit: str | None = None

    def matches(self, actual: float) -> bool:
        if self.value == 0:
            return abs(actual) <= self.tolerance_pct
        return abs(actual - self.value) / abs(self.value) <= self.tolerance_pct


class GoldenCase(BaseModel):
    """One evaluation case."""

    id: str
    question: str
    difficulty: Difficulty = Difficulty.MEDIUM
    tags: list[str] = Field(default_factory=list)

    # --- routing -------------------------------------------------------------
    expected_route: Route
    acceptable_routes: list[Route] = Field(
        default_factory=list,
        description="Routes that are also defensible. Hybrid is usually acceptable "
        "for a single-store question - it costs more but is not wrong.",
    )

    # --- structured path -----------------------------------------------------
    expected_tables: list[str] = Field(
        default_factory=list, description="Tables the query should touch, unqualified"
    )
    expected_value: NumericExpectation | None = None
    expected_row_count: int | None = None
    min_row_count: int | None = None

    # --- retrieval path ------------------------------------------------------
    expected_ciks: list[str] = Field(default_factory=list)
    expected_items: list[str] = Field(default_factory=list)
    relevant_section_ids: list[str] = Field(
        default_factory=list, description="Known-relevant sections, for recall@k"
    )

    # --- answer --------------------------------------------------------------
    must_mention: list[str] = Field(
        default_factory=list, description="Substrings the answer must contain (case-insensitive)"
    )
    must_not_mention: list[str] = Field(default_factory=list)
    rubric: str | None = Field(
        default=None, description="What a correct answer needs, for the LLM judge"
    )
    should_refuse: bool = False

    @model_validator(mode="after")
    def _check_coherent(self) -> GoldenCase:
        if self.should_refuse and self.expected_route != Route.REFUSE:
            raise ValueError(f"{self.id}: should_refuse implies expected_route: refuse")
        if self.expected_value is not None and self.expected_route == Route.RAG:
            raise ValueError(
                f"{self.id}: a numeric expectation on a RAG case will not be checked - "
                "figures in filing text are not extracted"
            )
        return self

    def route_is_acceptable(self, actual: Route) -> bool:
        return actual == self.expected_route or actual in self.acceptable_routes


def load_golden_set(path: Path | str | None = None) -> list[GoldenCase]:
    """Load and validate the golden set.

    Raises on a malformed case rather than skipping it: a case that silently
    disappears from the run inflates every score.
    """
    path = Path(path) if path else GOLDEN_DIR / "golden_set.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no golden set at {path}")

    payload: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases", []) if isinstance(payload, dict) else payload

    cases = [GoldenCase(**case) for case in raw_cases]

    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids in golden set: {sorted(duplicates)}")

    return cases


def filter_cases(
    cases: list[GoldenCase],
    *,
    tags: list[str] | None = None,
    routes: list[Route] | None = None,
    difficulty: Difficulty | None = None,
    ids: list[str] | None = None,
) -> list[GoldenCase]:
    """Subset the golden set for a targeted run."""
    selected = cases
    if ids:
        selected = [c for c in selected if c.id in set(ids)]
    if tags:
        wanted = set(tags)
        selected = [c for c in selected if wanted & set(c.tags)]
    if routes:
        selected = [c for c in selected if c.expected_route in set(routes)]
    if difficulty:
        selected = [c for c in selected if c.difficulty == difficulty]
    return selected
