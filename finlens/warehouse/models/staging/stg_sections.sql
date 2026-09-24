{{ config(materialized = 'view') }}

with source as (

    select * from {{ source('silver', 'sections') }}

)

select
    section_id,
    cast(cik as varchar)            as cik,
    accession_number,
    form,
    cast(filing_date as date)       as filing_date,
    cast(fiscal_year as integer)    as fiscal_year,
    nullif(trim(item), '')          as item,
    nullif(trim(title), '')         as section_title,
    cast(ordinal as integer)        as ordinal,
    text                            as section_text,
    cast(char_count as integer)     as char_count,
    cast(word_count as integer)     as word_count,
    source_path

from source
-- A "section" of under 200 characters is a heading with no body. Indexing it
-- costs an embedding and returns noise.
where char_count >= 200
