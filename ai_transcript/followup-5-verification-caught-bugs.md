# Followup 5: two real bugs, both caught by testing the literal thing

Two unrelated bugs, both found the same way — running the exact documented
command or the exact user interaction, rather than trusting that an
earlier, adjacent check already covered it. Same lesson as the pandas 3.x
bug from Checkpoint 7, twice more.

## Bug 1: bare `pytest tests/` fails on a fresh clone

**What was reported:** README's "Testing" section says to run
`pytest tests/`. On a genuinely fresh clone, that command fails with
`ModuleNotFoundError: No module named 'src'` on both test files —
consistently, not a fluke. `python -m pytest tests/` passes cleanly, all
23 tests. The two commands resolve imports differently: nothing in the
repo anchored pytest's rootdir, so its default import-mode resolution
couldn't find `src` relative to `tests/`.

**Reproduced before fixing:** cloned the local repo into a clean temp
directory, fresh `venv`, `pip install -r requirements.txt`, ran
`pytest tests/` bare — confirmed the exact failure (`ImportError` on both
`tests/test_matching.py` and `tests/test_validate.py`, collection
interrupted).

**Fix:** an empty `conftest.py` at the repository root (not inside
`tests/`) — the standard pytest fix for this failure mode. It anchors
pytest's rootdir so `src` resolves correctly regardless of invocation
method (bare `pytest`, `python -m pytest`, or an IDE's built-in test
runner, which typically invokes bare `pytest`).

**Verified after fixing, twice:** once in the same clone (confirms the fix
works), then again from a completely independent fresh `git clone` into a
new temp directory with a new `venv` — `pytest tests/` bare: 23 passed,
exactly as documented in README.

## Bug 2: Pipeline Health's explanation panel floats over other tabs

**What was found:** while verifying the custom theme (see
`followup-6-visual-polish.md`), the Pipeline Health tab's "What does this
mean?" `st.popover` was opened, then the user switched to the About tab
without closing it first — the popover's content kept rendering, floating
on top of the About tab's content instead of disappearing.

**Root cause:** Streamlit's `st.tabs` doesn't unmount inactive tab
content (it stays in the DOM, hidden, so widget state persists across tab
switches by design). `st.popover` renders its open content as an overlay
that isn't clipped by its parent tab panel's hidden state the way a normal
in-flow element would be, so an open popover keeps rendering at its fixed
position regardless of which tab is nominally active.

**Fix:** replaced `st.popover("What does this mean?")` with
`st.expander("What does this mean?")` for the same content. Expanders
render inline in normal document flow, so when their containing tab panel
is hidden, the expanded content is hidden with it — the failure mode
doesn't apply. This also removed a narrow two-column layout that existed
only to make room for the popover trigger button, letting the expander run
full-width like the "Checks" section's own expanders directly below it.

**Verified via the exact repro steps, post-fix:** opened "What does this
mean?" in Pipeline Health, switched to the About tab without closing it —
no floating content, clean tab switch. Re-ran `pytest tests/` (23/23) and
the one-way-arrow check.
