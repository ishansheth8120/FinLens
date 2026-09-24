{{
  config(
    materialized = 'view',
    tags = ['facts']
  )
}}

-- Light typing and filtering over the silver fact table. No business logic:
-- anything opinionated (which restatement wins, which concept means "revenue")
-- belongs downstream where it can be tested in isolation.

with source as (

    select * from {{ source('silver', 'facts') }}

),

renamed as (

    select
        fact_sk,
        cast(cik as varchar)                        as cik,
        taxonomy,
        concept,
        label                                       as concept_label,
        unit,
        cast(value as double)                       as value,
        cast(start_date as date)                    as period_start,
        cast(end_date as date)                      as period_end,
        period_type,
        period_kind,
        duration_days,
        cast(fiscal_year as integer)                as reported_fiscal_year,
        fiscal_period                               as reported_fiscal_period,
        cast(calendar_year as integer)              as calendar_year,
        cast(calendar_quarter as integer)           as calendar_quarter,
        calendar_period,
        form,
        cast(filed_date as date)                    as filed_date,
        accession_number,
        is_latest,
        restatement_count,
        value_changed,
        source_path,
        ingested_at

    from source
    where value is not null
      and end_date is not null

)

select *
from renamed
where calendar_year >= {{ var('min_fiscal_year') }}
  -- Facts dated in the future are a tagging error, and they poison "most
  -- recent period" logic by winning every ordering.
  and period_end <= current_date + interval 1 day
