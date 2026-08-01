# Checkpoint 5: `app.py`

Part of the unattended autonomous run. Full self-verification detail is in
`docs/AUTONOMOUS_RUN_LOG.md`'s Checkpoint 5 entry.

## What was asked

Implement `app.py` per `LLD.md` §4's caching strategy and `HLD.md`'s
three-screen concept (Patient Match, Trial Landscape, Pipeline Health).
Self-verify the one-way-arrow constraint mechanically (no reference to the
extract stage or the vectorizer-fitting function). Smoke-test that the app
actually boots and serves.

Mid-checkpoint, the user flagged that the plan's verification commands
(`grep`, `curl`, `kill %1`, `source .venv/bin/activate`) assumed a POSIX
shell on a machine that's actually native Windows, and directed a rewrite
of those steps in `docs/AUTONOMOUS_RUN_PLAN.md` to small, OS-independent
Python scripts instead — done before running Checkpoint 5's verification,
so the verification actually run matches what's documented.

## What was built

`app.py`: three `st.tabs` (Patient Match, Trial Landscape, Pipeline
Health), backed by the exact `@st.cache_data`/`@st.cache_resource` loader
stubs from `LLD.md` §4, all keyed on a fingerprint of `/data/processed`'s
file mtimes so a re-run of the ETL pipeline invalidates the cache
automatically. Patient Match builds a query from the patient form, hard-
filters to recruiting trials matching the condition (and sex/age where
given), ranks by TF-IDF cosine similarity, and explains each match with
the top overlapping terms. Trial Landscape aggregates phase mix, sponsor
class, status, and posting-year trend for a chosen condition. Pipeline
Health renders the quality report produced by Checkpoint 4's `etl.py` run
as an in-app panel, per-check, with per-condition breakdowns where
applicable.

The condition dropdown is derived from the loaded data's own
`shortlist_conditions` column rather than importing the fixed shortlist
constant from the extraction module — avoiding any import from that module
entirely, which both satisfies the one-way-arrow constraint structurally
(not just by avoiding the literal words) and stays correct if the
underlying data ever changes.

## Self-verification

Ran the rewritten, Windows-correct verification steps: a Python assertion
script confirmed neither `"extract"` nor `"fit_vectorizer"` appears
anywhere in `app.py` (this caught one real issue — see below); a
`subprocess.Popen` + `urllib.request` smoke test confirmed the app starts,
serves HTTP 200, and shuts down cleanly with no exceptions in its output.

## Judgment calls / deviations

- The one-way-arrow check initially failed: the module docstring named
  `src.matching.fit_vectorizer` directly to explain why the app doesn't
  call it. Reworded the docstring to describe the constraint without using
  that literal identifier, then re-verified. This is exactly the kind of
  case a mechanical check is supposed to catch even when the intent behind
  the flagged text is benign.
- Matched the LLD §4 caching stub signatures exactly (`processed_dir: str`)
  by converting the `Path` fingerprint call's `PROCESSED_DIR` argument to
  `str()` only at the loader call sites, keeping `storage.
  processed_dir_fingerprint`'s own `Path`-typed signature untouched.
- Added `streamlit` to `requirements.txt`, which no earlier checkpoint had
  populated since it's an app-layer, not `src/`-layer, dependency.
