"""The HTMX UI.

Server-rendered fragments, no build step, no framework. The whole point of the
page is to make three things visible that a JSON response hides:

* the generated SQL **and** the scoped SQL that actually ran,
* the verification result for every figure,
* the same question answered differently for two users.

A React app would take a week and show none of that any better.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse

from finlens.api.auth import DEMO_USERS
from finlens.api.deps import AgentDep
from finlens.governance.access import Principal
from finlens.logging import get_logger

log = get_logger(__name__)
router = APIRouter(tags=["ui"], include_in_schema=False)

STATIC = Path(__file__).parent.parent / "static"


def _e(value: Any) -> str:
    """Escape for HTML. Filing text is untrusted input and reaches this page."""
    return html.escape(str(value if value is not None else ""))


@router.get("/", response_class=HTMLResponse, summary="The UI")
def index() -> HTMLResponse:
    return HTMLResponse(STATIC.joinpath("index.html").read_text(encoding="utf-8"))


def _principal_for(username: str) -> Principal:
    user = DEMO_USERS.get(username)
    if user is None:
        return Principal.admin(user_id="anonymous")
    return Principal(
        user_id=user.user_id,
        role=user.role,
        permitted_ciks=frozenset(user.permitted_ciks),
        display_name=user.display_name,
    )


def _verification_badge(answer) -> str:
    report = answer.verification
    if report is None or report.checked == 0:
        return '<span class="badge">no figures to verify</span>'
    if report.has_failures:
        return (
            f'<span class="badge unverified">{report.failed} of {report.checked} '
            f"figures did not reconcile</span>"
        )
    return (
        f'<span class="badge verified">{report.reconciled} of {report.checked} '
        f"figures reconciled</span>"
    )


def _rows_table(result) -> str:
    if not result or not result.ok or not result.rows:
        return ""
    header = "".join(f"<th>{_e(c)}</th>" for c in result.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>"
        for row in result.rows[:15]
    )
    more = (
        f"<div class='sub'>{result.row_count} rows, showing 15</div>"
        if result.row_count > 15
        else ""
    )
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>{more}"


@router.post("/ui/ask", response_class=HTMLResponse, summary="UI answer fragment")
async def ui_ask(
    agent: AgentDep,
    question: Annotated[str, Form()],
    user: Annotated[str, Form()] = "admin",
) -> HTMLResponse:
    question = question.strip()
    if not question:
        return HTMLResponse('<div class="card">Ask something.</div>')

    principal = _principal_for(user)

    try:
        answer = await run_in_threadpool(agent.ask, question, principal=principal)
    except Exception as exc:  # noqa: BLE001
        log.error("ui.ask_failed", error=str(exc))
        return HTMLResponse(
            f'<div class="card"><strong>Could not answer.</strong>'
            f'<div class="warn">{_e(exc)}</div></div>'
        )

    parts = [
        '<div class="card">',
        f'<div><span class="badge">{_e(answer.route.value)}</span>'
        f'<span class="badge">{_e(principal.display_name or principal.user_id)}</span>'
        f"{_verification_badge(answer)}</div>",
        f'<div class="answer" style="margin-top:.7rem">{_e(answer.answer)}</div>',
    ]

    if answer.citations:
        cites = "".join(f"<li>{_e(c.label)}</li>" for c in answer.citations)
        parts.append(f"<ol class='cites'>{cites}</ol>")

    for warning in answer.warnings:
        parts.append(f'<div class="warn">{_e(warning)}</div>')

    # Verification detail. Shown expanded when something failed, because a
    # withheld figure is the one thing the reader must not scroll past.
    report = answer.verification
    if report is not None and report.checked:
        open_attr = " open" if report.has_failures else ""
        rows = "".join(
            f"<tr><td>{_e(v.claim.text)}</td><td>{v.claim.value:,.4g}</td>"
            f"<td>{_e(v.verdict.value)}</td><td>{_e(v.detail)}</td></tr>"
            for v in report.verifications
        )
        parts.append(
            f"<details{open_attr}><summary>Numeric verification "
            f"({report.reconciled}/{report.checked} reconciled)</summary>"
            f"<table><thead><tr><th>Claim</th><th>Value</th><th>Verdict</th>"
            f"<th>Detail</th></tr></thead><tbody>{rows}</tbody></table></details>"
        )

    sql = answer.sql_result
    if sql is not None and sql.sql:
        generated = (
            f"<div class='sub' style='margin-top:.6rem'>As generated by the model:</div>"
            f"<pre>{_e(sql.generated_sql)}</pre>"
            if sql.generated_sql and sql.generated_sql != sql.sql
            else ""
        )
        scoped_note = (
            "<div class='sub'>Rewritten to your entitlements before execution:</div>"
            if generated
            else ""
        )
        error = f'<div class="warn">{_e(sql.error)}</div>' if sql.error else ""
        parts.append(
            f"<details><summary>SQL and results</summary>{generated}{scoped_note}"
            f"<pre>{_e(sql.sql)}</pre>{error}{_rows_table(sql)}</details>"
        )

    if answer.retrieval and answer.retrieval.contexts:
        excerpts = "".join(
            f"<pre>{_e(c[:600])}</pre>" for c in answer.retrieval.contexts[:5]
        )
        parts.append(
            f"<details><summary>Retrieved excerpts "
            f"({len(answer.retrieval.contexts)})</summary>{excerpts}</details>"
        )

    parts.append(
        f'<div class="meta">{answer.elapsed_ms:.0f} ms · '
        f"{answer.usage.total_tokens:,} tokens · "
        f"{_e(answer.usage.provider or 'n/a')} · "
        f"request <code>{_e(answer.request_id)}</code> — "
        f'<a href="/audit/{_e(answer.request_id)}">audit</a> · '
        f'<a href="/audit/{_e(answer.request_id)}/lineage">lineage</a></div>'
    )
    parts.append("</div>")

    return HTMLResponse("".join(parts))
