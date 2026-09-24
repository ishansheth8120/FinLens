-- Row-level security for the filing chunk store (Supabase Postgres).
--
-- This is the strong half of the access control. The SQL rewrite in
-- `finlens/governance/access.py` protects the DuckDB warehouse because DuckDB
-- has no RLS; here the database itself refuses the rows, so a bug in the
-- application cannot leak them.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f finlens/governance/sql/rls.sql

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- The corpus
-- ---------------------------------------------------------------------------

create table if not exists filing_chunks (
    id              bigserial primary key,
    chunk_id        text not null unique,
    section_id      text not null,
    cik             text not null,
    ticker          text,
    company_name    text,
    accession       text not null,
    form            text not null,
    filing_date     date,
    fiscal_year     int not null,
    item_section    text,
    heading_path    text,
    citation_label  text,
    chunk_index     int not null default 0,
    token_estimate  int,
    content         text not null,
    source_url      text not null,
    -- 384 dimensions: bge-small-en-v1.5. Not arbitrary - 768-dim vectors over
    -- this corpus would not fit in Supabase's 500 MB free tier alongside the
    -- text, and the retrieval difference on financial prose is small.
    embedding       vector(384),
    created_at      timestamptz not null default now()
);

-- HNSW over cosine distance. Built after bulk load, not before: incremental
-- insertion into an HNSW graph is far slower than one build at the end.
create index if not exists filing_chunks_embedding_idx
    on filing_chunks using hnsw (embedding vector_cosine_ops);

-- Metadata filters run *before* the vector scan on almost every real query
-- ("Apple's risk factors in 2023"), so these matter as much as the ANN index.
create index if not exists filing_chunks_cik_year_idx on filing_chunks (cik, fiscal_year);
create index if not exists filing_chunks_item_idx     on filing_chunks (item_section);

-- Lexical half of hybrid search. A generated column so it can never drift out
-- of sync with `content`.
alter table filing_chunks
    add column if not exists content_tsv tsvector
    generated always as (to_tsvector('english', content)) stored;

create index if not exists filing_chunks_tsv_idx on filing_chunks using gin (content_tsv);

-- ---------------------------------------------------------------------------
-- Entitlements
-- ---------------------------------------------------------------------------

create table if not exists user_entity_access (
    user_id     uuid not null,
    cik         text not null,
    granted_at  timestamptz not null default now(),
    granted_by  text,
    primary key (user_id, cik)
);

create index if not exists user_entity_access_user_idx on user_entity_access (user_id);

-- An explicit wildcard row rather than a boolean column on a users table:
-- one mechanism, one place to audit, and revoking is a single delete.
create or replace function has_entity_access(target_cik text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
    select exists (
        select 1
        from user_entity_access
        where user_id = auth.uid()
          and (cik = target_cik or cik = '*')
    );
$$;

-- ---------------------------------------------------------------------------
-- The policies
-- ---------------------------------------------------------------------------

alter table filing_chunks       enable row level security;
alter table user_entity_access  enable row level security;

-- Force RLS for the table owner too. Without this, the role that created the
-- table bypasses every policy - which is exactly the role a careless
-- connection string uses, and the reason RLS demos so often prove nothing.
alter table filing_chunks       force row level security;
alter table user_entity_access  force row level security;

drop policy if exists filing_chunks_select on filing_chunks;
create policy filing_chunks_select
    on filing_chunks
    for select
    to authenticated
    using (has_entity_access(cik));

-- Read-only for application roles. Loading is done by the service role, which
-- bypasses RLS by design.
drop policy if exists filing_chunks_no_write on filing_chunks;
create policy filing_chunks_no_write
    on filing_chunks
    for all
    to authenticated
    using (false)
    with check (false);

-- Users may see their own grants and no one else's.
drop policy if exists user_entity_access_self on user_entity_access;
create policy user_entity_access_self
    on user_entity_access
    for select
    to authenticated
    using (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- Hybrid search
-- ---------------------------------------------------------------------------
--
-- Reciprocal rank fusion of dense and lexical results, inside the database.
--
-- RRF rather than a weighted blend of scores: cosine similarity and
-- `ts_rank_cd` are not on comparable scales, and any weighting tuned for one
-- query length fails at another. RRF uses only ranks, so it needs no
-- per-corpus calibration. k = 60 is the value from the original paper.
--
-- `security invoker` is load-bearing: the function must run as the caller so
-- the RLS policies above apply to it. A `security definer` search function
-- would quietly bypass every entitlement.

create or replace function search_chunks(
    query_embedding vector(384),
    query_text      text,
    match_limit     int     default 20,
    rrf_k           int     default 60,
    filter_ciks     text[]  default null,
    filter_items    text[]  default null,
    filter_year_min int     default null,
    filter_year_max int     default null
)
returns table (
    chunk_id       text,
    cik            text,
    ticker         text,
    fiscal_year    int,
    item_section   text,
    citation_label text,
    content        text,
    source_url     text,
    score          double precision
)
language sql
stable
security invoker
set search_path = public
as $$
    with filtered as (
        select *
        from filing_chunks
        where (filter_ciks     is null or cik          = any(filter_ciks))
          and (filter_items    is null or item_section = any(filter_items))
          and (filter_year_min is null or fiscal_year >= filter_year_min)
          and (filter_year_max is null or fiscal_year <= filter_year_max)
    ),
    dense as (
        select chunk_id,
               row_number() over (order by embedding <=> query_embedding) as rank
        from filtered
        where embedding is not null
        order by embedding <=> query_embedding
        -- Over-fetch from each arm: a chunk ranked 30th densely and 5th
        -- lexically should still surface, and cannot if each arm is cut at k.
        limit match_limit * 3
    ),
    lexical as (
        select chunk_id,
               row_number() over (
                   order by ts_rank_cd(content_tsv, websearch_to_tsquery('english', query_text)) desc
               ) as rank
        from filtered
        where query_text is not null
          and content_tsv @@ websearch_to_tsquery('english', query_text)
        limit match_limit * 3
    ),
    fused as (
        select coalesce(d.chunk_id, l.chunk_id) as chunk_id,
               coalesce(1.0 / (rrf_k + d.rank), 0.0)
             + coalesce(1.0 / (rrf_k + l.rank), 0.0) as score
        from dense d
        full outer join lexical l on d.chunk_id = l.chunk_id
    )
    select c.chunk_id, c.cik, c.ticker, c.fiscal_year, c.item_section,
           c.citation_label, c.content, c.source_url, f.score
    from fused f
    join filing_chunks c on c.chunk_id = f.chunk_id
    order by f.score desc
    limit match_limit;
$$;

-- ---------------------------------------------------------------------------
-- Demo entitlements
-- ---------------------------------------------------------------------------
-- Two users, different scopes, so the same question returns different answers.
-- Replace the UUIDs with real `auth.users` ids.
--
-- insert into user_entity_access (user_id, cik, granted_by) values
--   ('00000000-0000-0000-0000-000000000001', '*',          'bootstrap'),
--   ('00000000-0000-0000-0000-000000000002', '0000320193', 'bootstrap'),
--   ('00000000-0000-0000-0000-000000000002', '0000789019', 'bootstrap')
-- on conflict do nothing;
