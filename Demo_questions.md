##check the document is ready

docker compose exec postgres psql -U postgres -d modern_rag -c \
  "SELECT filename, status, failure_reason, created_at FROM documents ORDER BY created_at DESC LIMIT 10;"





"What are the six text wrapping modes described in the document?"
"What is the difference between square and tight text wrapping?"
"Which wrapping mode is used for watermarks?"
"What wrapping mode is described as placing the image in front of the text layer?





## TEXT QUESTIONS
*Tests: paragraph retrieval, multi-chunk reasoning, conversation rewriting*

---

### T1 — Direct factual retrieval
> What was ICICI Bank's net profit for fiscal 2025 and how much did it grow?

**Source type:** Text paragraph (MD&A summary, page 117)
**Expected answer:** Profit after tax grew from ₹408.88 billion in fiscal 2024 to
₹472.27 billion in fiscal 2025, an increase of 15.5%.
**Why it works:** Clean single-paragraph retrieval. Good opening question —
answer is fast and verifiable.

---

### T2 — Cause-and-effect reasoning
> Why did provisions and contingencies rise so sharply in fiscal 2025?

**Source type:** Multi-paragraph explanation (MD&A, pages 117–118)
**Expected answer:** Provisions rose 28.5% (₹36.43 bn → ₹46.83 bn) primarily
due to higher specific provisions for NPAs in retail and rural loans, plus
provisions for investments. In fiscal 2024, unusually high recoveries and
upgrades in non-retail loans had reduced provisions — that tailwind did not
repeat in fiscal 2025.
**Why it works:** The system must read an explanatory paragraph, not just pull a
number. This is the clearest demonstration of RAG doing reasoning, not search.

---

### T3 — ESG / non-financial disclosure
> What is ICICI Bank's carbon neutrality target and what emissions scope does it cover?

**Source type:** ESG section text (pages 45–46)
**Expected answer:** The Bank has set a target to achieve carbon neutrality in
Scope 1 and Scope 2 emissions across its operations by fiscal 2032.
**Why it works:** Shows the system retrieves non-financial content from deep in
the document with the same accuracy as financial data.

---

### T4 — Product feature detail
> What is iCRM and what capabilities does it give bank employees?

**Source type:** Business strategy / digital section (pages 25–26)
**Expected answer:** iCRM is a unified, cloud-based CRM platform providing
employees a real-time 360° view of each customer's relationship with the Bank.
It enables simplified customer onboarding journeys, enhanced relationship
management, intelligent customer insights, streamlined omni-channel
communication, centralised customer engagement memory, holistic Customer-360°
coverage, automated service and escalation, and real-time nudges — all
integrated with core banking systems.
**Why it works:** Tests synthesis of a multi-point infographic-style page into a
coherent prose answer.

---

### T5 — Follow-up / conversation rewrite *(run immediately after T1)*
> How did that compare to the previous year's growth rate?

**Source type:** Same MD&A text — but resolved via conversation history
**Expected answer:** The system should rewrite the query as "How did ICICI
Bank's net profit growth rate in fiscal 2025 compare to fiscal 2024?" and
answer: In fiscal 2024, net profit grew from ₹318.96 bn (FY2023) to
₹408.88 bn — roughly 28.2% growth. The FY2025 growth of 15.5% represents a
moderation but on a much larger base.
**Why it works:** Watch the "Searched as:" line appear in the UI showing the
rewritten query. This is the `resolved_query` field made visible — your most
impressive pipeline feature shown in one sentence.

---

## TABLE QUESTIONS
*Tests: structured data extraction, multi-row/column retrieval, numeric precision*

---

### TB1 — Single-table row lookup
> What was the interest spread and net interest margin as per the yield/cost table in the MD&A?

**Source type:** Yield, cost, spread and margin table (page 119/120)
**Expected answer:**

| Metric | Fiscal 2024 | Fiscal 2025 |
|---|---|---|
| Yield on interest-earning assets | 8.71% | 8.69% |
| Cost of interest-bearing liabilities | 4.86% | 5.10% |
| Interest spread | 3.85% | 3.59% |
| Net interest margin | 4.53% | 4.32% |

NIM fell from 4.53% to 4.32% because the cost of funds rose faster than
asset yields.
**Why it works:** Multi-column table extraction with correct pairing of values
to rows. The NIM compression story is the key insight from this table.

---

### TB2 — Multi-row aggregation from table
> How much did ICICI Bank lend to the agriculture sector and what share of net bank credit did it represent in fiscal 2025?

**Source type:** Priority sector lending table (page 130)
**Expected answer:** Agriculture sector lending was ₹2,025.15 billion, representing
18.0% of adjusted net bank credit in fiscal 2025 — exactly meeting the 18.0%
regulatory target. Small and marginal farmers alone accounted for ₹1,197.77
billion (10.6% vs a 10.0% target).
**Why it works:** Table has a "Target" column alongside actuals — the system
must retrieve three columns and connect the number to the compliance
narrative.

---

### TB3 — Cross-table P&L reconstruction
> From the operating results table, what was the core operating profit in fiscal 2025 and by how much did it grow?

**Source type:** Operating Results Data table (page 118)
**Expected answer:** Core operating profit was ₹653.96 billion in fiscal 2025,
up 12.5% from ₹581.22 billion in fiscal 2024. This was driven by NII growth
of 9.2% and fee income growth of 14.8%, partially offset by operating expenses
rising 8.3%.
**Why it works:** The table has 12 line items — the system picks the right row
without confusing it with operating profit (₹672.99 bn, which includes treasury
gains). Precision on a dense financial table.

---

### TB4 — Related party transactions table
> What was the maximum balance of deposits accepted from subsidiaries during fiscal 2025?

**Source type:** Related party maximum balances table (page 232)
**Expected answer:** ₹44,305.5 million in deposits accepted from subsidiaries
during fiscal 2025, up from ₹31,501.6 million in the prior year.
**Why it works:** This table is on page 232 of 341 — deep in the financial
statements. Confirms the system indexes and retrieves from the entire document,
not just the first few sections.

---

## IMAGE QUESTIONS
*Tests: image chunk retrieval, vision description accuracy, alt-text pipeline*

> **Note for the demo:** These questions work because the ingestion pipeline ran
> `moondream:1.8b` to describe each image and embedded those descriptions as
> chunks. The citation excerpt will show the image description text, not the
> image itself. That is expected behaviour — explain this to your manager before
> asking these.

---

### I1 — Bar chart reading
> What trend do the financial highlights charts show for total deposits from March 2021 to March 2025?

**Source type:** Bar chart — Total Deposits (Financial Highlights page, page 7)
**Expected answer:** Total deposits showed consistent growth over 5 years:
₹9,325.22 bn (Mar-21) → ₹10,645.72 bn (Mar-22) → ₹11,808.41 bn (Mar-23) →
₹14,128.25 bn (Mar-24) → ₹16,103.48 bn (Mar-25). The bars show acceleration
in FY2024 and FY2025 driven primarily by term deposit growth, with CASA
(current + savings) growing at a slower pace. The chart also breaks out the
CASA mix clearly.
**Why it works:** The financial highlights page (p.7) has four charts. This
tests whether the image chunk for the deposits chart was correctly described and
retrieved. If the system returns the right description, the multimodal pipeline
worked.

---

### I2 — Capital adequacy chart
> What does the capital adequacy chart show about ICICI Bank's Tier-1 and total CAR trend?

**Source type:** Capital Adequacy bar chart (Financial Highlights page, page 7)
**Expected answer:** The chart shows total CAR peaked at 19.16% in March 2022,
then moderated to 16.55% by March 2025 as the balance sheet grew. Tier-1 / CET-1
ratio has held steady at around 15.60%–15.94% since March 2023, with the Tier-2
buffer very thin (0.61% at March 2025). The trend shows healthy but declining
capital buffer above regulatory minimums.
**Why it works:** The chart shows a declining total CAR trend that the text alone
doesn't emphasise — image retrieval surfaces a story the tables don't tell
directly.

---

### I3 — Infographic / platform diagram
> What are the capabilities of the iCRM Unified CRM Platform as shown in the diagram?

**Source type:** iCRM capabilities diagram / infographic (page 25)
**Expected answer:** The diagram shows iCRM built around three core functions:
Customer Onboarding, Relationship Enrichment, and Service Fulfilment. Eight
capability nodes surround it: Simplified Customer Onboarding Journeys, Enhanced
Relationship Management, Intelligent Customer Insights On-the-Go, Streamlined
Omni-channel Communication, Centralised Customer Engagement Memory,
Holistic Customer-360° Coverage, Automated Service and Escalation Framework,
and Real-time Nudges and Updates. The platform is also noted as Integrated with
Core Banking Systems.
**Why it works:** This infographic exists only as an image — none of its
text content appears in the extractable text layer. If the system answers this
correctly, it proves the vision description pipeline captured content that
text-only RAG would miss entirely.

---

### I4 — Product screenshot
> What features of InstaBIZ are shown in the app screenshots in the document?

**Source type:** InstaBIZ app screenshots (page 27)
**Expected answer:** The screenshots show four InstaBIZ screens: GST Payment
(showing a successful GST challan payment with reference ID), Collection
Dashboard for Merchants (showing personalised collection view by payment type
with breakdowns for Card, UPI, Wallet, Cash), SmartLock (showing the ability
to temporarily lock/unblock banking channels like InstaBIZ app and Debit Card
Inquiry Card), and EEFC Account Opening (showing multi-currency selection
including USD, EUR, GBP, AED).
**Why it works:** App screenshots are pure image content. This tests whether
moondream correctly identified the four distinct screen contexts and their
content rather than giving a generic "shows a mobile banking app" description.

---

### I5 — Abstention on a visual question *(important credibility moment)*
> What is the pie chart breakdown of ICICI Bank's loan portfolio by geography?

**Source type:** Does not exist in this document
**Expected answer:** System should **abstain** — "No relevant evidence found in
your documents."
**Why it works:** There is no geography pie chart in this document. Loan mix
is shown as a stacked bar chart (p.7) broken by segment, not geography. An
overconfident system would hallucinate a pie chart breakdown. Showing clean
abstention here — especially after successfully answering I1–I4 — is the
strongest trust signal in the demo. Pause here and say it explicitly.

---

## Suggested 12-minute demo order

| Time | Question | What you are showing |
|------|----------|---------------------|
| 0:00 | Upload PDF, wait for Ready | Ingestion pipeline |
| 1:00 | T1 (net profit) | Basic text retrieval, fast |
| 2:00 | T5 (follow-up) | Conversation rewrite, "Searched as:" visible |
| 3:30 | T2 (why provisions rose) | Reasoning over text, not lookup |
| 5:00 | TB1 (yield/NIM table) | Table extraction with 4 columns |
| 6:30 | TB3 (operating results) | Correct row selection from dense P&L table |
| 8:00 | I1 (deposits chart) | Image chunk retrieved — multimodal pipeline |
| 9:00 | I3 (iCRM diagram) | Content invisible to text-only RAG, now retrievable |
| 10:30 | I5 (geography pie) | **Abstention** — pause, explain why this matters |
| 11:30 | Switch to baseline on T1 | A/B comparison, ~70ms vs ~1700ms live |

---

## Quick answer cheat sheet

| Question | Answer |
|----------|--------|
| Net Profit FY25 | ₹472.27 bn (+15.5%) |
| NIM FY25 | 4.32% (down from 4.53%) |
| Interest spread FY25 | 3.59% |
| Core operating profit FY25 | ₹653.96 bn (+12.5%) |
| Total deposits FY25 | ₹16,103.48 bn (+14.0%) |
| Total advances FY25 | ₹13,417.66 bn (+13.3%) |
| Agriculture lending FY25 | ₹2,025.15 bn = 18.0% of ANBC |
| Deposits from subsidiaries max balance | ₹44,305.5 mn |
| CAR FY25 | 16.55% (Tier-1: 15.94%) |
| Carbon neutrality target | Scope 1 + 2 by fiscal 2032 |
| ESG score (Sustainalytics) | 22.5 → 18.9 (Medium → Low Risk) |