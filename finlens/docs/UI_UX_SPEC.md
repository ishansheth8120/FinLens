
FinLens, UI/UX Product Specification
Status: Design direction agreed, implementation starting
Frontend: Next.js + React + TypeScript
Target devices: Laptop / desktop + tablet + mobile
Product type: Financial intelligence / SEC research terminal
1. Product Experience
FinLens should not feel like:
- a generic chatbot
- a Streamlit dashboard
- a financial website with a chatbot attached
- a developer debugging console
- an old-school Bloomberg clone
It should feel like a modern financial intelligence terminal.
The core experience is:
Ask a financial question → understand the answer immediately → inspect the evidence → understand how FinLens arrived at it.

The UI should make the system feel:
- intelligent
- fast
- trustworthy
- technical
- premium
- data-dense without being cluttered
- simple enough for a first-time user
2. Visual Design Direction
The agreed visual direction is:
Bloomberg Terminal × Palantir × modern AI research terminal

This is a conceptual direction, not a literal copy of either product.
Overall visual language
BLACK
DARK
MINIMAL
HIGH CONTRAST
PRECISION
DATA-DENSE
MODERN
TECHNICAL
The interface should have a predominantly dark environment.
Background hierarchy
We want multiple very subtle levels rather than one giant black canvas.
Level 0
Almost-black application background

Level 1
Slightly lighter cards/panels

Level 2
Elevated components

Level 3
Interactive / selected components
The differences should be subtle.
3. Color System
Color should communicate meaning rather than decoration.
Primary
Electric cyan
Used for:
- primary interactive elements
- active navigation
- links
- selected states
- key system indicators
- interactive financial charts
- focus states
Positive
Green
Used for:
- positive YoY growth
- positive returns
- improving metrics
- successful verification
- completed pipeline steps
Negative
Red
Used for:
- declining metrics
- negative changes
- warnings requiring attention
- failed pipeline stages
Warning
Amber
Used for:
- partial evidence
- uncertainty
- fallback behavior
- warnings
- stale data
- incomplete verification
Neutral
White / gray hierarchy:
White
→ primary information

Light gray
→ secondary information

Muted gray
→ metadata

Dark gray
→ borders/background structure
Important rule
Do not turn the entire interface green just because it's a "hacker terminal."
Color must remain scarce and meaningful.
4. Typography
We want two complementary typography systems.
Normal UI
Modern sans-serif.
Used for:
- navigation
- headings
- explanatory text
- buttons
- descriptions
- company names
- normal answers
Financial/data typography
Monospace.
Used for:
- ticker symbols
- financial values
- SQL
- request IDs
- system logs
- pipeline states
- technical metadata
- timestamps
- numerical tables
Example:
AAPL        $391.0B
FY2024      +2.6%
REVENUE     VERIFIED
This should immediately communicate:
"This is a financial/data system."

5. Layout Philosophy
The UI should have lots of negative space, despite being information-rich.
Avoid:
┌────┬────┬────┬────┐
│card│card│card│card│
├────┼────┼────┼────┤
│card│card│card│card│
└────┴────┴────┴────┘
Instead, use a hierarchy:
PRIMARY INFORMATION
        ↓
SECONDARY INFORMATION
        ↓
EVIDENCE / DETAILS
        ↓
TECHNICAL DIAGNOSTICS
The most important financial result should always dominate the screen.
6. Global Application Shell
Desktop layout:
┌─────────────────────────────────────────────────────┐
│ FINLENS                                  status/user │
├──────────────┬──────────────────────────────────────┤
│              │                                      │
│ Navigation   │             Main Content             │
│              │                                      │
│ Ask          │                                      │
│ Companies    │                                      │
│ Filings      │                                      │
│ Metrics      │                                      │
│ History      │                                      │
│              │                                      │
│              │                                      │
└──────────────┴──────────────────────────────────────┘
The sidebar should be compact.
We don't want the navigation to consume the majority of the screen.
7. Sidebar
Primary navigation:
FINLENS

⌕ Ask

◉ Companies

▤ Filings

▥ Metrics

◷ History
Potential future items:
Settings
System
API / Developer
Sidebar behavior
Desktop:
- persistent sidebar
- collapsible
- icon + label
- active state highlighted
Mobile:
- hidden by default
- hamburger/menu button
- slide-over navigation
8. Top Bar
Top bar should contain:
Left
Current context.
For example:
FINLENS / ASK
or:
FINLENS / COMPANIES / AAPL
Right
Potentially:
● SYSTEM ONLINE
and user/account controls.
The system status should be subtle rather than a giant banner.
9. Landing / Home Screen
This is the most important screen for first-time users.
The center of the screen should focus almost entirely on the query.
Example:
                 FINLENS

          SEC INTELLIGENCE TERMINAL

     Ask anything about public companies

 ┌─────────────────────────────────────────────┐
 │ What would you like to know?            ↵  │
 └─────────────────────────────────────────────┘

      Try asking

  What was Apple's revenue in 2024?

  Compare NVIDIA and AMD gross margins

  What risks did Tesla mention in its latest 10-K?
10. FinLens Branding
Brand should be minimal.
We don't need a huge logo.
Potential treatment:
FIN
LENS
or simply:
FINLENS
with subtle monospace/technical treatment.
The wordmark should feel like a professional intelligence system rather than a consumer finance app.
11. Query Box
This is the primary interaction.
It needs to feel extremely good.
Desktop
Large centered input.
Mobile
Nearly full-width input with comfortable touch target.
Features
The query box should support:
- natural language
- Enter to submit
- clear button
- loading state
- keyboard focus
- example prompts
- potentially command/history suggestions later
Potential placeholder:
Ask about companies, filings, financials, or management commentary...
12. Suggested Questions
Below the query box:
TRY ASKING

Revenue
What was Apple's revenue in 2024?

Comparison
Compare NVIDIA and AMD gross margins

Filings
What risks did Microsoft highlight?

Trends
Show Tesla's revenue growth over the last 5 years
These should be clickable.
They are not just decorative examples.
13. Query Submission
When the user submits:
The home screen transitions into the answer experience.
We should not immediately replace the entire page with a generic spinner.
Instead, the system should show the actual pipeline progressing.
14. Streaming Pipeline UI
This is one of the strongest UX opportunities because /ask/stream already exists.
The UI can show:
ANALYZING

✓ ROUTER
✓ SQL ENGINE
● RETRIEVAL
○ VERIFICATION
○ SYNTHESIS
As backend events arrive, states update.
Potential animation:
●
pulsing while active.
Then:
✓
when complete.
15. Pipeline Stages
The agreed conceptual stages are:
Router
Determines:
SQL
RAG
Hybrid
Warehouse
Structured financial data lookup.
RAG
SEC filing retrieval.
Verifier
Checks claims/evidence.
Synthesis
Creates the final answer.
16. Pipeline Detail Drawer
The pipeline should be expandable.
Collapsed:
Analysis pipeline     ✓ Verified
Expanded:
ROUTER
SQL

WAREHOUSE
AAPL / FY2024

RAG
5 filing sections retrieved

VERIFIER
1 / 1 claims verified

SYNTHESIS
Gemini
This gives technical transparency without overwhelming normal users.
17. Answer Screen
Once the answer arrives, the financial result should dominate.
For:
What was Apple's revenue in 2024?

The top could look like:
AAPL · APPLE INC.

FY2024 REVENUE

$391.0B

+2.6% YoY
Then:
Apple reported total net sales of $391.0 billion
for fiscal year 2024.
18. Metric Hero
Financial answers should have a hero metric whenever appropriate.
Example:
$391.0B
FY2024 Revenue
The number should be much larger than surrounding text.
Potential metadata:
FY2024
USD
SEC 10-K
VERIFIED
This is one of the most important visual components.
19. Positive / Negative Financial Changes
Example:
$391.0B
+2.6%
Positive:
+2.6%
uses the positive semantic color.
Negative:
-4.8%
uses the negative semantic color.
But the actual number remains the primary visual focus.
20. Natural Language Answer
Below the metric:
Apple reported total net sales of $391.0 billion
for fiscal year 2024, compared with $383.3 billion
in fiscal year 2023.
The answer should be:
- concise by default
- readable
- broken into paragraphs when necessary
- able to contain highlighted financial values
21. Inline Financial Highlighting
Important values inside answers should be visually distinguishable.
Example:
Apple reported $391.0 billion in FY2024 revenue, up 2.0% from FY2023.

The values can be slightly brighter/bolder.
We should not turn every number into a giant colored badge.
22. Citation System
Citations should be visible but unobtrusive.
Example:
Apple reported $391.0B in FY2024 revenue. [1]
Clicking [1] opens the relevant evidence.
23. Evidence Drawer
This is a core product feature.
When the user clicks a citation:
┌─────────────────────────────────────────┐
│ EVIDENCE                            ×    │
├─────────────────────────────────────────┤
│ Apple Inc.                              │
│ 2024 Form 10-K                          │
│                                         │
│ Relevant excerpt                        │
│                                         │
│ "...total net sales were $391.0..."     │
│                                         │
│ Source                                  │
│ SEC Filing                              │
│                                         │
│ [Open filing]                           │
└─────────────────────────────────────────┘
Desktop:
- side drawer
Mobile:
- bottom sheet / full-screen sheet
24. Source Information
Every evidence item should ideally expose:
Company
Filing type
Fiscal year
Filing date
Section
Source
Potential example:
APPLE INC.
10-K
FY2024
Filed: 2024-11-01

Item 8
Financial Statements
25. Evidence Excerpt
Show only the relevant excerpt initially.
Do not dump a 20-page filing into the interface.
Example:
Relevant excerpt

"...total net sales were $391.0 billion
for fiscal 2024..."
Potential future feature:
Show more
which expands the surrounding context.
26. Source Confidence / Verification
The existing backend has verification information.
We should surface it as:
✓ VERIFIED
rather than exposing internal technical terminology by default.
Clicking it could reveal:
1 claim checked
1 supporting source
No conflicting evidence detected
27. Verification Detail
Expanded state:
VERIFICATION

Claim
Apple FY2024 revenue was $391.0B

Evidence
Apple 2024 10-K

Verdict
✓ Supported

Detail
The filing reports total net sales of $391.0B.
This corresponds directly to functionality already present in the backend UI.
28. SQL Section
SQL should exist, but not dominate the normal experience.
Collapsed:
⌄ SQL & Results
Expanded:
SELECT ...
FROM main_marts...
WHERE ...
Then:
RESULTS

metric       value
revenue      391000000000
29. Generated vs Executed SQL
The backend already distinguishes generated SQL from rewritten/scoped SQL.
The UI should preserve this distinction.
Example:
GENERATED SQL

...

EXECUTED SQL

...
If they differ:
The generated query was rewritten before execution.
This is useful for debugging and auditability.
30. Retrieved Excerpts
Also keep a technical section:
⌄ Retrieved excerpts (5)
This is primarily for:
- power users
- developers
- researchers
- debugging
- transparency
It should not clutter the main answer.
31. Technical Metadata
At the bottom of the answer:
1.8s · 2,431 tokens · gemini · request abc123
Potential additional information:
Provider
Model
Elapsed time
Request ID
Again, secondary information.
32. Audit / Lineage
The existing backend exposes:
audit
lineage
These should remain accessible.
Potential UI:
Audit
Lineage
under an expandable Technical details section.
33. Warnings
Warnings should be highly visible but not alarming unless necessary.
Example:
⚠ Structured warehouse query returned no rows.
Answer was sourced from SEC filing evidence.
This is particularly important given the Apple test.
Color:
Amber.
34. Error States
We need a proper error experience.
Not:
500 Internal Server Error
Instead:
FINLENS COULDN'T COMPLETE THAT QUERY

The financial data service didn't return a usable result.

[Try again]
Potential technical details:
Show diagnostics
35. Partial Answer State
If one backend component fails but another succeeds:
Answer available
with:
⚠ Structured data unavailable
✓ Filing evidence available
This is better than treating the whole request as a failure.
36. Company Page
Company pages are a major future component.
Example:
APPLE INC.
AAPL

Technology
NASDAQ

$...
Then tabs/sections:
Overview
Financials
Filings
Ask
37. Company Overview
Top-level metrics:
Revenue
Revenue Growth
Gross Margin
Latest Filing
Cards should remain minimal.
Example:
REVENUE
$391.0B
FY2024

GROWTH
+2.0%
YoY

GROSS MARGIN
46.2%
FY2024
38. Financial Charts
Use Recharts.
Potential charts:
Revenue
Revenue
│
│           ╭───
│       ╭───╯
│   ╭───╯
└────────────────
  2021 22 23 24
Revenue growth
Line/bar chart.
Gross margin
Trend chart.
Charts should be:
- dark
- minimal
- grid-light
- tooltip-rich
- responsive
No excessive decoration.
39. Mobile Charts
Charts must resize rather than simply overflow.
On mobile:
- fewer axis labels
- horizontal scrolling only when genuinely necessary
- large enough touch targets
- tooltip adapted for touch
40. Filing Page
Potential layout:
APPLE INC.

FILINGS

10-K
Nov 1, 2024
FY2024

10-Q
Aug 2, 2024

10-Q
May 3, 2024
Each filing can open a filing detail view.
41. Filing Detail
Potential structure:
APPLE INC.
2024 FORM 10-K

Overview
Business
Risk Factors
MD&A
Financial Statements
Notes
Eventually we could make sections searchable.
42. Global Search / Command Interface
A future interaction model:
⌘ K
opens:
SEARCH FINLENS

Search companies...
Search filings...
Ask a question...
Potential commands:
AAPL
NVDA
"revenue Apple 2024"
"latest Tesla filing"
This would make FinLens feel more like a terminal.
43. Query History
Sidebar:
HISTORY

Today
What was Apple's revenue...

Yesterday
Compare NVIDIA and AMD...

Earlier
Tesla revenue growth...
Clicking history restores the answer.
This is a later-phase feature, not necessary for the first MVP.
44. Responsive Design Strategy
Desktop
Use:
- persistent sidebar
- wide answer area
- evidence drawer
- charts side-by-side where appropriate
Tablet
Use:
- collapsible sidebar
- flexible two-column layouts
- drawers
Mobile
Use:
- top navigation
- hamburger
- single-column layout
- bottom sheets
- stacked cards
- full-width query bar
- horizontally scrollable tables where necessary
45. Mobile Navigation
Mobile top bar:
☰     FINLENS      ●
Menu:
Ask
Companies
Filings
Metrics
History

────────────

System
Settings
46. Mobile Evidence
Desktop:
right-side drawer
Mobile:
bottom sheet
This is important because a desktop drawer squeezed onto mobile would be awkward.
47. Mobile Answer Priority
On mobile the order should be:
Ticker / Company
↓
Hero metric
↓
Answer
↓
Verification
↓
Evidence
↓
Charts
↓
Technical details
Technical details should be pushed toward the bottom.
48. Loading Experience
We should avoid generic:
Loading...
Instead:
FINLENS IS ANALYZING

✓ Understanding question
✓ Checking structured data
● Searching SEC filings
○ Verifying evidence
○ Preparing answer
This makes the waiting time meaningful.
49. Micro-interactions
We want subtle animations.
Using Framer Motion for:
- page transitions
- cards appearing
- drawer opening
- pipeline progression
- number/result transitions
- hover states
- active navigation
- chart entry
- citation opening
Important
Animations should communicate state.
Not:
everything flying around
The product should feel fast.
50. Hover States
Interactive elements should have subtle visual response.
Examples:
citation → slight cyan highlight
card → slightly brighter border
button → subtle elevation
navigation → background highlight
No excessive glow.
51. Focus States
Keyboard navigation should be properly supported.
Focused query box:
┌─────────────────────────────┐
│ Ask about Apple...          │
└─────────────────────────────┘
          ↑ subtle cyan focus
This matters especially because a terminal-like product naturally invites keyboard use.
52. Accessibility
Even though the visual style is dark/technical:
- sufficient contrast
- keyboard navigation
- visible focus
- semantic buttons
- accessible labels
- screen-reader-friendly controls
- no information conveyed solely through color
For example:
Don't rely solely on:
GREEN = positive
RED = negative
Also display:
+2.4%
-3.1%
53. Tables
Financial tables should be highly readable.
Example:
Metric             FY2022     FY2023     FY2024
────────────────────────────────────────────────
Revenue            $394B      $383B      $391B
Gross Margin       43.3%      44.1%      46.2%
Revenue Growth     ,         -2.8%      +2.0%
Use monospace numbers.
Right-align numerical columns.
54. Table Responsiveness
Desktop:
Full table.
Mobile:
Potentially:
Metric       FY2024
Revenue      $391B
Margin       46.2%
Growth       +2.0%
Or horizontal scroll for genuinely wide financial tables.
55. System Status
The application can use /health and /ready.
Potential status component:
SYSTEM

● API
● WAREHOUSE
● INDEX
● LLM
Green/cyan when healthy.
Amber if degraded.
Red if unavailable.
This should be hidden/minimized for ordinary users but accessible.
56. Technical / Developer Mode
The existing backend exposes a lot of valuable debugging information.
Rather than throwing it away, we hide it under:
Technical details
Containing:
Route
SQL
Results
Retrieved excerpts
Verification
Provider
Model
Tokens
Elapsed time
Request ID
Audit
Lineage
This gives us two UX layers:
Normal user
Simple.
Power user
Full observability.
57. Core UX Principle
The most important design rule:
Progressive disclosure.

The user should see:
First
What is the answer?
Then
Why should I trust it?
Then
Where did it come from?
Finally
How did the system produce it?
That ordering is critical.
58. Information Hierarchy
Every answer should roughly follow:
1. COMPANY / CONTEXT

2. HERO FINANCIAL VALUE

3. SHORT ANSWER

4. CHANGE / COMPARISON

5. SOURCE / VERIFICATION

6. EVIDENCE

7. CHART / TABLE

8. PIPELINE

9. SQL / RETRIEVAL / TECHNICAL DETAILS
59. What We Explicitly Don't Want
Avoid:
Generic chatbot UI
User:
What is Apple's revenue?

AI:
Apple's revenue was...
with nothing else.
Streamlit aesthetic
Avoid:
- giant default widgets
- generic sidebars
- default charts
- dashboard-card overload
Excessive hacker aesthetic
Avoid:
- green Matrix text
- CRT gimmicks
- excessive glow
- random terminal logs
- animated noise
Excessive financial-terminal density
Avoid making every screen look like Bloomberg.
FinLens should be inspired by professional terminals while remaining modern and approachable.
60. MVP vs Later
Phase 1, Core UI
Build first:
- dark design system
- responsive shell
- sidebar
- home screen
- query box
- suggested queries
- /ask
- /ask/stream
- streaming pipeline
- answer card
- hero metric
- citations
- evidence drawer
- verification
- warnings
- technical details
Phase 2, Intelligence UI
Then:
- company pages
- financial metrics
- charts
- filing browser
- filing detail
- company-specific questions
Phase 3, Power-user experience
Then:
- query history
- command palette
- keyboard shortcuts
- advanced SQL
- lineage
- audit
- saved queries
- comparison mode
Phase 4, Product polish
Finally:
- advanced animations
- transitions
- micro-interactions
- refined mobile behavior
- performance optimization
- skeleton states
- caching
- sophisticated search
61. The Finished FinLens Experience
The ideal journey is:
                    FINLENS
                       │
                       ▼
             "Ask anything..."
                       │
                       ▼
              User asks question
                       │
                       ▼
             ┌─────────────────┐
             │ ANALYZING       │
             │ ✓ Router        │
             │ ✓ Warehouse     │
             │ ● Retrieval     │
             │ ○ Verification  │
             │ ○ Synthesis     │
             └────────┬────────┘
                      ▼
              ┌───────────────┐
              │   $391.0B     │
              │ FY2024 REVENUE│
              └───────┬───────┘
                      │
                 Answer
                      │
              ✓ VERIFIED
                      │
             ┌────────▼────────┐
             │ SEC EVIDENCE    │
             │ Apple 10-K      │
             │ Relevant excerpt│
             └────────┬────────┘
                      │
             Technical Details
                      │
           SQL / RAG / Audit / Lineage
That is the product we're building.
The key distinction is that the UI isn't merely decorating the existing agent. The UI itself should communicate FinLens's core promise: financial answers that are fast to understand, grounded in SEC evidence, and transparent about how they were produced.




Absolutely. We should keep a **single evolving UI/UX specification** for FinLens, so the next implementation steps don't accidentally drift from decisions we've already made.

Below is the **delta from the previous documentation**, covering what we actually implemented/changed since then.

# FinLens UI/UX Documentation, Update

## 1. Frontend implementation status

The FinLens frontend is now running as a real **Next.js application** rather than only a conceptual UI.

Current stack:

- Next.js `16.3.6`
- React `19.2.8`
- Framer Motion `13.4.1`
- Lucide React `1.47.0`
- Recharts `3.10.1`
- Tailwind CSS
- TypeScript

Development server:

```text
http://localhost:3000
```

Backend:

```text
http://localhost:8000
```

The frontend and backend are now separate running applications.

---

# 2. Home screen, implemented

The previously documented home-screen concept has now been translated into an actual screen.

### Current structure

```text
┌──────────────────────────────────────────────────────────┐
│ FINLENS                              Systems operational  │
├──────────────┬───────────────────────────────────────────┤
│              │                                           │
│ FINLENS      │          SEC INTELLIGENCE TERMINAL        │
│              │                                           │
│ Workspace    │               Ask FinLens.                │
│              │                                           │
│ ✦ Ask        │      Query financial data, filings,      │
│ ◇ Companies  │      and company intelligence...         │
│ □ Filings    │                                           │
│ ◇ Metrics    │       ┌───────────────────────────┐       │
│              │       │ 🔍 Ask a financial        │       │
│ System       │       │    question...           │       │
│ ◷ History    │       │                           │       │
│ ⚙ Settings   │       │              Ask FinLens ↗│       │
│              │       └───────────────────────────┘       │
│              │                                           │
│ IS           │               TRY ASKING                  │
│ Research     │                                           │
│              │    Company       Compare                  │
│              │    Filings       Trend                    │
└──────────────┴───────────────────────────────────────────┘
```

This establishes the main visual hierarchy.

---

# 3. Sidebar, implemented

The sidebar is now a real persistent desktop navigation element.

### Workspace

- Ask
- Companies
- Filings
- Metrics

### System

- History
- Settings

### Bottom user area

Currently displays:

```text
IS
Research
Analyst workspace
```

The sidebar is intentionally restrained rather than dashboard-like.

### Responsive behavior

The sidebar is hidden below the desktop breakpoint.

On smaller screens, the main content becomes the primary surface and the mobile header displays:

```text
FINLENS
```

This follows the earlier mobile decision.

---

# 4. Top navigation, implemented

The desktop top bar now contains:

### Left

```text
WORKSPACE > ASK
```

This gives the user contextual location within the application.

### Right

```text
● SYSTEMS OPERATIONAL

IS
```

The system indicator uses the semantic green status color.

This is deliberately subtle rather than becoming a large monitoring dashboard.

---

# 5. FinLens branding, refined

The brand treatment is now:

```text
FINLENS
INTELLIGENCE TERMINAL
```

with:

```text
SEC INTELLIGENCE TERMINAL
```

on the home page.

The overall terminology reinforces the intended product positioning:

**financial intelligence terminal**, rather than:

- chatbot
- generic AI assistant
- dashboard
- Streamlit app

---

# 6. Query interface, implemented

The query box is now functional UI rather than a static placeholder.

It supports:

- natural-language questions
- multiline input
- Enter to submit
- Shift + Enter for a new line
- submit button
- disabled submit state
- loading state
- placeholder text
- focus border
- keyboard interaction

Current placeholder:

```text
Ask a financial question...
```

Button:

```text
Ask FinLens ↗
```

The query interface remains the primary interaction on the home page.

---

# 7. Suggested questions, now functional

Previously these were only visual suggestions.

They now actually submit questions.

Current suggestions:

### Company

> What was Apple's revenue in 2024?

### Compare

> Compare NVIDIA and AMD gross margins

### Filings

> What risks did Tesla mention in its latest 10-K?

### Trend

> Show Tesla's revenue growth over the last 5 years

Clicking a suggestion now initiates the FinLens analysis flow.

This is an important change because suggested queries have become **interactive entry points**, not merely examples.

---

# 8. Backend connection, implemented

The frontend is now connected to the actual FinLens API.

The flow is:

```text
User question
      ↓
Next.js frontend
      ↓
POST /ask
      ↓
FastAPI
      ↓
FinLens agent
      ↓
SQL / RAG / Hybrid
      ↓
Answer
      ↓
Next.js answer UI
```

The frontend sends:

```text
POST http://localhost:8000/ask
```

with:

```json
{
  "question": "What was Apple's revenue in 2024?"
}
```

This means the frontend is no longer a visual prototype.

It is now beginning to function as the actual FinLens client application.

---

# 9. Loading / analysis experience, implemented

We introduced a dedicated **FINLENS ANALYSIS** state.

Instead of displaying:

> Loading...

the UI shows the conceptual pipeline:

```text
FINLENS ANALYSIS

What was Apple's revenue in 2024?

● ROUTER
  Classifying your financial question

○ WAREHOUSE
  Querying structured financial data

○ RETRIEVAL
  Searching SEC filing evidence

○ VERIFICATION
  Cross-checking evidence

○ SYNTHESIS
  Preparing the answer
```

### Important distinction

At this stage, these are **visual analysis stages**, not yet driven by the actual streaming backend events.

That is intentional.

The next implementation step is to replace these simulated stages with the real `/ask/stream` events.

---

# 10. Answer screen, implemented

We have now introduced the first version of the actual answer experience.

The hierarchy is:

```text
QUESTION

What was Apple's revenue in 2024?


FINLENS ANSWER

[route]


Answer text


✓ VERIFIED
elapsed time
request ID
```

This follows the original principle:

> Answer first, technical details later.

---

# 11. Route indicator, implemented

The response can display the backend route.

For example:

```text
SQL
```

or:

```text
RAG
```

or potentially:

```text
HYBRID
```

This appears as a small technical metadata element rather than dominating the answer.

---

# 12. Verification, implemented

The answer surface now has a verification/evidence status.

Current visual treatment:

```text
✓ VERIFIED
```

using the semantic green system.

If verification data isn't available, the UI can instead show:

```text
Evidence returned
```

This is important because FinLens is supposed to communicate **trust**, not simply generate text.

---

# 13. Citations / Sources, first implementation

The answer screen now renders citations returned by the backend.

Current structure:

```text
SOURCES

01   Apple 2024 10-K
     relevant excerpt...

02   ...
```

The citation structure is intentionally understated.

We haven't yet implemented the previously planned **evidence drawer**.

That remains a next-stage feature.

---

# 14. Warnings, implemented

Backend warnings are now surfaced in the UI.

Visual treatment:

```text
⚠ WARNING

Structured warehouse query returned no rows...
```

Warnings use the previously defined **amber semantic color**.

This is particularly relevant to the current FinLens backend because we've already encountered the situation where SQL executes but returns no useful rows and the system falls back to filing evidence.

The UI should communicate that distinction rather than pretending everything came from the warehouse.

---

# 15. Error state, implemented

We now have a dedicated failure experience.

Instead of a raw browser/network error, FinLens displays:

```text
FINLENS COULDN'T COMPLETE THAT QUERY

FinLens could not connect to the analysis service...

[ ← Try again ]
```

This follows the earlier requirement that errors should be **human-readable**.

Technical errors are not dumped directly onto the main screen.

---

# 16. New question flow, implemented

Once an answer exists, the user gets:

```text
← New question
```

This returns them to the query interface.

So the basic interaction loop is now:

```text
Ask
 ↓
Analyze
 ↓
Answer
 ↓
New question
 ↓
Ask again
```

---

# 17. Technical details, implemented

We've added a collapsed:

```text
Technical details
```

section.

It can expose:

- SQL
- reasoning
- other backend metadata

This implements the earlier **progressive disclosure** principle.

The normal user sees the answer.

A technical/power user can inspect how FinLens produced it.

---

# 18. Answer metadata, implemented

The frontend is prepared to display backend metadata including:

- request ID
- route
- elapsed milliseconds
- verification
- warnings
- citations
- SQL
- reasoning

This mirrors the existing `/ask` response structure rather than inventing a separate frontend data model.

---

# 19. Motion design, implemented

Framer Motion is now actually being used.

Current animation behavior includes:

- home page entrance
- query interface entrance
- suggestion card entrance
- loading state transition
- answer transition
- error transition

The animation philosophy remains:

> subtle, fast, purposeful.

We're explicitly avoiding:

- excessive glowing
- bouncing
- flashy terminal animations
- "AI magic" effects

---

# 20. Current color system

The implementation now uses the previously documented semantic system.

### Primary

Cyan:

```text
#59D6FF
```

Used for:

- active navigation
- interactive emphasis
- system/analysis activity
- technical highlights

### Positive

Green:

```text
#43D58C
```

Used for:

- operational status
- verification
- successful states

### Warning

Amber:

Used for:

- warnings
- uncertainty
- incomplete/alternate evidence

### Error

Muted red:

Used for:

- API failures
- unsuccessful states

### Base

Almost-black:

```text
#07090C
```

with progressively lighter dark panels.

This creates the layered terminal appearance we wanted.

---

# 21. Typography hierarchy, implemented

Current hierarchy is intentionally compact:

### Product branding

Small uppercase / tracking.

### Main heading

```text
Ask FinLens.
```

Large, restrained, high contrast.

### Query

Medium size.

### Answer

Larger readable body text.

### Technical metadata

Small monospace / uppercase labels.

This maintains the distinction between:

**human-readable financial information**

and

**system information**.

---

# 22. Trust strip, implemented

The bottom of the home screen now communicates the three core information sources:

```text
✓ SEC filings

Structured financial data

Evidence-backed answers
```

This subtly reinforces what FinLens is without adding a large marketing section.

---

# 23. Progressive disclosure, now partly implemented

The current information hierarchy is:

```text
1. Question
2. Answer
3. Verification
4. Sources
5. Warnings
6. Technical details
```

This matches the product principle we documented earlier:

> What is the answer?  
> Why trust it?  
> Where did it come from?  
> How did the system produce it?

---

# 24. What has NOT been implemented yet

These remain planned and should **not** be considered completed:

### Streaming pipeline

Current pipeline is visual.

Next:

```text
/ask/stream
    ↓
real SSE events
    ↓
Router ✓
Warehouse ●
Retrieval ○
Verification ○
Synthesis ○
```

---

### Evidence drawer

Still planned:


```text
⌘ K

Search companies
Search filings
Ask FinLens
Previous questions
```

---

### Comparison mode

Not implemented.

---

### Saved queries

Not implemented.

---

# 25. Current product architecture

We have now moved from:

```text
UI mockup
```

to:

```text
                FINLENS

                 Next.js
                    │
          ┌─────────┴─────────┐
          │                   │
       Home UI           Answer UI
          │                   │
          └─────────┬─────────┘
                    │
                  /ask
                    │
                    ▼
                 FastAPI
                    │
                 Agent
             ┌──────┴──────┐
             │             │
            SQL           RAG
             │             │
             └──────┬──────┘
                    │
                 Answer
                    │
              Citations
              Verification
              Warnings
                    │
                    ▼
                Next.js
```

The next architectural improvement is:

```text
/ask/stream
```

so the frontend doesn't have to wait silently for the entire agent execution.

---

# 26. Updated core UX principle

The original principle still stands, but we've now started implementing it:

> **Progressive disclosure with an evidence-first financial answer experience.**

The user should primarily experience:

```text
Question
   ↓
Financial answer
   ↓
Evidence
   ↓
Verification
```

while technical information remains available underneath.

That distinction is becoming one of the defining characteristics of FinLens.

### Current milestone

I'd consider us roughly at:

**Foundation → ~Phase 1.5**

We have the shell, visual language, query experience, API connection, loading state, answer state, citations, verification, warnings and technical disclosure.

The next meaningful milestone isn't another page.

It's making the existing experience **genuinely intelligent and trustworthy** by connecting the analysis UI to the real streaming pipeline, then introducing the financial hero metric + evidence drawer.



Absolutely. I’ll treat this as the **new delta to the FinLens UI/backend documentation**, not rewrite the earlier documentation.

# FinLens, UI & Backend Documentation Update

**Scope:** Changes since the previous UI/UX documentation.

---

# 1. UI issues solved

## 1.1 Frontend is now a real Next.js application

Previously, we had established the UI direction and created the initial screen.

Since then, the frontend has been made operational with:

- Next.js 16.3.6
- React 19.2.8
- TypeScript
- Tailwind CSS
- Framer Motion
- Lucide React
- Recharts installed for future charting

Frontend runs on:

```text
http://localhost:3000
```

---

## 1.2 Backend connection established

The frontend is no longer purely static.

The query interface is connected to the existing FastAPI backend:

```text
Next.js
   ↓
FastAPI :8000
   ↓
FinLens Agent
```

The original integration used:

```text
POST /ask
```

This established the first working frontend → backend path.

---

# 2. API/server environment issues solved

Several local-development issues were encountered and resolved.

### Uvicorn missing

Initially:

```text
.venv/bin/uvicorn: No such file or directory
```

The required backend dependencies were installed, including:

```text
python-multipart
uvicorn
```

The backend subsequently started successfully.

### Port 8000 conflict

We encountered:

```text
ERROR: [Errno 48] Address already in use
```

A stale Python process was holding port 8000.

After resolving the stale process, FastAPI successfully started:

```text
Uvicorn running on http://0.0.0.0:8000
Application startup complete.
```

---

# 3. Backend health verified

Both backend health endpoints are working:

```text
GET /health
GET /ready
```

They return:

```json
{
  "status": "ok",
  "warehouse_available": true,
  "index_available": true
}
```

The API reports:

```text
embedding_provider = sentence-transformers
version = 0.1.0
```

### Important open issue

The health response reports:

```text
llm_configured: false
detail: no Anthropic credential found
```

This is potentially misleading because the actual FinLens LLM configuration uses Gemini/Groq and those providers were independently verified earlier.

**Status: OPEN / needs cleanup.**

The health check appears to be expecting/checking an Anthropic credential that isn't the primary configured provider.

---

# 4. Query submission UI solved

The query interface now supports actual submission.

Implemented:

- typing a question
- submit button
- Enter to submit
- Shift + Enter for multiline input
- disabled submit when empty
- suggested-question submission
- loading state
- error state
- returning to a new question

The basic interaction is now:

```text
Question
   ↓
Submit
   ↓
Backend
   ↓
Answer
```

---

# 5. Streaming `/ask/stream` integration completed

This is the largest UI/backend integration completed since the previous documentation.

We initially used `/ask` and then upgraded to:

```text
POST /ask/stream
```

The frontend now consumes the backend's **SSE stream**.

We verified the actual backend stream manually.

The real events are:

```text
status
route
sql
citation
verification
token
done
```

This was important because our initial frontend implementation incorrectly assumed the stream would contain an `answer` inside the `done` event.

---

# 6. SSE contract mismatch identified and fixed

### Initial problem

The frontend expected something like:

```text
done
{
  "answer": "..."
}
```

But the actual backend sends:

```text
event: token
data: {
  "text": "Apple reported..."
}
```

followed by:

```text
event: done
data: {
  "request_id": "...",
  "elapsed_ms": ...,
  "warnings": [...],
  "tokens": ...
}
```

Therefore the UI initially displayed:

> No answer was returned.

### Resolution

Frontend was changed to:

- accumulate `token` events
- treat `done` as metadata/finalization
- construct the final answer from the accumulated token text
- preserve `request_id`
- preserve warnings
- preserve timing
- update the pipeline from actual SSE events

This issue is **SOLVED**.

---

# 7. Real pipeline event mapping implemented

The UI pipeline now maps to actual backend events.

Current conceptual mapping:

```text
status
   ↓
ROUTER

route
   ↓
ROUTER complete

sql
   ↓
WAREHOUSE

citation
   ↓
RETRIEVAL

verification
   ↓
VERIFICATION

token
   ↓
SYNTHESIS

done
   ↓
COMPLETE
```

So the analysis interface is no longer entirely simulated.

This is an important architectural improvement.

---

# 8. Analysis screen upgraded

The analysis screen now responds to the actual SSE lifecycle.

It can show:

```text
✓ ROUTER
● WAREHOUSE
○ RETRIEVAL
○ VERIFICATION
○ SYNTHESIS
```

with states:

- pending
- active
- complete

Visual semantics:

### Pending

Muted gray.

### Active

Cyan + animated indicator.

### Complete

Green + check icon.

This matches the original FinLens design language.

---

# 9. Answer UI successfully receives backend output

The UI now successfully receives and displays:

- answer/token content
- route
- warnings
- elapsed time
- request ID
- citations
- verification information
- SQL
- technical information

We have therefore crossed an important boundary:

> **The frontend is now consuming actual FinLens backend output rather than mock data.**

---

# 10. Real backend behavior exposed an important issue

The Apple test exposed a backend/data-quality problem.

Question:

> What was Apple's revenue in 2024?

The backend generated SQL that returned:

```text
row_count: 0
```

But RAG subsequently found the actual number in Apple's 2024 10-K:

```text
Apple reported total net sales of $391.0 billion
for fiscal year 2024.
```

The backend nevertheless produced a final answer saying the revenue could not be provided.

---

# 11. Backend issue: zero-row SQL handling

This is currently **OPEN**.

Current flow:

```text
Question
   ↓
SQL generated
   ↓
SQL executes successfully
   ↓
0 rows
   ↓
RAG searches filing
   ↓
Correct number found
   ↓
Verification rejects filing number
   ↓
Final answer says number unavailable
```

This is undesirable for FinLens.

The system needs to distinguish:

```text
SQL failed
```

from:

```text
SQL succeeded but returned zero rows
```

and from:

```text
SQL returned data
```

These are materially different states.

---

# 12. Backend issue: RAG evidence vs structured data policy

The current verification behavior says, effectively:

> Numbers must come from query data.

That creates a conflict with FinLens's intended hybrid architecture.

In the Apple example:

```text
Warehouse
→ no result

SEC filing
→ explicit revenue figure
```

The system currently refuses to use the filing figure because it wasn't returned by SQL.

### Desired future behavior

FinLens should distinguish at least:

```text
VERIFIED, structured financial data

VERIFIED, SEC filing evidence

PARTIALLY VERIFIED

CONFLICTING EVIDENCE

UNVERIFIED
```

Rather than treating every non-SQL numeric answer as invalid.

**Status: OPEN.**

---

# 13. Backend warning behavior is working

The backend correctly generated warnings such as:

> The warehouse query returned nothing, so filing text was searched.

and:

> Revenue figure missing from query results; filing excerpt contains the number but numbers must come from query data.

The frontend successfully renders these warnings in an amber warning block.

So:

**Warning generation → working**

**Warning display → working**

**Underlying verification policy → OPEN**

---

# 14. Citation integration working

The backend sent:

```text
event: citation
```

with:

```text
AAPL 10-K 2024, Item 8 - Financial Statements and Supplementary Data
```

The frontend successfully receives citation events and has a Sources section.

Current UI:

```text
SOURCES

01
AAPL 10-K 2024, Item 8...
```

### Still open

The original planned interaction was richer:

```text
Citation
   ↓
Evidence drawer
   ↓
Company
Filing
Section
Excerpt
Open filing
```

That has **not yet been built**.

---

# 15. Verification integration, partially solved

The frontend receives:

```text
event: verification
```

and can show:

```text
✓ VERIFIED
```

or:

```text
Evidence returned
```

However, the actual verification semantics still need improvement.

In the Apple test:

```text
checked: 0
reconciled: 0
failed: 0
```

So the UI should eventually avoid implying a strong verification status when the evidence wasn't actually reconciled.

**Frontend plumbing: mostly solved.**

**Verification semantics: OPEN.**

---

# 16. Technical details successfully integrated

The answer UI now has a collapsed:

```text
TECHNICAL DETAILS
```

which can expose:

- SQL
- reasoning
- backend information

This preserves the earlier progressive-disclosure philosophy.

Normal user:

```text
Answer
Evidence
Verification
```

Power user:

```text
Technical details
SQL
Reasoning
```

---

# 17. Error handling implemented

The frontend now has a dedicated error state:

```text
FINLENS COULDN'T COMPLETE THAT QUERY
```

instead of exposing raw JavaScript/network errors.

It provides:

```text
← Try again
```

This issue is **SOLVED at the UI level**.

---

# 18. New-question flow implemented

After receiving an answer:

```text
← New question
```

returns to the main Ask interface.

The basic conversation loop is now functional:

```text
Ask
 ↓
Analyze
 ↓
Answer
 ↓
New question
 ↓
Ask
```

---

# 19. Current end-to-end architecture

As of now:

```text
                         FINLENS
                            │
                     ┌──────▼──────┐
                     │   Next.js   │
                     │    :3000    │
                     └──────┬──────┘
                            │
                       POST /ask/stream
                            │
                     ┌──────▼──────┐
                     │   FastAPI   │
                     │    :8000    │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │ FinLens      │
                     │ Agent        │
                     └──────┬──────┘
                            │
                ┌───────────┴───────────┐
                ▼                       ▼
             SQL/Data                 RAG
                │                       │
                └───────────┬───────────┘
                            ▼
                     Verification
                            │
                            ▼
                         SSE
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          pipeline        tokens        metadata
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                     FinLens UI
```

This is now a real application architecture.

---

# 20. UI issues currently OPEN

| Issue | Status |
|---|---|
| Basic FinLens shell | ✅ Solved |
| Dark terminal design | ✅ Solved |
| Responsive foundation | ✅ Solved |
| Query interface | ✅ Solved |
| Suggested questions | ✅ Solved |
| `/ask` integration | ✅ Solved |
| `/ask/stream` integration | ✅ Solved |
| SSE parsing | ✅ Solved |
| Real pipeline states | ✅ Solved |
| Token accumulation | ✅ Solved |
| Answer rendering | ✅ Solved |
| Error state | ✅ Solved |
| Warning display | ✅ Solved |
| Citation display | ✅ Solved |
| Technical details | ✅ Solved |
| Evidence drawer | 🔴 Open |
| Hero financial metric | 🔴 Open |
| Rich citation interaction | 🔴 Open |
| Live token rendering in answer card | 🟡 Partial |
| Mobile navigation | 🟡 Partial |
| Company pages | 🔴 Open |
| Financial charts | 🔴 Open |
| Filing browser | 🔴 Open |
| History | 🔴 Open |
| Command palette | 🔴 Open |
| Comparison mode | 🔴 Open |

---

# 21. Backend issues currently OPEN

| Issue | Status |
|---|---|
| FastAPI startup | ✅ Solved |
| `/health` | ✅ Working |
| `/ready` | ✅ Working |
| SSE endpoint | ✅ Working |
| SSE event contract understood | ✅ Solved |
| SQL generation | 🟡 Works but needs hardening |
| SQL zero-row handling | 🔴 Open |
| Entity/ticker resolution | 🟡 Needs improvement |
| SQL → RAG fallback | 🟡 Works, but policy needs improvement |
| Numeric evidence verification | 🔴 Open |
| Filing-derived numeric answers | 🔴 Open |
| Verification semantics | 🔴 Open |
| Health LLM configuration reporting | 🔴 Open |
| Response latency | 🔴 Open |
| Token/response optimization | 🔴 Open |
| Caching | 🔴 Open |
| dbt annual overlap test | 🔴 Open |
| Structured answer extraction | 🔴 Open |

---

# 22. Current known Apple test

The most useful integration test right now is:

```text
Question:
What was Apple's revenue in 2024?
```

Actual backend behavior:

```text
Route:
SQL

SQL:
row_count = 0

Citation:
AAPL 10-K 2024, Item 8

Verification:
checked = 0
reconciled = 0
failed = 0

RAG token:
Apple reported total net sales of $391.0 billion
for fiscal year 2024.
```

Current final UI behavior:

```text
The warehouse query did not return any revenue figure...
```

### Interpretation

This is **not a frontend failure anymore**.

It is now a clearly isolated **backend evidence/verification-policy problem**.

We're deliberately parking it, as requested.

---

# 23. Most important architectural conclusion

We've now reached a useful separation:

### UI layer

Mostly functional.

```text
Question
→ streaming analysis
→ answer
→ citations
→ warnings
→ technical details
```

### Intelligence layer

Functional but needs hardening.

```text
Routing
→ SQL/RAG
→ verification
→ synthesis
```

### Data/evidence layer

Available and working.

```text
SEC filings
Structured facts
Warehouse
Embedding index
RAG
```

The next work therefore shouldn't be random UI polishing.

When we resume backend work, the priority should be:

**evidence resolution → verification semantics → structured numeric answers → latency.**

When we resume UI work, the priority should be:

**hero financial result → evidence drawer → rich citations → company/filing experiences.**

This keeps the product architecture aligned with the original **answer → trust → evidence → technical transparency** hierarchy.