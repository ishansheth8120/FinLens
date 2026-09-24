"""The golden set is data, and data with no tests rots.

These are cheap and catch the failure that matters most: a case silently
dropping out of the run, which inflates every score in the report.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from finlens.agent.types import Route
from finlens.eval.golden import Difficulty, GoldenCase, filter_cases, load_golden_set

QUESTION_TYPES = {
    "single_fact": 15,
    "multi_period": 15,
    "cross_entity": 15,
    "narrative": 15,
    "hybrid": 10,
}


@pytest.fixture(scope="module")
def cases():
    return load_golden_set()


def test_golden_set_loads_and_validates(cases):
    assert len(cases) >= 70


def test_case_ids_are_unique(cases):
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(("tag", "expected"), QUESTION_TYPES.items())
def test_each_question_type_has_its_designed_count(cases, tag, expected):
    # The five-type split is the design; drifting away from it silently would
    # change what the headline numbers mean.
    actual = sum(1 for c in cases if tag in c.tags)
    assert actual == expected, f"{tag}: {actual} cases, expected {expected}"


def test_the_five_types_total_seventy(cases):
    typed = [c for c in cases if set(QUESTION_TYPES) & set(c.tags)]
    assert len(typed) == 70


def test_every_case_has_a_rubric(cases):
    # Without one the judge skips the case and only deterministic checks apply.
    missing = [c.id for c in cases if not c.rubric]
    assert not missing, f"cases with no rubric: {missing}"


def test_every_route_is_represented(cases):
    covered = {c.expected_route for c in cases}
    assert covered == set(Route), f"missing coverage for {set(Route) - covered}"


def test_adversarial_cases_exist(cases):
    assert len([c for c in cases if "adversarial" in c.tags]) >= 5


def test_the_period_traps_exist(cases):
    # Quarterly-vs-YTD and fiscal-year misalignment are the two failure modes
    # the report predicts will dominate. They must be measurable.
    assert any("period_trap" in c.tags for c in cases)
    assert any("fiscal_year" in c.tags for c in cases)


def test_the_false_premise_case_exists(cases):
    assert any("false_premise" in c.tags for c in cases)


def test_injection_cases_forbid_prompt_disclosure(cases):
    injection = [c for c in cases if "injection" in c.tags]
    assert injection
    assert any(c.must_not_mention for c in injection)


def test_most_cases_are_not_easy(cases):
    # An eval weighted to easy cases reports a high score and detects nothing.
    hard_enough = [c for c in cases if c.difficulty != Difficulty.EASY]
    assert len(hard_enough) / len(cases) > 0.7


def test_sql_cases_mostly_declare_expected_tables(cases):
    sql_cases = [c for c in cases if c.expected_route == Route.SQL and not c.should_refuse]
    with_tables = [c for c in sql_cases if c.expected_tables]
    assert len(with_tables) >= len(sql_cases) // 2


def test_narrative_cases_do_not_assert_figures(cases):
    # Figures in filing text are not extracted, so a numeric expectation on a
    # RAG case could never be checked. The model validator enforces this.
    for case in cases:
        if case.expected_route == Route.RAG:
            assert case.expected_value is None


# --- schema invariants -------------------------------------------------------


def test_should_refuse_requires_the_refuse_route():
    with pytest.raises(ValidationError):
        GoldenCase(id="bad", question="q", expected_route=Route.SQL, should_refuse=True)


def test_numeric_expectation_on_a_rag_case_is_rejected():
    with pytest.raises(ValidationError):
        GoldenCase(
            id="bad",
            question="q",
            expected_route=Route.RAG,
            expected_value={"value": 1.0},
        )


def test_route_acceptability_includes_the_alternatives():
    case = GoldenCase(
        id="x", question="q", expected_route=Route.RAG, acceptable_routes=[Route.HYBRID]
    )
    assert case.route_is_acceptable(Route.RAG)
    assert case.route_is_acceptable(Route.HYBRID)
    assert not case.route_is_acceptable(Route.SQL)


def test_numeric_tolerance_absorbs_a_restatement():
    from finlens.eval.golden import NumericExpectation

    expectation = NumericExpectation(value=383_285_000_000, tolerance_pct=0.01)
    assert expectation.matches(383_290_000_000)
    assert not expectation.matches(400_000_000_000)


def test_filter_cases(cases):
    assert all("narrative" in c.tags for c in filter_cases(cases, tags=["narrative"]))
    assert all(c.expected_route == Route.SQL for c in filter_cases(cases, routes=[Route.SQL]))
    assert len(filter_cases(cases, ids=[cases[0].id])) == 1
    assert all(
        c.difficulty == Difficulty.HARD for c in filter_cases(cases, difficulty=Difficulty.HARD)
    )
