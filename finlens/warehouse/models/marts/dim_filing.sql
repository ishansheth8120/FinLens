{{
  config(
    materialized = 'table',
    tags = ['dim']
  )
}}

with filings as (

    select * from {{ ref('stg_filings') }}

),

section_coverage as (

select
    cik,
    accession_number,
    count(*)        as section_count,
    sum(word_count) as total_words
from {{ ref('stg_sections') }}
group by cik, accession_number

)

select
    f.accession_number,
    f.cik,
    c.ticker,
    c.company_name,
    f.form,
    f.base_form,
    f.is_amendment,
    f.filing_date,
    f.report_date,
    f.days_to_file,
    f.primary_document,
    f.event_items,
    f.size_bytes,
    f.is_xbrl,
    f.is_inline_xbrl,

    coalesce(s.section_count, 0)            as section_count,
    coalesce(s.total_words, 0)              as total_words,
    coalesce(s.section_count, 0) > 0        as is_indexed,

    -- Direct link to the document on sec.gov. Every citation the agent emits
    -- resolves through this, so it is built once here rather than in prompts.
    'https://www.sec.gov/Archives/edgar/data/'
        || cast(cast(f.cik as bigint) as varchar) || '/'
        || replace(f.accession_number, '-', '') || '/'
        || coalesce(f.primary_document, '')  as filing_url

from filings f
left join {{ ref('dim_company') }} c on c.cik = f.cik
left join section_coverage s
    on s.cik = f.cik
   and s.accession_number = f.accession_number