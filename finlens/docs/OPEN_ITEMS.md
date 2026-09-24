# FinLens Open Items

This document tracks unresolved engineering and product items discovered during development and debugging.

## 1. Locate `period_kind` classification logic

**Status:** Open

Find the ingestion/normalization code that assigns:

`silver.facts.period_kind`

Expected values currently include:

- `instant`
- `quarterly`
- `half_year`
- `three_quarters`
- `annual`
- `irregular`

The dbt staging model passes this value through rather than determining it.

**Next step:** locate the ingestion/source code responsible for assigning `period_kind`.

---

## 2. Validate annual-period classification

**Status:** Open

`assert_no_overlapping_annual_periods` currently identifies 897 overlapping annual periods.

Examples include multiple overlapping 12-month windows for the same company and metric.

**Questions to answer:**

- What currently causes a fact to become `annual`?
- Are rolling 12-month periods incorrectly classified as annual?
- How are genuine fiscal-year periods distinguished from transition/stub periods?
- Are there legitimate cases that the test is expected to permit?

**Important:** do not weaken or remove the test before understanding the underlying classification.

---

## 3. Rebuild `fct_company_annual`

**Status:** Blocked

`fct_company_annual` exists in the dbt source models but its build is currently blocked by the annual-period data-quality failure.

After fixing period classification:

- rebuild the affected models
- run the annual-period test
- verify `fct_company_annual` materializes
- run its associated tests

---

## 4. Improve SQL generation for fiscal-year questions

**Status:** Open

The SQL generator incorrectly attempted to use `fiscal_year`.

The warehouse uses:

- `reported_fiscal_year`
- `reported_fiscal_period`
- `calendar_year`
- `calendar_period`
- `period_start`
- `period_end`

The prompt should make these semantics explicit.

Fiscal-year questions should also account for comparative periods within a filing rather than assuming `reported_fiscal_year` uniquely identifies one annual value.

---

## 5. Clarify `is_latest` semantics in SQL generation

**Status:** Open

`is_latest` does not mean "latest fiscal period."

The SQL-generation prompt should explicitly distinguish:

- latest/restatement record
- latest fiscal period
- requested reporting period

Avoid using `is_latest` as a substitute for fiscal-year selection.

---

## 6. Verify Apple FY2024 through the SQL path

**Status:** Open

After fixing SQL generation and period semantics, re-run:

> What was Apple's revenue in fiscal 2024?

Expected behavior:

1. Route to SQL.
2. Generate valid warehouse SQL.
3. Retrieve the FY2024 record directly.
4. Avoid unnecessary RAG fallback.
5. Return the value with appropriate filing evidence/citation.

---

## 7. Investigate LLM latency and rate limiting

**Status:** Open

The Apple request took approximately 88 seconds.

Observed timings showed:

- DuckDB execution: approximately 1.7 ms
- RAG retrieval: approximately 343 ms
- major delay: repeated Gemini rate-limit retries and subsequent LLM calls

Potential future work:

- reduce unnecessary retries
- improve provider fallback behavior
- avoid repeated LLM calls when deterministic repair is possible
- expose meaningful progress states to the UI

---

## 8. Improve UI progress states

**Status:** Open

The UI should communicate what the system is actually doing instead of appearing stuck during long LLM operations.

Potential stages:

- Classifying question
- Building financial query
- Querying structured financial data
- No structured match found
- Switching to SEC filing evidence
- Searching filing
- Cross-checking evidence
- Preparing answer
- Answer ready

Progress messages should reflect actual backend events and should not invent time estimates.

---

## 9. Review stale SQL guard tests

**Status:** Open

The production SQL guard allows:

- `main_marts`
- `main_semantic`
- `main`
- empty/default schema

Some existing unit tests still reference older schema names such as:

- `marts`
- `semantic`

Review and update those tests if they no longer represent the production schema.

---

## 10. Keep documentation synchronized

**Status:** Ongoing

When a debugging item is resolved:

1. Record the confirmed finding in `DEVELOPMENT_HANDOFF.md`.
2. Update or close the corresponding item in this document.
3. Commit and push the documentation change with the related code change where appropriate.
