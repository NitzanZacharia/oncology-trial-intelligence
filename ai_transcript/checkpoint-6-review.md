# Checkpoint 6: Code review pass

Part of the unattended autonomous run. Full detail is in
`docs/AUTONOMOUS_RUN_LOG.md`'s Checkpoint 6 entry.

## What was asked

Run a code-reviewer pass over `/src/`, `etl.py`, and `app.py`. Log a
summary of what was found and fixed.

## What was done

The `code-reviewer` agent installed via `agent-installer` earlier in this
run wasn't available as a session subagent type (installed to disk, but
this session's available agent list was fixed at startup) — ran the review
via `general-purpose` given an explicit code-reviewer persona and brief
instead, the same substitution used for `python-pro` earlier in the
project. The review read `docs/HLD.md`/`docs/LLD.md` first as the
authoritative spec, then reviewed every implementation file against it.

## Findings and outcomes

Two real bugs were found and fixed by the reviewer directly, both
independently re-verified before being accepted:

1. `app.py` transitively imported `src.extract` through
   `storage.py → transform.py → extract.py`, violating the documented
   one-way-arrow constraint even though no network call fired at import
   time. Fixed by relocating the two shared dtype-casting helpers from
   `transform.py` into `storage.py`, reversing the dependency direction.
   Verified via `sys.modules` introspection after `import app`.
2. `write_raw_checkpoint` wasn't atomic — a crash mid-write could leave a
   truncated file that the resume mechanism would then mistake for a
   complete checkpoint, permanently breaking that condition with no
   recovery path. Fixed with a write-tmp-then-`os.replace()` pattern.

A third finding was flagged by the reviewer as a design question rather
than fixed outright, since it touched documented function contracts:
`check_nct_id_format`/`check_required_fields` in `validate.py` always
reported a trivial pass, because `transform.transform_all` had already
dropped the offending rows *before* those checks ever ran — so
`quality_report.json` could never actually surface an NCT-ID-format or
required-field violation no matter how many rows were silently dropped
upstream. This is a genuine deviation from `LLD.md` §1.5's "dropped and
reported" rule, not a style question, so it was investigated and fixed
directly (not deferred) per the autonomous run's ground rule 1: made both
checks own their own drop and return `(clean_df, CheckResult)`, matching
the pattern the other three checks already use; removed the now-redundant
drop from `transform.py`; updated `docs/LLD.md` to match. Re-ran `etl.py`
end-to-end afterward — `studies_written` reconciled identically (13,335),
confirming the fix changes what gets *reported*, not what gets *written*
(the real API data happens to have zero such violations, exactly as
`project-plan.md`'s API grounding predicted — the checks are now
structurally capable of catching a real one, which they weren't before).

Two minor items were flagged as informational-only and left as-is: an
extremely unlikely, currently-unobserved null-guard gap in `etl.py`'s
summary-metric computation (not on any written data path), and two
intentional UX design choices in `app.py` that aren't defects.

## Judgment call

Re-running the full `etl.py` pipeline after a `validate.py`/`transform.py`
change (rather than trusting the diff alone) was treated as mandatory
self-verification, not optional — per the run plan's ground rule 2, the
same standard applied to the original Checkpoint 4 run.
