# Followup 1: Data volume investigation and dependency hardening

Three related items handled right after Checkpoint 7's clean-clone smoke
test passed, before any visual/UI debugging began. Not part of
`docs/AUTONOMOUS_RUN_PLAN.md`'s original 7-checkpoint scope — interactively
directed follow-up work, in the same spirit as Checkpoints 1-3.

## What was asked

After Checkpoint 7 completed, a direct question: is `studies.csv`'s
73.58MB size and `raw_rows_pulled`=15,425 consistent with correctly-scoped
extraction, or does it suggest the status/condition filter is broader than
intended? Investigate and report — no fix yet. Separately, once the
investigation resolved that question, update `HLD.md` §3's planning-time
estimate (which said "a few thousand rows at most") to match the real,
now-confirmed volume.

## The investigation: row count and filter scope

Numbers from `quality_report.json`:
- `raw_rows_pulled`: 15,425
- `studies_written`: 13,335
- `duplicate_studies_merged`: 2,090
- Reconciliation: 15,425 − 2,090 = 13,335 — checks out, not a
  double-counting artifact.

Read `src/extract.py`'s actual live request parameters directly (not from
memory of the spec) — confirmed every page request sends exactly
`"query.cond": condition` and `"filter.overallStatus": "RECRUITING"` per
shortlisted condition, matching the design exactly. **The status/condition
filter itself is correctly scoped — not the cause.**

The real driver, confirmed to be a deliberate design property rather than a
bug:
1. `query.cond` is a free-text/fuzzy condition search (per the API's own
   semantics), so `query.cond=lung` matches every trial whose condition
   text mentions lung cancer in any form (NSCLC, SCLC, lung neoplasms,
   etc.), not a single narrow diagnosis code — this is what makes the
   shortlist's 8 broad, high-incidence categories useful at all rather than
   requiring 50+ exact-match queries.
2. These 8 conditions were deliberately chosen for being "among the
   highest-incidence, highest-trial-volume cancer types" — so a real,
   honest pull of currently-recruiting studies for exactly these 8
   categories combined genuinely runs into the tens of thousands. `lung`
   alone pulled 4,931 raw rows (breast 2,663 / lung 4,931 / prostate 1,327
   / colorectal 1,640 / pancreatic 1,245 / melanoma 476 / leukemia 1,427 /
   lymphoma 1,716) — plausible for the single most trial-heavy cancer type
   on the registry, not an indication of a filter bug.

**Conclusion:** the row count is consistent with correctly-scoped
extraction combined with genuinely high real-world trial volume for this
8-condition shortlist. Not a bug. No code/doc change was made at this
point — investigation and report only, per explicit instruction at the
time not to fix or resize anything yet.

## `HLD.md` §3 correction

Direct follow-up to the investigation above. Updated `HLD.md` §3's
storage-format rationale from the planning-time estimate "a few thousand
rows across three tables at most" to state the real, confirmed volume:
"~181K rows across the three tables combined — 13,335 studies + 26,859
interventions + 141,449 locations."

Added a closing sentence confirming the section's actual conclusion (CSV
over Parquet/SQLite) still holds at this scale: pandas handles ~180K rows
of CSV without strain, the app's cached load is a one-time per-process
cost rather than a per-interaction one, and switching to Parquet now for a
compression benefit that changes no actual behavior isn't worth revisiting
this late. Only the stated assumption backing the conclusion changed — the
conclusion itself didn't.

## Dependency pinning: scikit-learn, joblib, streamlit

What changed (commit `4367988`, message: "fix: scikit-learn/joblib/streamlit versions"):

```diff
-scikit-learn
-joblib
-streamlit
+scikit-learn==1.8.0
+joblib==1.5.3
+streamlit==1.60.0
```

No dedicated log entry exists explaining this commit, and none was found
on inspection — worth being explicit about that rather than inventing a
reason after the fact. The most defensible inference available: the
adjacent comment already present in `requirements.txt` (added during
Checkpoint 7, explaining the `pandas` pin) reads "pinned below 4 to avoid
an untested future major version silently breaking a graded,
reproducibility-sensitive pipeline." This commit's pins follow the exact
same reasoning pattern — pinning the three dependencies that had been left
unpinned since the project's start to the exact versions already verified
working end-to-end, as defense-in-depth, extending the lesson learned from
the pandas 3.0.5 cold-start bug (Checkpoint 7) to the rest of
`requirements.txt`.

To be clear about what is and isn't known here: this is a judgment call
inferred from an adjacent code comment and an established pattern, not a
logged fact. No specific crash or incompatibility involving unpinned
scikit-learn, joblib, or streamlit versions is documented or known to have
occurred — the pinning is preventive, not a response to an observed
failure.
