{{
  config(
    materialized = 'table',
    tags = ['dim']
  )
}}

-- One row per company, with the filing-activity summary the agent needs to
-- answer "do we have data for X?" without a second query.

with companies as (

    select * from {{ ref('stg_companies') }}

),

filing_activity as (

    select
        cik,
        count(*)                                                as filing_count,
        min(filing_date)                                        as first_filing_date,
        max(filing_date)                                        as latest_filing_date,
        max(case when base_form = '10-K' then filing_date end)  as latest_10k_date,
        max(case when base_form = '10-Q' then filing_date end)  as latest_10q_date

    from {{ ref('stg_filings') }}
    group by cik

),

fact_coverage as (

    select
        cik,
        count(*)                    as fact_count,
        min(calendar_year)          as first_fact_year,
        max(calendar_year)          as latest_fact_year

    from {{ ref('stg_facts') }}
    where is_latest
    group by cik

)

select
    c.cik,
    c.ticker,
    c.company_name,
    c.exchange,
    c.sic_code,
    c.sic_description,
    {{ sic_sector('c.sic_code') }}      as sector,
    c.fiscal_year_end,
    c.state_of_incorporation,

    coalesce(f.filing_count, 0)         as filing_count,
    f.first_filing_date,
    f.latest_filing_date,
    f.latest_10k_date,
    f.latest_10q_date,

    coalesce(x.fact_count, 0)           as fact_count,
    x.first_fact_year,
    x.latest_fact_year,

    -- Cheap guard for the agent: a company with no XBRL history cannot answer
    -- a numeric question, and saying so beats returning an empty result set.
    coalesce(x.fact_count, 0) > 0       as has_financial_data

from companies c
left join filing_activity f on f.cik = c.cik
left join fact_coverage   x on x.cik = c.cik
