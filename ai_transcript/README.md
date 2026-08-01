# AI Transcript

This directory captures how Claude Code was used to build this project, per
`CLAUDE.md`'s submission requirements.

## Why this isn't a raw `/export` dump

`docs/AUTONOMOUS_RUN_PLAN.md` (ground rule 5) originally called for
exporting the live session transcript via a `/export` slash command after
each checkpoint. No tool available to the agent in this environment can
invoke that command (it's a CLI-level feature, not something exposed as a
callable tool during the run). This was identified as a blocker for that
specific mechanism — not for the underlying requirement — and resolved
conservatively per the plan's ground rule 4: substitute a manually-authored,
per-checkpoint summary of what was asked, what was built, what was
self-verified, and what judgment calls were made, sourced from the actual
session and from `docs/AUTONOMOUS_RUN_LOG.md`. This deviation is logged in
`docs/AUTONOMOUS_RUN_LOG.md`.

## Files

- `checkpoints-1-3-planning-and-implementation.md` — the human-reviewed
  phase: planning docs (project-plan.md, HLD.md, LLD.md) and the first
  three implementation checkpoints (synonyms.py/extract.py,
  transform.py/validate.py, storage.py/matching.py), each approved by the
  user before proceeding, including the two bugs the user caught/directed
  fixes for (the `fetch_condition_page` 429 backoff requirement, and the
  `run_all_checks` return-type bug).
- `checkpoint-4-etl.md` — `etl.py` implementation and its live run against
  the ClinicalTrials.gov API (Checkpoint 4 of the unattended autonomous
  run, `docs/AUTONOMOUS_RUN_PLAN.md`).
- `checkpoint-5-app.md` — `app.py` implementation (three-screen Streamlit
  UI) and its architecture-conformance/smoke-test self-verification
  (Checkpoint 5).
- `checkpoint-6-review.md` — the code review pass over `/src/`, `etl.py`,
  `app.py`, including a real bug found and fixed (a data-quality check
  that could structurally never fail) (Checkpoint 6).
- `checkpoint-7-tests-readme-smoke-test.md` — unit tests, `README.md`, and
  the final clean-clone smoke test, which caught a real pandas-3.x
  compatibility bug the main dev environment had been silently masking
  (Checkpoint 7, the final checkpoint of the autonomous run).
