"""Wiring the stages into one answer.

    principal -> route -> (scoped sql | scoped rag) -> synthesize -> verify -> audit

The orchestrator owns the decisions no individual stage can make:

* **Access scope.** Every query is rewritten to the principal's permitted
  entities before execution, and every retrieval is filtered to them. This
  happens here, once, rather than in each leg — a control applied in two places
  is a control with two places to forget it.
* **What a low-confidence route means.** Below a threshold the router's answer
  is not trustworthy enough to commit to one store, so both run.
* **Concurrency.** For `hybrid` the two legs are independent, so the wall clock
  is one leg rather than two.
* **Failure.** A failed SQL leg on a hybrid question should still answer from
  filing text, with a warning, rather than failing the request.
* **The audit record.** Written once, at the end, with everything that happened.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from finlens.agent import rag as rag_module
from finlens.agent import sql_gen
from finlens.agent.executor import SqlExecutor
from finlens.agent.llm import LlmClient, get_llm
from finlens.agent.router import route as route_question
from finlens.agent.sql_guard import referenced_tables
from finlens.agent.synthesis import synthesize
from finlens.agent.types import (
    Answer,
    Entities,
    RetrievalResult,
    Route,
    RouteDecision,
    SqlResult,
    Usage,
)
from finlens.config import Settings, get_settings
from finlens.governance.access import AccessPolicy, Principal, scope_sql
from finlens.governance.audit import AuditLog, AuditRecord, hash_rows, new_request_id, utcnow
from finlens.logging import get_logger

log = get_logger(__name__)

# Below this the router is guessing. Widening to both stores costs one extra
# retrieval and one extra generation; answering from the wrong store costs the
# answer.
CONFIDENCE_FLOOR = 0.5


class Agent:
    """Holds the expensive, reusable handles: LLM chain, executor, audit log.

    Constructed once per process. Building a `SqlExecutor` per request reopens
    the DuckDB file each time, which dominates latency on short questions.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm: LlmClient | None = None,
        audit: AuditLog | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or get_llm(self.settings)
        self._executor: SqlExecutor | None = None
        self._audit = audit
        self._owns_audit = audit is None

    @property
    def executor(self) -> SqlExecutor:
        if self._executor is None:
            self._executor = SqlExecutor(self.settings)
        return self._executor

    @property
    def audit(self) -> AuditLog:
        if self._audit is None:
            self._audit = AuditLog(settings=self.settings)
        return self._audit

    def close(self) -> None:
        if self._executor is not None:
            self._executor.close()
            self._executor = None
        if self._audit is not None and self._owns_audit:
            self._audit.close()
            self._audit = None

    def __enter__(self) -> Agent:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- legs -----------------------------------------------------------------

    def _run_sql(
        self, question: str, entities: Entities, policy: AccessPolicy
    ) -> tuple[SqlResult, Usage, str | None]:
        """Generate, scope, execute. Returns the result, usage and raw SQL.

        The unscoped SQL is returned separately so the audit record can show
        both what the model wrote and what actually ran — the diff between them
        *is* the access control, and it should be inspectable.
        """
        try:
            result, usage = sql_gen.answer_with_sql(
                question,
                entities=entities,
                llm=self.llm,
                executor=self.executor,
                settings=self.settings,
                scope=lambda sql: scope_sql(sql, policy),
            )
            return result, usage, result.generated_sql
        except FileNotFoundError as exc:
            # No warehouse built yet. A real, actionable deployment state rather
            # than a bug, so it comes back as a result.
            return SqlResult(sql="", error=str(exc)), Usage(), None

    def _run_rag(
        self, question: str, entities: Entities, policy: AccessPolicy
    ) -> RetrievalResult:
        try:
            return rag_module.retrieve(
                question,
                entities=entities,
                settings=self.settings,
                permitted_ciks=policy.retrieval_ciks(entities.ciks or None),
            )
        except Exception as exc:  # noqa: BLE001 - index may be absent or corrupt
            log.error("agent.rag_failed", error=str(exc))
            return RetrievalResult(query=question)

    def _metadata_answer(
        self, question: str, decision: RouteDecision, policy: AccessPolicy
    ) -> Answer:
        """Answer coverage questions straight from the warehouse.

        No model call for the SQL: the question space is small and fixed, so a
        written query is more reliable and much faster than a generated one.
        It is still scoped — coverage is itself information about which
        companies exist.
        """
        sql = scope_sql(
            """
            SELECT
                count(*)                                    AS companies,
                count(*) FILTER (WHERE has_financial_data)  AS with_financials,
                min(first_fact_year)                        AS earliest_year,
                max(latest_fact_year)                       AS latest_year,
                sum(filing_count)                           AS filings
            FROM marts.dim_company
            """,
            policy,
        )
        result = self.executor.execute(sql, explanation="Corpus coverage summary")
        return synthesize(
            question,
            route=Route.METADATA,
            sql_result=result,
            reasoning=decision.reasoning,
            llm=self.llm,
            settings=self.settings,
        )

    # -- entry point ----------------------------------------------------------

    def ask(
        self,
        question: str,
        *,
        principal: Principal | None = None,
        force_route: Route | None = None,
        write_audit: bool = True,
    ) -> Answer:
        """Answer one question end to end, within the principal's scope."""
        started = time.perf_counter()
        request_id = new_request_id()
        question = question.strip()

        # Default to unrestricted: a single-tenant deployment should not have to
        # configure entitlements to work. The API always passes a real principal.
        principal = principal or Principal.admin()
        policy = AccessPolicy(principal=principal)

        if not question:
            return Answer(
                question=question,
                answer="Ask me something.",
                route=Route.REFUSE,
                request_id=request_id,
            )

        decision, usage = route_question(question, llm=self.llm, settings=self.settings)
        if force_route is not None:
            decision.route = force_route
            decision.reasoning = f"Route forced to {force_route.value} by the caller."

        route = decision.route
        warnings: list[str] = []
        sql_result: SqlResult | None = None
        retrieval: RetrievalResult | None = None
        raw_sql: str | None = None

        if route == Route.REFUSE:
            answer = Answer(
                question=question,
                answer=decision.refusal_reason
                or (
                    "I answer questions about what companies have reported in their SEC "
                    "filings. This question falls outside that."
                ),
                route=route,
                reasoning=decision.reasoning,
                usage=usage,
            )
        elif route == Route.METADATA:
            answer = self._metadata_answer(question, decision, policy)
            answer.usage = usage.add(answer.usage)
        else:
            # A low-confidence single-store route is upgraded to both stores.
            if route in (Route.SQL, Route.RAG) and decision.confidence < CONFIDENCE_FLOOR:
                log.info(
                    "agent.widening_route", original=route.value, confidence=decision.confidence
                )
                warnings.append(
                    f"The question was ambiguous (routing confidence "
                    f"{decision.confidence:.0%}); both stores were searched."
                )
                route = Route.HYBRID

            if route == Route.HYBRID:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    sql_future = pool.submit(self._run_sql, question, decision.entities, policy)
                    rag_future = pool.submit(self._run_rag, question, decision.entities, policy)
                    sql_result, sql_usage, raw_sql = sql_future.result()
                    retrieval = rag_future.result()
                usage = usage.add(sql_usage)

            elif route == Route.SQL:
                sql_result, sql_usage, raw_sql = self._run_sql(
                    question, decision.entities, policy
                )
                usage = usage.add(sql_usage)
                # A SQL question whose query returned nothing is often still
                # answerable from filing text, and falling back beats a wrong no.
                if not sql_result.ok or not sql_result.rows:
                    log.info("agent.sql_fallback_to_rag")
                    warnings.append(
                        "The warehouse query returned nothing, so filing text was searched."
                    )
                    retrieval = self._run_rag(question, decision.entities, policy)

            else:
                retrieval = self._run_rag(question, decision.entities, policy)

            answer = synthesize(
                question,
                route=route,
                sql_result=sql_result,
                retrieval=retrieval,
                reasoning=decision.reasoning,
                warnings=warnings,
                llm=self.llm,
                settings=self.settings,
            )
            answer.usage = usage.add(answer.usage)

        answer.request_id = request_id
        answer.elapsed_ms = (time.perf_counter() - started) * 1000

        if not principal.unrestricted:
            answer.warnings.append(
                f"Answered within your entitlements ({principal.scope_description()})."
            )

        if write_audit:
            self._write_audit(request_id, question, principal, decision, answer, raw_sql)

        log.info(
            "agent.answered",
            request_id=request_id,
            user=principal.user_id,
            route=answer.route.value,
            citations=len(answer.citations),
            claims=len(answer.numeric_claims),
            unverified=answer.verification.failed if answer.verification else 0,
            elapsed_ms=round(answer.elapsed_ms, 1),
        )
        return answer

    def _write_audit(
        self,
        request_id: str,
        question: str,
        principal: Principal,
        decision: RouteDecision,
        answer: Answer,
        raw_sql: str | None,
    ) -> None:
        from finlens.agent.verifier import summarise

        report = answer.verification
        sql_result = answer.sql_result

        record = AuditRecord(
            request_id=request_id,
            ts=utcnow(),
            user_id=principal.user_id,
            user_role=principal.role.value,
            permitted_cik_count=(
                None if principal.unrestricted else len(principal.permitted_ciks)
            ),
            question=question,
            route=answer.route.value,
            route_confidence=decision.confidence,
            generated_sql=raw_sql,
            scoped_sql=sql_result.sql if sql_result else None,
            sql_tables=sorted(referenced_tables(sql_result.sql)) if sql_result else [],
            sql_error=sql_result.error if sql_result else None,
            row_count=sql_result.row_count if sql_result else None,
            result_hash=hash_rows(sql_result.rows) if sql_result and sql_result.ok else None,
            chunk_ids=[c.chunk_id for c in answer.citations if c.chunk_id],
            answer=answer.answer,
            numeric_claims=len(answer.numeric_claims),
            claims_reconciled=report.reconciled if report else 0,
            claims_failed=report.failed if report else 0,
            groundedness=report.groundedness if report else None,
            verification_detail=summarise(report) if report else {},
            llm_provider=answer.usage.provider,
            llm_model=answer.usage.model,
            prompt_tokens=answer.usage.input_tokens,
            completion_tokens=answer.usage.output_tokens,
            latency_ms=answer.elapsed_ms,
            warnings=answer.warnings,
        )
        self.audit.write(record)


def answer_question(
    question: str,
    *,
    principal: Principal | None = None,
    settings: Settings | None = None,
) -> Answer:
    """One-shot convenience wrapper. Prefer reusing an `Agent` in a server."""
    with Agent(settings) as agent:
        return agent.ask(question, principal=principal)
