# Oncology Trial Match

A clinical-trial matching and recommendation tool for a trial navigator or
oncologist with a specific patient — cancer type, biomarkers, stage, age,
sex — who needs a ranked, explained shortlist of actively recruiting
trials from [ClinicalTrials.gov](https://clinicaltrials.gov), not a raw
keyword search.

Full design rationale lives in `docs/project-plan.md`, `docs/HLD.md`, 
and `docs/LLD.md`; how it was built is in `docs/AUTONOMOUS_RUN_LOG.md`
and `/ai_transcript/` (see "AI usage" below).

## Setup

Requires Python 3.10+. No API key, no credentials, no manual data
preparation — the pipeline pulls live from ClinicalTrials.gov's free,
keyless API v2.

```
git clone <this-repo> && cd oncology-trial-intelligence
python -m venv .venv

# macOS/Linux
source .venv/bin/activate
# Windows
.venv\Scripts\activate.bat

pip install -r requirements.txt
python etl.py
streamlit run app.py
```

`python etl.py` takes a few minutes (pulls ~15k recruiting studies across
8 cancer types, paced to stay under ClinicalTrials.gov's community-observed
rate limit) and writes everything under `/data/raw` and `/data/processed`.
It's safe to re-run: each condition is checkpointed to `/data/raw`
independently, so a run that dies partway through resumes instead of
re-pulling from scratch. `streamlit run app.py` never touches the network
— it only ever reads `/data/processed`.

Repo data is already committed (see "Why the data is committed" below), so
`streamlit run app.py` alone works without running `etl.py` first if you
just want to look at the app.

## Architecture

```
ClinicalTrials.gov API v2
         │  (network I/O lives ONLY in etl.py)
         ▼
      etl.py
  extract -> transform -> validate -> store
         │
   ┌─────┴──────┐
   ▼            ▼
/data/raw   /data/processed
(per-cond.  (studies/interventions/locations.csv
 checkpoint, + tfidf_vectorizer.joblib/tfidf_matrix.joblib
 resume pt.) + quality_report.json)
                  │  (read-only, cached)
                  ▼
               app.py
          Streamlit UI (3 tabs)
   patient query -> filter -> rank -> explain
```

The arrow direction is one-way and enforced: `app.py` never imports the
extraction module and never calls the vectorizer-fitting function (see
`src/matching.py`'s module docstring) — every request the app serves is
answered entirely from what's already on disk. This is what makes
`python etl.py` and `streamlit run app.py` safe to run independently and
repeatedly.

**Pipeline stages** (`src/`, orchestrated by `etl.py`):
- **`extract.py`** — pages through `GET /api/v2/studies` for 8 shortlisted,
  high-incidence cancer types (breast, lung, prostate, colorectal,
  pancreatic, melanoma, leukemia, lymphoma), filtered to `RECRUITING`.
  Rate-limit handling has two layers: a fixed pacing delay between
  requests, and exponential backoff with up to 5 retries on an actual
  HTTP 429. Each condition's raw JSON is written atomically to
  `/data/raw/<condition>.json` as a checkpoint before moving to the next.
- **`transform.py`** — flattens each study's nested `protocolSection` into
  three tables (`studies`, `interventions`, `locations`), dedupes studies
  that appear under more than one shortlisted condition (first-seen-wins
  for scalar fields, union for the condition-tag column), and builds each
  study's `composite_text` — the document TF-IDF is fit over — with a
  small, hand-curated biomarker/notation synonym table applied additively
  (e.g. a trial saying "HER2-positive" also gets "HER2+" appended, so a
  query typed with either notation matches).
- **`validate.py`** — 16 data-quality checks (schema/format, dedupe,
  referential integrity, plausibility, missing-rate), each producing a
  `pass`/`warn`/`fail` verdict with explicit thresholds, written to
  `quality_report.json` and rendered as an in-app panel — not a build-time
  log line that disappears after the run.
- **`storage.py`** — flat tables as CSV, TF-IDF vectorizer/matrix via
  `joblib` (scikit-learn's own recommended path for fitted estimators).
  See `docs/HLD.md` §3 for why CSV/joblib over Parquet/SQLite/pickle.
- **`matching.py`** — TF-IDF cosine similarity. The vectorizer is fit
  exactly once, in `etl.py`; every app-time query only ever calls
  `.transform()` against that already-fitted vectorizer, so no re-fit ever
  happens per user interaction.

**App** (`app.py`, three tabs):
- **Patient Match** — profile form (condition, biomarker tags, stage, sex,
  age) → hard filter (`RECRUITING` + condition + sex/age eligibility) →
  TF-IDF cosine ranking → explanation panel showing the specific
  overlapping terms that drove each match, in plain language. No model,
  no LLM call at runtime — every score is reproducible offline from what's
  on disk.
- **Trial Landscape** — phase mix, sponsor-class breakdown, recruiting
  status, and posting-year trend for a chosen cancer type, computed
  entirely from the in-memory table.
- **Pipeline Health** — the data-quality report as a visible product
  surface: overall status, row counts, and every individual check with its
  threshold, offending examples, and per-condition breakdown.

## Data model

Three flat tables under `/data/processed`, one row per entity:

- **`studies.csv`** — one row per NCT ID: title, status, dates, sponsor,
  conditions, phase(s), enrollment, eligibility text/sex/age bounds, and
  the derived `composite_text`/`shortlist_conditions` columns. Full column
  list and dtypes: `docs/LLD.md` §1.1.
- **`interventions.csv`** — one row per study/intervention pair (type,
  name). `docs/LLD.md` §1.2.
- **`locations.csv`** — one row per study/facility pair (facility, city,
  state, country). `docs/LLD.md` §1.3.
- **`quality_report.json`** — machine-readable data-quality report, schema
  in `docs/LLD.md` §1.5.
- **`tfidf_vectorizer.joblib` / `tfidf_matrix.joblib`** — the fitted TF-IDF
  vectorizer and sparse similarity matrix, one row per `studies.csv` row in
  the same order.

## Known limitations

- **Eligibility text is unstructured.** ClinicalTrials.gov's API has no
  structured biomarker field anywhere — `eligibilityCriteria` is a single
  free-text blob. Biomarker matching is necessarily free-text keyword
  matching against that blob (helped by the synonym table), not a
  structured lookup or clinical NLP extraction. A patient query for a
  biomarker phrased in a way the trial's free text and the synonym table
  don't anticipate may under-match. This is a deliberate, documented scope
  boundary (`docs/project-plan.md` §0/§1), not an oversight.
- **Fixed 8-condition shortlist.** The ETL only ingests the 8 highest-
  incidence, highest-trial-volume cancer types, not all of oncology — a
  rare-cancer query outside this shortlist returns nothing.
- **No embeddings/LLM re-ranking.** TF-IDF + cosine similarity is the
  final, locked matching approach — a deliberate trade favoring
  transparency and full offline reproducibility (every score traceable to
  specific overlapping terms) over a marginal relevance gain from a
  heavier, less explainable model.
- **`overall_status` in the committed `quality_report.json` is `fail`.**
  This is not a broken pipeline — it's driven by one check
  (`missing_rate_phases`, ~26% overall, consistently 17–31% across all 8
  conditions individually) that reflects a genuine property of the data:
  `phase` only applies to drug/biologic trials, so observational and
  device/behavioral/procedure trials legitimately have none. See the
  Pipeline Health tab, or `docs/AUTONOMOUS_RUN_LOG.md`'s Checkpoint 4
  entry, for the full reasoning.
- **Locations are shown as a plain list**, not geocoded or ranked by
  distance — no "trials near me," per the explicit scope decision in
  `docs/project-plan.md`.

## Why the data is committed

`/data/raw` and `/data/processed` are committed to this repo rather than
`.gitignore`d, so the project is reviewable without necessarily re-running
`etl.py` against a live third-party API (`docs/HLD.md` §5). Running
`python etl.py` yourself regenerates all of it from scratch and will
produce very similar (row counts fluctuate slightly as trials open/close
on ClinicalTrials.gov between runs), but not byte-identical, output.

## Testing

```
pytest tests/
```

`tests/test_matching.py` covers ranking determinism (`rank_candidates`
returns the same order every time for the same inputs), the
`hard_filter`/index-alignment contract, and `explain_match`.
`tests/test_validate.py` covers every `check_*` function in `src/validate.py`
against known good/bad inputs, including the exact pass/warn/fail
thresholds from `docs/LLD.md` §2.

## AI usage

This project was built with Claude Code end-to-end: planning docs
(`docs/project-plan.md`, `docs/HLD.md`, `docs/LLD.md`) drafted by
specialized subagents and reviewed/corrected interactively before any
implementation code was written, followed by an interactively-reviewed
implementation phase (checkpoints 1–3), then an explicitly-authorized
unattended run through checkpoints 4–7 (ETL execution, `app.py`, code
review, tests/README/final smoke test) — self-verified against the locked
design docs and logged to `docs/AUTONOMOUS_RUN_LOG.md` at every step,
including the bugs found and fixed along the way (e.g. a data-quality
check that could structurally never fail because the offending rows were
already dropped upstream, found during the Checkpoint 6 code review and
fixed by making the check own its own drop — see that log entry for the
full account).

The full interaction record is under `/ai_transcript/`, one file per
checkpoint, plus a README there explaining why it's a manually-authored
summary rather than a raw `/export` dump (no tool available during the
unattended run could invoke that CLI command — logged as a deviation in
`docs/AUTONOMOUS_RUN_LOG.md`).

After the autonomous run's 7 checkpoints, a further round of fixes
happened: some via code-level investigation (confirming the ~181K-row data
volume was genuine trial volume, not a filter bug, and correcting
`HLD.md` §3's outdated estimate; pinning scikit-learn/joblib/streamlit as
defense-in-depth after the pandas-version lesson from Checkpoint 7), and a
distinct visual-debugging phase using a browser-automation tool
(chrome-devtools MCP) to actually load the running app and screenshot it.
That phase caught three real UI bugs by looking at rendered output rather
than code: bar charts not anchoring at zero (making substantial categories
render as invisible slivers), a comma-formatted year axis ("2,019" instead
of "2019"), and the Pipeline Health tab's fail status being buried without
an immediate explanation of what was driving it. A follow-up
chrome-devtools pass then confirmed all three fixes render correctly in an
actual browser session and exercised the Patient Match form end-to-end for
the first time (a real query, ranked results, and working age/sex hard
filters) — closing out two previously-open verification gaps. See
`/ai_transcript/followup-1-data-volume-and-dependency-hardening.md`,
`followup-2-chart-rendering-fixes.md`, and
`followup-3-chrome-devtools-verification.md` for the full detail.
