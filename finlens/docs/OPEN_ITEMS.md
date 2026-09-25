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






# FinLens — Real-Time Analysis Pipeline & Live System Trace

## Implementation Documentation / Future Work Specification

**Status:** Planned — do not implement yet
**Current UI:** Real backend-driven 5-stage progress pipeline is working
**Future enhancement:** Add a technical “LIVE SYSTEM TRACE” panel using the same real backend events

---

# 1. Objective

FinLens currently has a visually rich analysis screen showing the progress of an answer through five stages:

```text
ROUTER
   ↓
WAREHOUSE
   ↓
RETRIEVAL
   ↓
SYNTHESIS
   ↓
VERIFICATION
```

The pipeline is now driven by **actual backend execution events**, rather than artificial frontend delays.

The next enhancement is to use the currently unused space on the right side of the analysis screen to display a **technical live system trace**.

The trace should feel like:

* Bloomberg terminal
* modern developer console
* intelligence/research terminal
* lightweight hacker interface
* real-time system telemetry

It should **not** feel like:

* a generic loading spinner
* ChatGPT-style "thinking" messages
* fake progress percentages
* generic `"Analyzing..."`, `"Searching..."`, `"Generating..."` messages
* a decorative animation pretending to represent backend work

The fundamental principle is:

> **Every meaningful trace message should correspond to something the backend actually did or knows.**

---

# 2. Current Architecture

The current request lifecycle is approximately:

```text
User question
      │
      ▼
Frontend
      │
      │ POST /ask/stream
      ▼
FastAPI SSE endpoint
      │
      ▼
Agent.ask()
      │
      ├── Route question
      │
      ├── SQL / RAG / HYBRID
      │
      ├── Synthesis
      │
      ├── Verification
      │
      └── Audit
      │
      ▼
Answer
      │
      ▼
SSE events
      │
      ▼
Frontend
```

The important change already implemented is that `Agent.ask()` can emit progress callbacks during execution.

The SSE endpoint bridges those callbacks into the browser using an async queue.

---

# 3. Current Backend Progress Events

The backend now has the following conceptual events.

## Routing

```text
route
```

Payload contains:

```json
{
  "route": "sql",
  "confidence": 0.96
}
```

This tells the frontend that routing has actually completed.

---

# 4. Warehouse Events

When SQL execution begins:

```text
warehouse_started
```

When it completes:

```text
warehouse_completed
```

Payload currently includes:

```json
{
  "ok": true,
  "row_count": 1
}
```

This is particularly valuable for the future trace because it gives us real information.

For example:

```text
> warehouse.init
> warehouse.query.execute
> rows.returned=1
```

---

# 5. Retrieval Events

When filing retrieval begins:

```text
retrieval_started
```

When retrieval completes:

```text
retrieval_completed
```

The start event can include a reason.

For example, SQL fallback:

```json
{
  "reason": "sql_fallback"
}
```

Hybrid:

```json
{
  "reason": "hybrid"
}
```

Normal RAG:

```json
{}
```

This distinction is useful because the technical trace can explain *why* retrieval happened.

For example:

```text
> retrieval.init
> reason=sql_fallback
```

versus:

```text
> retrieval.init
> mode=hybrid
```

---

# 6. Synthesis Events

When answer synthesis starts:

```text
synthesis_started
```

When synthesis completes:

```text
synthesis_completed
```

Current payload:

```json
{
  "verified": true
}
```

This represents the long-running LLM synthesis portion of the pipeline.

Therefore, while the user is waiting here, the trace can legitimately show something such as:

```text
> evidence.locked
> synthesis.init
> model.inference.active
```

The UI can animate the final line while waiting for the real completion event.

---

# 7. Important Verification Architecture

There is an important implementation detail that must be preserved in future work.

The current backend does **not** actually execute:

```text
SYNTHESIS
    ↓
VERIFICATION
```

as two independent sequential stages.

Instead, the actual architecture is closer to:

```text
SYNTHESIS
    │
    ├── LLM generates answer
    │
    └── verify(...)
          │
          ▼
      Verification result
```

Therefore:

```text
SYNTHESIS_STARTED
        ↓
LLM inference
        ↓
verification
        ↓
SYNTHESIS_COMPLETED
```

The existing UI visually presents Verification as a separate stage because that is useful for communicating the conceptual pipeline.

However, future implementation should make the telemetry truthful.

---

# 8. Recommended Future Verification Events

When we implement the next iteration, add:

```text
verification_started
verification_completed
```

around the actual `verify(...)` call.

The resulting lifecycle becomes:

```text
route
    ↓
warehouse_started
    ↓
warehouse_completed
    ↓
retrieval_started
    ↓
retrieval_completed
    ↓
synthesis_started
    ↓
verification_started
    ↓
verification_completed
    ↓
synthesis_completed
```

For an SQL-only request where retrieval is not needed, the retrieval events would naturally be absent.

For HYBRID:

```text
route
    ↓
warehouse_started
retrieval_started
    ↓
warehouse_completed
retrieval_completed
    ↓
synthesis_started
    ↓
verification_started
    ↓
verification_completed
    ↓
synthesis_completed
```

---

# 9. Future UI: Live System Trace

## Location

Use the currently unused right-hand portion of the analysis screen.

Current structure:

```text
┌─────────────────────────────────────────────────────────────┐
│ FINLENS / ANALYSIS                              PIPELINE     │
│                                                             │
│ Question                                                    │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ LIVE PIPELINE                                           │ │
│ │                                                         │ │
│ │ ROUTER                                                  │ │
│ │ WAREHOUSE                                               │ │
│ │ RETRIEVAL                                               │ │
│ │ VERIFICATION                                            │ │
│ │ SYNTHESIS                                               │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

Future layout:

```text
┌─────────────────────────────────────────────────────────────┐
│ FINLENS / ANALYSIS                              PIPELINE     │
│                                                             │
│ Question                                                    │
│                                                             │
│ ┌─────────────────────────────────┐ ┌─────────────────────┐ │
│ │ LIVE PIPELINE                   │ │ SYSTEM TRACE        │ │
│ │                                 │ │                     │ │
│ │ ROUTER              ✓           │ │ > route=SQL         │ │
│ │ WAREHOUSE           ✓           │ │ > confidence=.96    │ │
│ │ RETRIEVAL           ●           │ │ > warehouse.init    │ │
│ │ VERIFICATION        ○           │ │ > query.execute     │ │
│ │ SYNTHESIS           ○           │ │ > rows.returned=1   │ │
│ │                                 │ │ > retrieval.init    │ │
│ │                                 │ │ > evidence.search   │ │
│ └─────────────────────────────────┘ └─────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

# 10. Design Philosophy

The trace should feel like **telemetry**, not conversation.

Avoid:

```text
Analyzing your question...
Searching the database...
Looking for relevant documents...
Generating your answer...
Almost there...
```

Instead:

```text
> intent.detected
> route=SQL
> confidence=0.96

> warehouse.init
> query.compile

> warehouse.execute
> rows.returned=1

> retrieval.init
> index.search

> evidence.selected=3

> synthesis.init
> inference.active
```

The difference is important.

The first feels like a chatbot.

The second feels like a **financial intelligence system exposing its internal execution pipeline**.

---

# 11. Trace Message Categories

We should divide messages into several categories.

## 11.1 Router

Possible real information:

```text
> intent.detected
> route=SQL
> confidence=0.96
```

If available:

```text
> entities.detected=APPLE
```

Potential future:

```text
> question.scope=financial
```

Only show values actually available from the routing layer.

---

# 12. Warehouse Trace

The warehouse is the best opportunity for technical telemetry.

Current real information:

```text
warehouse_started
warehouse_completed
row_count
ok
```

Therefore:

```text
> warehouse.init
> source=structured_financial_data
> query.execute
> query.complete
> rows.returned=1
```

Future backend telemetry could expose:

```text
> schema=marts
> table=fact_financials
> filters=entity,period
> rows.scanned=...
> rows.returned=1
> execution_ms=...
```

But these values **must not be invented**.

If DuckDB/Snowflake/etc. does not currently expose `rows_scanned`, do not display:

```text
> rows.scanned=847291
```

just to make the interface look technical.

---

# 13. Retrieval Trace

Potential real telemetry:

```text
> retrieval.init
> mode=RAG
```

or:

```text
> retrieval.init
> reason=sql_fallback
```

or:

```text
> retrieval.init
> mode=hybrid
```

Future RAG instrumentation could expose:

```text
> embedding.generate
> vector.search
> candidates=18
> reranking
> evidence.selected=3
```

Again, only expose values that the retrieval system actually knows.

This is an important principle:

> **Technical-looking fake numbers are worse than no numbers.**

---

# 14. Synthesis Trace

Synthesis is likely to be one of the most visually interesting phases because it may be the longest waiting period.

Real events:

```text
> synthesis.init
> evidence.locked
> model.inference.active
```

When complete:

```text
> model.inference.complete
```

Potential future telemetry:

```text
> evidence.blocks=4
> numeric_claims=2
> model.provider=...
> model.calls=...
```

Only expose these if they are already available in a safe and intentional telemetry payload.

---

# 15. Verification Trace

Once explicit verification events are added:

```text
> verification.init
> claims.checked=1
> verification=PASS
```

or:

```text
> verification.init
> claims.checked=3
> verification=2/3
```

The current `Answer` object already contains verification information such as:

* checked
* reconciled
* failed
* unchecked
* groundedness

So future telemetry can potentially expose carefully selected values.

Example:

```text
> claims.detected=2
> claims.checked=2
> numeric.reconciliation=PASS
```

Avoid dumping the entire verification object into the UI.

---

# 16. Trace Animation

The trace should not require a heavy animation framework.

Use lightweight CSS.

For example:

### New event

Fade in:

```text
> retrieval.init
```

### Active event

A subtle cursor:

```text
> model.inference.active_
```

The cursor can blink using CSS.

### Old events

Older lines gradually become lower contrast.

Example:

```text
> route=SQL
> warehouse.init
> rows.returned=1
> retrieval.init
> model.inference.active_
```

The newest line should have the strongest visual emphasis.

---

# 17. Do NOT Fake Backend Progress

This is one of the most important requirements.

Do **not** do this:

```text
query.execute
  ↓
wait 300ms
query.scanning
  ↓
wait 400ms
query.complete
```

if the backend hasn't actually reported those events.

Likewise, don't fabricate:

```text
> scanning 10%
> scanning 25%
> scanning 47%
> scanning 83%
```

unless the backend provides actual progress information.

The animation should be driven by:

```text
real event
      +
lightweight visual treatment
```

not:

```text
timer
      +
fictional event
```

---

# 18. Event-to-Trace Mapping

The frontend should maintain a deterministic mapping.

| Backend event            | Pipeline              | Trace                        |
| ------------------------ | --------------------- | ---------------------------- |
| `status`                 | Router active         | `> session.init`             |
| `route`                  | Router complete       | `> route=SQL`                |
| `warehouse_started`      | Warehouse active      | `> warehouse.init`           |
| `warehouse_completed`    | Warehouse complete    | `> rows.returned=1`          |
| `retrieval_started`      | Retrieval active      | `> retrieval.init`           |
| `retrieval_completed`    | Retrieval complete    | `> evidence.search.complete` |
| `synthesis_started`      | Synthesis active      | `> model.inference.active`   |
| `verification_started`   | Verification active   | `> verification.init`        |
| `verification_completed` | Verification complete | `> verification=PASS`        |
| `synthesis_completed`    | Synthesis complete    | `> response.compiled`        |
| `done`                   | Finished              | `> pipeline.complete`        |

The exact trace wording can evolve.

The **event contract should remain stable**.

---

# 19. Do Not Couple Visual Text to Backend Internals Too Tightly

We should avoid making the frontend depend on exact internal implementation names.

Bad:

```text
> rag_module.retrieve()
```

Better:

```text
> retrieval.init
```

Bad:

```text
> ThreadPoolExecutor(max_workers=2)
```

Better:

```text
> parallel.retrieval=ACTIVE
```

The trace should communicate architecture without exposing implementation details that may change.

---

# 20. HYBRID Queries

HYBRID is particularly interesting.

The backend runs:

```text
SQL
+
RAG
```

concurrently.

The UI should communicate that.

For example:

```text
> route=HYBRID
> confidence=0.42

> warehouse.init
> retrieval.init
> execution.parallel=TRUE

> warehouse.complete
> rows.returned=7

> retrieval.complete
> evidence.selected=4
```

The main pipeline can still show:

```text
WAREHOUSE     ✓
RETRIEVAL     ✓
```

while the trace explains that they ran concurrently.

This is a particularly useful detail for technical users.

---

# 21. SQL Fallback

Another interesting real behavior is:

```text
SQL
 ↓
no usable rows
 ↓
RAG fallback
```

The trace should make this visible.

Example:

```text
> route=SQL

> warehouse.init
> query.execute
> rows.returned=0

> warehouse.complete

> retrieval.init
> reason=sql_fallback

> evidence.search
```

This gives technical users insight into why FinLens changed behavior without exposing unnecessary implementation detail.

---

# 22. Error Handling

The trace should also handle failures.

For example:

```text
> warehouse.init
> query.execute
> query.error
```

Then:

```text
> retrieval.init
> reason=sql_fallback
```

The trace should **not** crash because an optional telemetry field is missing.

Every trace renderer should gracefully handle:

```text
undefined
null
missing payload
unknown event
```

Unknown events can simply be ignored by the pipeline UI or displayed as a generic trace event if deliberately supported.

---

# 23. Performance Requirements

The system trace must remain extremely lightweight.

### Avoid

* large canvas animations
* continuous React re-renders
* huge arrays of trace messages
* expensive syntax highlighting
* per-frame JavaScript animation
* complex particle systems
* WebGL
* excessive Framer Motion usage

### Prefer

* CSS animations
* bounded trace array
* `max-height` / overflow
* simple opacity transitions
* one active cursor
* existing SSE connection
* existing backend events

Recommended trace history:

```text
MAX_TRACE_LINES = 12–20
```

When a new event arrives:

```text
trace = [...trace, event].slice(-20)
```

This keeps the DOM small.

---

# 24. Trace Lifecycle

At request start:

```text
> session.init
```

Then:

```text
> route.pending
```

As events arrive, append real telemetry.

At completion:

```text
> verification=PASS
> response.compiled
> pipeline.complete
```

Then the analysis screen transitions to the answer.

The trace does not need to remain visible after the answer is displayed unless we later decide to expose it as an expandable diagnostic panel.

---

# 25. Possible Future "Technical Mode"

Eventually we could make the trace collapsible.

Normal user:

```text
LIVE SYSTEM TRACE
> route=SQL
> warehouse.complete
> evidence.selected=3
```

Technical user:

```text
[ EXPAND DIAGNOSTICS ]
```

Expanded:

```text
ROUTER
route: SQL
confidence: 0.96
entities: APPLE

WAREHOUSE
status: complete
rows_returned: 1

RETRIEVAL
status: complete
mode: RAG
...

SYNTHESIS
model: ...
calls: ...

VERIFICATION
checked: 1
failed: 0
groundedness: ...
```

But this is **later**.

For now, the live trace should remain visually compact.

---

# 26. Visual Language

The trace should use the existing FinLens visual language:

### Background

Near-black:

```text
#07090c
```

### Primary accent

Cyan / electric blue.

### Completion

Green.

### Error

Red/orange, used sparingly.

### Typography

Monospace.

The existing Geist Mono / monospace setup is suitable.

---

# 27. Example Final Experience

For:

> What was Apple's revenue in 2024?

The user might see:

```text
FINLENS / ANALYSIS                         PIPELINE
What was Apple's revenue in 2024?              72%

┌───────────────────────────────┐  ┌──────────────────────────────┐
│ LIVE PIPELINE                 │  │ LIVE SYSTEM TRACE            │
│                               │  │                              │
│ ✓ ROUTER                      │  │ 09:31:42.184  ROUTER        │
│   Classifying question        │  │ > intent.detected             │
│                               │  │ > route=SQL                   │
│ ✓ WAREHOUSE                   │  │ > confidence=0.96             │
│   Querying financial data     │  │                              │
│                               │  │ 09:31:42.641  WAREHOUSE       │
│ ✓ RETRIEVAL                   │  │ > query.execute                │
│   Searching SEC evidence      │  │ > source=financial_data       │
│                               │  │                              │
│ ● SYNTHESIS                   │  │ 09:31:43.018  WAREHOUSE       │
│   Preparing answer            │  │ > rows.returned=1             │
│                               │  │                              │
│ ○ VERIFICATION                │  │ 09:31:43.022  SYNTHESIS       │
│   Cross-checking evidence     │  │ > evidence.locked             │
│                               │  │ > model.inference.active_     │
└───────────────────────────────┘  └──────────────────────────────┘
```

This makes the waiting period feel like the user is **watching an intelligence system work**, rather than waiting for a chatbot.

---

# 28. Implementation Sequence

When we return to this feature, implement in this order.

### Phase 1 — Backend event accuracy

Add:

```text
verification_started
verification_completed
```

Ensure events correspond exactly to actual execution.

---

### Phase 2 — Backend telemetry enrichment

Gradually expose safe, useful fields:

```text
route
confidence
row_count
retrieval mode
fallback reason
verification counts
elapsed time
```

Only expose information the backend genuinely knows.

---

### Phase 3 — Frontend trace model

Create a type similar to:

```typescript
type TraceEntry = {
  id: string;
  timestamp: string;
  stage: StageName;
  message: string;
  detail?: string;
  state: "active" | "complete" | "info" | "error";
};
```

Keep this independent from the pipeline stage state.

---

### Phase 4 — Event → Trace mapper

Create one centralized function:

```typescript
eventToTrace(eventName, payload)
```

Example:

```text
warehouse_completed
        ↓
{
  stage: "warehouse",
  message: "rows.returned",
  detail: "1"
}
```

This prevents trace logic from being scattered throughout the SSE handler.

---

### Phase 5 — Trace UI

Build:

```text
SystemTrace
```

with:

* monospace typography
* bounded history
* newest event highlighted
* subtle fade-in
* blinking active cursor
* auto-scroll
* no heavy animation

---

### Phase 6 — Layout

Use the empty right-hand space.

Desktop:

```text
Pipeline ~65%
Trace    ~35%
```

On smaller screens:

```text
Pipeline
↓
Trace
```

or hide/collapse trace depending on available width.

---

### Phase 7 — Polish

Add:

* timestamp formatting
* event severity
* subtle scanline/noise if visually appropriate
* cursor animation
* line fading
* terminal-style separators

But **only after the underlying telemetry is correct**.

---

# 29. Non-Goals

This feature should **not** become:

### A fake progress simulator

No artificial percentages.

### A developer log dump

Don't expose:

```text
Python stack traces
ThreadPoolExecutor internals
raw SQL
internal object names
```

unless explicitly placed in a diagnostic mode.

### A second answer

The trace is not supposed to explain the financial answer.

Its purpose is:

> **Show the system executing the analysis.**

### A performance-heavy animation

The analysis screen should remain fast.

---

# 30. Core Principle

The entire feature can be summarized in one architectural rule:

> **The backend owns truth. The frontend owns presentation.**

Backend says:

```text
warehouse_completed
rows=1
```

Frontend decides how that becomes:

```text
09:31:43.018  WAREHOUSE
> rows.returned=1
```

Backend says:

```text
synthesis_started
```

Frontend decides how that becomes:

```text
09:31:43.022  SYNTHESIS
> evidence.locked
> model.inference.active_
```

This separation means we can dramatically improve the visual experience without compromising the factual integrity of the progress display.

---

# 31. Final Target Architecture

The eventual FinLens analysis screen should have **two synchronized representations of the same real execution stream**:

```text
                    REAL BACKEND EVENTS
                           │
                           │
                    SSE EVENT STREAM
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
       PIPELINE VISUALIZER        SYSTEM TRACE
              │                         │
              │                         │
       ROUTER ✓                  > route=SQL
       WAREHOUSE ✓               > confidence=.96
       RETRIEVAL ●               > warehouse.init
       SYNTHESIS ○               > rows.returned=1
       VERIFICATION ○            > retrieval.init
                                  > evidence.selected=3
                                  > inference.active_
```

That is the direction I'd preserve.

**The progress pipeline tells the user *where FinLens is*.
The system trace tells the technical user *what FinLens is doing*.**

And both are driven by the **same real backend execution**, so we don't reintroduce the fake-progress problem we just solved.

