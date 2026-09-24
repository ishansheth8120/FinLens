{{ config(materialized = 'view') }}

with source as (

    select * from {{ source('silver', 'filings') }}

)

select
    cast(cik as varchar)                as cik,
    accession_number,
    form,
    base_form,
    is_amendment,
    cast(filing_date as date)           as filing_date,
    cast(report_date as date)           as report_date,
    primary_document,
    nullif(trim(items), '')             as event_items,
    cast(size as bigint)                as size_bytes,
    is_xbrl,
    is_inline_xbrl,

    -- Filing lag is a genuine analytical signal: a company that suddenly takes
    -- three weeks longer to file than it ever has is worth asking about.
    date_diff('day', report_date, filing_date) as days_to_file

from source
where accession_number is not null
