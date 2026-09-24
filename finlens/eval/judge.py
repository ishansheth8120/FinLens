"""LLM-as-judge for the checks a substring match cannot make.

Two things are graded, and keeping them separate is the point:

**Correctness** - does the answer satisfy the case's rubric?
**Groundedness** - is every factual claim supported by the evidence that was
actually retrieved?

An answer can be correct and ungrounded: the model knew Apple's revenue and
stated it, while the retrieved evidence said nothing. That is the failure this
whole system is built to prevent, and it is invisible to a correctness score
alone, because the answer is *right*.

The judge sees the evidence and the answer, never the rubric's expected values
alongside a hint about which way to grade, and it grades before it scores.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from finlens.agent.llm import LlmClient, LlmError, get_llm
from finlens.agent.types import Answer, Usage
from finlens.config import Settings, get_settings
from finlens.eval.golden import GoldenCase
from finlens.logging import get_logger

log = get_logger(__name__)

JUDGE_SYSTEM = """\
You grade answers produced by a question-answering system over SEC EDGAR filings.

You are given the question, the evidence the system retrieved, the answer it
produced, and a rubric describing what a correct answer needs.

Grade two things independently.

**Correctness (0-5)** - how well the answer satisfies the rubric.
  5 - fully satisfies it, with the right figures, period and framing
  4 - correct, with a minor omission or an imprecision that does not mislead
  3 - substantially correct but incomplete, or hedged where it should be direct
  2 - partially correct; a material part is wrong or missing
  1 - largely wrong, though it addresses the question
  0 - wrong, or does not address the question

**Grounded (true/false)** - whether every factual claim in the answer is
supported by the evidence shown. Judge this on the evidence alone. If the answer
states a figure or a fact that does not appear in the evidence, it is not
grounded, *even if you know it is true* - an unsupported correct claim is the
specific failure being tested for, and marking it grounded defeats the measure.

Arithmetic performed on figures that are present is grounded. Restating the
company's own characterisation, attributed as such, is grounded. Filling a gap
with outside knowledge is not.

An answer that correctly says the evidence is insufficient scores well on both:
high correctness if declining was the right call under the rubric, and grounded,
because it claimed nothing.

Be a hard marker. Inflated scores make the eval useless for detecting
regressions, which is the only thing it is for.
"""


class Judgement(BaseModel):
    correctness: int = Field(ge=0, le=5)
    grounded: bool
    reasoning: str = Field(description="Two or three sentences on the grade")
    unsupported_claims: list[str] = Field(
        default_factory=list,
        description="Claims in the answer with no support in the evidence",
    )


def _evidence_text(answer: Answer) -> str:
    parts: list[str] = []

    if answer.sql_result is not None:
        if answer.sql_result.ok:
            parts.append(
                f"WAREHOUSE QUERY RESULT\n"
                f"SQL: {answer.sql_result.sql}\n\n"
                f"{answer.sql_result.to_markdown(max_rows=20)}"
            )
        else:
            parts.append(f"WAREHOUSE QUERY FAILED: {answer.sql_result.error}")

    if answer.retrieval is not None and answer.retrieval.contexts:
        parts.append("FILING EXCERPTS\n\n" + "\n\n".join(answer.retrieval.contexts))

    return "\n\n---\n\n".join(parts) if parts else "(no evidence was retrieved)"


def judge_answer(
    case: GoldenCase,
    answer: Answer,
    *,
    llm: LlmClient | None = None,
    settings: Settings | None = None,
) -> tuple[Judgement | None, Usage]:
    """Grade one answer. Returns ``None`` when the case has no rubric."""
    if not case.rubric:
        return None, Usage()

    settings = settings or get_settings()
    # The judge runs on the same provider chain as the answerer. A weaker judge
    # caps the ceiling of every number the eval reports, and does so invisibly.
    llm = llm or get_llm(settings)

    prompt = (
        f"<question>\n{case.question}\n</question>\n\n"
        f"<rubric>\n{case.rubric.strip()}\n</rubric>\n\n"
        f"<evidence>\n{_evidence_text(answer)}\n</evidence>\n\n"
        f"<answer>\n{answer.answer}\n</answer>"
    )

    try:
        judgement, usage = llm.parse(
            prompt,
            system=JUDGE_SYSTEM,
            schema=Judgement,
            max_tokens=2000,
        )
    except LlmError as exc:
        log.error("judge.failed", case=case.id, error=str(exc))
        return None, Usage()

    log.info(
        "judge.graded",
        case=case.id,
        correctness=judgement.correctness,
        grounded=judgement.grounded,
    )
    return judgement, usage


def normalise_score(judgement: Judgement) -> float:
    """Map 0-5 onto 0-1 so it aggregates alongside the pass rates."""
    return judgement.correctness / 5.0
