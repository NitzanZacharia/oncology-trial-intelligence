# Followup 4: explainability layer (About tab, tooltips, plain-language Pipeline Health)

A purely additive UI layer aimed at a patient/caregiver reader, distinct
from the trial-navigator persona the rest of the app was originally scoped
for. Planned before any code changed, then implemented and verified.

## What was asked

Make the app genuinely understandable to someone with no clinical-trials
or cancer-treatment background — the assignment brief itself asks for
something "business-facing" that presents insights clearly to a
non-technical stakeholder. Explicit constraints: plan first (no
implementation until the plan was reviewed), ground the plan in
screenshots of the actually-rendered app rather than the code, and keep
the result purely additive with zero change to already-verified functional
behavior (ranking, filtering, the data pipeline).

## The plan

Written to `docs/EXPLAINABILITY_PLAN.md` after: reading `app.py` directly,
using chrome-devtools to screenshot all three existing tabs (including a
submitted Patient Match query and an expanded Pipeline Health check), and
delegating the content/copy draft — glossary entries, per-check
plain-language translations, and a must-have/nice-to-have prioritization —
to the `technical-writer` subagent (no `product-manager` agent is
installed in this environment).

**Two corrections made before accepting the subagent's draft**, both worth
recording since they're exactly the kind of thing that's easy to wave
through:
1. The task's framing assumed `docs/project-plan.md` already named a
   patient/caregiver persona as one of three. It doesn't — the only
   persona language anywhere in the docs is "a clinical trial navigator or
   oncologist." Checked by reading the file directly rather than trusting
   the premise. This was flagged as new, additive scope being decided now,
   not a return to something already planned.
2. The subagent's glossary draft defined "Enrolling by invitation" as
   "has finished all treatment phases" — factually wrong; that status
   describes a closed-referral enrollment method, not trial completion.
   Corrected before the plan was finalized.

Also corrected: an assumed Streamlit API surface. `st.altair_chart` does
not accept a `help=` parameter (verified via `streamlit docs st.altair_chart`
against the actual installed 1.60.0), so chart tooltips were redirected to
`help=` on the preceding `st.subheader` call instead. `st.expander`'s
`help=` support was also unconfirmed at plan time — flagged for
verification before implementation, which is exactly what surfaced the
`st.popover`-vs-`st.expander` distinction later (see
`followup-5-verification-caught-bugs.md`).

## What was built

- **4th tab, "About / How to read this"** — appended last (not first), so
  Patient Match stays the default-active tab on load, preserving the
  existing landing experience exactly. Intro paragraph, one paragraph per
  existing tab explaining its purpose, and a 6-entry glossary (NCT ID,
  phase, recruiting status, sponsor class, eligibility criteria,
  biomarker). A one-line caption under the page title points new users to
  it.
- **Tooltips** (`help=`) on: the Patient Match similarity-score metric, the
  Trial Landscape phase-mix and sponsor-class chart headings, and the
  recruiting-count metric.
- **Pipeline Health plain-language rewrite**: the raw
  `"Driven by: missing_rate_phases (25.7368%)"` line was replaced with an
  expandable explanation (`st.popover` at the time; see
  `followup-5-verification-caught-bugs.md` for why it's now
  `st.expander`) — traffic-light meaning for FAIL/WARN/PASS, which check
  is currently driving the status, and specifically why
  `missing_rate_phases` failing is expected (phase only applies to
  drug/biologic trials) rather than a defect. Percentages were also
  rounded to one decimal everywhere they're displayed. All 16 checks got a
  short plain-language one-liner added above their existing technical
  description.

## Verification

- `pytest tests/` — 23/23 pass (nothing in `src/` touched).
- Re-ran the one-way-arrow architecture check
  (`"extract" not in open("app.py", encoding="utf-8").read()`, etc.) —
  still passes.
- Full chrome-devtools pass through all four tabs: submitted a real
  Patient Match query, expanded the Pipeline Health status explanation and
  two individual checks, confirmed the About tab's content and glossary
  render as drafted, and confirmed the three pre-existing tabs are
  visually unchanged except for the new tooltip affordances.

## Judgment call

Tab placement: appended as tab 4 rather than tab 1, specifically so the
default-landing experience for a returning navigator is byte-for-byte what
it was before — discoverability for a first-time reader is handled by the
one-line pointer caption instead of reordering.
