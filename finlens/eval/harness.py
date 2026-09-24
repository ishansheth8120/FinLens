"""Running the golden set and writing a report.

Every run is persisted under `finlens/eval/runs/<timestamp>/` with the full
per-case detail, not just the summary. Two reasons: a regression is diagnosed by
diffing the *answers*, not the aggregate; and the report in `finlens/docs`
references specific run IDs, so the numbers in it stay traceable to the run that
produced them.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finlens.agent.orchestrator import Agent
from finlens.agent.types import Usage
from finlens.config import Settings, get_settings
from finlens.embed.providers import get_provider
from finlens.eval.golden import GoldenCase, load_golden_set
from finlens.eval.judge import judge_answer, normalise_score
from finlens.eval.metrics import CaseScore, aggregate, aggregate_by, score_case
from finlens.logging import get_logger

log = get_logger(__name__)

RUNS_DIR = Path(__file__).parent / "runs"


@dataclass
class EvalReport:
    run_id: str
    started_at: str
    settings_snapshot: dict[str, Any]
    scores: list[CaseScore] = field(default_factory=list)
    answers: dict[str, str] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    by_type: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_difficulty: dict[str, dict[str, Any]] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "elapsed_s": round(self.elapsed_s, 1),
            "settings": self.settings_snapshot,
            "caveats": self.caveats,
            "summary": self.summary,
            "by_type": self.by_type,
            "by_difficulty": self.by_difficulty,
            "cases": [asdict(s) for s in self.scores],
            "answers": self.answers,
        }

    def to_markdown(self) -> str:
        """A report that is readable in a PR comment."""
        lines = [
            f"# Eval run `{self.run_id}`",
            "",
            f"{self.summary.get('cases', 0)} cases | "
            f"{self.elapsed_s:.0f}s | "
            f"{self.summary.get('total_tokens', 0):,} tokens",
            "",
        ]

        if self.caveats:
            lines.append("> **Caveats**")
            lines.extend(f"> - {c}" for c in self.caveats)
            lines.append("")

        lines.extend(["| Metric | Value |", "| --- | --- |"])
        for key, value in self.summary.items():
            lines.append(f"| {key} | {_format_metric(value)} |")

        if self.by_type:
            lines.extend(
                [
                    "",
                    "## By question type",
                    "",
                    "| Type | Cases | Pass | Route acc. | Judge | Grounded |",
                    "| --- | ---: | ---: | ---: | ---: | ---: |",
                ]
            )
            for name, row in self.by_type.items():
                lines.append(
                    f"| {name} | {row['cases']} | {_format_metric(row['pass_rate'])} | "
                    f"{_format_metric(row['route_accuracy'])} | "
                    f"{_format_metric(row['judge_mean_score'])} | "
                    f"{_format_metric(row['verifier_groundedness'])} |"
                )

        failures = [s for s in self.scores if not s.passed]
        if failures:
            lines.extend(["", f"## Failures ({len(failures)})", ""])
            for score in failures:
                notes = "; ".join(score.notes) or score.error or "no detail"
                lines.append(f"- **{score.case_id}** (routed `{score.actual_route}`) - {notes}")

        return "\n".join(lines)


def _format_metric(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _settings_snapshot(settings: Settings) -> dict[str, Any]:
    """What the run was configured with. Numbers are meaningless without it."""
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.model_for(settings.llm_provider),
        "llm_fallbacks": settings.llm_fallback_providers,
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.embedding_model,
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_top_n": settings.rerank_top_n,
        "chunk_target_tokens": settings.chunk_target_tokens,
    }


def _caveats(settings: Settings) -> list[str]:
    """Conditions that make some of the numbers not mean what they look like."""
    caveats: list[str] = []

    try:
        provider = get_provider(settings)
        if not provider.is_semantic:
            caveats.append(
                f"Embedding provider is `{provider.name}`, a deterministic stand-in with no "
                "semantic meaning. Retrieval and RAG-path numbers in this run are not "
                "meaningful; set FINLENS_EMBEDDING_PROVIDER before reporting them."
            )
    except Exception as exc:  # noqa: BLE001
        caveats.append(f"Could not construct the embedding provider: {exc}")

    if not Path(settings.duckdb_path).exists():
        caveats.append(
            f"No warehouse at `{settings.duckdb_path}`. Every SQL-path case will fail for "
            "that reason rather than for a modelling reason."
        )

    index_path = Path(settings.vector_store_path) / "chunks.duckdb"
    if not index_path.exists():
        caveats.append(f"No vector index at `{index_path}`. RAG-path cases have nothing to search.")

    return caveats


def run_eval(
    cases: list[GoldenCase] | None = None,
    *,
    settings: Settings | None = None,
    with_judge: bool = True,
    save: bool = True,
) -> EvalReport:
    """Run the golden set end to end."""
    settings = settings or get_settings()
    cases = cases if cases is not None else load_golden_set()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = EvalReport(
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        settings_snapshot=_settings_snapshot(settings),
        caveats=_caveats(settings),
    )
    for caveat in report.caveats:
        log.warning("eval.caveat", detail=caveat)

    started = time.perf_counter()
    judge_usage = Usage()

    with Agent(settings) as agent:
        for i, case in enumerate(cases, start=1):
            log.info("eval.case", n=i, of=len(cases), case=case.id)
            try:
                answer = agent.ask(case.question)
            except Exception as exc:  # noqa: BLE001 - one bad case must not end the run
                log.error("eval.case_failed", case=case.id, error=str(exc))
                report.scores.append(CaseScore(case_id=case.id, error=str(exc)))
                continue

            score = score_case(case, answer)
            report.answers[case.id] = answer.answer

            if with_judge:
                judgement, usage = judge_answer(case, answer, settings=settings)
                judge_usage = judge_usage.add(usage)
                if judgement is not None:
                    score.judge_score = normalise_score(judgement)
                    score.judge_grounded = judgement.grounded
                    score.judge_reasoning = judgement.reasoning
                    if judgement.unsupported_claims:
                        score.notes.append(
                            f"unsupported: {'; '.join(judgement.unsupported_claims[:3])}"
                        )

            report.scores.append(score)

    report.elapsed_s = time.perf_counter() - started
    report.summary = aggregate(report.scores)
    report.by_type = aggregate_by(report.scores, "question_type")
    report.by_difficulty = aggregate_by(report.scores, "difficulty")
    report.summary["judge_tokens"] = judge_usage.input_tokens + judge_usage.output_tokens

    if save:
        save_report(report)

    log.info("eval.complete", run_id=run_id, **{k: v for k, v in report.summary.items() if v is not None})
    return report


def save_report(report: EvalReport, directory: Path | None = None) -> Path:
    """Persist the run. Returns the directory written."""
    target = Path(directory or RUNS_DIR) / report.run_id
    target.mkdir(parents=True, exist_ok=True)

    (target / "report.json").write_text(
        json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
    )
    (target / "report.md").write_text(report.to_markdown(), encoding="utf-8")

    log.info("eval.saved", path=str(target))
    return target


def load_report(run_id: str, directory: Path | None = None) -> dict[str, Any]:
    path = Path(directory or RUNS_DIR) / run_id / "report.json"
    return json.loads(path.read_text(encoding="utf-8"))


def compare_runs(baseline_id: str, candidate_id: str) -> dict[str, dict[str, Any]]:
    """Diff two runs' summaries.

    What a CI gate should read: a headline number moving by a point is noise, a
    case flipping from pass to fail is not.
    """
    baseline = load_report(baseline_id)
    candidate = load_report(candidate_id)

    diff: dict[str, dict[str, Any]] = {}
    for key, new_value in candidate["summary"].items():
        old_value = baseline["summary"].get(key)
        if isinstance(new_value, (int, float)) and isinstance(old_value, (int, float)):
            diff[key] = {
                "baseline": old_value,
                "candidate": new_value,
                "delta": new_value - old_value,
            }

    baseline_pass = {c["case_id"] for c in baseline["cases"] if _passed(c)}
    candidate_pass = {c["case_id"] for c in candidate["cases"] if _passed(c)}
    diff["_cases"] = {
        "regressed": sorted(baseline_pass - candidate_pass),
        "fixed": sorted(candidate_pass - baseline_pass),
    }
    return diff


def _passed(case: dict[str, Any]) -> bool:
    """Recompute `passed` from a serialised case, since it is a property."""
    checks = [
        case.get(k)
        for k in (
            "route_acceptable",
            "sql_executed",
            "sql_tables_correct",
            "sql_row_count_ok",
            "sql_value_correct",
            "mentions_ok",
            "refusal_correct",
        )
    ]
    applicable = [c for c in checks if c is not None]
    return bool(applicable) and all(applicable) and not case.get("error")
