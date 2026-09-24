from __future__ import annotations

import pytest

from finlens.agent.router import extract_hints, heuristic_route
from finlens.agent.types import Route


@pytest.mark.parametrize(
    "question",
    [
        "Should I buy Apple stock?",
        "What will Nvidia's stock price be next year?",
        "Can you predict the stock price for Tesla?",
    ],
)
def test_advice_and_prediction_are_refused_without_a_model_call(question):
    decision = heuristic_route(question)
    assert decision is not None
    assert decision.route == Route.REFUSE
    assert decision.refusal_reason


@pytest.mark.parametrize(
    "question",
    [
        "What companies do you have data for?",
        "How many filings are in the corpus?",
    ],
)
def test_coverage_questions_route_to_metadata(question):
    decision = heuristic_route(question)
    assert decision is not None
    assert decision.route == Route.METADATA


@pytest.mark.parametrize(
    "question",
    [
        "What was Apple's revenue in 2023?",
        "What supply chain risks does Apple disclose?",
        "Why did Intel's margin fall?",
    ],
)
def test_ordinary_questions_fall_through_to_the_model(question):
    # The heuristic must stay high-precision; a wrong shortcut skips the very
    # model call that would have caught it.
    assert heuristic_route(question) is None


def test_years_are_extracted():
    hints = extract_hints("Compare 2021 and 2023 revenue")
    assert hints.fiscal_years == [2021, 2023]


def test_implausible_years_are_ignored():
    hints = extract_hints("Section 1250 of the code, and 3000 units")
    assert hints.fiscal_years == []


def test_tickers_are_extracted_but_common_acronyms_are_not():
    hints = extract_hints("Compare AAPL and MSFT under US GAAP per the SEC")
    assert "AAPL" in hints.tickers
    assert "MSFT" in hints.tickers
    assert "GAAP" not in hints.tickers
    assert "SEC" not in hints.tickers


def test_a_shouted_question_yields_no_tickers():
    # Otherwise every word in an all-caps question becomes a ticker and the
    # retrieval filter matches nothing.
    assert extract_hints("WHAT WAS THE REVENUE LAST YEAR") .tickers == []


@pytest.mark.parametrize(
    ("phrase", "item"),
    [
        ("risk factors", "1A"),
        ("MD&A", "7"),
        ("legal proceedings", "3"),
        ("cybersecurity", "1C"),
    ],
)
def test_section_phrases_map_to_item_numbers(phrase, item):
    hints = extract_hints(f"What does Apple say in its {phrase}?")
    assert item in hints.items
