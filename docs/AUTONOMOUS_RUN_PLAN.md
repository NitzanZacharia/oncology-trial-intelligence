# Autonomous Run Plan — Checkpoints 4 through Final Smoke Test

Status: governs unattended execution. No human is available to approve steps
during this run. Read this in full before starting, then execute checkpoints
in order without stopping for approval — self-verify each one instead, per
the rules below, and log everything to `docs/AUTONOMOUS_RUN_LOG.md`.

## Ground rules for unattended operation

1. **Source of truth is locked.** `docs/HLD.md`, `docs/LLD.md`, and
   `docs/project-plan.md` are not to be redesigned. If something in them
   turns out to be genuinely wrong (like the `run_all_checks` return-type
   bug found and fixed earlier), fix it the same way: make the smallest
   correct change, update the doc to match, log exactly what and why.
2. **Self-verify every checkpoint before moving to the next one**, the same
   way you independently caught the `run_all_checks` bug without being
   asked to: trace the actual output against the relevant LLD/HLD section,
   don't just assume the code you wrote matches the spec.
3. **Log after every checkpoint** to `docs/AUTONOMOUS_RUN_LOG.md` (create if
   missing), appending — never overwriting. Each entry: timestamp,
   checkpoint name, what was built, self-verification result (what you
   checked and what you found), any deviation from the plan and why, any
   judgment call you made and the reasoning, and any concern worth a human
   double-checking later.
4. **Only stop early for a genuine blocker** — something that cannot be
   resolved by picking the most conservative, spec-consistent interpretation
   (e.g., the live API fundamentally doesn't return what the LLD assumes).
   If that happens, write the blocker as the top entry in the log, in plain
   language, and halt. Routine ambiguity should be resolved conservatively
   and logged, not treated as a reason to stop.
5. **Capture the AI transcript incrementally, not at the end.** After each
   checkpoint below, export the session so far (`/export`) into
   `/ai_transcript/`, named by checkpoint (e.g.
   `ai_transcript/checkpoint-4-etl.md`). This is a submission requirement,
   not optional polish.

## Checkpoint 4 — `etl.py`

- Implement per `LLD.md` §3 module layout: orchestrate
  `extract.extract_all` → `transform.transform_all` → `validate.run_all_checks`
  → `storage.write_tables` / `storage.write_tfidf_artifacts` →
  `matching.fit_vectorizer`, in that order, per `HLD.md` §1's one-way
  architecture (`etl.py` is the only network-I/O caller).
- Run it for real against the live ClinicalTrials.gov API.
- Self-verify: read back the actual `quality_report.json` produced.
  Confirm `overall_status`, row counts, and per-check results are internally
  consistent (e.g. `studies_written` roughly matches expectations for 8
  recruiting cancer types, no check silently shows 0/0 total_count, no
  required-field check shows anything but pass per §2.5's fail-at-any-rate
  rule). If anything looks off, investigate before proceeding — don't wave
  it through because the script exited 0.
- Log the actual row counts and `overall_status` achieved.

## Checkpoint 5 — `app.py`

- Implement per `LLD.md` §4 caching strategy and the three-screen concept
  (Patient Match, Trial Landscape, Pipeline Health) from `HLD.md`.
- Self-verify architecture conformance mechanically, not by reading:
  ```
  grep -n "extract\|fit_vectorizer" app.py
  ```
  This must return nothing. If it returns something, fix it before
  proceeding — this is the one-way-arrow constraint from HLD §1.
- Smoke-test it actually runs:
  ```
  streamlit run app.py --server.headless true &
  sleep 5
  curl -s -o /dev/null -w "%{http_code}" http://localhost:8501
  kill %1
  ```
  Confirm the curl returns `200`. Log the result.

## Checkpoint 6 — Review pass

- Use `code-reviewer` on the full `/src/`, `etl.py`, and `app.py`.
- Log a summary of what it found and what was fixed as a result.

## Checkpoint 7 — Tests, README, final assembly

- Implement the unit tests called for in `project-plan.md` milestones
  16–19: ranking determinism (`matching.rank_candidates` given the same
  query/matrix returns the same ranked order every time) and validation
  rules (each `check_*` function in `validate.py` against known good/bad
  inputs).
- Write `README.md`: setup, architecture summary, data model, known
  limitations (including the unstructured-eligibility-text limitation from
  `project-plan.md` §0), and how AI was used — reference
  `docs/AUTONOMOUS_RUN_LOG.md` and `/ai_transcript/` explicitly here.
- Final clean-clone smoke test — this is the one step that most needs to
  actually happen, unattended or not:
  ```
  cd /tmp && rm -rf smoke-test && git clone <repo-path> smoke-test && cd smoke-test
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python etl.py
  streamlit run app.py --server.headless true &
  sleep 5
  curl -s -o /dev/null -w "%{http_code}" http://localhost:8501
  kill %1
  ```
  Log the outcome. This is the single most important self-verification in
  the whole plan — it's the exact sequence a reviewer will run.

## When done

Write a final summary entry at the top of `docs/AUTONOMOUS_RUN_LOG.md`:
what was completed, the final clean-clone smoke test result, and a short
list of anything flagged during the run that's worth a human look before
submission.
