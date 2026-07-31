# Project Plan — Oncology Trial Match

Status: draft for lead approval, before any code is written.

## 0. API grounding (verified against live `GET /api/v2/studies` calls)

- Endpoint: `https://clinicaltrials.gov/api/v2/studies` — no key, no auth, keyless.
- Filters: `query.cond` (condition/disease text), `query.term` (general keyword), `query.intr`
  (intervention), `query.spons` (sponsor); `filter.overallStatus` and `filter.phase` take
  comma-separated enum values (e.g. `RECRUITING,ACTIVE_NOT_RECRUITING`, `PHASE2,PHASE3`).
- Pagination is cursor-based: request `pageToken`, response returns `nextPageToken`; `pageSize`
  max 1000, default 10. No documented official rate limit; community-observed safe rate is
  roughly 50 requests/minute per IP — comfortably generous for a bounded ETL pull.
- `fields=` lets you request a subset of fields to shrink payloads (confirmed working).
- Each study is a nested `protocolSection` with modules: `identificationModule` (nctId,
  briefTitle, officialTitle), `statusModule` (overallStatus, dates), `sponsorCollaboratorsModule`
  (leadSponsor incl. class: INDUSTRY/NIH/OTHER/etc.), `conditionsModule` (conditions[],
  keywords[]), `designModule` (studyType, phases[], enrollmentInfo), `armsInterventionsModule`
  (interventions: type, name), `eligibilityModule` (eligibilityCriteria, sex, minimumAge,
  maximumAge, healthyVolunteers), `contactsLocationsModule` (locations: facility, city, state,
  country).
- **Critical finding:** there is no structured biomarker field anywhere in the schema.
  `eligibilityCriteria` is a single free-text blob ("Inclusion Criteria:" / "Exclusion Criteria:"
  with bullet points). Any biomarker matching is necessarily free-text keyword matching against
  this blob, not a structured lookup. This shapes the scope decisions below.

## 1. Scope

### Core capability — patient-profile matching (IN)

- Patient profile form (Streamlit): condition (dropdown, from a fixed shortlist ingested by
  ETL), biomarker tags (free-text, e.g. "HER2+", "EGFR mutation"), stage (free text, optional),
  age, sex.
- ETL ingests **recruiting studies for a fixed shortlist of ~8 cancer types** (e.g. breast,
  lung, prostate, colorectal, pancreatic, melanoma, leukemia, lymphoma) — not all of oncology —
  and stores them as flat tables (`studies`, `interventions`, `locations`) under
  `/data/processed`. These 8 were picked specifically because they are among the
  highest-incidence, highest-trial-volume cancer types on ClinicalTrials.gov: each pulls enough
  actively recruiting studies for TF-IDF ranking and the landscape view to be meaningful rather
  than sparse, and each is a widely recognized diagnosis category a clinical trial navigator or
  reviewer will immediately recognize — a rare-cancer shortlist would risk both a thin trial pool
  per condition and a demo that's harder to sanity-check by inspection.
- Matching pipeline, in order:
  1. Hard filter: `overallStatus = RECRUITING`, condition must match the selected cancer type,
     and (where present) sex/age eligibility from `eligibilityModule` must not exclude the
     patient.
  2. Rank the remaining trials by cosine similarity between a TF-IDF vector of the patient's
     query text (condition + biomarker tags + stage keywords) and a TF-IDF vector of each
     trial's composite document (title + conditions + keywords + eligibility criteria text).
  3. **Explainability = traceability, concretely:** the explanation panel lists the specific
     shared terms that drove the score (the highest-weight overlapping TF-IDF terms between
     query and trial documents), rendered as plain language, e.g. "Matched terms: HER2,
     metastatic, trastuzumab." No opaque model and no LLM call at runtime — every score is
     reproducible offline from the processed data.
- A small biomarker synonym/alias table (e.g. "HER2+" ↔ "HER2-positive") is applied during
  transform to reduce obvious keyword-matching misses — this is the one piece of "smarts"
  beyond raw TF-IDF, and it stays a static lookup table, not NLP.

### Core capability — explicitly OUT

- No clinical NER / biomarker entity extraction, no genomic/biomarker knowledge base.
- No trained ML model or embeddings, no LLM calls at runtime (matches brief's preference for a
  transparent, explainable approach).
- No live API calls from `app.py` — the app only reads `/data/processed`; all network I/O is in
  `etl.py`, matching the required `python etl.py` → `streamlit run app.py` flow.
- No user accounts/saved sessions; no multi-condition patients (one primary cancer type per
  query); no geo/"trials near me" ranking (locations shown as a plain list only).
- No ingestion beyond the fixed cancer-type shortlist.

### Secondary capability — trial landscape view (IN)

- For a selected cancer type: phase mix, sponsor-class breakdown (industry/NIH/other),
  recruiting-vs-not counts, studies-started-per-year trend.
- All filters (condition, status, phase, sponsor class) operate on the already-processed table
  in memory — no live calls.

### Secondary capability — explicitly OUT

- No cross-condition comparison, no drill-down into trial results/outcomes (recruiting trials
  rarely have a populated `resultsSection` anyway, so it's skipped entirely).

## 2. Milestones (24-hour straight-through window)

| Hours | Milestone |
|---|---|
| 0–1 | Lock this plan, finalize cancer-type shortlist, scaffold repo dirs/requirements.txt/README skeleton |
| 1–3 | API exploration: live queries per shortlisted condition, save sample raw JSON to `/data/raw`, confirm field edge cases (missing eligibilityModule, missing phases on observational studies, multi-location records) |
| 3–7 | `etl.py` build: paginated extract with rate-limit-safe pacing and per-condition checkpointing, transform into flat tables, build TF-IDF index, write `/data/processed` |
| 7–9 | Data quality/validation layer: schema + type checks, dedupe on NCT ID, referential checks between tables, plausibility checks (dates, enrollment, phase enum), machine-readable quality report |
| 9–16 | `app.py` build: patient profile form, ranked matches + explanation panel, landscape view + charts/filters |
| 16–19 | Testing: unit tests for ranking determinism and validation rules, full clean-clone run of the exact required command sequence |
| 19–21 | README (setup, architecture, data quality, limitations) + assemble `/ai_transcript/` |
| 21–24 | Buffer: bug fixes, re-run clean-clone smoke test, trim scope further if behind rather than touch core matching logic |

## 3. Key risks & mitigations

1. **Pagination/rate-limit hiccups mid-pull.** Fixed condition shortlist + explicit pacing
   between paged requests + per-condition raw JSON checkpointing so a failed run resumes
   instead of re-pulling everything.
2. **Eligibility text is unstructured, so "biomarker match" is inherently lossy** (e.g.
   "HER2-positive" vs "HER2+"). Mitigate with a small synonym table during transform, and state
   this as a documented known limitation rather than attempting NLP extraction under time
   pressure.
3. **Scope creep toward "smarter" matching** (embeddings/LLM re-ranking) eating the whole
   budget. TF-IDF + cosine is locked as the final approach in this plan; anything smarter is
   explicitly out of scope, per the brief's own preference for a smaller reliable solution.
4. **Streamlit recomputing TF-IDF on every widget interaction**, causing a sluggish UI.
   Precompute the TF-IDF matrix once in ETL and load/cache it at app start
   (`st.cache_data`/`st.cache_resource`), never per-query.
5. **Data quality checks reduced to superficial null-checks** (this is 15% of the grade).
   Design checks up front as schema/type validation, dedupe, referential integrity across
   tables, and plausibility checks — and surface the results as a visible in-app panel, not
   just a log line.
6. **Running out of time for README/AI transcript**, both explicit submission requirements.
   Hard-stop feature work at hour 19 regardless of app polish; assemble the transcript
   incrementally throughout rather than reconstructing it at the end.
7. **Cold-start failure on a truly fresh clone.** Run the exact required command sequence
   (`venv` → `pip install` → `python etl.py` → `streamlit run app.py`) from a clean clone during
   the testing milestone, not just from the dev environment.
