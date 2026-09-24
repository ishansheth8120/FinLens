# Deploying FinLens

Everything here is free. The only money in the project is a domain.

---

## 1. Accounts

Roughly 45 minutes, all free, none needs a card.

| Service | What for | Where |
|---|---|---|
| Google AI Studio | Gemini Flash API key | aistudio.google.com/apikey |
| Groq | Fallback LLM key | console.groq.com/keys |
| Cloudflare | R2 object storage, 10 GB | dash.cloudflare.com → R2 |
| Google Cloud | BigQuery sandbox, 10 GB + 1 TB/mo | console.cloud.google.com |
| Supabase | Postgres + pgvector, 500 MB | supabase.com |
| Hugging Face | Spaces hosting | huggingface.co |

Nothing breaks if you skip one — the corresponding component falls back to a
local implementation, and `/health` says which.

---

## 2. Cloudflare R2

Create a bucket named `finlens`, then **Manage API Tokens** → create a token
with Object Read & Write.

```bash
FINLENS_STORAGE_BACKEND=s3
FINLENS_STORAGE_BUCKET=finlens
R2_ENDPOINT_URL=https://<account_id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
```

Two R2-specific details that will otherwise cost an afternoon: the region must
be `auto` (R2 has no regions, and boto3 signing fails with anything else), and
path-style access must be on (R2 has no virtual-host addressing, so without it
every read 404s). Both are already set in `finlens/storage/s3.py`.

---

## 3. BigQuery sandbox

The sandbox tier needs no billing account. It has one consequence worth knowing
in advance: **every table gets a 60-day expiry**, whether you ask for it or not.
For a rebuilt-nightly warehouse that is irrelevant; for anything you want to
keep, export to R2.

```bash
gcloud auth application-default login
bq mk --location=US finlens

export GCP_PROJECT=your-project-id
export FINLENS_DBT_TARGET=bigquery
make warehouse
```

`maximum_bytes_billed` is set to 10 GB in `profiles.yml` — a guardrail against
one runaway scan eating the monthly terabyte.

---

## 4. Supabase + pgvector

Project Settings → Database → Connection string (use the **session** pooler for
long-lived connections).

```bash
export SUPABASE_DB_URL='postgresql://...'
psql "$SUPABASE_DB_URL" -f finlens/governance/sql/rls.sql
```

That script creates `filing_chunks`, the HNSW index, the FTS index, the
`user_entity_access` entitlement table, the RLS policies, and the
`search_chunks` hybrid search function.

Then grant entitlements to your demo users:

```sql
insert into user_entity_access (user_id, cik, granted_by) values
  ('<admin-uuid>',   '*',          'bootstrap'),
  ('<analyst-uuid>', '0000320193', 'bootstrap'),
  ('<analyst-uuid>', '0000789019', 'bootstrap');
```

Set `FINLENS_VECTOR_BACKEND=pgvector` and rebuild the index.

**Check RLS actually works** before believing the demo. The two ways it silently
does not: the table owner bypasses policies unless `FORCE ROW LEVEL SECURITY` is
set (it is, in the script), and a `security definer` search function bypasses
them too (`search_chunks` is `security invoker`, deliberately). Verify by
querying as each role and confirming the row counts differ.

---

## 5. Building the data

The ingest is the slow part, and it is rate-limited by SEC rather than by your
machine.

```bash
finlens-ingest structured --limit 300   # ~15 min at 8 req/s
finlens-ingest text                     # ~10 min, 10 companies × 5 filings
make spark                              # needs Java 11+
make warehouse
finlens-embed build --rebuild           # ~20 min on CPU
```

Then check it:

```bash
finlens-embed stats
finlens-ask ask "What was Apple's revenue in fiscal 2023?"
```

---

## 6. Hugging Face Spaces

Create a Space with the **Docker** SDK. The image expects port 7860 and uid
1000, both already set in `Dockerfile.space`.

```bash
git remote add space https://huggingface.co/spaces/<user>/finlens
git push space main
```

Set these as Space secrets (Settings → Variables and secrets):

```
GOOGLE_API_KEY
GROQ_API_KEY
FINLENS_SEC_USER_AGENT
FINLENS_JWT_SECRET
SUPABASE_DB_URL          # if using pgvector
```

The Space ships the prebuilt `data/` directory in the image. A Space has
ephemeral disk and no Spark, so rebuilding on cold start is not an option —
build the warehouse and index in CI, commit or upload them, and treat the Space
as read-only.

---

## 7. Domain

The single highest-value purchase in the project. A `.dev` or `.xyz` is
₹200–800/year.

Cloudflare DNS → CNAME to the Space's `*.hf.space` hostname, then add the custom
domain in the Space settings.

---

## 8. Cost

| | Monthly |
|---|---|
| Everything above | ₹0 |
| Domain | ~₹40 amortised |

The limits that would actually bite first, in order: Supabase's 500 MB (which is
why embeddings are 384-dimensional and the text corpus is ten companies),
Gemini's requests-per-minute during an eval run (which is why there is a
fallback chain), and BigQuery's 1 TB of queries (which a warehouse this size
will not approach).
