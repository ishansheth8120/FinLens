{{
  config(
    materialized = 'table',
    tags = ['fct']
  )
}}

-- Wide, one row per company-year, with the ratios pre-computed.
--
-- The long tables are the right shape for a warehouse and the wrong shape for a
-- language model: asking one to write a five-way self-join on `metric` to get a
-- margin is where text-to-SQL reliably falls over. This model trades storage
-- for a large drop in generated-SQL complexity, and the eval set is what
-- justifies the trade (see `finlens/docs/`).

{% set annual_metrics = [
    'revenue', 'cost_of_revenue', 'gross_profit', 'operating_income', 'net_income',
    'rd_expense', 'sgna_expense', 'interest_expense', 'tax_expense',
    'operating_cash_flow', 'investing_cash_flow', 'financing_cash_flow',
    'capex', 'dividends_paid', 'buybacks',
    'shares_diluted', 'eps_diluted'
] %}

{% set instant_metrics = [
    'total_assets', 'total_liabilities', 'stockholders_equity', 'cash',
    'inventory', 'current_assets', 'current_liabilities', 'long_term_debt'
] %}

with flows as (

    select
        cik,
        calendar_year as fiscal_year,
        {% for metric in annual_metrics %}
        max(case when metric = '{{ metric }}' then value end) as {{ metric }}
        {%- if not loop.last %},{% endif %}
        {% endfor %}

    from {{ ref('fct_company_metric') }}
    where period_kind = 'annual'
    group by cik, calendar_year

),

-- Balances are point-in-time, so "the FY2023 balance" means the one closest to
-- the fiscal year end - not an aggregate over the year.
balances_ranked as (

    select
        cik,
        calendar_year as fiscal_year,
        metric,
        value,
        row_number() over (
            partition by cik, calendar_year, metric
            order by period_end desc
        ) as recency_rank

    from {{ ref('fct_company_metric') }}
    where period_kind = 'instant'

),

balances as (

    select
        cik,
        fiscal_year,
        {% for metric in instant_metrics %}
        max(case when metric = '{{ metric }}' then value end) as {{ metric }}
        {%- if not loop.last %},{% endif %}
        {% endfor %}

    from balances_ranked
    where recency_rank = 1
    group by cik, fiscal_year

),

combined as (

    select
        coalesce(f.cik, b.cik)                  as cik,
        coalesce(f.fiscal_year, b.fiscal_year)  as fiscal_year,
        {% for metric in annual_metrics %}
        f.{{ metric }},
        {% endfor %}
        {% for metric in instant_metrics %}
        b.{{ metric }}{% if not loop.last %},{% endif %}
        {% endfor %}

    from flows f
    full outer join balances b
        on  f.cik = b.cik
        and f.fiscal_year = b.fiscal_year

)

select
    {{ dbt_utils.generate_surrogate_key(['x.cik', 'x.fiscal_year']) }} as company_year_sk,

    x.cik,
    c.ticker,
    c.company_name,
    c.sector,
    x.fiscal_year,

    {% for metric in annual_metrics %}
    x.{{ metric }},
    {% endfor %}
    {% for metric in instant_metrics %}
    x.{{ metric }},
    {% endfor %}

    -- Derived ratios. All divisions go through `safe_divide` because a
    -- zero-revenue year is common (pre-revenue biotech) and a division error
    -- would fail the whole model build rather than one row.
    {{ safe_divide('x.gross_profit', 'x.revenue') }}         as gross_margin,
    {{ safe_divide('x.operating_income', 'x.revenue') }}     as operating_margin,
    {{ safe_divide('x.net_income', 'x.revenue') }}           as net_margin,
    {{ safe_divide('x.rd_expense', 'x.revenue') }}           as rd_intensity,
    {{ safe_divide('x.net_income', 'x.stockholders_equity') }} as return_on_equity,
    {{ safe_divide('x.net_income', 'x.total_assets') }}      as return_on_assets,
    {{ safe_divide('x.total_liabilities', 'x.stockholders_equity') }} as debt_to_equity,
    {{ safe_divide('x.current_assets', 'x.current_liabilities') }} as current_ratio,
    {{ safe_divide('x.operating_cash_flow - x.capex', 'x.revenue') }} as fcf_margin,
    x.operating_cash_flow - x.capex                          as free_cash_flow,

    {{ safe_divide(
        'x.revenue - lag(x.revenue) over (partition by x.cik order by x.fiscal_year)',
        'abs(lag(x.revenue) over (partition by x.cik order by x.fiscal_year))'
    ) }}                                                     as revenue_growth

from combined x
left join {{ ref('dim_company') }} c on c.cik = x.cik
where x.fiscal_year is not null
