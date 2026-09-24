-- A company should not have two overlapping annual periods for the same metric
-- in the current-value table. When it does, a year-over-year comparison silently
-- compares a 12-month figure against a transition-period stub.
--
-- Genuine cause: a fiscal-year change, where the transition year is short. Those
-- are real and rare; this test surfaces them rather than assuming they are bugs.

with annual as (

    select
        cik,
        metric,
        period_start,
        period_end
    from {{ ref('fct_company_metric') }}
    where period_kind = 'annual'
      and period_start is not null

)

select
    a.cik,
    a.metric,
    a.period_start   as period_a_start,
    a.period_end     as period_a_end,
    b.period_start   as period_b_start,
    b.period_end     as period_b_end

from annual a
join annual b
    on  a.cik = b.cik
    and a.metric = b.metric
    and a.period_end < b.period_end
    and b.period_start < a.period_end
    -- Ignore single-day touches at the boundary: many filers report a period
    -- ending 2023-12-31 and the next starting 2023-12-31.
    and date_diff('day', b.period_start, a.period_end) > 1
