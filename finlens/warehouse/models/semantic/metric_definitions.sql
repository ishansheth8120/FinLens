{{ config(materialized = 'view') }}

-- A queryable catalogue of what each metric means and how well it is covered.
--
-- Two consumers: the text-to-SQL prompt (which needs the definitions) and the
-- agent's "can I answer this?" check (which needs the coverage). Keeping it as
-- a model rather than a static file means coverage is always current.

with definitions as (

    select
        metric,
        min(metric_description)                      as description,
        min(expected_unit)                           as unit,
        min(expected_period_type)                    as period_type,
        count(*)                                     as source_concept_count,
        string_agg(concept, ', ' order by priority)  as source_concepts

    from {{ ref('stg_concept_map') }}
    group by metric

),

coverage as (

    select
        metric,
        count(distinct cik)     as companies_reporting,
        count(*)                as fact_count,
        min(calendar_year)      as first_year,
        max(calendar_year)      as latest_year

    from {{ ref('fct_company_metric') }}
    group by metric

)

select
    d.metric,
    d.description,
    d.unit,
    d.period_type,
    d.source_concepts,
    d.source_concept_count,

    coalesce(c.companies_reporting, 0)  as companies_reporting,
    coalesce(c.fact_count, 0)           as fact_count,
    c.first_year,
    c.latest_year

from definitions d
left join coverage c on c.metric = d.metric
order by companies_reporting desc
