"""API tests.

The agent is stubbed: these check the HTTP contract, auth and the entitlement
plumbing, not answer quality. Answer quality is what `finlens/eval` is for, and
conflating the two produces tests that need an API key to run.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from finlens.agent.types import (
    Answer,
    Citation,
    ClaimVerdict,
    ClaimVerification,
    NumericClaim,
    Route,
    SqlResult,
    Usage,
    VerificationReport,
)
from finlens.api.main import create_app
from finlens.governance.audit import AuditLog


class StubAgent:
    """Records the principal it was asked with, and returns a fixed answer."""

    def __init__(self):
        self.calls: list[dict] = []

    def ask(self, question, *, principal=None, force_route=None, write_audit=True):
        self.calls.append(
            {"question": question, "principal": principal, "force_route": force_route}
        )
        return Answer(
            question=question,
            answer="Apple reported $383.3B in FY2023 revenue.",
            route=Route.SQL,
            request_id="req-123",
            citations=[Citation(label="FinLens warehouse (1 rows)", source_type="warehouse")],
            numeric_claims=[NumericClaim(text="$383.3B", value=383.3e9, unit="USD")],
            verification=VerificationReport(
                verifications=[
                    ClaimVerification(
                        claim=NumericClaim(text="$383.3B", value=383.3e9),
                        verdict=ClaimVerdict.RECONCILED,
                    )
                ],
                checked=1,
                reconciled=1,
            ),
            sql_result=SqlResult(
                sql="SELECT revenue FROM (SELECT * FROM marts.fct_company_annual "
                "WHERE cik IN ('0000320193'))",
                generated_sql="SELECT revenue FROM marts.fct_company_annual",
                columns=["revenue"],
                rows=[[383285000000.0]],
                row_count=1,
            ),
            usage=Usage(input_tokens=100, output_tokens=50, calls=2, provider="gemini"),
            elapsed_ms=1234.0,
        )

    def close(self):
        pass


@pytest.fixture
def stub_agent():
    return StubAgent()


@pytest.fixture
def client(stub_agent, tmp_path, settings):
    app = create_app()
    audit = AuditLog(tmp_path / "audit.duckdb", settings=settings)

    with TestClient(app) as test_client:
        # Replace what lifespan built - the stub must be installed after startup.
        app.state.agent = stub_agent
        app.state.audit = audit
        yield test_client

    audit.close()


def auth_header(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/auth/token", json={"username": username, "password": username})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --- health ------------------------------------------------------------------


def test_health_is_always_200(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"]


def test_ready_reports_503_without_any_store(client):
    # Neither warehouse nor index exists in the test tmpdir.
    assert client.get("/ready").status_code == 503


def test_health_flags_the_non_semantic_embedding_provider(client):
    detail = " ".join(client.get("/health").json()["detail"])
    assert "hash" in detail


# --- auth --------------------------------------------------------------------


def test_token_round_trip(client):
    header = auth_header(client, "analyst")
    me = client.get("/auth/me", headers=header).json()

    assert me["user_id"] == "analyst"
    assert me["role"] == "analyst"
    assert not me["unrestricted"]
    assert "0000320193" in me["permitted_ciks"]


def test_admin_is_unrestricted(client):
    me = client.get("/auth/me", headers=auth_header(client, "admin")).json()
    assert me["unrestricted"]


def test_bad_password_is_rejected(client):
    response = client.post("/auth/token", json={"username": "analyst", "password": "wrong"})
    assert response.status_code == 401


def test_unknown_user_is_rejected(client):
    response = client.post("/auth/token", json={"username": "nobody", "password": "x"})
    assert response.status_code == 401


def test_a_garbage_token_is_rejected(client):
    response = client.get("/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert response.status_code == 401


def test_anonymous_is_allowed_by_default(client):
    # Single-tenant deployments should not need a login to work.
    assert client.get("/auth/me").json()["user_id"] == "anonymous"


# --- ask ---------------------------------------------------------------------


def test_ask_returns_the_contract(client):
    response = client.post("/ask", json={"question": "What was Apple's revenue in 2023?"})
    assert response.status_code == 200

    body = response.json()
    assert body["answer"]
    assert body["route"] == "sql"
    assert body["request_id"] == "req-123"
    assert body["citations"]
    assert body["usage"]["provider"] == "gemini"


def test_ask_exposes_both_the_generated_and_the_executed_sql(client):
    body = client.post("/ask", json={"question": "q"}).json()
    # Showing the difference is the point: it is how a reviewer sees that the
    # access filter was applied and that the model did not write it.
    assert body["sql"]["generated_sql"] != body["sql"]["sql"]
    assert "cik IN" in body["sql"]["sql"]


def test_ask_reports_verification(client):
    body = client.post("/ask", json={"question": "q"}).json()
    assert body["verification"]["checked"] == 1
    assert body["verification"]["reconciled"] == 1
    assert body["verification"]["groundedness"] == 1.0


def test_ask_passes_the_authenticated_principal_to_the_agent(client, stub_agent):
    client.post("/ask", json={"question": "q"}, headers=auth_header(client, "analyst"))

    principal = stub_agent.calls[-1]["principal"]
    assert principal.user_id == "analyst"
    assert not principal.unrestricted
    assert principal.permitted_ciks == frozenset({"0000320193", "0000789019"})


def test_two_users_reach_the_agent_with_different_scopes(client, stub_agent):
    """The entitlement demo, at the HTTP boundary."""
    client.post("/ask", json={"question": "q"}, headers=auth_header(client, "admin"))
    client.post("/ask", json={"question": "q"}, headers=auth_header(client, "analyst"))

    admin, analyst = stub_agent.calls[-2]["principal"], stub_agent.calls[-1]["principal"]
    assert admin.unrestricted
    assert not analyst.unrestricted


def test_excerpts_can_be_suppressed(client):
    body = client.post("/ask", json={"question": "q", "include_excerpts": False}).json()
    assert all(c["excerpt"] is None for c in body["citations"])


def test_sql_can_be_suppressed(client):
    body = client.post("/ask", json={"question": "q", "include_sql": False}).json()
    assert body["sql"] is None


def test_a_blank_question_is_rejected(client):
    assert client.post("/ask", json={"question": "   "}).status_code == 422


def test_an_overlong_question_is_rejected(client):
    assert client.post("/ask", json={"question": "x" * 5000}).status_code == 422


def test_a_forced_route_is_passed_through(client, stub_agent):
    client.post("/ask", json={"question": "q", "route": "rag"})
    assert stub_agent.calls[-1]["force_route"] == Route.RAG


def test_stream_emits_the_event_sequence(client):
    with client.stream("POST", "/ask/stream", json={"question": "q"}) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    for event in ("status", "route", "sql", "verification", "token", "done"):
        assert f"event: {event}" in body


# --- audit -------------------------------------------------------------------


def _seed(client, audit, user_id="analyst"):
    from finlens.governance.audit import AuditRecord, utcnow

    audit.write(
        AuditRecord(
            request_id="req-123",
            ts=utcnow(),
            user_id=user_id,
            question="What was Apple's revenue?",
            route="sql",
            sql_tables=["marts.fct_company_annual"],
            answer="Apple reported $383.3B.",
            claims_failed=0,
        )
    )


def test_replay_returns_the_record(client, tmp_path):
    audit = client.app.state.audit
    _seed(client, audit)

    body = client.get("/audit/req-123", headers=auth_header(client, "admin")).json()
    assert body["question"] == "What was Apple's revenue?"
    assert body["sql_tables"] == ["marts.fct_company_annual"]


def test_an_analyst_cannot_replay_another_users_request(client):
    _seed(client, client.app.state.audit, user_id="someone-else")

    response = client.get("/audit/req-123", headers=auth_header(client, "analyst"))
    # 404, not 403: confirming the id exists would itself leak.
    assert response.status_code == 404


def test_an_analyst_can_replay_their_own_request(client):
    _seed(client, client.app.state.audit, user_id="analyst")
    assert client.get("/audit/req-123", headers=auth_header(client, "analyst")).status_code == 200


def test_unknown_request_id_is_404(client):
    response = client.get("/audit/nope", headers=auth_header(client, "admin"))
    assert response.status_code == 404


def test_stats_are_admin_only(client):
    assert client.get("/audit/stats", headers=auth_header(client, "analyst")).status_code == 403
    assert client.get("/audit/stats", headers=auth_header(client, "admin")).status_code == 200


def test_lineage_traces_to_sec(client):
    _seed(client, client.app.state.audit, user_id="admin")

    body = client.get("/audit/req-123/lineage", headers=auth_header(client, "admin")).json()
    assert body["trails"]
    assert "SEC EDGAR" in body["rendered"]


# --- catalog -----------------------------------------------------------------


def test_catalog_returns_503_without_a_warehouse(client):
    # Actionable deployment state, not a 500.
    assert client.get("/companies").status_code == 503


def test_an_invalid_cik_is_a_400_not_a_500(client):
    response = client.get("/companies/not-a-cik")
    assert response.status_code in (400, 503)
