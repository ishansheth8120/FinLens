"""Deterministic scoring.

Everything here is computable without a model. That matters: these are the
numbers that stay comparable across runs and across prompt changes, because
nothing about them can drift. The judge in `judge.py` handles what genuinely
needs reading, and its scores are reported separately for exactly that reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from finlens.agent.sql_guard import referenced_tables
from finlens.agent.types import Answer, Route
from finlens.eval.golden import GoldenCase


@dataclass
class CaseScore:
    """Per-case outcome. Every field is None when the case does not test it."""

    case_id: str
    route_correct: bool | None = None
    route_acceptable: bool | None = None
    actual_route: str = ""

    sql_executed: bool | None = None
    sql_tables_correct: bool | None = None
    sql_row_count_ok: bool | None = None
    sql_value_correct: bool | None = None

    retrieval_recall_at_k: float | None = None
    retrieval_company_precision: float | None = None
    retrieval_item_hit: bool | None = None

    mentions_ok: bool | None = None
    refusal_correct: bool | None = None

    # Deterministic groundedness, from the numeric verifier. Distinct from the
    # judge's opinion of groundedness: this one is arithmetic, not a grade.
    claims_asserted: int = 0
    claims_reconciled: int = 0
    claims_failed: int = 0
    verifier_groundedness: float | None = None

    judge_score: float | None = None
    judge_grounded: bool | None = None
    judge_reasoning: str | None = None

    question_type: str = ""
    difficulty: str = ""

    error: str | None = None
    elapsed_ms: float = 0.0
    tokens: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Overall pass: every check the case actually specified must hold.

        Deliberately strict. A case that routes correctly but returns the wrong
        number has not passed, and averaging the sub-scores into a partial
        credit would hide that.
        """
        checks = [
            self.route_acceptable,
            self.sql_executed,
            self.sql_tables_correct,
            self.sql_row_count_ok,
            self.sql_value_correct,
            self.mentions_ok,
            self.refusal_correct,
            # An answer containing a figure that did not reconcile has not
            # passed, however well it routed.
            None if self.claims_asserted == 0 else self.claims_failed == 0,
        ]
        applicable = [c for c in checks if c is not None]
        return bool(applicable) and all(applicable) and self.error is None


def score_routing(case: GoldenCase, answer: Answer) -> tuple[bool, bool]:
    """(exact match, acceptable) for the route."""
    return answer.route == case.expected_route, case.route_is_acceptable(answer.route)


def score_sql(case: GoldenCase, answer: Answer, score: CaseScore) -> None:
    """Fill in the SQL-path checks, in place."""
    if answer.sql_result is None:
        # Only a failure if the case expected the SQL path to run at all.
        if case.expected_route in (Route.SQL, Route.HYBRID) and case.expected_tables:
            score.sql_executed = False
            score.notes.append("no SQL was generated")
        return

    score.sql_executed = answer.sql_result.ok
    if not answer.sql_result.ok:
        score.notes.append(f"sql error: {answer.sql_result.error}")
        return

    if case.expected_tables:
        used = referenced_tables(answer.sql_result.sql)
        # Match on the bare table name: the query may qualify with a schema and
        # the case should not have to know which.
        bare = {t.split(".")[-1] for t in used}
        score.sql_tables_correct = bool(bare & set(case.expected_tables))
        if not score.sql_tables_correct:
            score.notes.append(
                f"used {sorted(bare)}, expected one of {case.expected_tables}"
            )

    if case.expected_row_count is not None:
        score.sql_row_count_ok = answer.sql_result.row_count == case.expected_row_count
    elif case.min_row_count is not None:
        score.sql_row_count_ok = answer.sql_result.row_count >= case.min_row_count
        if not score.sql_row_count_ok:
            score.notes.append(
                f"{answer.sql_result.row_count} rows, expected at least {case.min_row_count}"
            )

    if case.expected_value is not None:
        score.sql_value_correct = _first_numeric_matches(answer, case)


def _first_numeric_matches(answer: Answer, case: GoldenCase) -> bool:
    """Check the expected figure against the first numeric cell returned.

    A blunt check, and knowingly so: a stricter one would need the case to
    declare which column and row hold the answer, which makes cases brittle
    against a query that is correct but shaped differently.
    """
    assert case.expected_value is not None
    result = answer.sql_result
    if result is None or not result.rows:
        return False

    for row in result.rows:
        for cell in row:
            if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                if case.expected_value.matches(float(cell)):
                    return True
    return False


def score_retrieval(case: GoldenCase, answer: Answer, score: CaseScore) -> None:
    """Fill in the retrieval checks, in place."""
    if answer.retrieval is None:
        return

    citations = answer.retrieval.citations

    if case.relevant_section_ids:
        retrieved = {c.section_id for c in citations if c.section_id}
        relevant = set(case.relevant_section_ids)
        score.retrieval_recall_at_k = len(retrieved & relevant) / len(relevant)

    # Company precision: what share of retrieved chunks are from a company the
    # question is actually about. The dominant retrieval failure on this corpus
    # is returning a competitor's near-identical risk factor, and this catches it.
    if case.expected_ciks:
        labels = [c.label or "" for c in citations]
        if labels:
            expected = set(case.expected_ciks)
            hits = sum(1 for label in labels if any(cik in label for cik in expected))
            score.retrieval_company_precision = hits / len(labels)

    if case.expected_items:
        # `item` is not on the Citation, so this reads the label, which carries
        # "Item 1A" by construction in `fct_filing_section.citation_label`.
        wanted = {f"Item {i}" for i in case.expected_items}
        score.retrieval_item_hit = any(
            any(w in (c.label or "") for w in wanted) for c in citations
        )


def score_mentions(case: GoldenCase, answer: Answer) -> bool | None:
    """Case-insensitive substring checks on the answer text."""
    if not case.must_mention and not case.must_not_mention:
        return None

    lowered = answer.answer.lower()
    required = all(m.lower() in lowered for m in case.must_mention)
    forbidden = any(m.lower() in lowered for m in case.must_not_mention)
    return required and not forbidden


def score_refusal(case: GoldenCase, answer: Answer) -> bool | None:
    if not case.should_refuse:
        return None
    return answer.route == Route.REFUSE


def score_case(case: GoldenCase, answer: Answer) -> CaseScore:
    """Run every deterministic check that applies to this case."""
    exact, acceptable = score_routing(case, answer)
    score = CaseScore(
        case_id=case.id,
        route_correct=exact,
        route_acceptable=acceptable,
        actual_route=answer.route.value,
        elapsed_ms=answer.elapsed_ms,
        tokens=answer.usage.input_tokens + answer.usage.output_tokens,
    )

    if not acceptable:
        score.notes.append(f"routed to {answer.route.value}, expected {case.expected_route.value}")

    score_sql(case, answer, score)
    score_retrieval(case, answer, score)
    score.mentions_ok = score_mentions(case, answer)
    score.refusal_correct = score_refusal(case, answer)
    score_verification(answer, score)

    score.question_type = question_type_of(case)
    score.difficulty = case.difficulty.value

    return score


QUESTION_TYPES = ("single_fact", "multi_period", "cross_entity", "narrative", "hybrid")


def question_type_of(case: GoldenCase) -> str:
    """Which of the five designed types this case belongs to.

    Cases outside the five (metadata, refusal, pure adversarial) are grouped as
    `other` so they still appear in the breakdown rather than vanishing.
    """
    for question_type in QUESTION_TYPES:
        if question_type in case.tags:
            return question_type
    return "other"


def score_verification(answer: Answer, score: CaseScore) -> None:
    """Carry the numeric verifier's outcome onto the score."""
    report = answer.verification
    if report is None:
        return

    score.claims_asserted = len(report.verifications)
    score.claims_reconciled = report.reconciled
    score.claims_failed = report.failed
    score.verifier_groundedness = report.groundedness

    if report.has_failures:
        score.notes.append(
            "unreconciled figures: "
            + "; ".join(f"{v.claim.value:,.4g} ({v.verdict.value})" for v in report.failures()[:3])
        )


# -- aggregation --------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def aggregate(scores: list[CaseScore]) -> dict[str, float | int | None]:
    """Roll per-case scores into the headline numbers."""

    def rate(attribute: str) -> float | None:
        values = [
            1.0 if getattr(s, attribute) else 0.0
            for s in scores
            if getattr(s, attribute) is not None
        ]
        return _mean(values)

    return {
        "cases": len(scores),
        "pass_rate": _mean([1.0 if s.passed else 0.0 for s in scores]),
        "route_accuracy": rate("route_correct"),
        "route_acceptable_rate": rate("route_acceptable"),
        "sql_execution_rate": rate("sql_executed"),
        "sql_table_accuracy": rate("sql_tables_correct"),
        "sql_row_count_accuracy": rate("sql_row_count_ok"),
        "sql_value_accuracy": rate("sql_value_correct"),
        "retrieval_recall_at_k": _mean(
            [s.retrieval_recall_at_k for s in scores if s.retrieval_recall_at_k is not None]
        ),
        "retrieval_company_precision": _mean(
            [
                s.retrieval_company_precision
                for s in scores
                if s.retrieval_company_precision is not None
            ]
        ),
        "retrieval_item_hit_rate": rate("retrieval_item_hit"),
        "mention_accuracy": rate("mentions_ok"),
        "refusal_accuracy": rate("refusal_correct"),
        # The headline groundedness number: share of asserted figures that
        # reconcile against the rows they claim to come from. Arithmetic, not
        # a model's opinion.
        "verifier_groundedness": (
            sum(s.claims_reconciled for s in scores) / total_claims
            if (total_claims := sum(s.claims_asserted for s in scores))
            else None
        ),
        "claims_asserted": sum(s.claims_asserted for s in scores),
        "claims_failed": sum(s.claims_failed for s in scores),
        "answers_with_unverified_figures": sum(1 for s in scores if s.claims_failed > 0),
        "judge_mean_score": _mean([s.judge_score for s in scores if s.judge_score is not None]),
        "judge_grounded_rate": rate("judge_grounded"),
        "errors": sum(1 for s in scores if s.error),
        "mean_latency_ms": _mean([s.elapsed_ms for s in scores]),
        "p95_latency_ms": _percentile([s.elapsed_ms for s in scores], 0.95),
        "total_tokens": sum(s.tokens for s in scores),
    }


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[index]


def aggregate_by(scores: list[CaseScore], attribute: str) -> dict[str, dict[str, Any]]:
    """Break the headline numbers down by question type or difficulty.

    The whole point of the five-type split: a single pass rate hides that
    multi-period comparisons fail three times as often as single facts, and
    that difference is what tells you where to spend the next week.
    """
    groups: dict[str, list[CaseScore]] = {}
    for score in scores:
        groups.setdefault(getattr(score, attribute) or "unknown", []).append(score)

    return {
        name: {
            "cases": len(group),
            "pass_rate": _mean([1.0 if s.passed else 0.0 for s in group]),
            "route_accuracy": _mean(
                [1.0 if s.route_correct else 0.0 for s in group if s.route_correct is not None]
            ),
            "judge_mean_score": _mean(
                [s.judge_score for s in group if s.judge_score is not None]
            ),
            "verifier_groundedness": (
                sum(s.claims_reconciled for s in group) / claims
                if (claims := sum(s.claims_asserted for s in group))
                else None
            ),
            "mean_latency_ms": _mean([s.elapsed_ms for s in group]),
        }
        for name, group in sorted(groups.items())
    }
