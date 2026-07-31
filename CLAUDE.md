# Project Context

## Assignment (condensed)
24-hour take-home for an AI Data Engineer role. Deliverable: an end-to-end
AI-assisted data product using Python + Streamlit + a free public API.

Hard requirements:
- ETL layer that extracts, transforms, validates, and stores data locally
  (`etl.py`).
- Business-facing Streamlit app (`app.py`) with interactive filtering.
- Meaningful data quality checks and error handling — not just null checks.
- Free/public API only: no paid access, no private credentials, no
  reviewer-provided secrets. Keyless preferred. Must run without any manual
  data prep.
- Git repo is the only submission format. Full AI conversation transcript
  must be included under `/ai_transcript/`.
- Required structure: README.md, requirements.txt, app.py, etl.py,
  /data/raw/, /data/processed/, /ai_transcript/, /src/ (optional),
  /tests/ (optional).
- Must run via exactly:
  ```
  git clone <repo> && cd <repo>
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python etl.py
  streamlit run app.py
  ```
- Grading weights: End-to-End Ownership 25%, Architecture & ETL Design 25%,
  Analytics & Product Thinking 20%, Data Quality & Reliability 15%,
  AI Interaction 15%.
- Brief explicitly rewards a smaller, reliable, well-designed solution over
  an overbuilt one.

## Product idea (seed only — design the rest from here)
**Oncology Trial Match** — a clinical trial matching and recommendation tool.

- Persona: a clinical trial navigator or oncologist with a specific patient
  (cancer type, stage, biomarkers) who needs a ranked shortlist of actively
  recruiting trials — not a raw keyword search.
- Data source: ClinicalTrials.gov API v2, `https://clinicaltrials.gov/api/v2/studies`
  — free, public, no API key required.
- Core capability: given a structured patient profile, rank recruiting
  trials by relevance (not just keyword match), with a plain-language
  explanation of why each trial matched.
- Secondary capability: an aggregate "trial landscape" view for a chosen
  cancer type — phase mix, sponsor type, volume over time.
- Data quality should be a visible product feature, not a hidden log.
- Scope constraint: prefer a transparent, explainable matching approach
  (e.g. TF-IDF/similarity-based) over a trained ML model or LLM calls —
  no external ML dependency, fully explainable, runs offline.

## Working agreement
Do not write implementation code until the planning docs below are drafted
and I've explicitly approved each one. Ask me before moving to the next
phase.
