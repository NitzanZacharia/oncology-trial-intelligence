# Explainability Plan — layperson patient/caregiver audience

Status: planning document, approved, not yet implemented. No code in `app.py` or
elsewhere has changed as a result of this document.

## Context

Oncology Trial Match is fully built, tested, and verified (23/23 unit tests, manual
`chrome-devtools` verification of all three tabs, clean-clone smoke test passing). The
app currently assumes navigator-level fluency: raw NCT IDs, phase enums
(`PHASE1;PHASE2`, `EARLY_PHASE1`), sponsor-class enums (`OTHER`, `INDUSTRY`, `NIH`),
and a Pipeline Health tab that renders `"🔴 Overall status: FAIL"` /
`"Driven by: missing_rate_phases (25.7368%)"` verbatim from the JSON report, with no
translation for a non-technical reader.

**Correction to how this effort was originally framed**: `docs/project-plan.md` does
**not** name a patient/caregiver persona (verified by reading it directly, not from
memory). The only persona language anywhere in the docs is `CLAUDE.md`'s "a clinical
trial navigator or oncologist" and `docs/project-plan.md:40`'s "...a widely recognized
diagnosis category a clinical trial navigator or reviewer will immediately recognize."
Every other use of "patient" in `project-plan.md` refers to the data object (the
profile a navigator fills in), never a distinct end-user type. `docs/AUTONOMOUS_RUN_LOG.md`
has zero mentions of a caregiver persona being considered and deferred — it wasn't
part of the original scope. So this is genuinely new, additive scope being decided
now, not a return to something already planned. That doesn't weaken the case for doing
it — the assignment brief itself asks for something "business-facing" that presents
insights clearly to a non-technical stakeholder — it just means this document should
own that framing honestly.

**How this plan was produced**: grounded by reading `app.py` in full directly, reading
`requirements.txt` (`streamlit==1.60.0`, comfortably past `st.popover`'s 1.32
minimum), and using `chrome-devtools` to load the live app and step through all three
tabs (Patient Match with a submitted query, Trial Landscape on both `breast` and
`melanoma`, Pipeline Health with the failing check expanded) — so this plan is based
on what's actually rendered, not assumed. Confirmed via `grep` that neither
`tests/test_matching.py` nor `tests/test_validate.py` reference `app.py`, tab names,
or any UI string, so nothing in the test suite constrains tab count or wording. The
content/copy draft and prioritization tiering below were drafted by the
`technical-writer` subagent (no `product-manager` agent is installed in this
environment) and then reviewed against the actual code — one factual error and one
Streamlit API assumption from that draft were corrected before inclusion here (see
inline notes below).

---

## Non-goals (constraint, not assumption)

This addition must be purely additive:

- **No change to ranking**: `src/matching.py`'s TF-IDF/cosine logic, `hard_filter`,
  `rank_candidates`, `explain_match` — untouched.
- **No change to the ETL pipeline**: `etl.py`, `src/extract.py`, `src/transform.py`,
  `src/validate.py` — untouched. The Pipeline Health translations are a *display*
  layer over the existing `quality_report.json`; check logic, thresholds, and the
  report schema itself do not change.
- **No change to already-committed data** under `/data/raw` or `/data/processed`.
- **No new dependencies.** Everything here is achievable with Streamlit primitives
  already available at `streamlit==1.60.0` (`help=`, `st.popover`, `st.caption`,
  `st.expander`) — no new `pip` package.
- **No change to the required run sequence** (`git clone` → `venv` → `pip install` →
  `python etl.py` → `streamlit run app.py`) or to `requirements.txt`.
- **No change to existing tab order/position for the three current tabs** — Patient
  Match stays tab 1 and the default-active tab on load, Trial Landscape stays tab 2,
  Pipeline Health stays tab 3. The new About tab is appended as tab 4, not inserted
  first, so the default landing experience for a returning navigator is unchanged.
  Discoverability for a first-time caregiver is handled instead by one added caption
  under the page title (see §1) rather than by reordering.
- **No test changes required** — confirmed via grep that neither existing test file
  references `app.py` or any UI string.

---

## Technical notes (verify before implementation)

1. **`st.altair_chart` does not accept a `help=` parameter.** Where this plan says
   "tooltip on the phase-mix chart" or "sponsor-class chart," the actual mechanism is
   `help=` on the **`st.subheader("Phase mix", ...)`** call that already precedes
   each chart (`app.py:176`, `app.py:180`) — Streamlit added `help=` to text elements
   (`title`/`header`/`subheader`/`caption`), confirmed available at 1.60.0.
2. **`st.expander`'s `help=` support is unconfirmed.** Before locking in a hover
   tooltip on a check row before expanding, load the `developing-with-streamlit`
   skill (fetches version-matched reference docs) and confirm. If unsupported, the
   fallback below already works with zero changes: the plain-language translation
   lives in the expander body, which definitely works today.

---

## 1. New "About / How to read this" tab

Appended as the 4th tab (`st.tabs(["Patient Match", "Trial Landscape", "Pipeline
Health", "About / How to read this"])`). Add one caption under the existing page
title (`app.py:281`, right after
`st.caption("A clinical-trial matching and recommendation tool over ClinicalTrials.gov data.")`):

> `st.caption("New here? The 'About / How to read this' tab has a plain-language guide and glossary.")`

**Intro paragraph:**
> This tool helps match cancer patients with clinical trials that might be right for
> them. Whether you're a clinical trial navigator, oncologist, or a patient or family
> member exploring options, you'll get a ranked shortlist of trials based on cancer
> type, stage, and biomarkers, each with a plain-language note on why it matched.
> Everything here comes from ClinicalTrials.gov's public registry — nothing is
> generated or guessed.

**Per-tab explanations:**

> **Patient Match** — Enter a cancer type, and optionally stage and biomarkers (like
> "HER2+" or "EGFR mutation"), and this tab returns actively recruiting trials ranked
> by how closely they match. Each result shows the trial's ID, title, testing phase,
> sponsor, number of locations, and exactly which words from your profile matched the
> trial's description — so you can see *why* it's on the list, not just that it is.

> **Trial Landscape** — For a chosen cancer type, this tab shows the shape of the
> whole recruiting-trial pool: how many trials are in early vs. late testing, who's
> running them (companies, universities, government), and how trial activity has
> changed over time. Useful for understanding how much research is happening for a
> given cancer type, not for finding a specific trial.

> **Pipeline Health** — A report card for the underlying data itself: how many trial
> records were processed, and whether anything looked off (missing fields,
> implausible values, broken links between tables). This is shown openly rather than
> hidden, because a matching tool is only as trustworthy as the data behind it.

**Glossary:**

> **NCT ID** — Every trial registered on ClinicalTrials.gov has a unique ID starting
> with "NCT" followed by 8 digits (e.g. `NCT06603597`). Click it to see the trial's
> full listing on ClinicalTrials.gov.
>
> **Phase** — How far along a drug/biologic trial is in testing. `EARLY_PHASE1` and
> `PHASE1` test safety in a small group first; `PHASE2` tests whether it works;
> `PHASE3` compares it to standard treatment in a larger group; `PHASE4` monitors it
> after approval. Trials for surgery, devices, or behavioral therapy usually don't
> have a phase at all — that's normal, not missing data.
>
> **Recruiting status** — Whether a trial is currently open to new participants.
> "Recruiting" means yes, actively enrolling — this tool only shows those. "Active,
> not recruiting" means the trial is ongoing but not taking new participants right
> now. "Enrolling by invitation" means participants are selected directly from a
> specific pre-identified group rather than through open sign-up. "Completed" means
> the trial has finished.
>
> **Sponsor class** — Who's running the trial. `INDUSTRY` = a pharmaceutical/biotech
> company. `NIH` = the U.S. National Institutes of Health. `NETWORK` = a cooperative
> group of hospitals/cancer centers. `OTHER` = academic medical centers, universities,
> and hospitals not otherwise categorized (ClinicalTrials.gov's enum has no separate
> "academic" bucket). None of these categories implies better or worse trial quality.
>
> **Eligibility criteria** — The rules for who can join a trial: cancer type, stage,
> prior treatments, age, and other health conditions. This tool reads that text to
> help rank and filter matches, but always verify eligibility directly with the trial
> team — it's not a substitute for medical guidance.
>
> **Biomarker** — A measurable trait of the cancer that can affect which treatments
> apply, e.g. `HER2+` (common in some breast cancers) or an `EGFR mutation` (common in
> some lung cancers). Entering known biomarkers narrows the match to trials looking
> for that same trait.

*(Note: the subagent's first draft defined "Enrolling by invitation" as "has finished
all treatment phases," which is factually wrong — that status describes a
closed-referral enrollment method, not trial completion. Corrected above.)*

---

## 2. Per-element tooltip plan

| Element | Mechanism | Copy |
|---|---|---|
| Similarity score metric (`app.py:147`) | `help=` on the existing `st.metric` call | "How closely this trial's description matches the patient profile you entered, from 0 to 1. Higher means more shared terms (condition, biomarkers, stage) — not a medical judgment of fit, just a text-similarity score." |
| "Matched terms" caption (`app.py:155-158`) | Keep as inline `st.caption`; reword only the empty-overlap fallback | Keep `"Matched terms: her2, positive, breast"` as-is. Change the fallback from `"No overlapping TF-IDF terms — ranked by hard filter only."` to `"No shared keywords, but this trial still passes the basic filters (cancer type, and sex/age if specified)."` |
| Phase-mix chart (`app.py:176-178`) | `help=` on `st.subheader("Phase mix")` (see Technical Notes) | "Each bar is a testing phase among recruiting trials for this cancer type. Blank/'Not specified' bars are trials that don't have a phase at all (common for surgery, device, or behavioral trials) — not missing data." |
| Sponsor-class chart (`app.py:180-186`) | `help=` on `st.subheader("Sponsor class")` | "Who's running each trial — company, government, hospital network, etc. See the glossary tab for what each category means. Sponsor type isn't a quality signal." |
| Recruiting-count metric (`app.py:190`) | `help=` on the existing `st.metric` call | "How many trials for this cancer type are open to new participants right now. This number changes daily as trials open and close." |
| Year-trend chart (`app.py:192-214`) | Keep the existing `st.caption` — already the right mechanism | No change needed. |
| Pipeline Health overall status badge (`app.py:226-228`) | `st.popover` next to the existing `st.subheader` | See §3 — highest-value item in this plan. |
| Each of the 16 individual checks (`app.py:245-260`) | Plain-language line added to the existing expander body; `help=` on the expander title only if confirmed supported (see Technical Notes) | See §3 table. |

---

## 3. Plain-language translation of Pipeline Health

**The headline fix** — replacing `st.caption(f"Driven by: {summary}")` (today:
`"Driven by: missing_rate_phases (25.7368%)"`) with an `st.popover` next to the
status badge:

> **Popover title**: "What does this status mean?"
>
> **Body**:
> "🔴 **Red (FAIL)** means at least one check found an issue affecting more than 20%
> of records. Right now that's one check: **missing phase information, in 25.7% of
> trials.**
>
> Here's why: a trial's 'phase' only applies to drug or biologic treatments in human
> testing. Trials for surgery, medical devices, or behavioral therapy don't have a
> phase at all — that's expected, not an error. We checked this across every cancer
> type in this dataset individually (17%–31% missing in each), and it's consistent
> everywhere, which is what you'd expect from a real structural property of the data,
> not a bug affecting one condition.
>
> This does not affect your trial matches — phase is shown when available and
> omitted when it isn't, and the ranking doesn't depend on it.
>
> 🟡 **Orange (WARN)** means an issue affects up to 20% of records but is being
> handled automatically. 🟢 **Green (PASS)** means no issues were found. See each
> check below for full detail."

Also round the displayed percentage to one decimal (`25.7%` instead of the current
raw `25.7368%`) wherever shown to a non-technical reader.

**Plain-language one-liner for all 16 checks** (additive above the existing technical
`description`/`threshold_note` lines — a navigator who wants the precise technical
wording still has it):

| # | Check | Plain-language line |
|---|---|---|
| 1 | `nct_id_format` | Every trial's ID follows the standard NCT format. ✅ No issues. |
| 2 | `required_field_missing_nct_id` | Every trial has an ID on record. ✅ No issues. |
| 3 | `required_field_missing_brief_title` | Every trial has a title on record. ✅ No issues. |
| 4 | `required_field_missing_overall_status` | Every trial's recruiting status is known. ✅ No issues. |
| 5 | `required_field_missing_conditions` | Every trial lists at least one condition it treats. ✅ No issues. |
| 6 | `referential_integrity_interventions` | Every listed treatment is correctly linked to a real trial. ✅ No issues. |
| 7 | `referential_integrity_locations` | Every listed location is correctly linked to a real trial. ✅ No issues. |
| 8 | `enrollment_plausibility` | A small number of trials (0.18%) listed an unrealistic target enrollment (e.g. 0 or over 100,000) — those values were cleared rather than shown as fact. |
| 9 | `phase_enum` | Every phase value on record matches an official category. ✅ No issues. |
| 10 | `date_ordering` | No trial has a start date after its own completion date or similar impossible ordering. ✅ No issues. |
| 11 | `age_parsing` | A small number of trials (0.3%) described age limits in a way that couldn't be read as a number — those were cleared rather than guessed at. |
| 12 | `missing_rate_sponsor_class` | Sponsor information is present for nearly all trials. ✅ No issues. |
| 13 | `missing_rate_phases` | See the popover above — this is the one driving the overall status. |
| 14 | `missing_rate_enrollment_count` | Target enrollment numbers are present for nearly all trials. ✅ No issues. |
| 15 | `missing_rate_eligibility_criteria` | Eligibility text is present for nearly all trials. ✅ No issues. |
| 16 | `missing_rate_sex` | Sex-eligibility information is present for nearly all trials. ✅ No issues. |

---

## 4. Prioritized tier list

**Must-have** (do together as one unit):
1. **Pipeline Health FAIL popover + rounded percentages** (§3 headline fix). The
   single highest-leverage item — the screen most likely to make a caregiver distrust
   the whole tool for the wrong reason, and Data Quality & Reliability is an explicit
   15%-weighted grading criterion per `CLAUDE.md`, so this also directly serves the
   graded rubric, not just UX polish.
2. **About tab: intro + 3 per-tab paragraphs + 6-entry glossary** (§1). Cheapest way
   to give a first-time reader orientation; almost pure content, near-zero
   implementation risk.
3. **Tooltips on similarity score, phase-mix chart, sponsor-class chart** (§2, first
   three rows). These account for most of the raw-enum jargon a caregiver hits in the
   first 30 seconds of using Patient Match and Trial Landscape.

**Nice-to-have** (worth doing if time allows):
4. Tooltip on the recruiting-count metric — a single number, low ambiguity even
   unexplained, lower payoff than the must-haves.
5. The 16-check plain-language line table beyond `missing_rate_phases` (already
   covered by the must-have popover) — valuable for a caregiver who expands checks,
   but most won't go that deep once the overall badge is explained.
6. `help=` on individual check titles/expanders — marginal discoverability gain,
   contingent on the Technical Notes verification step passing.

**Cut / out of scope for this plan:**
- Chart legend/axis-level annotations beyond the section-heading tooltip — Altair
  doesn't expose this cleanly through Streamlit's wrapper without custom HTML.
- Any guided walkthrough, tutorial mode, or persisted "don't show again" state.
- Video/media explanations — no hosting mechanism in scope for a keyless, offline-run
  take-home project.

---

## Verification (for the implementation pass, not this document)

1. Confirm the two Technical Notes items (`st.subheader(help=...)`,
   `st.expander(help=...)` support) against the installed Streamlit version via the
   `developing-with-streamlit` skill before wiring tooltips to a specific call.
2. After implementation: `python -m pytest tests/` should still be 23/23 (nothing here
   touches `src/`), then a `chrome-devtools` pass — load the app, click through all 4
   tabs, expand the FAIL popover and at least 2 Pipeline Health checks, submit a
   Patient Match query — confirming new content renders and the three
   previously-verified tabs are visually unchanged except for the new tooltip
   affordances.
3. Re-run the one-way-arrow architecture check (`"extract" not in
   open("app.py").read()` etc., per `docs/AUTONOMOUS_RUN_LOG.md`'s Checkpoint 5
   pattern) since implementation touches `app.py`.
