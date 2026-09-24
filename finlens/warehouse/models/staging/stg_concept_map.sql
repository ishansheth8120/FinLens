{{ config(materialized = 'view') }}

-- The seed that resolves the many-to-one mess of XBRL tags onto stable metric
-- names. `priority` breaks ties: a company that tags both
-- `RevenueFromContractWithCustomerExcludingAssessedTax` and the legacy
-- `Revenues` should resolve to the former.

select
    metric,
    taxonomy,
    concept,
    cast(priority as integer)   as priority,
    unit                        as expected_unit,
    period_type                 as expected_period_type,
    description                 as metric_description

from {{ ref('concept_map') }}
