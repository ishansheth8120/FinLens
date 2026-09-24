from __future__ import annotations

import pytest

from finlens.governance.audit import AuditLog, AuditRecord, hash_rows, new_request_id, utcnow


@pytest.fixture
def audit(tmp_path):
    with AuditLog(tmp_path / "audit.duckdb") as log:
        yield log


def record(**overrides) -> AuditRecord:
    base = {
        "request_id": new_request_id(),
        "ts": utcnow(),
        "user_id": "analyst-1",
        "user_role": "analyst",
        "question": "What was Apple's revenue in 2023?",
        "route": "sql",
        "route_confidence": 0.9,
        "generated_sql": "SELECT revenue FROM marts.fct_company_annual",
        "scoped_sql": "SELECT revenue FROM (SELECT * FROM marts.fct_company_annual WHERE cik IN ('0000320193'))",
        "sql_tables": ["marts.fct_company_annual"],
        "row_count": 1,
        "answer": "Apple reported $383.3B.",
        "numeric_claims": 1,
        "claims_reconciled": 1,
        "latency_ms": 1234.5,
    }
    base.update(overrides)
    return AuditRecord(**base)


def test_write_and_replay(audit):
    written = record()
    audit.write(written)

    replayed = audit.get(written.request_id)
    assert replayed is not None
    assert replayed["question"] == written.question
    assert replayed["route"] == "sql"
    assert replayed["user_id"] == "analyst-1"


def test_both_the_generated_and_the_scoped_sql_are_kept(audit):
    # The difference between them is the access control; an audit trail that
    # kept only one could not show that it was applied.
    written = record()
    audit.write(written)

    replayed = audit.get(written.request_id)
    assert replayed["generated_sql"] != replayed["scoped_sql"]
    assert "0000320193" in replayed["scoped_sql"]
    assert "0000320193" not in replayed["generated_sql"]


def test_json_columns_round_trip(audit):
    written = record(
        sql_tables=["marts.dim_company", "marts.fct_company_annual"],
        chunk_ids=["c1", "c2"],
        warnings=["truncated"],
        verification_detail={"checked": 2, "failed": 0},
    )
    audit.write(written)

    replayed = audit.get(written.request_id)
    assert replayed["sql_tables"] == ["marts.dim_company", "marts.fct_company_annual"]
    assert replayed["chunk_ids"] == ["c1", "c2"]
    assert replayed["warnings"] == ["truncated"]
    assert replayed["verification_detail"]["checked"] == 2


def test_unknown_request_id_returns_none(audit):
    assert audit.get("does-not-exist") is None


def test_recent_is_newest_first_and_filterable(audit):
    audit.write(record(user_id="a", question="first"))
    audit.write(record(user_id="b", question="second"))

    assert len(audit.recent()) == 2
    assert [r["user_id"] for r in audit.recent(user_id="a")] == ["a"]


def test_failures_surfaces_unreconciled_answers(audit):
    audit.write(record(claims_failed=0))
    audit.write(record(claims_failed=2, question="the bad one"))

    failures = audit.failures()
    assert len(failures) == 1
    assert failures[0]["question"] == "the bad one"


def test_stats(audit):
    audit.write(record(latency_ms=100, prompt_tokens=10, completion_tokens=5, groundedness=1.0))
    audit.write(record(latency_ms=300, prompt_tokens=20, completion_tokens=5, groundedness=0.5))

    stats = audit.stats()
    assert stats["requests"] == 2
    assert stats["total_tokens"] == 40
    assert stats["mean_latency_ms"] == pytest.approx(200)
    assert stats["mean_groundedness"] == pytest.approx(0.75)


def test_a_duplicate_request_id_does_not_crash_the_request(audit):
    # The audit write must never propagate into the user's request path.
    written = record()
    audit.write(written)
    audit.write(written)  # primary key violation, swallowed and logged
    assert audit.get(written.request_id) is not None


def test_records_survive_reopening(tmp_path):
    path = tmp_path / "audit.duckdb"
    written = record()

    with AuditLog(path) as log:
        log.write(written)
    with AuditLog(path) as log:
        assert log.get(written.request_id) is not None


# --- result hashing ----------------------------------------------------------


def test_hash_is_stable_for_identical_rows():
    assert hash_rows([[1, "a"]]) == hash_rows([[1, "a"]])


def test_hash_changes_when_the_data_changes():
    assert hash_rows([[1, "a"]]) != hash_rows([[2, "a"]])


def test_hash_is_order_sensitive():
    # Row order is part of the answer for anything ranked, so two orderings are
    # genuinely different result sets.
    assert hash_rows([[1], [2]]) != hash_rows([[2], [1]])


def test_hash_handles_dates_and_nulls():
    from datetime import date

    assert hash_rows([[date(2023, 9, 30), None]]) is not None


def test_hash_of_nothing_is_none():
    assert hash_rows(None) is None
