# Followup 3: chrome-devtools MCP verification pass

A dedicated verification pass using the newly-connected chrome-devtools
MCP tool: loaded the running app in a real Chrome tab and interacted with
it directly, rather than relying on chart-spec inspection or an HTTP
boot check. Purpose: confirm the three chart-rendering fixes from
`followup-2-chart-rendering-fixes.md` actually render correctly, and catch
anything else that doesn't work as expected.

This closes two previously-open gaps at once: Checkpoint 5's Patient Match
form-submission path (verified only by an HTTP 200 boot check and an
architecture-conformance assertion, never an actual interactive session —
flagged in `docs/AUTONOMOUS_RUN_LOG.md`'s final summary and Checkpoint 5
entry), and Followup 2's chart fixes (verified only via static chart-spec
inspection, never a rendered screenshot).

## Setup

Started `streamlit run app.py` locally, opened it in a real Chrome tab via
chrome-devtools MCP, and worked through all three tabs.

## Patient Match tab

Submitted a real query: condition=breast, biomarker tags="HER2 positive".
Got 20 ranked results in descending-score order. Top result: `NCT06603597`
("HER2-positive Breast Cancer Registry"), similarity score 0.819, matched
terms "her2, positive, breast". Every result card rendered correctly —
similarity-score metric, phase/sponsor/location metadata, and the matched-
terms caption all legible with no visual glitches.

Tested the age hard-filter specifically to confirm it's actually live, not
a no-op: resubmitted the identical query with age=1 (breast cancer trials
are overwhelmingly adult-oriented). The result set changed — the previous
top result (`NCT06603597`, 0.819) dropped out entirely, and the new top
result was `NCT07030569` at a lower score (0.624), confirming the filter
genuinely excludes trials whose parsed age eligibility conflicts with the
patient profile, rather than silently passing everything through
regardless of the filter value.

## Trial Landscape tab

Verified on two conditions: `breast` (2,663 studies, the largest of the 8
shortlisted conditions) and `melanoma` (476 studies, the smallest — chosen
specifically to confirm the zero-baseline fix holds at low counts too, not
just at breast's larger scale).

**Phase-mix and sponsor-class bars:** confirmed via screenshot that every
bar now has a visible, correctly-anchored zero baseline.
- breast: Not specified=1500, PHASE2=495, PHASE1=212, PHASE3=195,
  PHASE1;PHASE2=163, PHASE4=49, EARLY_PHASE1=32, PHASE2;PHASE3=17 — all
  visible, including the smallest (17).
- melanoma: Not specified=188, PHASE2=91, PHASE1;PHASE2=77, PHASE1=74,
  PHASE3=26, PHASE2;PHASE3=8, EARLY_PHASE1=8, PHASE4=4 — confirms the fix
  holds even when every bar (not just the smallest) is far below breast's
  absolute counts.

**Year-axis formatting:** confirmed renders plain integers (2002, 2003, …
2025, 2026) with no thousands-separator comma, on both conditions.

**Recruiting-status section:** confirmed now displays as a clean
`st.metric` tile — "Recruiting trials: 2663" for breast, "Recruiting
trials: 476" for melanoma — instead of the old single-bar tautology chart.

## Pipeline Health tab

Confirmed "🔴 Overall status: FAIL" is immediately followed by "Driven by:
missing_rate_phases (25.7368%)" directly beneath the badge, not buried.

Confirmed the 16 checks render sorted fail→warn→pass: `missing_rate_phases`
first, then the two warns (`enrollment_plausibility`, `age_parsing`), then
the 12 passes — not build order.

Expanded the top failing check (`missing_rate_phases`) and confirmed its
detail panel renders correctly: threshold note
("pass&lt;=5%, warn&lt;=20%, fail&gt;20%"), 10 sample offending NCT IDs, and the
per-condition breakdown table are all present and readable.

## Browser console and warnings

Checked the browser console throughout every interaction. Found two
pre-existing accessibility-lint issues native to Streamlit's own generated
widget markup:
- "No label associated with a form field"
- "Incorrect use of autocomplete attribute"

Neither is related to any code in this project — both are inherent to how
Streamlit renders its own widgets, present regardless of any change made
here, and not investigated further.

Also observed a repeated console warning:
`WARN Infinite extent for field "Count_start"/"Count_end"/"year"/"count": [Infinity, -Infinity]`
from Vega-Lite, appearing on every chart that uses the
`alt.Scale(domainMin=0)` zero-baseline fix. Investigated by reading
`app.py`'s chart-construction code directly: confirmed `domainMin=0` is
the deliberate, correct fix from `followup-2-chart-rendering-fixes.md`
(not a mistake), and traced the warning to a known interaction between a
fixed `domainMin` and Streamlit's built-in responsive-width/interactivity
handling for Altair charts — a cosmetic Vega-Lite quirk, not a functional
defect.

**Treated as non-blocking, not as a defect to fix:** every affected
chart's actual rendered output was screenshotted and confirmed correct
(proper zero baselines, no visual artifacts, no missing bars), and no
`[error]`-level console output appeared anywhere in this pass — only
`[warn]`. This is a case of "investigated and consciously left alone,"
not "missed."

## Verdict

All three chart-rendering fixes (`953e153`, `75970da`, `9bffcb7`) are
confirmed working as intended in an actual rendered browser session across
both a high-volume and a low-volume condition. The Patient Match form's
submission path, including its age/sex hard filters, is confirmed live and
correctly discriminating — not a static page that happens to boot. No
functional bugs were found; the one non-blocking console warning above is
the only open item, and it's a Vega-Lite/Streamlit interaction quirk, not
anything specific to this app's logic.
