# FinLens

Question answering over SEC EDGAR filings — **with every figure machine-checked
against its source before it is served.**

```
"What was Apple's gross margin in fiscal 2023?"
  → 44.1%, from the FY2023 10-K, reconciled against the warehouse row

"What supply chain risks does Apple disclose?"
  → quoted from Item 1A, cited, linked to sec.gov
```

Runs entirely on permanently-free infrastructure. The deliverable is the report
in **[finlens/docs/ARCHITECTURE.md](finlens/docs/ARCHITECTURE.md)**.

---

## The thing that makes this different

Give a language model a table of correct figures and ask for commentary. It will
usually be right. Occasionally it will state a number that is not in the table —
a transposed digit, a growth rate against the wrong base, a figure recalled from
training rather than read from the rows.

The answer reads perfectly. The citation resolves. Nobody catches it.

FinLens recomputes every asserted figure against the actual query results before
serving. Anything that does not reconcile is **removed** from the answer, not
annotated with a warning. See [`finlens/agent/verifier.py`](finlens/agent/verifier.py).

Alongside that: entity-level access control enforced by SQL rewrite and Postgres
RLS, an append-only audit log with full request replay, and lineage from any
sentence back to an SEC URL.

---

## Architecture

```
EDGAR ──ingest──▶ R2 (raw/, dt= partitioned) ──Spark──▶ silver/ ──dbt──▶ BigQuery
                        │                                                    │
                        └── 10-K text ──▶ sections ──chunk+embed──▶ pgvector │
                                                                        │    │
   question ──▶ router ──┬──▶ text-to-SQL ──▶ warehouse ────────────────┼────┘
                         ├──▶ hybrid retrieval ──────────────────────────┘
                         └──▶ refuse / metadata
                                    │
                              synthesis ──▶ VERIFIER ──▶ answer + citations
                                                              │
                                                        audit log
```

| Directory | Contents |
|---|---|
| [`finlens/ingest/`](finlens/ingest/) | Rate-limited EDGAR clients: submissions, companyfacts, frames, documents |
| [`finlens/storage/`](finlens/storage/) | Object store — boto3/R2, with a local backend |
| [`finlens/spark/`](finlens/spark/) | PySpark: raw JSON/HTML → conformed silver Parquet |
| [`finlens/warehouse/`](finlens/warehouse/) | dbt project — DuckDB and BigQuery targets |
| [`finlens/embed/`](finlens/embed/) | Chunking, local CPU embeddings, hybrid vector search |
| [`finlens/agent/`](finlens/agent/) | Router, text-to-SQL, RAG, synthesis, **verifier** |
| [`finlens/governance/`](finlens/governance/) | Access control, audit log, lineage, RLS policies |
| [`finlens/eval/`](finlens/eval/) | 70-case golden set, metrics, LLM judge, harness |
| [`finlens/api/`](finlens/api/) | FastAPI + HTMX UI |
| [`finlens/airflow/`](finlens/airflow/) | DAGs: daily ingest, backfill, nightly eval gate |
| [`finlens/docs/`](finlens/docs/) | **The report** |

---

## Quick start

Python 3.10+. Java 11+ only for the Spark jobs.

```bash
make setup                  # venv + dependencies
cp .env.example .env        # then set FINLENS_SEC_USER_AGENT
make test                   # ~280 unit tests, no network, no API key
```

**Set `FINLENS_SEC_USER_AGENT` to a real contact address before ingesting.** SEC
blocks automated access without one, and the block applies to your IP for hours.

With no credentials at all the pipeline still runs end to end on the local
filesystem — it just has no LLM and uses a non-semantic embedding stand-in.
`GET /health` tells you exactly which parts are degraded.

```bash
make demo                   # ingest → warehouse → index, ~25 companies
make api                    # serve on :8000, UI at http://localhost:8000/
```

---

## Running it properly

```bash
# 1. Land raw EDGAR data. Two layers, different scales — see report §3.
finlens-ingest structured --limit 300   # XBRL facts, ~15 min at 8 req/s
finlens-ingest text                     # 10-K text, 10 companies
finlens-ingest scope                    # show the configured universes

# 2. Raw → silver  (needs Java)
make spark

# 3. Silver → warehouse marts, with tests
make warehouse

# 4. Chunk and embed
finlens-embed build --rebuild
finlens-embed stats

# 5. Ask
finlens-ask ask "What was Apple's revenue in fiscal 2023?"
finlens-ask explain "Why did Intel's gross margin fall in 2023?"
finlens-ask route "Should I buy Apple stock?"
```

Deployment to the free-tier services is in
**[finlens/docs/DEPLOY.md](finlens/docs/DEPLOY.md)**.

---

## Configuration

Environment-driven — see [.env.example](.env.example). Every service has a
permanently-free tier, and each has a local fallback.

| Variable | Default | Why it matters |
|---|---|---|
| `FINLENS_SEC_USER_AGENT` | placeholder | **Required.** SEC blocks requests without a real contact. |
| `GOOGLE_API_KEY` | unset | Gemini Flash, free. Falls back to `GROQ_API_KEY`. |
| `FINLENS_STORAGE_BACKEND` | `local` | `s3` for Cloudflare R2. |
| `FINLENS_WAREHOUSE_BACKEND` | `duckdb` | `bigquery` for the sandbox tier. |
| `FINLENS_VECTOR_BACKEND` | `duckdb` | `pgvector` for Supabase — **this is what enables RLS**. |
| `FINLENS_EMBEDDING_PROVIDER` | `sentence-transformers` | `hash` is a non-semantic stand-in for CI. Never evaluate on it. |

---

## Evaluation

Four independent failure surfaces, so four separate measurements:

```bash
finlens-eval list                       # the 70-case golden set
finlens-eval run                        # everything, with the LLM judge
finlens-eval run --tags adversarial     # routing traps and injection
finlens-eval run --tags multi_period    # the predicted worst category
finlens-eval compare <base> <candidate> # gate on case-level regressions
```

Reported per question type as well as in aggregate — a single pass rate hides
that multi-period comparisons fail several times as often as single facts, and
that difference is what tells you where to spend the next week.

Two groundedness numbers are reported separately and on purpose: the
**verifier's** (arithmetic, unarguable, covers figures with a result set behind
them) and the **judge's** (covers qualitative claims, but is itself a model).
Reporting only one would overstate the guarantee.

**Current status:** the harness and the golden set are built and tested. The
results tables in the report are marked `PENDING` — no accuracy number is
published until a run produces it.

---

## The two-user demo

```bash
curl -s localhost:8000/auth/demo-users | jq
```

Ask the same question as each. `admin` sees every company; `analyst` sees Apple
and Microsoft only. The difference is enforced by rewriting the SQL and by
Postgres row-level security — not by asking the model nicely. The UI shows both
the SQL the model wrote and the scoped SQL that actually ran.

---

## Development

```bash
make test        # unit tests
make lint        # ruff
make fmt         # ruff --fix
make dbt-test    # warehouse data tests
make clean       # drop derived data, keep the raw zone
```

Tests needing the JVM or the network are marked `integration` and excluded from
the default run.

---

## Known limitations

Stated here rather than left to be discovered:

- **Numbers quoted from filing prose are not verified.** The verifier reconciles
  against the warehouse; a figure in MD&A text has no structured counterpart.
- **The text corpus is ten companies.** By design (report §3), but it means most
  narrative questions about the wider universe correctly return nothing.
- **Section extraction is heuristic** — degrades on pre-2010 and image-heavy
  filings, which fall back to a whole-document section.
- **SIC, not GICS.** The only classification EDGAR publishes is dated and coarse.
- **No reranker.** The hook exists and is unimplemented.
- **Demo-grade auth.** JWT with a config secret and seeded users.
- **Retrieval recall is unmeasured** until chunks are labelled against a pinned
  corpus snapshot. Reported as N/A rather than estimated.

## Licence

MIT. Built on public data.
