{{
  config(
    materialized = 'table',
    tags = ['fct']
  )
}}

-- Current-value metric table: the latest reported figure for each
-- (company, metric, period), with growth already computed.
--
-- `fct_financial_fact` keeps every restatement vintage because "what did they
-- say at the time" is a real question. This model answers the far more common
-- one - "what is the number" - and exists so that generated SQL does not have
-- to get the `is_latest` filter right to be correct.

with latest_facts as (

    select *
    from {{ ref('fct_financial_fact') }}
    where is_latest
      and period_kind in ('annual', 'quarterly', 'instant')

),

ranked_facts as (

    select
        f.*,
        cm.priority as concept_priority,

        row_number() over (
            partition by
                f.cik,
                f.metric,
                f.period_start,
                f.period_end,
                f.period_kind
            order by
                cm.priority asc,
                f.filed_date desc,
                f.accession_number desc
        ) as metric_rank

    from latest_facts f
    left join {{ ref('stg_concept_map') }} cm
        on cm.taxonomy = f.taxonomy
       and cm.concept = f.concept

),

facts as (

    select *
    from ranked_facts
    where metric_rank = 1

),

labelled as (

    select
        *,
        case
            when period_kind = 'annual'    then 'FY'
            when period_kind = 'quarterly' then 'Q' || cast(calendar_quarter as varchar)
            when period_kind = 'instant'   then 'PIT'
        end as period_label

    from facts

),

with_growth as (

    select
        *,
        lag(value) over (
            partition by cik, metric, period_kind
            order by period_end
        ) as prior_period_value,

        lag(value, 4) over (
            partition by cik, metric, period_kind
            order by period_end
        ) as year_ago_value

    from labelled

)

select
  {{ dbt_utils.generate_surrogate_key(['g.cik', 'g.metric', 'g.period_start', 'g.period_end', 'g.period_kind']) }}
                                        as company_metric_sk,

    g.cik,
    c.ticker,
    c.company_name,
    c.sector,

    g.metric,
    g.unit,
    g.value,

    g.period_end,
    g.period_start,
    g.period_kind,
    g.period_label,
    g.calendar_year,
    g.calendar_quarter,
    g.calendar_period,

    g.prior_period_value,
    {{ safe_divide('g.value - g.prior_period_value', 'abs(g.prior_period_value)') }}
                                        as pct_change_prior_period,

    -- Year-over-year for quarterly series only: for an annual series the
    -- four-period lag is four years back, which is not what "YoY" means.
    case when g.period_kind = 'quarterly' then g.year_ago_value end
                                        as year_ago_value,
    case
        when g.period_kind = 'quarterly'
        then {{ safe_divide('g.value - g.year_ago_value', 'abs(g.year_ago_value)') }}
    end                                 as pct_change_year_over_year,

    g.form,
    g.filed_date,
    g.accession_number,
    g.restatement_count

from with_growth g
left join {{ ref('dim_company') }} c on c.cik = g.cik
