# Followup 2: Chart rendering fixes

Three UI defects found via visual inspection of the running app (not
static code review) and fixed in three successive commits, all touching
only `app.py`. Verification for all three, at the time, was static (chart
spec inspection + an HTTP 200 boot check) — an actual interactive browser
session came later, in `followup-3-chrome-devtools-verification.md`.

## Phase-mix and sponsor-class bars: silent zero-baseline bug (`953e153`)

**What was visually wrong:** `st.bar_chart` wasn't reliably anchoring the
y-axis at zero, which rendered real, substantial categories as
barely-visible slivers relative to the largest bar — indistinguishable
from "no data" at a glance.

**What the data actually showed** (breast cancer condition): PHASE1=212,
PHASE3=195, PHASE1;PHASE2=163, PHASE4=49, EARLY_PHASE1=32,
PHASE2;PHASE3=17 — every one of these is a real, substantial category that
the missing zero baseline was rendering as effectively invisible.

Separately, the "Recruiting status" chart always showed exactly one 100%
bar for every condition, permanently — the ETL's hard `RECRUITING` filter
guarantees no other status ever appears in the data it's fed, so the chart
was structurally incapable of showing anything but a single full bar
(verified: 2,663/2,663 for breast). It was displaying a tautology, not a
finding.

**What changed:**
1. Replaced both bar charts with an explicit `st.altair_chart` +
   `alt.Scale(domainMin=0)`, via a shared `_zero_anchored_bar_chart`
   helper, independent of whatever the Streamlit/Altair version's default
   happens to be. Added a caption noting `"OTHER"` covers most
   academic/hospital sponsors, since ClinicalTrials.gov's sponsor-class
   enum has no separate academic category.
2. Replaced the recruiting-status chart with a single `st.metric` showing
   the recruiting count directly (e.g. "Recruiting trials: 2663") instead
   of a chart that could only ever show one outcome.
3. Added a caption on the studies-per-year line chart noting the final
   year is partial (year-to-date), so the recent dip isn't misread as a
   real decline — verified against real data: 2026 year-to-date=367 vs.
   2025 (a full year)=649 for breast, a genuine partial-year artifact, not
   noise.

**Verified (at the time):** chart-spec inspection confirmed `domainMin=0`
is present in the actual Altair encoding, a clean app boot (HTTP 200, no
exceptions), and the underlying numbers cross-checked directly against
`data/processed/studies.csv`.

## Year-chart x-axis: comma-formatted years (`75970da`)

**What was visually wrong:** `st.line_chart` delegates to Vega-Lite's
default quantitative-axis number formatting, which applies a
thousands-separator comma to any large-enough number on the axis —
including years, rendering "2,019" instead of "2019".

**What changed:** replaced with an explicit Altair line chart
(`axis=alt.Axis(format="d")` forces plain integer labels), keeping the
same zero-anchored y-axis convention as the other two chart fixes in this
tab.

**Verified (at the time):** chart-spec inspection confirmed the
x-encoding's `axis.format == "d"`, plus a clean app boot (HTTP 200, no
exceptions).

## Pipeline Health: fail status buried without explanation (`9bffcb7`)

**What was visually wrong:** the overall-status banner gave no indication
of *which* check(s) were driving a non-passing status, and the 16 checks
were listed in fixed build order rather than by severity — the one FAIL
(`missing_rate_phases`) was buried 13 items deep behind 12 passing checks,
meaning a reviewer had to expand and read every prior check to even find
the one that mattered.

**What changed:**
1. Added a `"Driven by: <name> (<pct>%)"` caption directly under the
   status banner, computed from any check whose status matches
   `overall_status` (only shown when status isn't `pass`). Verified
   against the real report: renders exactly as `"Driven by:
   missing_rate_phases (25.7368%)"`.
2. Sorted the checks list fail-first, then warn, then pass, instead of
   build order — `missing_rate_phases` now renders first, not 13th.

**Verified (at the time):** direct computation against
`data/processed/quality_report.json` confirmed both the driven-by summary
text and the sort order match expectations, plus a clean app boot (HTTP
200, no exceptions).

## Summary

All three were real rendering defects — silent data loss (invisible bars),
a formatting error (comma-formatted years), and buried status information
— each caught by looking at what the app actually renders, not by reading
the code that generates it. Verification at the time was still static
(chart-spec inspection, not a rendered screenshot); an actual interactive
browser session confirming all three render correctly came in the next
follow-up (`followup-3-chrome-devtools-verification.md`).
