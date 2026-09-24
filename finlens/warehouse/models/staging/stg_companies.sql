{{ config(materialized = 'view') }}

with source as (

    select * from {{ source('silver', 'companies') }}

)

select
    cast(cik as varchar)                    as cik,
    nullif(trim(ticker), '')                as ticker,
    trim(name)                              as company_name,
    nullif(trim(exchange), '')              as exchange,
    nullif(trim(sic), '')                   as sic_code,
    nullif(trim(sic_description), '')       as sic_description,
    nullif(trim(fiscal_year_end), '')       as fiscal_year_end,
    nullif(trim(state_of_incorporation), '') as state_of_incorporation,
    ingested_at

from source
where cik is not null
  and trim(coalesce(name, '')) <> ''
