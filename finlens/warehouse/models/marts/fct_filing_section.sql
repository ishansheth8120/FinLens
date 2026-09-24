{{
  config(
    materialized = 'table',
    tags = ['fct', 'rag']
  )
}}

-- The retrieval corpus, denormalised.
--
-- The vector index stores an ID and an embedding; everything a citation needs -
-- company name, ticker, form, date, URL - is joined on here so the RAG path
-- reads one table and never has to fan out to build a source line.

with sections as (

    select * from {{ ref('stg_sections') }}

)

select
    s.section_id,
    s.cik,
    c.ticker,
    c.company_name,
    c.sector,

    s.accession_number,
    s.form,
    s.filing_date,
    s.fiscal_year,

    s.item,
    s.section_title,
    s.ordinal,
    s.section_text,
    s.char_count,
    s.word_count,

    f.filing_url,

    -- Pre-built citation label. Generated in SQL rather than in a prompt so
    -- every citation in every answer is formatted identically and is testable.
    coalesce(c.ticker, c.company_name, s.cik)
        || ' ' || s.form
        || ' ' || cast(s.fiscal_year as varchar)
        || coalesce(', Item ' || s.item, '')
        || coalesce(' - ' || s.section_title, '')   as citation_label

from sections s
left join {{ ref('dim_company') }} c on c.cik = s.cik
left join {{ ref('dim_filing') }}  f
    on  f.cik = s.cik
    and f.accession_number = s.accession_number
