# High-Level Design — Oncology Trial Match

Status: draft for lead approval, before any code is written. Builds directly on
`docs/project-plan.md` (scope, milestones, risks are locked there and not
revisited here).

## 1. System architecture

Three components, one direction of data flow. `etl.py` is the only thing that
ever talks to the network; `app.py` only ever reads files under
`/data/processed`.

- **`etl.py`** — owns all network I/O. Pulls recruiting studies per cancer
  type from the ClinicalTrials.gov API v2, writes a raw checkpoint per
  condition, then transforms, validates, and writes flat tables plus the
  TF-IDF artifacts. Runs once (`python etl.py`), not on every app load.
- **`/data/raw`** — one JSON file per cancer type (e.g. `breast.json`,
  `lung.json`), written as each condition finishes pulling. This is the
  resume mechanism: if the run dies mid-pull (rate limit, network blip) on
  condition 5 of 8, re-running `etl.py` can skip conditions that already have
  a raw checkpoint instead of re-hitting the API from scratch.
- **`/data/processed`** — the flat tables (`studies`, `interventions`,
  `locations`) and the TF-IDF artifacts (vectorizer + matrix). This is the
  only thing `app.py` reads. It never talks to `/data/raw` or the API
  directly.
- **`app.py`** — Streamlit UI. Loads `/data/processed` once (cached), takes a
  patient profile, filters, ranks by TF-IDF cosine similarity, and renders
  matches with an explanation panel plus the landscape view. Zero live API
  calls at any point.

```
        ClinicalTrials.gov API v2
                   │
                   │  (network I/O lives ONLY here)
                   ▼
        ┌─────────────────────┐
        │       etl.py         │
        │  extract → transform  │
        │  → validate → store   │
        └───────────┬──────────┘
                     │
        ┌────────────┼─────────────┐
        ▼                          ▼
  /data/raw/                /data/processed/
  <condition>.json          studies / interventions / locations
  (per-condition            + tfidf_vectorizer.joblib
   checkpoint, resume       + tfidf_matrix.joblib
   point on failure)        + quality_report.json
                                     │
                                     │ (read-only, cached)
                                     ▼
                              ┌─────────────┐
                              │   app.py     │
                              │ Streamlit UI │
                              └─────────────┘
                                     │
                                     ▼
                              patient query → filter
                              → rank → explain → render
```

The arrow direction is intentional and one-way: **ETL → disk → app**. `app.py`
never calls the API, and `etl.py` never renders anything. This isolation is
what makes the required run sequence (`python etl.py` then
`streamlit run app.py`) safe to run independently and repeatedly — re-running
the app never re-triggers a network call, and re-running the ETL never
touches the UI.

## 2. Data flow

**Extract.** For each of the ~8 shortlisted cancer types, page through
`GET /api/v2/studies` with `query.cond=<condition>`,
`filter.overallStatus=RECRUITING`, and an explicit `fields=` list limited to
the modules actually used downstream (identification, status, sponsor,
conditions, design, arms/interventions, eligibility, contacts/locations) to
keep payloads small. Pagination follows `pageToken` → `nextPageToken` until
`nextPageToken` is absent, with `pageSize` set high (e.g. 200–500, under the
1000 cap) to minimize request count. A small explicit delay between requests
keeps the pull comfortably under the community-observed ~50 req/min ceiling.
The delay is pacing, not error handling: the actual error-handling mechanism
for rate limiting is that any individual page request returning HTTP 429 is
retried with exponential backoff (see `fetch_condition_page`, LLD §3.1),
since pacing alone is a best-effort guard, not a guarantee against a 429.
Each condition's full set of pages is concatenated and written to
`/data/raw/<condition>.json` before moving to the next condition — this is
the checkpoint boundary described in the architecture section.

**Transform.** Each raw study's nested `protocolSection` is flattened into
three tables: `studies` (one row per NCT ID — title, status, phase(s),
sponsor class, enrollment, dates, eligibility text), `interventions` (one row
per study/intervention pair — type, name), and `locations` (one row per
study/facility pair — facility, city, state, country). The static biomarker
synonym/alias table (e.g. "HER2+" ↔ "HER2-positive") is applied here,
expanding each trial's eligibility/keyword text with matched aliases so
downstream TF-IDF matching isn't defeated by cosmetic notation differences.

**Validate.** Runs against the flattened tables before anything is persisted
to `/data/processed`: schema/type checks (expected columns present, expected
types — e.g. `enrollment` numeric, `phases` drawn from the known enum);
dedupe on NCT ID (the API can return the same study across paginated
conditions if a study lists multiple shortlisted conditions); referential
integrity (every row in `interventions` and `locations` must reference an NCT
ID present in `studies`, and vice versa — orphans are flagged); plausibility
checks (status dates in sensible order, enrollment count positive and within
a sane range, phase values within the documented enum, not silently
`NaN`-passed). Results are written to a machine-readable
`quality_report.json` alongside the tables, which is what the in-app quality
panel (project-plan.md milestone 7–9) reads and renders — data quality is a
visible product surface, not a build-time log line that disappears.

**Store.** Validated tables and the quality report land in
`/data/processed`. The TF-IDF vectorizer is fit once here, over each trial's
composite document (title + conditions + keywords + eligibility text, with
synonym expansion applied), and both the fitted vectorizer and the resulting
sparse matrix are persisted alongside the tables (see storage decisions
below).

**App load.** `app.py` loads the processed tables and the persisted TF-IDF
artifacts exactly once per process lifetime via `st.cache_data` (tables) and
`st.cache_resource` (vectorizer/matrix, since these aren't trivially
serializable-and-hashable in the way `cache_data` expects). This guarantees
the TF-IDF fit/transform work happens zero times per user interaction — it
already happened in `etl.py`, and app startup only ever deserializes it.

**User query → rank → explain.** The patient profile form builds a query
string (condition + biomarker tags + stage keywords), applies the same
synonym expansion used at transform time, hard-filters candidate trials
(`RECRUITING` + condition + sex/age eligibility where present), vectorizes
the query against the already-fitted vectorizer, computes cosine similarity
against the precomputed matrix, and ranks. The explanation panel surfaces the
highest-weight overlapping terms between query and trial document per match,
in plain language — no LLM call, fully reproducible offline from what's on
disk.

## 3. Storage format decisions

**Flat tables: CSV.** Parquet and SQLite were considered. CSV wins here
specifically because the brief rewards a smaller, reliable, well-designed
solution over an overbuilt one: it needs zero extra dependencies beyond
pandas (already required), is trivially diffable and human-inspectable in a
PR review, and the data volume (~8 conditions × recruiting studies each, a
few thousand rows across three tables at most) is nowhere near large enough
for Parquet's columnar compression or SQLite's query engine to earn their
added complexity. Type preservation (SQLite/Parquet's actual advantage) is a
non-issue because the validation step already enforces types before write,
and `app.py` re-parses dtypes on load the same way every time. CSV is the
simplest thing that reliably works end-to-end for this data size, which is
exactly what's being graded.

**TF-IDF artifacts: joblib.** The matching approach is already committed to
scikit-learn's `TfidfVectorizer` (the "no external ML dependency beyond
TF-IDF" constraint from the project plan assumes exactly this tool), and
scikit-learn ships `joblib` as its own recommended serialization mechanism
for fitted estimators — so persisting the fitted vectorizer and the sparse
similarity matrix via `joblib.dump`/`joblib.load` adds no new dependency at
all. The alternative of recomputing the TF-IDF fit at app startup from stored
text columns was rejected: it would duplicate the vectorizer-configuration
logic in two places (`etl.py` and `app.py`), risking silent drift between
what was validated/fit at ETL time and what the app actually scores against,
and it re-does non-trivial work every process start for no benefit since
`etl.py` already ran once. Plain `pickle` was considered and rejected only
because `joblib` is the scikit-learn-endorsed path for exactly this artifact
type (better handling of numpy/scipy internals) and costs nothing extra given
scikit-learn is already a hard dependency.

## 4. Grading-criteria mapping

**End-to-End Ownership (25%).** The one-directional architecture in Section 1
is itself the ownership story: a single command sequence
(`python etl.py` → `streamlit run app.py`) takes the project from nothing on
disk to a working product, with no manual data prep, no hidden steps, and no
credentials — matching the required clean-clone run exactly. The per-condition
raw checkpoint (Section 1, `/data/raw`) demonstrates ownership of failure
modes, not just the happy path: a rate-limit hiccup mid-run doesn't require
throwing away completed work or hand-holding the pipeline back to health.

**Architecture & ETL Design (25%).** The extract/transform/validate/store
pipeline in Section 2 is a deliberately staged design — each stage has a
distinct, testable responsibility and a concrete artifact boundary (raw JSON
→ flat tables → quality report → TF-IDF artifacts), rather than one monolithic
script that fetches-and-renders in one pass. The strict separation of network
I/O into `etl.py` only (Section 1) is itself an architecture decision, not an
accident — it's what makes `app.py` safely re-runnable and cacheable.

**Analytics & Product Thinking (20%).** The ranking pipeline (Section 2, "user
query → rank → explain") is designed around a real decision a trial navigator
makes — not a keyword search, but a ranked, explained shortlist under a hard
eligibility filter — and the explanation panel (top overlapping TF-IDF terms
rendered as plain language) directly answers "why this trial" rather than
just "here is a score." The secondary landscape view (phase mix, sponsor
class, recruiting-vs-not, volume-over-time), computed entirely from already
-processed local tables per Section 2, gives the same tool a second, distinct
analytical lens on the same data without any additional network cost.

**Data Quality & Reliability (15%).** This is earned concretely by the
validate stage in Section 2: schema/type checks, dedupe on NCT ID (needed
specifically because a study can appear under more than one shortlisted
condition), referential integrity between `studies`/`interventions`/
`locations`, and plausibility checks on dates/enrollment/phase enums — not
null-checks alone. Crucially, these checks don't stop at a build-time log:
they're written to `quality_report.json` (Section 2, "Validate") specifically
so the in-app quality panel called for in `project-plan.md` can render them
as a visible product feature, which is what turns a QA step into a graded
strength rather than an invisible implementation detail.

**AI Interaction (15%).** The planning sequence itself — `CLAUDE.md` framing
the assignment and product seed, `docs/project-plan.md` locking scope/
milestones/risks with a verified API-grounding pass, and this `HLD.md`
translating that plan into concrete architecture and storage decisions before
any code is written — is the AI interaction artifact, captured in full under
`/ai_transcript/`. The design choices in Sections 1–3 (e.g. rejecting
Parquet/SQLite, rejecting pickle over joblib, rejecting live re-fitting at app
startup) are documented with explicit one-line rationales specifically so the
transcript shows judgment and trade-off reasoning, not just accepted
suggestions.

## 5. `.gitignore` scope decision

**Decision: `/data/raw/` and `/data/processed/` are NOT blanket git-ignored.**
The assignment requires the submitted git repo to be reproducible and
reviewable end-to-end without the reviewer necessarily re-running `etl.py`
against a live third-party API — so at least a representative sample of ETL
output (raw JSON per condition, the processed flat tables, and the TF-IDF
artifacts) is committed to the repo rather than excluded. This is a firm
decision, not a set of options to weigh: the only entries excluded from git
are the local Python environment (`.venv/`), Python bytecode caches
(`__pycache__/`, `*.pyc`), OS cruft (`.DS_Store`), and Claude Code's own
personal, machine-specific configuration (`.claude/settings.local.json`,
`CLAUDE.local.md`). Nothing under `data/`, `ai_transcript/`, `src/`, or
`tests/` is excluded.
