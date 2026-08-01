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
