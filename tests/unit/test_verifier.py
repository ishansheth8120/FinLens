"""The verifier is the project's central claim, so it is tested hardest.

Two directions matter equally:
  - it must not reject correct restatements (false positives make it unusable)
  - it must not accept a fabricated figure (false negatives make it pointless)
"""

from __future__ import annotations

import pytest

from finlens.agent.types import ClaimVerdict, NumericClaim, SqlResult
from finlens.agent.verifier import redact_failures, verify, verify_claim


def result(columns: list[str], rows: list[list]) -> SqlResult:
    return SqlResult(sql="SELECT 1", columns=columns, rows=rows, row_count=len(rows))


def claim(value: float, text: str = "the figure", **kwargs) -> NumericClaim:
    return NumericClaim(text=text, value=value, **kwargs)


# --- direct matches ----------------------------------------------------------


def test_exact_value_reconciles():
    rows = result(["revenue"], [[383285000000.0]])
    assert verify_claim(claim(383285000000.0), rows).verdict == ClaimVerdict.RECONCILED


def test_rounded_restatement_reconciles():
    # "$383.3 billion" for 383,285,000,000 is correct, not an error.
    rows = result(["revenue"], [[383285000000.0]])
    assert verify_claim(claim(383.3e9), rows).verdict == ClaimVerdict.RECONCILED


def test_scaled_restatement_reconciles():
    # The model reporting billions when the column is in dollars.
    rows = result(["revenue"], [[383285000000.0]])
    assert verify_claim(claim(383.285), rows).verdict == ClaimVerdict.RECONCILED


def test_fraction_stated_as_percent_reconciles():
    # gross_margin 0.441 reported as "44.1%".
    rows = result(["gross_margin"], [[0.441]])
    assert verify_claim(claim(44.1), rows).verdict == ClaimVerdict.RECONCILED


def test_percent_stated_as_fraction_reconciles():
    rows = result(["growth_pct"], [[15.2]])
    assert verify_claim(claim(0.152), rows).verdict == ClaimVerdict.RECONCILED


def test_a_value_in_any_row_or_column_counts():
    rows = result(
        ["ticker", "year", "revenue"],
        [["AAPL", 2023, 383285.0], ["MSFT", 2023, 211915.0]],
    )
    assert verify_claim(claim(211915.0), rows).verdict == ClaimVerdict.RECONCILED


# --- derived matches ---------------------------------------------------------


def test_difference_between_two_values_reconciles():
    rows = result(["y2022", "y2023"], [[394328.0, 383285.0]])
    verification = verify_claim(claim(-11043.0, "revenue fell by $11.0B"), rows)
    assert verification.verdict == ClaimVerdict.RECONCILED
    assert "-" in verification.detail or "derived" in verification.detail


def test_percent_change_reconciles():
    # (383285 - 394328) / 394328 = -2.80%
    rows = result(["y2022", "y2023"], [[394328.0, 383285.0]])
    verification = verify_claim(claim(-2.8, "revenue declined 2.8%"), rows)
    assert verification.verdict == ClaimVerdict.RECONCILED
    assert "derived" in verification.detail


def test_ratio_reconciles():
    # gross_profit / revenue = 169148 / 383285 = 0.4413
    rows = result(["revenue", "gross_profit"], [[383285.0, 169148.0]])
    verification = verify_claim(claim(44.13, "a gross margin of 44.1%"), rows)
    assert verification.verdict == ClaimVerdict.RECONCILED


# --- the failures that matter ------------------------------------------------


def test_a_fabricated_figure_is_unsupported():
    # The number the model "knows" but that is nowhere in the data.
    rows = result(["revenue"], [[383285.0]])
    verification = verify_claim(claim(99999999.0, "revenue was $100B"), rows)
    assert verification.verdict == ClaimVerdict.UNSUPPORTED
    assert verification.is_failure


def test_a_transposed_digit_is_a_mismatch():
    # 383285 -> 383825. Close enough to be a computation slip, not a fabrication.
    rows = result(["revenue"], [[383285.0]])
    verification = verify_claim(claim(383825.0), rows)
    assert verification.verdict == ClaimVerdict.MISMATCH
    assert verification.matched_value == 383285.0
    assert verification.is_failure


def test_a_wrong_growth_rate_is_caught():
    rows = result(["y2022", "y2023"], [[394328.0, 383285.0]])
    # The real change is -2.8%; claiming +15% must not pass.
    assert verify_claim(claim(15.0, "grew 15%"), rows).is_failure


def test_booleans_are_not_treated_as_numbers():
    # `has_financial_data = True` must not verify a claim of "1".
    rows = result(["has_financial_data"], [[True]])
    assert verify_claim(claim(1.0), rows).verdict == ClaimVerdict.UNCHECKABLE


def test_nulls_are_ignored():
    rows = result(["revenue"], [[None], [383285.0]])
    assert verify_claim(claim(383285.0), rows).verdict == ClaimVerdict.RECONCILED


# --- uncheckable -------------------------------------------------------------


@pytest.mark.parametrize(
    "sql_result",
    [
        None,
        SqlResult(sql="x", error="boom"),
        SqlResult(sql="x", columns=["a"], rows=[]),
    ],
)
def test_no_result_set_is_uncheckable_not_a_failure(sql_result):
    # A pure-RAG answer has no rows. That is not a verification failure, and
    # scoring it as one would make every narrative answer look ungrounded.
    verification = verify_claim(claim(1.0), sql_result)
    assert verification.verdict == ClaimVerdict.UNCHECKABLE
    assert not verification.is_failure


def test_text_only_results_are_uncheckable():
    rows = result(["company_name"], [["Apple Inc."]])
    assert verify_claim(claim(5.0), rows).verdict == ClaimVerdict.UNCHECKABLE


# --- report ------------------------------------------------------------------


def test_report_counts_and_groundedness():
    rows = result(["revenue"], [[100.0]])
    report = verify(
        [claim(100.0, "a"), claim(100.0, "b"), claim(50000.0, "c")],
        rows,
    )
    assert report.checked == 3
    assert report.reconciled == 2
    assert report.failed == 1
    assert report.groundedness == pytest.approx(2 / 3)
    assert report.has_failures


def test_groundedness_is_none_when_nothing_was_checkable():
    report = verify([claim(1.0)], None)
    assert report.checked == 0
    assert report.groundedness is None
    assert not report.has_failures


def test_no_claims_is_a_clean_report():
    report = verify([], result(["a"], [[1.0]]))
    assert report.checked == 0
    assert not report.has_failures


# --- redaction ---------------------------------------------------------------


def test_redaction_replaces_only_the_failing_clause():
    rows = result(["revenue"], [[100.0]])
    commentary = "Revenue was 100 million. Net income was 42 million."
    report = verify(
        [
            claim(100.0, "Revenue was 100 million"),
            claim(42.0, "Net income was 42 million"),
        ],
        rows,
    )
    edited, warnings = redact_failures(commentary, report)

    assert "Revenue was 100 million" in edited
    assert "Net income was 42 million" not in edited
    assert "figure withheld" in edited
    assert len(warnings) == 1


def test_redaction_is_a_no_op_when_everything_reconciles():
    rows = result(["revenue"], [[100.0]])
    commentary = "Revenue was 100 million."
    report = verify([claim(100.0, "Revenue was 100 million")], rows)

    edited, warnings = redact_failures(commentary, report)
    assert edited == commentary
    assert warnings == []
