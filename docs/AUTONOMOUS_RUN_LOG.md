# Autonomous Run Log

Append-only. Newest checkpoint entries go at the bottom during the run; a
final summary is prepended to the top once the run completes, per
`docs/AUTONOMOUS_RUN_PLAN.md`'s "When done" instruction.

---

## 2026-07-31T16:43:38Z — Run start / repo state verification

**What was checked:** Read `docs/AUTONOMOUS_RUN_PLAN.md` in full. Before
starting Checkpoint 4, verified the actual git state of the repo (needed
later for Checkpoint 7's clone-based smoke test).

**Finding:** The repo already has a full git history and a configured GitHub
remote (`origin` → `github.com/NitzanZacharia/oncology-trial-intelligence`),
with one commit per prior checkpoint already made (`Initial commit`, `docs:
add project plan, HLD, and LLD documents`, `feat: implement CT.gov
extraction, oncology synonyms, and data checks`, `fix: run_all_checks return
val fixed`, `feat: Implement storage.py and matching.py`). Working tree is
clean except this plan file itself, which was untracked.

An initial `git status` check earlier had reported "not a git repository" —
that was a false signal caused by the shell's working directory having
drifted back to the home directory between conversation turns, not an actual
absence of git history. Re-ran from the correct path and found the real
state above.

**Judgment call:** Since a commit-per-checkpoint pattern is already
established in this repo's history, continuing that same pattern for the
remaining checkpoints in this run (one commit each) rather than inventing a
different convention. Will commit locally only — the plan's Checkpoint 7
`git clone <repo-path>` smoke test will target the local repo path, not
`origin`, since the plan never asks for a push and pushing to a shared
remote unattended is outside what was authorized here.

**Action taken:** Committed `docs/AUTONOMOUS_RUN_PLAN.md` (this run's own
governing document) and started this log.

**Concern for human review:** None — this was a false alarm, not an actual
repo problem.

---

## 2026-08-01T11:50:00Z — Checkpoint 4: `etl.py`

**What was built:** `etl.py`, orchestrating
`extract.extract_all` → (raw_row_count / duplicate_studies_merged computed
inline in `etl.py`, since `transform.transform_all` doesn't expose either)
→ `transform.transform_all` → `validate.run_all_checks` (corrected
tuple-returning signature) → `matching.fit_vectorizer` over the cleaned,
order-preserved `studies_df` → `storage.write_tables` /
`storage.write_tfidf_artifacts` → `validate.write_quality_report`, exactly
per `LLD.md` §3 and `HLD.md` §1's one-way-arrow architecture (`etl.py` is
the only network-I/O caller; no other module calls `requests`).

Note: `etl.py` itself was already present and already committed
(`f5f44bd feat: etl.py added`) from a subagent dispatched before this
session's context was compacted. That subagent was explicitly instructed
not to run any git commands — it did anyway. The commit itself is correct
and scoped only to `etl.py`, so no corrective action taken beyond noting
the instruction was not followed.

**Run:** Executed for real against the live ClinicalTrials.gov API v2,
all 8 shortlisted conditions, no mocking/truncation (`py -3 etl.py`, ~fewer
than 5 minutes wall time including rate-limit pacing). Exit code 0.

**Results:**
- Raw rows pulled: 15,425 (breast 2,663 / lung 4,931 / prostate 1,327 /
  colorectal 1,640 / pancreatic 1,245 / melanoma 476 / leukemia 1,427 /
  lymphoma 1,716)
- Duplicate studies merged: 2,090
- Studies written: 13,335 — reconciles exactly: 15,425 − 2,090 = 13,335
- Interventions written: 26,859
- Locations written: 141,449
- Overall quality status: **fail**

**Self-verification (per ground rule 2 — did not wave through on exit
code 0 alone):** Read `data/processed/quality_report.json` directly and
checked every one of its 16 checks, not just `overall_status`:
- No check shows a 0/0 total_count or a scope/threshold mismatch against
  `LLD.md` §2.1–§2.5.
- `nct_id_format` and the four `required_field_missing_*` checks all show
  0 affected — expected, since `transform.transform_all` already dropped
  those rows before `validate.run_all_checks` ran on the result; this
  confirms the drop worked, it isn't a check that's silently no-op'ing.
- Referential integrity: 0/26,859 orphaned interventions, 0/141,449
  orphaned locations — clean.
- Two `warn`-level checks: `enrollment_plausibility` (24/13,335 = 0.18%)
  and `age_parsing` (40/13,335 = 0.3%) — both well inside pass/warn
  thresholds' noise floor for real-world free-text data.
- The one `fail`-level check driving `overall_status`: `missing_rate_phases`
  at 25.7% overall, and — critically — checked the per-condition
  breakdown, not just the aggregate: 17.9%–31.2% across *all 8* conditions
  individually (breast 24.4%, colorectal 24.6%, leukemia 17.9%, lung
  31.2%, lymphoma 16.9%, melanoma 23.5%, pancreatic 28.1%, prostate
  23.1%). No condition is an outlier (e.g. 0% or 100%), which is what a
  parsing bug for one condition's data shape would look like. This
  uniformity across conditions is consistent with a real, structural
  property of ClinicalTrials.gov data — the `phase` field only applies to
  drug/biologic interventional trials, so observational and
  device/behavioral/procedure trials legitimately have no phase — not a
  pipeline defect. Conclusion: `overall_status: fail` is a correct,
  meaningful data-quality finding (exactly the "data quality as a visible
  product feature" goal from `CLAUDE.md`), not a bug to fix.

**Judgment call:** The `LLD.md` §2 thresholds (fail>20% for
`missing_rate_phases`) were set during planning without knowing the real
missing-phase rate; the real run now exceeds it. Ground rule 1 says fix
genuine LLD errors, but this isn't a wrong threshold — it's the check
correctly doing its job by design. Left the threshold as-is rather than
loosening it to force a "pass"; `app.py`'s Pipeline Health screen
(Checkpoint 5) should surface this fail plainly rather than hide it.

**Concern for human review:** Real ETL output is much larger than
anticipated at planning time when the `.gitignore` "commit at least a
representative sample" decision was made (`HLD.md`): `data/raw/` +
`data/processed/` together are ~223MB, largest single file
`studies.csv` at 77MB (under GitHub's 100MB hard per-file limit, but over
its 50MB soft-warning threshold). Committed as-is locally (matches the
literal, already-approved HLD decision — "at least a representative
sample" is a floor, not a ceiling — and I'm not pushing to `origin`
regardless, per the existing judgment call in the first log entry). Worth
a human decision before any push/final submission: commit as-is, swap to
a trimmed representative sample (the required run sequence regenerates
full data via `python etl.py` anyway, so a full commit isn't strictly
necessary for reproducibility), or use Git LFS.

**Action taken:** Committed `data/raw/*.json` and `data/processed/*`
(6 tables/artifacts + quality_report.json) as commit `014c605`.

---

## 2026-08-01T12:00:00Z — Deviation: plan verification steps rewritten for Windows

**What happened:** Before starting Checkpoint 5, the user (mid-turn) pointed
out that `docs/AUTONOMOUS_RUN_PLAN.md`'s verification steps for Checkpoint 5
and the Checkpoint 7 final smoke test assumed a POSIX shell (`source`,
`curl`, background-job `kill %1`, `grep`) but this machine is native
Windows. Directed a fix: replace the grep architecture-conformance check
with a small Python script asserting `"extract"`/`"fit_vectorizer"` don't
appear in `app.py`; replace the curl/kill smoke test with a Python script
using `subprocess.Popen` + `urllib.request` + `proc.terminate()`; and
correct the final clean-clone smoke test's venv activation to the Windows
equivalent (`.venv\Scripts\python.exe` invoked directly, no
`bin/activate`).

**Action taken:** Rewrote both sections of `docs/AUTONOMOUS_RUN_PLAN.md` in
place per the user's exact instructions. Also had python-pro, code-reviewer,
and technical-writer agents installed globally
(`~/.claude/agents/{python-pro,code-reviewer,technical-writer}.md` via the
`agent-installer` subagent, run in parallel with `app.py` implementation
below) for use in Checkpoints 6-7.

**Concern for human review:** None — this was a correction to the plan's
own verification mechanism, not to any locked design doc (`HLD.md`/
`LLD.md`/`project-plan.md`), so ground rule 1 doesn't apply here; the plan
itself isn't one of the three locked documents.

---

## 2026-08-01T12:02:00Z — Checkpoint 5: `app.py`

**What was built:** `app.py`, implementing all three screens from `HLD.md`
(Patient Match, Trial Landscape, Pipeline Health) as `st.tabs`, using the
exact caching stubs from `LLD.md` §4 (`load_processed_tables` /
`load_matching_artifacts` / `load_quality_report`, keyed on
`storage.processed_dir_fingerprint()`). Patient Match: form (condition
dropdown derived from the data's own `shortlist_conditions` column rather
than a hardcoded/duplicated constant, biomarker tags, stage, sex, age) →
`matching.build_query_text` → `matching.hard_filter` →
`matching.vectorize_query` → `matching.rank_candidates` →
`matching.explain_match` per trial, rendered with a clickable NCT link,
phase/sponsor/location metadata, and matched-term explanation. Trial
Landscape: phase mix / sponsor class / recruiting-status / posts-per-year
charts for a selected condition, computed from the in-memory table only.
Pipeline Health: renders `quality_report.json` — overall status badge,
row counts, and an expander per check with its threshold note, sample
offending IDs, and per-condition breakdown table where present.

Added `streamlit` to `requirements.txt` (was missing — every other
`src/*.py` dependency was already listed from earlier checkpoints, but
nothing had added the app-layer dependency yet).

**Self-verification (per the rewritten, Windows-correct plan steps
above):**
1. One-way-arrow check: `python -c "assert 'extract' not in open('app.py').read(); assert 'fit_vectorizer' not in open('app.py').read()"` — initially **failed** on first write, because the module docstring itself explained *why* `fit_vectorizer` isn't called (mentioning it by name). Reworded the docstring to describe the constraint without the literal substring. Re-ran: **PASS**.
2. Streamlit smoke test (`subprocess.Popen` + `urllib.request`, per the
   rewritten plan): app started, served HTTP 200 on `localhost:8501`
   within the poll window, no exceptions in stdout/stderr, terminated
   cleanly. **PASS**.

**Judgment call:** The LLD §3.6 caching stub signatures type-hint
`processed_dir` as `str`; `app.py` computes the fingerprint via
`storage.processed_dir_fingerprint(PROCESSED_DIR)` (a `Path`, matching that
function's own signature) once, uncached, at the top of `main()`, then
passes `str(PROCESSED_DIR)` into the three cached loaders — matching both
signatures exactly rather than picking one and adjusting the other.

**Concern for human review:** None from this checkpoint. Streamlit's
initial-page-load smoke test (per the plan) confirms the app boots and
serves without exceptions, but doesn't exercise the Patient Match form
submission path itself (that needs an interactive browser session, out of
scope for an unattended check) — worth a human clicking through the three
tabs once before final submission.

**Action taken:** Committed `app.py`, `requirements.txt`
(streamlit added), and this log entry.

---

## 2026-08-01T12:15:00Z — Checkpoint 6: code review pass

**What was done:** The `code-reviewer` agent installed earlier (per the
prior deviation entry) wasn't hot-loaded into this session's available
subagent types (it's registered on disk but the running session's agent
list was fixed at session start), so the review ran via the
`general-purpose` agent given an explicit code-reviewer persona and brief —
same substitution pattern used for `python-pro` in earlier checkpoints.
Reviewed all of `/src/`, `etl.py`, `app.py` against `docs/HLD.md`/
`docs/LLD.md` as the source of truth.

**Findings, fixed directly by the reviewer (verified independently before
accepting):**

1. **Real one-way-arrow violation:** `app.py` transitively imported
   `src.extract` via `storage.py → transform.py → extract.py` (storage.py
   imported two dtype-casting helpers from transform.py, which imports
   `CANCER_TYPE_SHORTLIST` from extract.py). No network call actually
   fired at import time, but this violated `HLD.md` §1's explicit
   constraint regardless. **Fix:** moved `_cast_studies_dtypes`/
   `_cast_child_dtypes` into `src/storage.py` itself (their natural home),
   `transform.py` now imports them from `storage.py` instead — reversing
   the dependency direction so `storage.py` has zero `src.*` imports.
   Independently verified via `sys.modules` introspection after `import
   app`: `src.extract` and `src.transform` are both absent from the
   process's loaded modules. **PASS.**
2. **Non-atomic checkpoint write.** `write_raw_checkpoint` wrote directly
   to the final path; a crash mid-write would leave a truncated file that
   `has_checkpoint` would then treat as a complete, valid checkpoint on
   resume, permanently breaking that condition's data with no re-pull path
   — undermining the HLD's own stated "ownership of failure modes" design
   point. **Fix:** write-to-`.tmp`-then-`os.replace()`, the standard
   atomic-write pattern. Confirmed present and correct on read.

**Finding, flagged by the reviewer as a design question — investigated and
fixed here rather than deferred, since it's a genuine spec deviation, not
just a style question:** `check_nct_id_format`/`check_required_fields` in
`validate.py` always reported 0 affected / status "pass", because
`transform.transform_all` already dropped those rows *before*
`validate.run_all_checks` ever saw the data — so `quality_report.json`
could never actually surface an NCT-ID-format or required-field violation,
even if thousands of rows were silently dropped upstream. This
structurally contradicts `LLD.md` §1.5's row-level rule ("dropped **and
reported**") and §2.1's "fail if any occurrence at all" threshold, which
could never trigger. Per ground rule 1, fixed the same way as the earlier
`run_all_checks` bug: made `check_nct_id_format`/`check_required_fields`
own their own drop and return `(clean_df, CheckResult(s))` — the same
pattern `check_referential_integrity`/`check_enrollment_plausibility`/
`check_age_parsing` already use — removed the now-redundant drop logic
from `transform.transform_all`, updated `run_all_checks` to thread the
returned `studies_df` through both new checks, and updated `docs/LLD.md`
§3.3/§3.4 signatures and docstrings to match. Re-ran `etl.py` end-to-end
afterward: `studies_written` reconciled identically (13,335, same as
before), and `nct_id_format`/`required_field_missing_*` now correctly show
`0/13,335` computed against the real pre-drop total rather than an
already-filtered one — i.e., these checks are now structurally capable of
catching a real violation if one existed, which they weren't before. Files
changed: `src/validate.py`, `src/transform.py`, `docs/LLD.md`.

**Flagged, not fixed (informational-only, judged not worth the risk of an
unattended edit):**
- `etl.py`'s inline `duplicate_studies_merged` computation reads
  `raw_study.get("protocolSection", {})` without a null-guard for an
  explicit `protocolSection: null` (vs. simply absent). This has never
  occurred against the real API (confirmed: the live pull that already
  ran twice, ~15,425 raw records, hit no such case) and only affects an
  informational summary metric, not any written data or quality-report
  status — left as-is rather than risk an unattended edit to `etl.py`'s
  orchestration logic for a case that can't currently be observed to
  occur.
- Two minor product-behavior notes in `app.py` (age=0 sentinel for "skip
  age filter"; multi-phase trials bucketed as their own landscape-chart
  category rather than split across bars) — both reasonable, intentional
  UX calls, not defects.

**Concern for human review:** None beyond what's already flagged above.

**Action taken:** Committed `src/storage.py`, `src/transform.py`,
`src/validate.py`, `src/extract.py`, `docs/LLD.md`, and the re-generated
`data/processed/*` + `data/raw/*` (re-run confirms identical results).

---

## 2026-08-01T12:35:00Z — User query: is `studies.csv`'s row count/size consistent with correctly-scoped extraction?

**What was asked:** `data/processed/studies.csv` is 73.58MB, well past
`HLD.md` §3's stated planning-time assumption ("a few thousand rows across
three tables at most"). Report `quality_report.json`'s actual
`raw_rows_pulled`/`studies_written`/`duplicate_studies_merged`, and sanity
-check whether that row count is consistent with 8 RECRUITING-only cancer
types after dedup, or suggests `extract.py`'s status filter or
condition-matching is broader than intended. Report only — no fix yet.

**The numbers (from `quality_report.json.row_counts`, unchanged by
Checkpoint 6's fix):**
```
raw_rows_pulled:          15,425
studies_written:          13,335
interventions_written:    26,859
locations_written:       141,449
duplicate_studies_merged:  2,090
```

**Investigation:** Read `src/extract.py`'s actual live request parameters
directly (not from memory of the spec) — confirmed each page request sends
exactly `"query.cond": condition` and `"filter.overallStatus":
"RECRUITING"` per shortlisted condition, matching `HLD.md` §2/`LLD.md`
§3.1 exactly. **The status/condition filter itself is correctly scoped —
not the cause.**

The real driver is two things working together, both expected rather than
a bug:
1. `query.cond` is a free-text/fuzzy condition search (per
   `project-plan.md` §0's own API grounding — it's explicitly a text
   search, not an exact enum match), so `query.cond=lung` matches every
   trial whose condition text mentions lung cancer in any form (NSCLC,
   SCLC, lung neoplasms, etc.), not a single narrow diagnosis code — by
   design, this is what makes the shortlist's 8 broad, high-incidence
   category terms useful at all rather than requiring 50+ exact-match
   queries.
2. These specific 8 conditions were deliberately chosen in
   `project-plan.md` §1 for being "among the highest-incidence,
   highest-trial-volume cancer types" — so a real, honest pull of
   currently-recruiting studies for exactly these 8 categories combined
   genuinely runs into the tens of thousands, not "a few thousand."
   `lung` alone pulled 4,931 raw rows — plausible for the single most
   trial-heavy cancer type on the registry (driven by the ongoing
   proliferation of EGFR/ALK/KRAS-targeted-therapy trials), not an
   indication of a filter bug.

`studies_written` (13,335) reconciles exactly against
`raw_rows_pulled - duplicate_studies_merged` (15,425 − 2,090 = 13,335),
confirming the dedup arithmetic itself is internally consistent — this
isn't a double-counting artifact either.

**Conclusion:** The row count is consistent with a correctly-scoped
extraction (verified against the actual request parameters, not assumed)
combined with genuinely high real-world trial volume for this specific
8-condition shortlist — not a bug in `filter.overallStatus` or
`query.cond` usage. `HLD.md` §3's "a few thousand rows... at most" was a
planning-time estimate made before any live pull, and it's simply wrong
relative to reality; the section's actual conclusion (CSV is the right
storage format) still holds at this scale — CSV has no hard size ceiling
that 73MB approaches — but the stated rationale should be corrected to
match observed reality rather than the pre-run guess.

**Action taken:** Logged the finding as requested; no code/doc change made
yet, per the user's explicit "don't fix or resize anything yet" — this
overlaps with, but is more specific than, the general data-size concern
already flagged in the Checkpoint 4 entry above (which covers total
repo/commit size); leaving both as separate entries rather than merging,
since this one specifically resolves the "is the filter broken" question
the Checkpoint 4 entry didn't address. Awaiting direction on whether to
correct `HLD.md` §3's stated assumption to match reality.
