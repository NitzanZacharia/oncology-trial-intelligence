# Checkpoints 1-3: Planning and human-reviewed implementation

This phase was fully interactive — every artifact was reviewed and
explicitly approved by the user before the next step began, per
`CLAUDE.md`'s working agreement ("Do not write implementation code until
the planning docs below are drafted and I've explicitly approved each
one.").

## Planning phase

1. **`docs/project-plan.md`** — produced by a `project-manager` subagent
   from `CLAUDE.md`'s assignment requirements and product idea seed: scope,
   a 24-hour milestone breakdown, and key risks. User requested one fix:
   add an explicit rationale sentence for why these specific 8 cancer types
   (breast, lung, prostate, colorectal, pancreatic, melanoma, leukemia,
   lymphoma) were chosen — added, citing trial volume/incidence/general
   familiarity.

2. **`docs/HLD.md`** — produced by a `data-engineer` subagent: system
   architecture, data flow, storage format decisions (CSV for flat tables,
   joblib for TF-IDF artifacts — not pickle, not re-fit-on-load), and how
   the design maps to each `CLAUDE.md` grading criterion. The user gave an
   explicit `.gitignore` scope instruction up front: `data/raw/` and
   `data/processed/` must NOT be blanket-ignored (the assignment requires
   them to persist for reproducibility); only `.venv/`, `__pycache__/`,
   `.DS_Store`, `.claude/settings.local.json`, and `CLAUDE.local.md` should
   be excluded.

3. **`docs/LLD.md`** — produced by a `data-engineer`/`python-pro` subagent:
   the exact flattened schema for trial records, specific data-quality
   check logic and pass/warn/fail thresholds, function signatures for
   everything under `/src/`, and the Streamlit caching strategy
   (`st.cache_data` for flat tables, `st.cache_resource` for the TF-IDF
   vectorizer/matrix, both keyed on a fingerprint of `/data/processed/`'s
   mtimes so a re-run of `etl.py` auto-invalidates stale cache).

**User-directed fix to both docs together:** `fetch_condition_page`'s
docstring in `LLD.md` was updated to require retry-with-exponential-backoff
on HTTP 429 responses specifically (not just the fixed 1.2s inter-page
pacing delay already planned), and `HLD.md`'s Extract section was updated
to note this is the actual rate-limit error-handling mechanism.

## Implementation, checkpoint by checkpoint

**Checkpoint 1 — `src/synonyms.py` + `src/extract.py`** (via `python-pro`):
built to `LLD.md` §3.1-3.2 exactly, including the 429 retry-with-backoff
requirement. After review, the user asked to "clean the dead-code" — an
unreachable trailing `raise` in `fetch_condition_page` left over after the
retry loop already covered every return/raise path — which was removed.

**Checkpoint 2 — `src/transform.py` + `src/validate.py`** (via
`python-pro`): built to `LLD.md` §3.3-3.4 against the actual raw JSON shape
`extract.py` produces, matching precisely: first-seen-wins scalar merging
in `merge_duplicate_studies` using `CANCER_TYPE_SHORTLIST`'s iteration
order while unioning `shortlist_conditions`; additive-only synonym
expansion in `build_composite_text` (never find-and-replace); the exact
age-parsing regex/unit conversions and the "absent" vs. "present but
unparseable" distinction; and required-field violations actually dropping
rows, not just flagging them.

During self-verification of this checkpoint, a real bug was found — not a
subagent mistake, but a flaw in the LLD's own original signature:
`run_all_checks` internally computed cleaned DataFrames (dropping
referential-integrity orphans, nulling implausible enrollment, parsing
ages) but only returned the report dict, silently discarding the cleaned
data. This was flagged to the user rather than fixed unilaterally, since it
touched an already-approved signature. The user confirmed and directed the
fix: `run_all_checks` now returns
`tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]`, with `LLD.md` §3.4
updated to match. The user explicitly asked to see this change before
continuing, and it was shown and approved before the next checkpoint began.

**Checkpoint 3 — `src/storage.py` + `src/matching.py`** (via `python-pro`):
built to `LLD.md` §3.5-3.6, enforcing the HLD's storage-format decisions
without re-litigating them (CSV for flat tables, joblib for TF-IDF
artifacts), and with `fit_vectorizer()` explicitly walled off as
ETL-time-only — never callable from anything `app.py` would import. This
checkpoint also produced the index/row-order alignment contract documented
in both modules' docstrings: `hard_filter()` must never call
`.reset_index()`, and `write_tables`/`read_tables` must never reorder rows,
so that `hard_filter(...).index.tolist()` values remain valid positional
indices into the TF-IDF matrix fit over that same `studies_df`.

## Transition to autonomous execution

After Checkpoint 3 was approved, the user authored
`docs/AUTONOMOUS_RUN_PLAN.md` directly and instructed the agent to execute
Checkpoints 4-7 unattended: self-verify each one, log to
`docs/AUTONOMOUS_RUN_LOG.md`, resolve routine ambiguity conservatively, and
only stop for a genuine blocker. See `checkpoint-4-etl.md` onward for that
phase.
