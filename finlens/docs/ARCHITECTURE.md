# FinLens — Architecture and Evaluation

Question answering over SEC EDGAR filings, with every figure machine-checked
against its source before it is served.

**Status:** the system is built and tested; the measured-results sections (§6,
§7) are marked `PENDING` and state exactly what will fill them. Nothing in this
document reports a number that has not been produced by a run.

**Cost:** ₹0/month plus a domain. Every component sits inside a permanently-free
tier.

---

## 1. The problem

An equity analyst wants two things from a filing, and they live in different
halves of it.

*"What was Apple's FY2023 gross margin, and how does it compare with
Microsoft's?"* — a number, and one that has to be right. It comes from XBRL
tags, which are structured, comparable across companies, and messy in specific
ways covered in §4.

*"What supply-chain risks does Apple disclose?"* — prose, from Item 1A. There is
no structured representation of it and no way to compute it.

Most systems built on filings pick one half. A text-only RAG system answers the
first question by retrieving a sentence that happens to contain a number, which
is unreliable in a way the output does not reveal — the sentence is real, the
citation resolves, and the figure may still be the wrong period, the wrong
entity or a restated value. A SQL-only system cannot answer the second question
at all.

FinLens does both, routes between them, and — the part that matters — verifies
the numbers it produces.

### The specific failure this is built against

Give a language model a table of correct figures and ask for commentary. It will
usually be right. Occasionally it will state a number that is not in the table:
a transposed digit, a growth rate computed against the wrong base, a figure
recalled from training rather than read from the rows.

The answer reads perfectly. The citation resolves. Nobody catches it.

That is the failure mode that makes LLM output unusable in a regulated context,
and it is not solved by better prompting, a better model, or a groundedness
score from a second model. It is solved by recomputing the number.
`finlens/agent/verifier.py` does that, and §5.4 describes how.

---

## 2. Architecture

```
                    ┌─────────────────────────────────────────┐
   SEC EDGAR ──────▶│ ingest/   rate-limited, cached, manifest │
   data.sec.gov     └────────────────────┬────────────────────┘
   www.sec.gov                           │
                                         ▼
                          Cloudflare R2  (raw/, partitioned by dt=)
                                         │
                        ┌────────────────┴────────────────┐
                        ▼                                 ▼
             300 companies                        10 companies
             companyfacts JSON                    10-K HTML
                        │                                 │
                        ▼                                 ▼
              ┌──────────────────┐              ┌──────────────────┐
              │ spark/           │              │ spark/           │
              │ explode, dedupe  │              │ item extraction  │
              │ restatements     │              │ (1A, 7, 7A)      │
              └────────┬─────────┘              └────────┬─────────┘
                       ▼                                 ▼
              curated/silver/facts              curated/silver/sections
                       │                                 │
                       ▼                                 ▼
              ┌──────────────────┐              ┌──────────────────┐
              │ warehouse/ (dbt) │              │ embed/           │
              │ staging → marts  │              │ chunk 800/100    │
              │ BigQuery/DuckDB  │              │ bge-small-en     │
              └────────┬─────────┘              └────────┬─────────┘
                       │                                 ▼
                       │                        Supabase pgvector
                       │                        + row-level security
                       │                                 │
                       └────────────┬────────────────────┘
                                    ▼
                       ┌────────────────────────┐
              question │ agent/                 │
              ────────▶│  router                │
                       │  ├─ text-to-SQL ──┐    │
                       │  ├─ hybrid RAG ───┤    │
                       │  └─ synthesis  ◀──┘    │
                       │      │                 │
                       │      ▼                 │
                       │  VERIFIER ◀────────────┼── recompute every figure
                       │      │                 │
                       └──────┼─────────────────┘
                              ▼
                    answer + citations + verification report
                              │
                              ▼
                       audit log (append-only, replayable)
```

### Component map

| Layer | Technology | Why this one |
|---|---|---|
| Source | SEC EDGAR APIs | Free, no key, public. Nothing about this system is deniable. |
| Object store | Cloudflare R2 | 10 GB free, zero egress, S3 API. The code is `boto3`. |
| Batch | PySpark in Docker | Free, local. The structured layer genuinely needs it (§3). |
| Warehouse | BigQuery sandbox / DuckDB | 10 GB + 1 TB queries free, permanently, no card. DuckDB target for local. |
| Transform | dbt-core | The semantic layer is where correctness logic belongs (§4). |
| Embeddings | `bge-small-en-v1.5` | Local CPU, free forever, 384-dim — fits the Supabase tier. |
| Vector + RLS | Supabase pgvector | 500 MB free, and RLS is the governance layer (§8). |
| LLM | Gemini Flash → Groq | Both free-tier. Provider-agnostic with a fallback chain (§5.1). |
| API | FastAPI + Docker | — |
| Orchestration | Airflow (DAGs) + GitHub Actions | Actions is free on public repos. |

Deliberately **not** used: Snowflake (trial expires; BigQuery proves the same
skill), OpenAI (costs money), Pinecone (restrictive free tier), managed Spark.

---

## 3. The scale-asymmetry decision

**Structured layer: 300 companies. Text layer: 10 companies.** This is the
central design decision, and it is deliberate rather than a resource compromise.

### The reasoning

Retrieval cost scales with corpus size; retrieval *value* does not.

Adding the 290th company's 10-K text to the index costs an embedding pass, 500
MB of storage pressure, and — the part people miss — it degrades retrieval for
every other company, because risk-factor language is near-identical across
issuers in the same sector. A query about Apple's supply-chain risk that
retrieves Dell's supply-chain risk is worse than one that cannot retrieve
anything, because the answer looks right.

Structured coverage behaves the opposite way. The 290th company's XBRL costs one
small JSON document, and it makes every cross-sectional question better:
"which company had the highest R&D intensity" is only meaningful over a
population. Coverage *is* the value.

So: broad where breadth compounds, narrow where it dilutes.

### What this costs

Real, and stated plainly: FinLens cannot answer a narrative question about a
company outside the ten. Case `nr-15` in the golden set tests exactly this — the
correct answer is "the text corpus does not cover Coca-Cola", and an invented
answer is scored as a failure. Case `hy-02` tests the seam directly: Boeing is
in the structured universe but not the text universe, so the figure is available
and the narrative is not, and the answer must say so.

### Configuration

```python
structured_universe_size = 300   # XBRL facts, 2019+
text_universe = [10 tickers]     # 10-K text, 2020+
text_items = ["1A", "7", "7A"]   # Risk Factors, MD&A, Market Risk
```

Item 8 (financial statements) is deliberately **not** indexed. It is already in
the structured layer, and indexing it would create two sources of truth for the
same number — the retrieval path could then contradict the warehouse, and there
would be no principled way to decide which was right.

---

## 4. The concept-mapping problem

This is the most finance-specific engineering in the project, and the part that
would be hardest to get right without knowing the domain.

### The problem

"Revenue" is not one XBRL tag. It is at least four, and which one a company uses
depends on when it filed and how it interpreted the standard:

| Tag | Used by |
|---|---|
| `RevenueFromContractWithCustomerExcludingAssessedTax` | Post-ASC-606, most filers |
| `RevenueFromContractWithCustomerIncludingAssessedTax` | Post-ASC-606, tax-inclusive |
| `Revenues` | Pre-ASC-606, and some filers throughout |
| `SalesRevenueNet` | Legacy, retired after ASC 606 |

A query filtering on any single tag silently returns nothing for a large
fraction of the population, and — worse — returns *something* for the rest, so
the result looks complete.

### The solution

A priority-ordered mapping from canonical metric to source tags, resolved with
coalesce logic. It lives in `finlens/warehouse/seeds/concept_map.csv` as data,
not code, so adding a tag is a one-line change reviewable by someone who knows
accounting but not Python:

```csv
metric,taxonomy,concept,priority,unit,period_type,description
revenue,us-gaap,RevenueFromContractWithCustomerExcludingAssessedTax,1,USD,duration,...
revenue,us-gaap,RevenueFromContractWithCustomerIncludingAssessedTax,2,USD,duration,...
revenue,us-gaap,Revenues,3,USD,duration,Pre-ASC-606 total revenues
revenue,us-gaap,SalesRevenueNet,4,USD,duration,Legacy net sales tag
```

`fct_financial_fact` joins facts to this seed and takes the highest-priority
concept per (company, metric, period, filing). A company tagging both
`Revenues` and the ASC 606 tag in the same period resolves to the latter.

The mapping covers 36 tags across 25 canonical metrics.

### Three more traps in the same data

**Restatements.** A concept/period pair appears once per filing that reported
it. Ten years of 10-Ks means FY2019 revenue appears repeatedly, sometimes with
different values. Handling: `silver_facts` ranks by `filed_date` and marks
`is_latest`, keeping every vintage. `fct_company_metric` pre-filters to the
current value; `fct_financial_fact` retains all of them, because "what did they
report at the time" is a legitimate question and deleting the answer to it would
be wrong.

**Instants versus durations.** A fact with only `end` is a balance at a point in
time; one with `start` and `end` covers a period. Summing balances across
quarters is meaningless. Handling: `period_type` is derived and every mart
filters on it.

**Year-to-date contamination.** This is the subtle one. XBRL carries 3-month,
6-month, 9-month and 12-month durations under the *same* concept. A query for
"quarterly revenue" that does not filter on duration length picks up the
nine-month YTD figure alongside Q3 and reports a number roughly three times too
large. Handling: `period_kind` buckets duration in days —
`quarterly` (80–100), `half_year` (170–190), `three_quarters` (260–285),
`annual` (350–380) — and the marts filter to `annual` and `quarterly` only.
Golden-set cases `sf-09` and `mp-05` exist to catch a regression here.

### Why the wide mart exists

`fct_company_annual` is one row per company-year with 25 metrics and 11
pre-computed ratios. It duplicates data that is already in the long tables, and
it earns that cost.

The long tables are the right shape for a warehouse and the wrong shape for a
language model. Asking one to compute gross margin from `fct_company_metric`
requires a self-join on `metric` with matched periods — and that self-join is
where generated SQL reliably falls over. Pre-computing the ratio moves the
correctness burden from the model into dbt, where it is tested. §7 will report
what that trade actually bought.

---

## 5. The agent

```
question → router → { text-to-SQL → warehouse }  → synthesis → verifier → answer
                   └ { hybrid retrieval        } ↗
```

Plain Python state machine, not LangGraph. The control flow is a routing
decision and two independent legs; a framework would add a dependency and an
abstraction layer without removing any of the code that matters.

### 5.1 Provider-agnostic LLM access

Three providers behind one interface, with an automatic fallback chain:

```
Gemini Flash  (primary)   free tier, ~15 req/min
Groq          (fallback)  free tier, separate limit pool
Anthropic     (optional)  paid; kept as a quality baseline for comparison
```

The chain is not a nicety. Both free tiers are rate-limited rather than metered,
so a 78-case eval run *will* hit a limit partway through. Without a fallback the
run dies at case 40 having spent an hour and produced nothing comparable.

`Usage` records which provider actually served each call, because a run served
half by Groq is not comparable to one served by Gemini, and an eval that does
not record that is reporting a number it cannot reproduce.

Structured outputs are used throughout — router decisions, generated SQL, judge
verdicts. Gemini enforces a response schema natively; Groq guarantees valid JSON
but not schema conformance, so the schema goes in the prompt and Pydantic
validates. A malformed response is a validation error at the boundary rather
than a `KeyError` three frames deeper.

### 5.2 The router

One structured call, classifying into `sql` / `rag` / `hybrid` / `metadata` /
`refuse` and extracting entities.

A heuristic pre-pass handles unambiguous cases (investment advice, price
predictions, coverage questions) with no model call at all. It is deliberately
high-precision: a heuristic that fires wrongly is worse than one that never
fires, because the model call it skipped was the thing that would have caught
the mistake.

Below 0.5 confidence the route is upgraded to `hybrid` — both stores searched.
Costs roughly one extra retrieval and one extra generation; answering from the
wrong store costs the answer.

Routing accuracy is reported separately in §6 because it is upstream of
everything: a numeric question sent to RAG produces a fluent, cited, wrong
answer, and no downstream component can recover from it.

### 5.3 Text-to-SQL and the query allowlist

Generated SQL is parsed with `sqlglot` — not regex-matched — and must satisfy
three controls before it runs:

1. **Table allowlist.** Only the seven `mart_`-layer models. Not staging, not
   raw, not `information_schema`. This is why the marts are narrow: the model's
   blast radius is exactly that list.
2. **Read-only.** Anything that is not a single `SELECT`/`WITH` is rejected.
3. **Bounded.** A row limit is injected when absent, clamped when excessive.

The AST matters. A regex looking for `delete` rejects
`WHERE company_name = 'Delete Inc.'` and accepts `SEL/**/ECT`. A parser answers
the question the way the database will. Both behaviours are tested.

The connection is *also* opened read-only, which is the actual boundary — a
parser can be fooled, a read-only DuckDB connection cannot be talked into
writing. The guard exists to reject bad queries with a usable error, and to
catch the expensive-but-legal ones a read-only flag says nothing about.

A failed query is fed back with its error for up to two repair attempts.
Capped at two deliberately: past that the model tends to rewrite the query into
something that runs but answers a different question, which is worse than an
honest failure.

### 5.4 The numeric verifier — the headline feature

Every figure the model asserts is recomputed against the actual query rows
before the answer is served.

Synthesis returns structured output, not prose:

```json
{
  "commentary": "Apple's gross margin rose to 44.1% in FY2023 [1]...",
  "numeric_claims": [
    {"text": "rose to 44.1%", "value": 44.1, "unit": "percent",
     "source_rows": [0], "derivation": "gross_profit / revenue"}
  ],
  "citation_indices": [1],
  "caveats": []
}
```

Each claim is then reconciled against the result set. Three ways to pass:

1. **Direct match** — the value appears in the rows.
2. **Scaled match** — it appears at a different magnitude. Reporting
   383,285,000,000 as "$383.3B", or 0.441 as "44.1%", is a correct restatement,
   not an error. The checker is scale-aware across thousands/millions/billions/
   trillions and the percent-fraction pair.
3. **Derived match** — it equals a difference, ratio or percent change between
   two values that *are* present. Arithmetic on the given data is legitimate.

Anything else is `mismatch` (a number was found, and it is not this one) or
`unsupported` (nothing in the rows corresponds at any scale). Both are failures,
and the failing clause is **removed** from the commentary and replaced with an
explicit marker — not annotated with a warning, because readers do not read
warnings.

The verifier never consults outside knowledge. A figure that is true of the real
world but absent from the rows is `unsupported`, deliberately: that is precisely
the failure being hunted.

#### The tolerance problem

A fixed relative tolerance cannot work here, and getting this wrong makes the
whole feature useless in one direction or the other.

Set it loose enough to accept "$383.3B" for 383,285,000,000 (0.004% off) and it
also accepts **383,825** for **383,285** — a transposed digit, 0.14% off, and
exactly the error the module exists to catch. Set it tight and every rounded
figure fails.

The resolution: infer tolerance from the precision the claim was *stated* at.
"383.3 billion" is 4 significant figures and gets a half-unit-in-last-place
window of ±50 million. "383,825" is 6 significant figures and gets ±0.5. The
first reconciles; the second does not. This is implemented in
`verifier.significant_digits` / `tolerance_for` and is the single most
carefully-tested function in the codebase (`tests/unit/test_verifier.py`).

#### What it does not do

Pure-RAG answers have no result set, so their claims are `uncheckable` — not
failures. Numbers quoted from filing *text* are not verified, because the text
is unparsed prose. That is a real gap and it is stated in §10.

### 5.5 Retrieval

Hybrid: dense (pgvector cosine) + lexical (Postgres full-text), fused by
reciprocal rank.

RRF rather than a weighted score blend, because cosine similarity and
`ts_rank_cd` are not on comparable scales and any weighting tuned for one query
length fails at another. RRF uses only ranks, so it needs no per-corpus
calibration. k=60, from the original paper.

Hybrid is not optional in this domain. Filings are full of exact strings —
tickers, item numbers, defined terms, dollar amounts — that dense retrieval
handles poorly and BM25 nails. Most portfolio RAG projects are dense-only; the
ablation in §6 measures what the lexical arm is worth here.

Metadata filtering happens **before** scoring. Almost every real question is
scoped ("Apple's risk factors in 2023"), and pre-filtering to a few hundred
candidates then scoring exactly beats an approximate search over everything
followed by a post-filter that discards most results.

Reranking is currently rank-preserving with light diversification (at most three
chunks per filing, so one verbose 10-K cannot crowd out the other companies in a
comparison). A cross-encoder is the obvious next step and is **not implemented**
— the hook exists, unimplemented rather than stubbed with something that
pretends to rerank, so the eval numbers describe what the system actually does.

---

## 6. Evaluation

### Method

70 hand-written cases across five types, plus 8 routing and safety cases:

| Type | Count | Example |
|---|---:|---|
| Single fact | 15 | Apple's FY2023 total revenue |
| Multi-period | 15 | Apple's gross margin, 2021 → 2024 |
| Cross-entity | 15 | Highest R&D as % of revenue in 2023 |
| Narrative | 15 | Supply-chain risks Apple flagged |
| Hybrid | 10 | Intel's margin decline, and its explanation |
| Metadata / refusal / adversarial | 8 | Prompt injection, false premise, private company |

Expected answers were written by hand from the filings. Numeric expectations
carry a tolerance rather than a bare figure, because a golden set that fails
when a company restates is a golden set you learn to ignore.

Cases are tagged, and the harness reports **per type** as well as in aggregate.
A single pass rate hides that multi-period comparisons fail several times as
often as single facts, and that difference is what tells you where to spend the
next week.

### Metrics

| Metric | What it measures | How |
|---|---|---|
| Routing accuracy | Confusion matrix across 5 classes | Deterministic |
| SQL execution rate | Generated queries that run | Deterministic |
| SQL table accuracy | Query hit the right grain | AST inspection |
| **Verifier groundedness** | **Asserted figures that reconcile** | **Arithmetic** |
| Retrieval recall@5 | Relevant chunks in top 5 | Against labelled chunks |
| Company precision | Retrieved chunks from the right company | Deterministic |
| Judge correctness | 0–5 against the case rubric | LLM judge |
| Judge groundedness | Claims supported by shown evidence | LLM judge |
| p50 / p95 latency | — | Measured |
| Tokens per query | — | Measured |

Verifier groundedness and judge groundedness are reported **separately and both**
on purpose. The verifier is arithmetic and cannot be argued with, but only covers
figures with a result set behind them. The judge covers qualitative claims but is
itself a model and can be wrong. Reporting only one would overstate the guarantee.

The judge is deliberately a hard marker and grades correctness and groundedness
independently, because an answer can be **correct and ungrounded** — the model
knew Apple's revenue and stated it while the evidence said nothing. That is the
failure this system exists to prevent, and it is invisible to a correctness score
alone, because the answer is *right*.

### Results

> **PENDING.** These require a full pipeline run against live EDGAR data and a
> configured LLM provider. Populated by `finlens-eval run`, which writes
> `finlens/eval/runs/<run_id>/report.{json,md}`; the numbers here are copied
> from a named run so they stay traceable.
>
> The harness refuses to present retrieval numbers as meaningful when the
> non-semantic `hash` embedding stand-in is active, and prints that as a caveat
> on the run.

| Metric | Value | Run |
|---|---|---|
| Cases | — | — |
| Pass rate | — | — |
| Routing accuracy | — | — |
| SQL execution rate | — | — |
| Verifier groundedness | — | — |
| Retrieval recall@5 | — | — |
| Judge correctness (mean) | — | — |
| p50 / p95 latency | — | — |

---

## 7. Failure analysis

> **PENDING** the run in §6. What follows is the *prediction*, recorded before
> measurement so it can be scored honestly against what actually happens.
> Recording it in advance is the point: a failure analysis written after the
> fact tends to rationalise whatever the numbers turned out to be.

### Predicted dominant failure: multi-period comparisons

**Mechanism.** Fiscal versus calendar year confusion. Apple's "fiscal 2023" ends
September 2023; NVIDIA's "fiscal 2024" ends January 2024. The warehouse stores
`fiscal_year` as the calendar year the period *ends* in, which is unambiguous but
is not what a question means by "2023". Expected symptoms: off-by-one-year
answers, and cross-entity comparisons between periods a year apart.

**Cases that will show it:** `mp-02`, `mp-14`, `ce-15`, `sf-04`.

**Predicted fix.** Move the logic out of the LLM and into the semantic layer —
pre-compute period-over-period changes in dbt rather than asking the model to
align periods and subtract. That is the same move already made for ratios (§4),
and if the prediction holds, measuring it before and after is the most useful
result this project can produce.

### Other predicted categories

| Category | Mechanism | Likely fix |
|---|---|---|
| YTD contamination | Quarterly queries picking up 9-month durations | Already mitigated by `period_kind`; measures whether the mitigation holds |
| Cross-company retrieval bleed | Near-identical risk language across issuers | Tighter CIK pre-filter; measured by company precision |
| Coverage confusion | Text universe is 10 companies, structured is 300 | Router needs coverage awareness, not just topic awareness |
| Sparse-tag metrics | Headcount, segment data are inconsistently tagged | Report coverage alongside the answer rather than ranking on partial data |

### Verifier interception rate

The number this project is really about: **how many answers contained a figure
that did not reconcile, and were corrected before serving.** Reported from
`/audit/failures` over the eval run and over live traffic. If it is zero, the
verifier is cheap insurance. If it is not, it is the whole product.

---

## 8. Governance

Three controls. This is the part that transfers directly from working inside a
regulated environment, and it is what separates a demo from a system.

### 8.1 Entity-level access control

Two analysts ask an identical question and get different answers, because they
are entitled to different companies. Desk-level entity permissioning, research
walls and restricted lists are ordinary in a bank, and none of them can be
implemented by telling the model which companies to avoid. **A prompt is not a
control.**

Enforced in two places the model cannot reach:

**The warehouse — AST rewrite.** Every generated query is rewritten before
execution. Each entity-scoped table reference becomes a filtered subquery:

```sql
-- the model writes
FROM marts.fct_company_annual a

-- what actually runs
FROM (SELECT * FROM marts.fct_company_annual
      WHERE cik IN ('0000320193')) AS a
```

Done on the AST, so it survives joins, CTEs and subqueries, and preserves the
alias. A model that writes `WHERE cik = '<forbidden>'` gets an empty result, not
a leak. An empty entitlement set renders as a never-true predicate rather than
as no predicate — tested, because `IN ()` is a syntax error and the naive
implementation of that edge case fails open.

**The vector store — Postgres RLS.** `filing_chunks` has row-level security
keyed to `auth.uid()` via a `user_entity_access` table, with `FORCE ROW LEVEL
SECURITY` so the table owner does not bypass it. The hybrid search function is
`security invoker`, so policies apply to it — a `security definer` search
function would silently bypass every entitlement, which is the most common way
an RLS demo proves nothing.

The two mechanisms differ because the engines differ, and that is worth being
explicit about: RLS is the stronger control, and the SQL rewrite is what you do
when the engine has no RLS (DuckDB does not). On BigQuery the equivalent is an
authorised view — the same idea with the rewrite done once at deploy time.

### 8.2 Query allowlist

§5.3. Documented here as a control: parsed, not pattern-matched; seven tables;
read-only connection; enforced row limit.

### 8.3 Audit log

Append-only. Every request records:

`request_id · timestamp · user_id · role · question · route · confidence ·
generated_sql · scoped_sql · tables · row_count · result_hash · chunk_ids ·
answer · numeric_claims · reconciled · failed · groundedness · provider · model ·
prompt_tokens · completion_tokens · latency_ms · warnings`

`GET /audit/{request_id}` replays it exactly.

Two decisions worth defending. **Both the generated and the scoped SQL are
stored** — the difference between them *is* the access control, and a log that
kept only one could not demonstrate it was applied. **The result hash, not the
result rows** — storing every row of every query grows without bound and
duplicates the warehouse; a SHA-256 answers the question that actually gets
asked in an incident ("was this the same data we served then?") at fixed cost.

An analyst sees only their own requests; confirming that another user's request
id exists is itself a leak, so an unauthorised replay returns 404, not 403.

### 8.4 Lineage

Any sentence in the output traces back to an SEC URL:

```
answer sentence
  → numeric claim / citation          (agent output)
    → warehouse row / chunk id        (result set / vector index)
      → dbt model                     (fct_company_annual)
        → dbt staging                 (stg_facts)
          → lake silver               (curated/silver/facts, Parquet)
            → lake raw                (raw/companyfacts/dt=…, SHA-256 in manifest)
              → accession number
                → https://www.sec.gov/Archives/edgar/data/320193/…
```

`GET /audit/{request_id}/lineage` renders it. Assembled from the audit record,
the dbt manifest and the raw manifest rather than from a separate lineage store
that could disagree with them.

---

## 9. What I would do differently at 100× scale

At 30,000 companies with full text, five things break. Ordered by when they
would bite.

**1. The single DuckDB file.** The current topology shares one file between the
API, Spark and Airflow. Correct and fast on one host; it does not survive a
second one. First change: the lake becomes the only shared state (it already is,
in R2), and the warehouse becomes BigQuery for everything rather than a local
DuckDB with BigQuery as an alternate target. The `duckdb` target stays as the
local development path — one engine for laptops, one for the cluster, same
models — which is already how `profiles.yml` is structured.

**2. Full-refresh dbt builds.** Rebuilding every mart nightly is fine at 300
companies and absurd at 30,000. `fct_financial_fact` becomes incremental on
`filed_date`, with a periodic full refresh to catch restatements of old periods —
which incremental logic keyed on filing date will otherwise miss, because a
restatement of FY2019 arrives with a 2026 filing date and *should* update a 2019
row. That subtlety is why incremental was not done prematurely: getting it
slightly wrong produces a warehouse that is quietly stale in exactly the periods
people ask about.

**3. Exact vector scoring.** Currently a filtered exact scan, which is the right
call at ~20k chunks and pre-filtered candidate sets. At 2M chunks the HNSW index
becomes load-bearing rather than optional, and the pre-filter/post-filter
trade-off inverts: filtered ANN search with an aggressive `ef_search`, and
accepting approximate recall. The interface already accommodates it
(`create_ann_index`), so this is a tuning change rather than a rewrite.

**4. Sequential ingest.** SEC's 10 req/s ceiling is the binding constraint and it
is per-IP, so parallelism does not help — 30,000 companies is roughly an hour of
wall clock at the ceiling for metadata alone, and days with documents. At that
scale the right answer is to stop polling per-company and consume the daily index
files instead, pulling only what changed. That is a different ingest strategy,
not a bigger version of this one.

**5. Per-request LLM calls.** Router + SQL-gen + synthesis is three calls per
question, and the router's latency lands on every one. At scale: cache the
schema-catalogue prefix (already structured for it — the catalogue is byte-stable
and sits at the front of the system prompt), batch the eval harness through the
Batch API at half price, and consider a fine-tuned small model for routing, which
is a bounded classification problem with abundant labelled data from the audit
log.

**What would not change.** The verifier, the concept mapping, and the governance
model all get *more* valuable with scale, not less. They are the parts worth
keeping.

---

## 10. Limitations

Stated here rather than discovered by a reviewer.

- **Numbers in filing text are not verified.** The verifier reconciles against
  the warehouse. A figure quoted from MD&A prose has no structured counterpart
  to check against and is served on the strength of its citation alone.
- **Section extraction is heuristic.** Item detection works on most modern
  inline-XBRL filings and degrades on pre-2010 and image-heavy documents. Those
  fall back to a whole-document section, which chunks and embeds usefully but
  cannot be filtered by item.
- **SIC, not GICS.** The only industry classification EDGAR publishes is dated
  and coarse. Sector comparisons inherit that.
- **No reranker.** The hook exists and is unimplemented.
- **Demo-grade authentication.** JWT with a config secret and seeded users. Real
  deployments should front this with Supabase Auth or an IdP and keep only the
  principal mapping.
- **The text corpus is ten companies.** By design (§3), but it means most
  narrative questions about the wider universe correctly return nothing.
- **Retrieval recall is unmeasured** until relevant chunks are labelled against
  a pinned corpus snapshot. Reported as N/A rather than estimated.

---

## Appendix: running it

```bash
make setup                          # venv + dependencies
cp .env.example .env                # set FINLENS_SEC_USER_AGENT
make test                           # 271 unit tests, no network

finlens-ingest structured --limit 50   # XBRL for 50 companies
finlens-ingest text                    # 10-K text for the text universe
make spark                             # raw → silver  (needs Java)
make warehouse                         # dbt build + tests
finlens-embed build --rebuild          # chunk + embed

finlens-ask ask "What was Apple's revenue in fiscal 2023?"
finlens-eval run                       # the golden set
make api                               # serve on :8000
```

Costs nothing to run. SEC requires a real contact address in
`FINLENS_SEC_USER_AGENT` — requests without one get blocked at the edge.
