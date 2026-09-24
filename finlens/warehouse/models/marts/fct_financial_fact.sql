{{
  config(
    materialized = 'table',
    tags = ['fct']
  )
}}

-- The long, metric-resolved fact table. One row per
-- (company, metric, period, restatement-vintage).
--
-- This is the model most generated SQL should hit, because it hides the two
-- things a question-asker should never have to know: that "revenue" is four
-- different XBRL tags depending on the year, and that the same period appears
-- once per filing that restated it.

with facts as (

    select * from {{ ref('stg_facts') }}

),

concept_map as (

    select * from {{ ref('stg_concept_map') }}

),

mapped as (

    select
        f.*,
        m.metric,
        m.priority           as concept_priority,
        m.metric_description

    from facts f
    inner join concept_map m
        on  m.taxonomy = f.taxonomy
        and m.concept  = f.concept

),

-- A company may tag two concepts that both map to `revenue` in the same period.
-- Keep the highest-priority concept per (company, metric, period, vintage).
deduplicated as (

    select
        *,
        row_number() over (
            partition by cik, metric, period_start, period_end, accession_number
            order by concept_priority asc, value desc
        ) as concept_rank

    from mapped

)

select
    {{ dbt_utils.generate_surrogate_key([
        'cik', 'metric', 'period_start', 'period_end', 'accession_number'
    ]) }}                                   as financial_fact_sk,

    cik,
    metric,
    metric_description,
    concept,
    taxonomy,
    unit,
    value,

    period_start,
    period_end,
    period_type,
    period_kind,
    duration_days,
    calendar_year,
    calendar_quarter,
    calendar_period,
    reported_fiscal_year,
    reported_fiscal_period,

    form,
    filed_date,
    accession_number,

    is_latest,
    restatement_count,
    value_changed

from deduplicated
where concept_rank = 1
