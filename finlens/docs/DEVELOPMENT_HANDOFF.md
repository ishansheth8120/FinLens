# FinLens Development Handoff
## Development Recovery / Continuation Notes

**Project:** FinLens  
**Purpose:** Question answering over SEC EDGAR filings using an XBRL financial warehouse + filing-text RAG system behind a routed agent.

**Local repository:**
```text
/Users/ishansheth/Projects/FinLens
```

**Environment:**
- macOS
- Python 3.12
- Virtual environment: `.venv`
- Shell prompt currently appears as:
```text
((.venv) ) ishansheth@... FinLens %
```

---

# 1. What FinLens Is

FinLens is designed as a financial question-answering system over SEC EDGAR data.

The architecture has roughly these layers:

```text
SEC EDGAR
   │
   ├── Raw filings / submissions / companyfacts
   │
   ▼
Ingestion / Spark
   │
   ▼
Curated Silver Data
   │
   ▼
dbt / DuckDB Warehouse
   │
   ├── Financial facts
   ├── Company dimensions
   ├── Filing dimensions
   ├── Company metrics
   └── Filing sections
          │
          ├───────────────┐
          ▼               ▼
     SQL Agent          RAG Index
          │               │
          └──────┬────────┘
                 ▼
              Router
                 │
                 ▼
             FinLens Ask
```

The intended agent decides whether a question should be answered through:

1. **SQL** against the financial warehouse, or
2. **RAG** against filing text.

---

# 2. Repository Structure

Important directories:

```text
FinLens/
├── finlens/
│   ├── agent/
│   ├── api/
│   ├── embed/
│   ├── eval/
│   ├── governance/
│   ├── ingest/
│   ├── spark/
│   ├── storage/
│   └── warehouse/
│
├── data/
│   ├── lake/
│   │   ├── raw/
│   │   └── curated/
│   ├── warehouse/
│   └── index/
│
├── Makefile
├── pyproject.toml
└── .env
```

There is **no `.git` repository at the root**, so normal git history cannot currently be used to recover previous implementation decisions.

---

# 3. Existing Data Before We Started

The project already contained substantial data. This was NOT a fresh setup.

Approximate existing sizes:

```text
data/lake/raw/companyfacts     ~88 MB
data/lake/raw/documents        ~137 MB
data/lake/raw/submissions      ~7.9 MB
data/lake/raw/universe         ~1.7 MB

data/lake/curated/silver/companies   ~16 KB
data/lake/curated/silver/facts      ~52 MB
data/lake/curated/silver/filings    ~2.1 MB
data/lake/curated/silver/sections   ~6.8 MB

data/warehouse/finlens.duckdb       ~42 MB
data/warehouse/audit.duckdb         ~780 KB

data/index/                         initially empty
```

Therefore, the project was already substantially built and populated.

---

# 4. Configuration

`.env` currently contains:

```text
FINLENS_SEC_USER_AGENT="FinLens/0.1 (ishansheth.8120@gmail.com)"
```

This is correctly configured for SEC access.

No LLM API key was found in the environment during our checks.

The configured LLM defaults to Gemini with Groq as fallback.

---

# 5. Important FinLens Configuration

`finlens/config.py` contains the relevant defaults.

Warehouse:

```text
warehouse_backend = duckdb
duckdb_path = REPO_ROOT / "data" / "warehouse" / "finlens.duckdb"
```

dbt:

```text
dbt_project_dir = REPO_ROOT / "finlens" / "warehouse"
dbt_profiles_dir = REPO_ROOT / "finlens" / "warehouse"
```

Vector index:

```text
vector_backend = duckdb
vector_store_path = REPO_ROOT / "data" / "index"
```

Embedding:

```text
provider = sentence-transformers
model = BAAI/bge-small-en-v1.5
dimension = 384
```

Text universe currently includes:

```text
AAPL
MSFT
NVDA
GOOGL
AMZN
META
INTC
TSLA
AMD
CRM
```

Text years begin from 2020.

Relevant filing sections include:

```text
Item 1A
Item 7
Item 7A
```

---

# 6. Makefile Commands

The root `Makefile` contains the main project workflows.

Important targets:

```text
make setup
make setup-spark
make setup-warehouse
make test
make spark
make warehouse
make index
make demo
make api
make eval
```

Relevant definitions:

### Setup

```bash
python3 -m venv .venv
pip install -e '.[all]'
```

### Warehouse

```bash
pip install -e '.[warehouse]'
cd finlens/warehouse && .venv/bin/dbt deps
```

### Index

```bash
.venv/bin/finlens-embed build --rebuild
.venv/bin/finlens-embed stats
```

### API

```bash
.venv/bin/uvicorn finlens.api.main:app --reload --host 0.0.0.0 --port 8000
```

### Demo

```text
ingest → spark → warehouse → index
```

---

# 7. First Problem: Embedding Build Failed

Initially we ran:

```bash
./.venv/bin/finlens-embed build --rebuild
```

The embedding dependency was not properly installed yet.

The application fell back to the `hash` provider and then failed because:

```text
marts.fct_filing_section
```

did not exist.

At this point there were actually two separate problems:

1. The embedding package needed to be installed.
2. The embedding code referenced the wrong DuckDB schema.

---

# 8. Installed Embedding Dependencies

We installed:

```bash
./.venv/bin/pip install -e '.[embed]'
```

This succeeded.

Important installed components included:

```text
sentence-transformers 6.1.0
torch 2.14.0
transformers 5.17.0
numpy
duckdb
```

After this, local sentence-transformer embeddings were available.

---

# 9. dbt / Warehouse Setup

We initially accidentally tried to run dbt from:

```text
FinLens/finlens/warehouse
```

using:

```bash
../.venv/bin/dbt
```

That path was wrong.

From:

```text
FinLens/finlens/warehouse
```

the correct venv is:

```text
../../.venv
```

We then returned to the repository root and confirmed:

```bash
./.venv/bin/dbt --version
```

Result:

```text
dbt 1.12.5
dbt-duckdb 1.11.0
```

---

# 10. Successful dbt Build

From the repository root, we ran:

```bash
./.venv/bin/dbt build \
  --project-dir finlens/warehouse \
  --profiles-dir finlens/warehouse \
  --no-partial-parse
```

The build successfully materialized the important warehouse models.

The dbt project has schema configurations such as:

```yaml
+schema: staging
+schema: marts
+schema: semantic
+schema: reference
```

However, dbt's DuckDB behavior results in actual schemas:

```text
main_staging
main_marts
main_semantic
main_reference
```

rather than bare:

```text
staging
marts
semantic
reference
```

This distinction became important later.

---

# 11. Warehouse Schemas Confirmed

We ran:

```bash
./.venv/bin/python -c "import duckdb; c=duckdb.connect('data/warehouse/finlens.duckdb'); print(c.sql('show schemas').df().to_string(index=False))"
```

The result was:

```text
database_name    schema_name
finlens          main
finlens          main_marts
finlens          main_reference
finlens          main_semantic
finlens          main_staging
```

There is **NO `marts` schema**.

There IS:

```text
main_marts
```

This is a critical fact.

---

# 12. dbt Tests

The dbt build did not achieve a completely clean test run.

One important test failed:

```text
assert_no_overlapping_annual_periods
```

It reported:

```text
Got 897 results, configured to fail if != 0
```

However, the actual warehouse models were still created.

Later runs also showed the `fct_company_metric` uniqueness test being investigated. One run showed duplicate results, while a subsequent run showed that uniqueness test passing.

The final relevant run showed:

```text
PASS=46
WARN=0
ERROR=1
SKIP=6
```

The one remaining failure was:

```text
assert_no_overlapping_annual_periods
```

with 897 results.

This is a **data-quality/test issue**, not the reason the SQL agent currently fails.

Do not confuse this with the SQL guard problem.

---

# 13. Warehouse Models Successfully Created

Important models include:

```text
main_marts.dim_company
main_marts.dim_filing
main_marts.fct_financial_fact
main_marts.fct_company_metric
main_marts.fct_company_annual
main_marts.fct_filing_section
main_semantic.metric_definitions
```

The logs explicitly show dbt creating the models in `main_marts`.

---

# 14. `fct_financial_fact` Schema Inspection

We originally tried:

```sql
SELECT *
FROM main_marts.fct_financial_fact
WHERE ticker='AAPL'
LIMIT 5;
```

This failed because:

```text
ticker
```

is not a column in `fct_financial_fact`.

DuckDB suggested columns such as:

```text
cik
calendar_year
metric_description
calendar_period
calendar_quarter
```

We then ran:

```sql
DESCRIBE main_marts.fct_financial_fact
```

Important columns are:

```text
financial_fact_sk
cik
metric
metric_description
concept
taxonomy
unit
value
period_start
period_end
period_type
period_kind
duration_days
calendar_year
calendar_quarter
calendar_period
reported_fiscal_year
reported_fiscal_period
form
filed_date
accession_number
is_latest
restatement_count
value_changed
```

The table contains data.

A direct:

```sql
SELECT *
FROM main_marts.fct_financial_fact
LIMIT 5
```

worked successfully.

Therefore, the financial warehouse itself is functioning.

---

# 15. `finlens-ask schema`

We ran:

```bash
./.venv/bin/finlens-ask schema
```

The CLI successfully described the intended semantic warehouse.

Important objects:

### `main_marts.dim_company`

One row per SEC registrant.

Includes information such as:

```text
ticker
company_name
sector
has_financial_data
latest_fact_year
```

### `main_marts.dim_filing`

Filing-level dimension.

### `main_marts.fct_company_metric`

Current-value metric time series.

Includes:

```text
period_label
pct_change_year_over_year
```

### `main_marts.fct_company_annual`

Annual company-level metrics.

### `main_marts.fct_financial_fact`

Long-form financial facts, including restatement vintages.

### `main_marts.fct_filing_section`

Filing-text corpus for RAG.

### `main_semantic.metric_definitions`

Semantic definitions of financial metrics.

This confirms that FinLens itself expects these `main_marts` objects.

---

# 16. Embedding Index Problem

The embedding code initially contained:

```sql
FROM marts.fct_filing_section
```

in:

```text
finlens/embed/index.py
```

This was incorrect because the actual DuckDB schema is:

```text
main_marts
```

The project output confirmed both the dbt configuration and this stale reference.

We changed:

```sql
FROM marts.fct_filing_section
```

to:

```sql
FROM main_marts.fct_filing_section
```

using:

```bash
sed -i '' \
's/FROM marts\.fct_filing_section/FROM main_marts.fct_filing_section/' \
finlens/embed/index.py
```

---

# 17. Embedding Build Successfully Completed

We then ran:

```bash
./.venv/bin/finlens-embed build --rebuild
```

This time it worked.

The model loaded:

```text
BAAI/bge-small-en-v1.5
```

It used Apple's MPS backend:

```text
No device provided, using mps
```

The index was created at:

```text
/Users/ishansheth/Projects/FinLens/data/index/chunks.duckdb
```

Final result:

```text
565 sections
6934 chunks
6934 embedded
0 failed batches
```

FTS index was also built.

The final message was essentially:

```text
index.complete
summary='565 sections -> 6934 chunks, 6934 embedded, 0 failed batches'
```

Therefore:

**RAG indexing is currently working.**

Do NOT rebuild this again unless the source corpus or embedding configuration changes.

---

# 18. Mac / Hardware Concern

The embedding process took several minutes and used MPS.

This is normal for local sentence-transformer embedding.

It does not require:

- Docker
- cloud GPU
- another machine
- a VM
- a separate environment

Normal behavior includes:

- increased CPU/GPU usage
- increased RAM usage
- fan activity
- battery drain
- heat

For long embedding jobs, being plugged into power is sensible.

The completed embedding job did not indicate a hardware problem.

---

# 19. RAG Index Status

Current known state:

```text
Vector backend: DuckDB
Embedding provider: sentence-transformers
Model: BAAI/bge-small-en-v1.5
Dimension: 384

Sections: 565
Chunks: 6934
Embeddings: 6934
Failed batches: 0
FTS: built
```

This part should be considered **working**.

---

# 20. SQL Agent Test

We then tested an actual financial question:

```bash
./.venv/bin/finlens-ask explain \
"What was Apple's total revenue in fiscal years 2023, 2024, and 2025?"
```

The router correctly identified the question as SQL-oriented:

```text
route=sql
confidence=0.95
tickers=['AAPL']
```

So routing itself appears to work.

---

# 21. SQL Agent Error #1: Schema Guard

The generated SQL attempted to use:

```text
main_marts.dim_company
main_marts.fct_company_metric
```

The SQL guard rejected it with:

```text
schema not permitted: main_marts
```

This is currently the most important unresolved application bug.

The contradiction is:

```text
DuckDB:
    main_marts EXISTS

FinLens schema command:
    expects main_marts

dbt:
    creates main_marts

SQL guard:
    rejects main_marts
```

Therefore the problem is almost certainly in the **FinLens SQL validation/allowlist layer**, not in DuckDB and not in dbt.

The `agent` optional dependency explicitly includes:

```text
sqlglot>=25.0
```

because the SQL guard uses AST-based SQL validation.

---

# 22. SQL Agent Error #2: Retry Without Schema

After rejecting:

```text
main_marts
```

the agent attempted to strip the schema and retry.

It then generated references such as:

```text
fct_company_metric
```

without a schema.

DuckDB naturally failed because there is no unqualified:

```text
fct_company_metric
```

in the default schema.

The correct object is:

```text
main_marts.fct_company_metric
```

Therefore the retry mechanism makes the original problem worse.

---

# 23. SQL Agent Error #3: Gemini Rate Limiting

The system attempted multiple Gemini calls.

Eventually Gemini calls were rate limited.

There was also a warning that Groq was unavailable because:

```text
GROQ_API_KEY
```

was not set.

So the active provider chain effectively had Gemini available but no Groq fallback.

This is an environment/provider limitation, separate from the SQL guard bug.

---

# 24. SQL Agent Error #4: Invalid Structured SQL Response

Eventually structured SQL generation failed with an error equivalent to:

```text
model did not return a valid GeneratedSql
```

with:

```text
Unterminated string starting at:
line 3 column 18
char 332
```

This indicates malformed structured output from the LLM.

Again, this is separate from the warehouse itself.

---

# 25. RAG Fallback Worked

After the SQL path failed, FinLens automatically fell back to RAG.

The log showed:

```text
rag.retrieved hits=5
```

It retrieved filing sections for:

```text
AAPL 10-K 2023
AAPL 10-K 2024
AAPL 10-K 2025
```

The answer produced values for:

```text
2023: $383.3B
2024: $391.0B
2025: unavailable
```

and noted that 2025 coverage was incomplete.

This proves an important thing:

**The RAG pipeline from query → retrieval → synthesis is functioning.**

The current weakness is primarily the SQL-agent path.

---

# 26. Current Problems, Categorized

## A. FIXED

### Embedding dependency

Fixed by:

```bash
./.venv/bin/pip install -e '.[embed]'
```

### Wrong schema in embedding indexer

Fixed:

```text
marts.fct_filing_section
```

→

```text
main_marts.fct_filing_section
```

### RAG index

Successfully built:

```text
565 sections
6934 chunks
6934 embeddings
0 failed batches
```

### DuckDB warehouse

Confirmed operational.

### dbt model materialization

Confirmed operational.

---

# 27. CURRENTLY BROKEN

## SQL guard schema allowlist

Error:

```text
schema not permitted: main_marts
```

This must be fixed before reliable SQL answering can work.

---

# 28. SECONDARY ISSUE

Gemini structured-output reliability.

Observed:

```text
rate limit
```

and:

```text
Unterminated string
```

This can be addressed after the SQL guard is fixed.

Potentially the project should:

- improve structured-output handling
- reduce retries
- use a valid fallback provider
- configure `GROQ_API_KEY` if desired
- possibly make SQL generation more deterministic

But **do not tackle this first**.

First make the SQL guard accept the schema that the warehouse actually uses.

---

# 29. DATA QUALITY ISSUE

dbt test:

```text
assert_no_overlapping_annual_periods
```

currently reports:

```text
897 results
```

This should eventually be investigated.

However:

- warehouse models are created
- `fct_filing_section` is valid
- RAG index successfully built
- direct financial-fact queries work

Therefore this is **not the immediate blocker for continuing agent development**.

---

# 30. What NOT To Do When Continuing

Do NOT:

```bash
make clean
```

Do NOT:

```bash
make clean-all
```

Do NOT delete:

```text
data/warehouse
data/index
data/lake
```

Do NOT rerun the full ingestion pipeline.

Do NOT rebuild the embeddings.

Do NOT rebuild dbt unnecessarily.

The expensive/data-producing stages are already substantially complete.

---

# 31. Current Project State

Think of the system as:

```text
                FINLENS CURRENT STATE

SEC RAW DATA ──────────────── WORKING
      │
      ▼
CURATED DATA ──────────────── WORKING
      │
      ▼
DUCKDB WAREHOUSE ──────────── WORKING
      │
      ├── main_marts.dim_company       ✓
      ├── main_marts.dim_filing        ✓
      ├── main_marts.fct_financial_fact ✓
      ├── main_marts.fct_company_metric ✓
      ├── main_marts.fct_filing_section ✓
      └── main_semantic...              ✓
      
RAG INDEX ─────────────────── WORKING
      │
      ├── 565 sections
      ├── 6,934 chunks
      ├── 6,934 embeddings
      └── FTS index
       
ROUTER ────────────────────── WORKING
      │
      └── recognizes SQL question ✓
      
SQL AGENT ─────────────────── BROKEN
      │
      └── SQL guard rejects main_marts
      
RAG AGENT ─────────────────── WORKING
      │
      └── successfully retrieves filing text
      
LLM PROVIDER ──────────────── PARTIAL
      │
      ├── Gemini available but rate limits occurred
      └── Groq unavailable without GROQ_API_KEY
```

---

# 32. Exact Next Step

When development resumes, start from:

```text
/Users/ishansheth/Projects/FinLens
```

with:

```bash
source .venv/bin/activate
```

Then locate the SQL guard.

Run:

```bash
grep -RniE "schema.*(permit|allow)|permit.*schema|allow.*schema|sql.*guard" \
  finlens/agent finlens/api finlens/config.py \
  --exclude-dir=__pycache__
```

The purpose is to find the implementation responsible for:

```text
schema not permitted: main_marts
```

---

# 33. What We Expect To Find

Likely possibilities include an allowlist similar to:

```python
ALLOWED_SCHEMAS = {
    "marts",
    "semantic",
}
```

when it should correspond to the actual DuckDB schemas:

```python
ALLOWED_SCHEMAS = {
    "main_marts",
    "main_semantic",
}
```

OR the guard may be deriving the schema incorrectly from dbt configuration.

**Do not make this change blindly.**

First inspect the actual guard implementation.

---

# 34. Next Development Sequence

Once the guard code is located:

### Step 1
Inspect the guard.

### Step 2
Fix the schema mismatch.

### Step 3
Run a direct SQL-agent test.

For example:

```bash
./.venv/bin/finlens-ask explain \
"What was Apple's total revenue in fiscal years 2023, 2024, and 2025?"
```

### Step 4
If SQL generation works, verify the actual returned numbers directly against DuckDB.

### Step 5
Then address Gemini reliability/rate limits.

### Step 6
Then investigate the 897 annual-period test failures.

### Step 7
Only after that move toward API/UI/evaluation work.

---

# 35. Useful Direct Warehouse Test

When testing financial facts, remember that:

```text
fct_financial_fact
```

does NOT have a ticker column.

It has:

```text
cik
```

Ticker/company information belongs in the dimensional/metric models.

So this is not valid:

```sql
WHERE ticker = 'AAPL'
```

against:

```text
main_marts.fct_financial_fact
```

Instead, inspect the model schema or join through the appropriate company dimension.

---

# 36. Important Working Command Reference

### Activate environment

```bash
cd /Users/ishansheth/Projects/FinLens
source .venv/bin/activate
```

### Check dbt

```bash
./.venv/bin/dbt --version
```

Expected approximately:

```text
dbt 1.12.5
dbt-duckdb 1.11.0
```

### Check schemas

```bash
./.venv/bin/python -c "import duckdb; c=duckdb.connect('data/warehouse/finlens.duckdb', read_only=True); print(c.sql('show schemas').df().to_string(index=False))"
```

Expected:

```text
main
main_marts
main_reference
main_semantic
main_staging
```

### Check FinLens semantic schema

```bash
./.venv/bin/finlens-ask schema
```

### Check embedding index

```bash
./.venv/bin/finlens-embed stats
```

Expected index characteristics:

```text
~6934 chunks
dimension 384
BAAI/bge-small-en-v1.5
```

### Test RAG search

```bash
./.venv/bin/finlens-embed search \
"What are Apple's main business risks?"
```

### Test agent

```bash
./.venv/bin/finlens-ask explain \
"What was Apple's total revenue in fiscal years 2023, 2024, and 2025?"
```

---

# 37. Most Important Recovery Statement

When continuing this project, the correct mental model is:

> **FinLens is not starting from scratch. The data ingestion, DuckDB warehouse, filing-section corpus, embeddings, and RAG retrieval pipeline are already substantially working. The current development task is to repair the SQL-agent layer, beginning with the SQL guard's incorrect rejection of the real `main_marts` schema.**

Do not restart the pipeline.

---

# 38. Current Stop Point

**Development should currently stop at the SQL guard investigation.**

Last known blocker:

```text
schema not permitted: main_marts
```

Next command:

```bash
grep -RniE "schema.*(permit|allow)|permit.*schema|allow.*schema|sql.*guard" \
  finlens/agent finlens/api finlens/config.py \
  --exclude-dir=__pycache__
```

After finding the relevant source, inspect it before modifying anything.

---

## End of Handoff




FinLens, Engineering Progress & Issue Log
1. Project objective
FinLens is a financial intelligence and question-answering system built around SEC EDGAR data.
The intended flow is:
SEC EDGAR
    ↓
Raw Data Lake
    ↓
Spark Ingestion
    ↓
Silver / Curated Data
    ↓
DuckDB + dbt Warehouse
    ↓
 ┌───────────────┐
 │ User Question │
 └───────┬───────┘
         ↓
      Router
      ↙   ↘
    SQL   RAG
     ↓     ↓
 Warehouse Vector Index
     ↘   ↙
    Verification
         ↓
      Synthesis
         ↓
      Answer
The end goal is a polished financial research terminal rather than simply a backend demo.
2. Initial project architecture
The project already had a fairly complete backend before we resumed work.
Core stack
Layer	Technology
Language	Python 3.12
Data source	SEC EDGAR
Ingestion	Apache Spark
Data lake	Local filesystem
Warehouse	DuckDB
Transformations	dbt
Vector DB	DuckDB
Embeddings	Sentence Transformers
Embedding model	BAAI/bge-small-en-v1.5
RAG	Custom implementation
LLM primary	Gemini
LLM fallback	Groq
API	FastAPI
CLI	Typer
SQL validation	SQLGlot
Data models	Pydantic
Testing	Pytest
Frontend	Next.js / React, now being added


3. Data pipeline issues
Issue #1, Warehouse schema wasn't where the embedding code expected
The embedding code originally queried:
marts.fct_filing_section
But the actual DuckDB schema was:
main_marts
main_reference
main_semantic
main_staging
So the actual table was:
main_marts.fct_filing_section
Fix
We changed:
marts.fct_filing_section

to:
main_marts.fct_filing_section

in:
finlens/embed/index.py
Result
The embedding build then succeeded.
565 sections
↓
6934 chunks
↓
6934 embedded
↓
0 failed batches
FTS was also successfully built.
Index:
data/index/chunks.duckdb
4. Embedding/index problem solved
The final embedding configuration is:
Provider: sentence-transformers
Model: BAAI/bge-small-en-v1.5
Dimension: 384
Device: Apple MPS
The index rebuild command:
finlens-embed build --rebuild
worked successfully.
This established that the entire:
filing sections
→ chunking
→ embeddings
→ vector index
→ retrieval
pipeline is operational.
5. dbt issue
There was an annual overlap test failure.
Approximately:
897 overlaps
were reported by a dbt test.
However, importantly:
fct_filing_section
was successfully built and the RAG system was able to use it.
Decision
We did not blindly rebuild the entire warehouse.
Reason:
The actual required mart existed and the RAG pipeline was functional. The overlap issue needed separate investigation rather than destabilizing the working pipeline.
This remains a known technical debt item.
6. LLM provider problems
This was one of the bigger issues.
Initially FinLens was configured around Gemini.
The first real LLM requests encountered:
503 Service Unavailable
from Gemini due to high demand.
Later we hit:
429 quota exhausted
The error indicated the Gemini free-tier request limit had been reached.
The important lesson was:
Gemini's free API access is quota-based, not an unlimited lifetime free API.

7. Gemini model configuration
The configuration originally had:
gemini-2.0-flash
but the runtime configuration was changed to:
gemini-3.6-flash
The Gemini provider itself was tested independently.
Result:
FINLENS_OK
provider = gemini
model = gemini-3.6-flash
So the provider implementation itself was working.
The problem was availability/quota rather than basic integration.
8. Groq fallback added
Rather than depending entirely on Gemini, we added Groq as a fallback provider.
Current architecture:
Gemini
   ↓ failure
Groq
Configuration:
llm_provider = gemini
llm_fallback_providers = ["groq"]
Groq model was changed from the stale:
llama-3.3-70b-versatile
to:
openai/gpt-oss-120b
9. Groq integration issue
We needed the Groq Python package.
Installed:
groq 1.7.0
The Groq provider was then tested independently.
Result:
GROQ_OK
provider = groq
model = openai/gpt-oss-120b
So Groq was operational.
10. Automatic LLM fallback verified
This was an important milestone.
We temporarily used an invalid Gemini model.
The provider chain reported:
['gemini', 'groq']
Gemini failed with:
404
The system automatically switched to Groq.
Result:
FALLBACK_OK
So the actual production architecture now has resilience against:
- Gemini outages
- Gemini quota exhaustion
- Gemini temporary failures
- model availability problems
without requiring the caller to manually switch providers.
11. SQL generation issue
We then tested the actual financial question:
What was Apple's revenue in 2024?

The router correctly identified:
Route: SQL
Entity: AAPL
Metric: revenue
Year: 2024
However, the first generated SQL was wrong.
It attempted to use:
fiscal_year
on a table that did not contain that column.
The actual schema used a different temporal representation, including:
calendar_period
in the relevant table.
12. SQL repair loop
Fortunately, the SQL generation architecture already had a repair mechanism.
Current design:
Generate SQL
     ↓
SQL Guard
     ↓
Execute
     ↓
Failure?
     ↓
Send SQL + error back to LLM
     ↓
Generate repaired SQL
Maximum repairs:
2
This is implemented in:
finlens/agent/sql_gen.py
13. SQL repair succeeded syntactically, but another problem appeared
On the second test, the first SQL attempt failed with:
Table "m" does not have a column named "fiscal_year"
The model repaired the SQL.
This time the SQL was valid.
But:
rows = 0
The system logged:
sql_gen.succeeded attempt=2 rows=0
This is an important unresolved issue.
Why this matters
A query can be:
syntactically valid
+
allowed by SQL guard
+
successfully executed
while still being semantically wrong because it returned nothing.
Currently the system treats:
SQL executed successfully
as success even when:
0 rows
14. Current solution to zero-row SQL
At present, the orchestrator falls back to RAG when SQL doesn't provide useful results.
So the actual execution became:
SQL
 ↓
0 rows
 ↓
RAG fallback
 ↓
filing retrieval
 ↓
LLM synthesis
This allowed the question to still be answered.
But this is not yet the ideal architecture.
Future fix
For numeric/entity-specific questions, we should distinguish:
SQL execution success
from:
SQL answer success
A zero-row result should potentially trigger:
repair / alternate query / entity resolution
before immediately falling back to RAG.
This is currently one of our backend hardening priorities.
15. RAG pipeline then worked
For the Apple revenue question, RAG retrieved:
5 filing sections
The relevant 2024 10-K text contained Apple's reported revenue.
The synthesis produced:
Apple reported total net sales of $391.0 billion for fiscal year 2024.

The system also generated:
1 claim
1 citation
unverified = 0
So the citation/verifier/synthesis pipeline worked.
16. Important warning from the Apple test
Although the final answer was correct, the system warned that the warehouse query returned nothing.
So the answer came from filing text rather than the warehouse.
Conceptually:
Warehouse
   ↓
0 rows
   ↓
RAG
   ↓
Apple 2024 10-K
   ↓
$391.0B
This is useful because it exposed a real product-quality distinction:
FinLens should tell the user whether an answer came from structured financial data, filing evidence, or both.

That will eventually become part of the UI.
17. Performance issue discovered
The Apple question took approximately:
81.7 seconds
with around:
15,267 tokens
That is obviously too slow for a polished financial research interface.
The reason was not one single component. The request went through several expensive operations:
Router
 ↓
SQL generation
 ↓
SQL failure
 ↓
LLM repair
 ↓
0 rows
 ↓
RAG
 ↓
retrieval
 ↓
synthesis
So the backend currently does more work than necessary.
This is another reason we want to improve:
- SQL generation accuracy
- zero-row handling
- routing
- model selection
- prompt size
- unnecessary fallback behavior
18. Existing API discovery
We then inspected the FastAPI layer.
The backend already exposes considerably more functionality than initially expected.
Main API
POST /ask
This executes the FinLens agent and returns structured answer information.
The response includes:
request_id
question
answer
route
citations
sql
verification
warnings
reasoning
usage
elapsed_ms
  Pasted text
19. Streaming API discovered
More importantly, the backend already has:
POST /ask/stream
which exposes SSE events.
It can stream events such as:
routing
route
SQL
citations
verification
answer paragraphs
done
  Pasted text
This is excellent for the frontend because we don't need to fake a loading animation.
The UI can actually show:
ROUTER       ✓
SQL ENGINE   ✓
RAG          ...
VERIFY       ...
SYNTHESIS    ...
as the backend progresses.
20. Existing catalog APIs
We also discovered existing company/filing APIs:
GET /companies
GET /companies/{cik}
GET /companies/{cik}/filings
GET /metrics
  Pasted text
This means the frontend can eventually support:
Search Apple
↓
Company page
↓
Financial metrics
↓
Filings
↓
Ask questions about company
without requiring us to build a separate backend catalog system.
21. Existing health APIs
Already available:
GET /health
GET /ready
  Pasted text
These can be used by the frontend/system status indicator.
For example:
FINLENS
● API ONLINE
● WAREHOUSE READY
● INDEX READY
● LLM ONLINE
22. Existing UI discovered
There was already an HTML/HTMX interface.
It includes:
- answer
- route
- user
- verification
- citations
- warnings
- SQL
- SQL results
- retrieval excerpts
- timing
- tokens
- provider
- audit
- lineage
  Pasted text
The actual answer page also exposes the detailed diagnostics.   Pasted text
Decision
We are not throwing away the backend functionality.
We're replacing the presentation layer.
The existing HTMX UI becomes effectively our reference for what information the new frontend should expose.
23. Frontend decision
We discussed whether to use Streamlit.
Decision:
Not Streamlit for the final product.
Instead:
Next.js
React
TypeScript
Tailwind
shadcn/ui
Framer Motion
Recharts
Lucide
with:
Next.js frontend
       ↓
FastAPI
       ↓
FinLens Agent
       ↓
DuckDB / RAG / LLM
Reason: we want a real product-like interface with:
- responsive mobile UI
- polished animations
- financial charts
- company pages
- streaming responses
- command/search interface
- evidence panels
- keyboard shortcuts
- responsive layouts
- richer interaction
24. Frontend design direction
The agreed visual direction is roughly:
Bloomberg Terminal × Palantir × modern AI research terminal

Not literally copying either product.
Visual characteristics
Almost-black background
+
Dark panels
+
Thin borders
+
High contrast
+
Minimal color
+
Monospace financial data
+
Modern sans-serif UI
Accent semantics:
Cyan    → interactive / primary
Green   → positive financial movement
Red     → negative movement
Amber   → warning
White   → primary information
Gray    → secondary information
We specifically want to avoid the cliché:
everything = green hacker text
The interface should feel sophisticated rather than gimmicky.
25. Planned frontend screens
Home
FINLENS

SEC INTELLIGENCE TERMINAL

[ Ask anything about public companies... ]

Suggested:
• What was Apple's revenue in 2024?
• Compare NVIDIA and AMD gross margin
• Show Microsoft's revenue growth
• What did Tesla say about AI?
Answer screen
Large financial result:
AAPL
FY2024 REVENUE

$391.0B
Then:
Answer
Evidence
Sources
Verification
Pipeline
Evidence drawer
Show:
SEC Filing
10-K
2024

Relevant excerpt
↓
Citation
↓
Source
Pipeline
Potentially:
ROUTER       ✓
WAREHOUSE    ✓
RAG          ✓
VERIFIER     ✓
SYNTHESIS    ✓
Company intelligence
AAPL
Apple Inc.

Revenue
Gross Margin
Revenue Growth
...

Financial charts
Filings
Ask about Apple
26. Mobile requirement
The frontend is explicitly being designed for:
Desktop / laptop
+
tablet
+
mobile
We don't want a desktop interface merely squeezed into a phone.
For example:
Desktop:
┌──────────────┬─────────────────────────┐
│ NAV          │ ANSWER                  │
│              │                         │
│ Companies    │ $391.0B                 │
│ Filings      │ Apple FY2024 Revenue    │
│              │                         │
│              │ Evidence                │
└──────────────┴─────────────────────────┘
Mobile:
┌─────────────────────┐
│ FINLENS        ☰    │
├─────────────────────┤
│                     │
│ $391.0B             │
│ FY2024 Revenue      │
│                     │
│ Answer              │
│                     │
│ Evidence            │
│                     │
│ Pipeline             │
└─────────────────────┘
27. Current frontend setup problem
We created:
/Users/ishansheth/Projects/FinLens/frontend
using:
npx create-next-app@latest .
Next.js creation itself started successfully.
But npm failed with:
EACCES
specifically:
/Users/ishansheth/.npm/_cacache/...
The error explained that the npm cache contains root-owned files.
So this is an environment permission problem, not a Next.js problem.
28. Current frontend fix
We are fixing it with:
sudo chown -R 501:20 ~/.npm
Then:
npm cache verify
npm install
npm install framer-motion lucide-react recharts
After that:
npm run dev
29. Current state
So right now FinLens is approximately here:
                    FINLENS
                       │
                       ▼
                 SEC EDGAR DATA
                       │
                       ▼
                Spark ingestion
                       │
                       ▼
                  Data Lake
                       │
                       ▼
                 dbt + DuckDB
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
          SQL/RAG             Vector Index
             │                   │
             └─────────┬─────────┘
                       ▼
                  FinLens Agent
                       │
                ┌──────┴──────┐
                ▼             ▼
             Gemini          Groq
             primary        fallback
                │             │
                └──────┬──────┘
                       ▼
                    FastAPI
                       │
                       ▼
                ┌──────────────┐
                │   Next.js    │ ← WE ARE HERE
                │   FRONTEND   │
                └──────────────┘
30. Remaining known technical debt
These are the things I would not forget from our previous work:
Backend
P0 / important
- SQL generation occasionally chooses the wrong schema/column.
- SQL can return 0 rows while being treated as successful.
- Entity/ticker resolution needs stronger handling.
- Numeric questions should prefer structured warehouse evidence.
- RAG fallback should be intentional rather than accidental.
- 80s response time needs optimization.
P1
- Investigate the ~897 annual overlap dbt test failures.
- Improve citation/evidence cross-checking.
- Reduce token usage.
- Potentially cache common questions/queries.
- Improve observability around routing and fallback.
Frontend
- Finish Next.js installation.
- Build design system.
- Build query interface.
- Connect /ask.
- Connect /ask/stream.
- Build streaming pipeline UI.
- Build answer/result cards.
- Build evidence drawer.
- Build company pages.
- Add charts.
- Add mobile navigation.
- Add loading/error/empty states.
- Add query history.
- Add keyboard shortcuts.
31. Most important lessons from the debugging
There are a few architectural lessons worth preserving.
1. "It executes" doesn't mean "it answered"
Our SQL example proved this:
SQL valid
      ≠
SQL useful
We need semantic validation.
2. LLM providers should be interchangeable
The Gemini → Groq fallback proved valuable.
3. Structured financial questions should use structured data first
For:
revenue
margin
EPS
growth
market metrics
we should prioritize the warehouse.
For:
What did management say about AI?
Why did margins decline?
What risks did Apple mention?
RAG is more appropriate.
4. Evidence needs to be a first-class product feature
FinLens shouldn't just say:
$391B
It should be able to show:
$391B
FY2024
Apple 10-K
SEC evidence
5. The existing backend is further along than the frontend
We don't need to rebuild FinLens.
We're primarily hardening the agent and building the product interface around it.
Current milestone
We're now moving from:
"Can FinLens technically answer financial questions?"
to:
"Can FinLens feel like a real financial intelligence product?"
And the immediate step is simply getting the Next.js dependency installation clean. Once that succeeds, we can start building the actual UI rather than spending more time on setup.
## Current Debugging Findings: SEC Revenue Query and Warehouse Period Classification

### Problem observed

For the question:

> What was Apple's revenue in fiscal 2024?

FinLens correctly classified the question as an SQL/warehouse query. The SQL generator initially used a non-existent `fiscal_year` column, while the warehouse uses `reported_fiscal_year`, `reported_fiscal_period`, `calendar_year`, and `calendar_period`.

The generated SQL was subsequently executable but returned zero rows. FinLens then correctly fell back to RAG/SEC filing evidence and produced Apple's FY2024 revenue as $391.035 billion based on reported net sales.

### Warehouse findings

The actual warehouse contains the relevant Apple FY2024 data in:

`main_marts.fct_financial_fact`

Important columns include:

- `cik`
- `metric`
- `value`
- `period_start`
- `period_end`
- `period_kind`
- `duration_days`
- `calendar_year`
- `calendar_period`
- `reported_fiscal_year`
- `reported_fiscal_period`
- `form`
- `filed_date`
- `accession_number`
- `is_latest`

The Apple 2024 10-K contains comparative historical values. Therefore, filtering only on `reported_fiscal_year = 2024` can return multiple periods.

For Apple's FY2024 revenue, the relevant period ends on `2024-09-28`.

### `is_latest` finding

`is_latest` must not be interpreted as "latest fiscal year."

For Apple's 2024 10-K, a comparative historical record can have `is_latest = true` while the FY2024 record has `is_latest = false`.

This appears to represent latest/restatement-record semantics rather than latest fiscal-period semantics.

### dbt findings

The correct DuckDB database is:

`/Users/ishansheth/Projects/FinLens/data/warehouse/finlens.duckdb`

The dbt profile required `FINLENS_DUCKDB_PATH` to be explicitly set to this location during debugging.

The FastAPI/Uvicorn development server also held a DuckDB lock, so it had to be stopped before running dbt.

Once the lock and path issues were resolved, dbt successfully built the upstream models but failed on:

`assert_no_overlapping_annual_periods`

The test reported 897 overlapping annual-period records.

### Overlapping annual-period finding

Diagnostic results showed examples where the same company/metric had multiple overlapping periods classified as annual, including:

- 2015-07-01 → 2016-06-30
- 2015-10-01 → 2016-09-30
- 2016-01-01 → 2016-12-31
- 2016-04-01 → 2017-03-31

The number and nature of these overlaps suggest that multiple rolling or non-fiscal reporting windows may currently be classified as `period_kind = 'annual'`.

The existing data-quality test should therefore not be weakened or removed until the classification logic is understood.

### Current data flow

`SEC EDGAR / XBRL → ingestion / normalization → silver.facts → stg_facts → fct_financial_fact → curated marts → SQL agent`

`stg_facts` passes `period_kind` through from `silver.facts`. The current repository search has not yet located the code that actually assigns `period_kind`.

### SQL/RAG behavior

The SQL path is preferred for structured financial questions.

If the warehouse query returns no usable result, FinLens falls back to SEC filing text retrieval.

The Apple example demonstrated that this fallback works correctly, but the SQL generation and period semantics need improvement so that valid warehouse records are found directly.

### Latency finding

The Apple request took approximately 88 seconds.

The DuckDB query itself executed in approximately 1.7 ms and RAG retrieval in approximately 343 ms.

The dominant latency came from repeated Gemini rate-limit retries and subsequent LLM calls.

