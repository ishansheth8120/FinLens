-- Gross margin outside [-10, 1] is almost always a units error, not a business
-- reality: a company reporting revenue in thousands and cost of revenue in
-- dollars produces exactly this. Margins below -1000% do occur in genuinely
-- distressed micro-caps, so the lower bound is deliberately loose.
--
-- This is a data-quality canary rather than a hard invariant. It has caught
-- concept-mapping mistakes twice as often as it has caught real anomalies.

select
    cik,
    ticker,
    fiscal_year,
    revenue,
    gross_profit,
    gross_margin

from {{ ref('fct_company_annual') }}

where gross_margin is not null
  and (gross_margin > 1.0 or gross_margin < -10.0)
  -- Only care where the numbers are large enough to matter.
  and abs(coalesce(revenue, 0)) > 1000000
