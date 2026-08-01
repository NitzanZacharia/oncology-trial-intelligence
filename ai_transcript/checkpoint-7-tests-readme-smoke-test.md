# Checkpoint 7: Tests, README, final clean-clone smoke test

Part of the unattended autonomous run — the final checkpoint. Full detail
is in `docs/AUTONOMOUS_RUN_LOG.md`'s Checkpoint 7 entry.

## What was asked

Implement unit tests for ranking determinism and every `validate.py`
check against known good/bad inputs. Write `README.md`. Run the final
clean-clone smoke test — described in the plan as "the single most
important self-verification in the whole plan," since it's the exact
sequence a reviewer runs.

## What was built

23 tests across `tests/test_matching.py` and `tests/test_validate.py`,
and a full `README.md` covering setup, architecture, data model, known
limitations, why the data is committed, and AI usage.

## What the smoke test found

This is the interesting part. Running the documented setup sequence
against a genuinely clean `git clone` + fresh `venv` + unpinned
`pip install -r requirements.txt` — rather than the already-many-times-
verified main development environment — surfaced a real bug that every
prior checkpoint's self-verification had missed: a fresh install pulled
pandas 3.0.5, and `etl.py` crashed with `AttributeError: 'float' object
has no attribute 'replace'` inside `build_composite_text`.

The cause: code like `study_row.get("keywords") or ""` assumes a missing
value is `None`. It isn't always — pandas can represent a missing cell as
a float `NaN`, and `NaN` is truthy in Python, so `NaN or ""` evaluates to
`NaN`, not the empty-string fallback. This had apparently never triggered
under pandas 2.3.3 (the version already installed system-wide, used for
every earlier checkpoint's runs) but did under 3.0.5's different missing-
value handling for this data. Fixed with a `pd.isna()`-aware helper used
for all four fields that build the TF-IDF composite text.

This is exactly why the plan specifies a *clean-clone* smoke test rather
than treating a already-passing dev-environment run as sufficient — a
subtly different but equally valid environment (same `requirements.txt`,
different resolved versions) exposed a real defect that had been silently
compatible with the one specific environment used throughout the rest of
the run.

## Verification after the fix

- Re-ran the full pipeline in the main dev environment (pandas 2.3.3):
  byte-identical output to before the fix — confirms the fix changes
  nothing when values are already `None`, only when they're `NaN`.
- Pinned `requirements.txt` to `pandas>=2.3,<4` — belt-and-suspenders on
  top of the code fix, since the fix alone makes the logic version-
  agnostic but pinning avoids an entirely untested future major version
  breaking a reproducibility-graded pipeline.
- Ran the full clean-clone sequence again, fresh, from the fixed commit:
  clone → venv → `pip install` (pandas 3.0.5 again) → `etl.py` (exit 0,
  identical row counts) → `pytest tests/` (23/23 pass) → Streamlit smoke
  test (HTTP 200, clean shutdown). All green.

## Judgment call

Treated the pandas-version bug as worth fixing immediately rather than
just flagging for human review, since it's a literal cold-start failure
on the exact required command sequence (`git clone && ... && python
etl.py && streamlit run app.py`) — `project-plan.md` §3's risk #7 names
this specific failure mode as the reason the final smoke test exists at
all.

## End of the autonomous run

This closes out Checkpoints 4-7 as authorized. See the prepended summary
at the top of `docs/AUTONOMOUS_RUN_LOG.md` for the full run's outcome and
what remains for human review.
