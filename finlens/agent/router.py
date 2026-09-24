"""Deciding which retrieval path a question needs.

The router is one model call with a structured output. It is deliberately not a
tool-use loop: the decision is a classification with entity extraction, it has
to happen before anything else can start, and its latency lands on every single
request. One constrained call is the right shape.

A heuristic pre-pass handles the unambiguous cases without a model call at all.
It fires on maybe a fifth of real traffic and saves both the latency and the
tokens; anything it is not certain about falls through to the model.
"""

from __future__ import annotations

import re

from finlens.agent.llm import LlmClient, LlmError, get_llm
from finlens.agent.prompts import render
from finlens.agent.schema_catalog import metric_names
from finlens.agent.types import Entities, Route, RouteDecision, Usage
from finlens.config import Settings, get_settings
from finlens.logging import get_logger

log = get_logger(__name__)

# Phrases that make the route unambiguous. Kept short and high-precision: a
# heuristic that fires wrongly is worse than one that never fires, because the
# model call it skipped was the thing that would have caught the mistake.
_METADATA_PATTERNS = (
    r"\bwhat (companies|tickers|years|forms) (are|do you) (available|covered|have)\b",
    r"\bhow many (companies|filings|documents) (are|do you)\b",
    r"\bdo you have (data|filings|coverage) for\b",
    r"\bwhat('s| is) (in|covered by) (the|your) (index|corpus|warehouse)\b",
)

_REFUSE_PATTERNS = (
    r"\bshould i (buy|sell|invest|short)\b",
    r"\b(price target|stock price|share price) (for|of|prediction)\b",
    r"\b(will|is going to) (the stock|shares|it) (go|rise|fall|crash)\b",
    r"\b(predict|forecast) (the )?(stock|share|price)\b",
    # "what will X's stock price be next year" - the most common phrasing, and
    # the one the patterns above all miss because the verb is split.
    r"\bwhat will\b.{0,60}\b(stock|share) price\b",
    r"\b(stock|share) price\b.{0,20}\b(be|reach|hit|end up)\b",
)

_ITEM_HINTS: dict[str, str] = {
    "risk factor": "1A",
    "risk factors": "1A",
    "md&a": "7",
    "management's discussion": "7",
    "management discussion": "7",
    "legal proceeding": "3",
    "properties": "2",
    "cybersecurity": "1C",
    "controls and procedures": "9A",
}

_TICKER = re.compile(r"\b([A-Z]{1,5})\b")
_YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")


def heuristic_route(question: str) -> RouteDecision | None:
    """Return a decision for the unambiguous cases, else ``None``."""
    lowered = question.lower().strip()

    for pattern in _REFUSE_PATTERNS:
        if re.search(pattern, lowered):
            return RouteDecision(
                route=Route.REFUSE,
                reasoning="Asks for a prediction or investment advice, which filings cannot support.",
                confidence=0.9,
                refusal_reason=(
                    "FinLens answers questions about what companies have reported in their SEC "
                    "filings. It does not forecast prices or give investment advice."
                ),
            )

    for pattern in _METADATA_PATTERNS:
        if re.search(pattern, lowered):
            return RouteDecision(
                route=Route.METADATA,
                reasoning="Asks about corpus coverage rather than filing content.",
                confidence=0.85,
            )

    return None


def extract_hints(question: str) -> Entities:
    """Cheap entity extraction, merged into whatever the model finds.

    Regex catches things the model sometimes drops (a bare year, an all-caps
    ticker); the model catches everything regex cannot (company names, implied
    metrics). Neither alone is sufficient.
    """
    years = [int(y) for y in _YEAR.findall(question)]
    lowered = question.lower()
    items = sorted({item for phrase, item in _ITEM_HINTS.items() if phrase in lowered})

    # Only treat an all-caps token as a ticker if the question is not entirely
    # uppercase - otherwise every word in a shouted question is a "ticker".
    tickers: list[str] = []
    if question != question.upper():
        stopwords = {"SEC", "GAAP", "XBRL", "EDGAR", "CEO", "CFO", "USD", "AI", "US", "IT", "A", "I"}
        tickers = [t for t in _TICKER.findall(question) if t not in stopwords and len(t) >= 2]

    return Entities(tickers=tickers, fiscal_years=sorted(set(years)), items=items)


def _merge(model_entities: Entities, hints: Entities) -> Entities:
    """Union the two extractions, preferring the model's ordering."""

    def union(primary: list[str], secondary: list[str]) -> list[str]:
        seen = list(primary)
        seen.extend(v for v in secondary if v not in primary)
        return seen

    return Entities(
        tickers=union(model_entities.tickers, hints.tickers),
        company_names=model_entities.company_names,
        ciks=model_entities.ciks,
        metrics=model_entities.metrics,
        fiscal_years=sorted(set(model_entities.fiscal_years) | set(hints.fiscal_years)),
        forms=model_entities.forms,
        items=union(model_entities.items, hints.items),
    )


def route(
    question: str,
    *,
    llm: LlmClient | None = None,
    settings: Settings | None = None,
    use_heuristics: bool = True,
) -> tuple[RouteDecision, Usage]:
    """Classify a question and extract its entities."""
    settings = settings or get_settings()
    hints = extract_hints(question)

    if use_heuristics:
        shortcut = heuristic_route(question)
        if shortcut is not None:
            shortcut.entities = _merge(shortcut.entities, hints)
            log.info("router.heuristic", route=shortcut.route.value)
            return shortcut, Usage()

    llm = llm or get_llm(settings)
    system = render("router", metrics=", ".join(metric_names(settings)) or "(warehouse not built)")

    try:
        decision, usage = llm.parse(
            f"<question>\n{question}\n</question>",
            system=system,
            schema=RouteDecision,
            # Routing is a classification, not an analysis, and its latency lands
            # on every single request - so it gets a small token budget.
            max_tokens=2000,
        )
    except LlmError as exc:
        # Never fail a request on a routing error. Hybrid is the safe default -
        # it searches both stores, costs more, and answers the question.
        log.error("router.failed", error=str(exc))
        return (
            RouteDecision(
                route=Route.HYBRID,
                reasoning=f"Router unavailable ({exc}); searching both stores.",
                entities=hints,
                confidence=0.0,
            ),
            Usage(),
        )

    decision.entities = _merge(decision.entities, hints)
    log.info(
        "router.decided",
        route=decision.route.value,
        confidence=decision.confidence,
        tickers=decision.entities.tickers,
    )
    return decision, usage
