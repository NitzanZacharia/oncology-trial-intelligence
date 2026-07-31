"""Static biomarker/notation synonym table used by both ETL transform (composite_text
expansion, LLD §1.4) and app-time query building (LLD §3.6 build_query_text).

This is deliberately a small, hand-curated lookup table — not an ontology, not NLP —
per project-plan.md §1 ("one piece of smarts") and §3 risk #2/#3.
"""

SYNONYM_TABLE: dict[str, list[str]] = {
    # HER2 (breast, and increasingly other solid tumors)
    "her2+": ["her2-positive", "her2 positive"],
    "her2-positive": ["her2+", "her2 positive"],
    "her2 positive": ["her2+", "her2-positive"],
    "her2-negative": ["her2 negative"],
    "her2 negative": ["her2-negative"],
    # Hormone receptor status (breast)
    "er+": ["er-positive", "estrogen receptor positive"],
    "er-positive": ["er+", "estrogen receptor positive"],
    "er-negative": ["er-", "estrogen receptor negative"],
    "pr+": ["pr-positive", "progesterone receptor positive"],
    "pr-positive": ["pr+", "progesterone receptor positive"],
    "triple negative": ["triple-negative", "tnbc"],
    "triple-negative": ["triple negative", "tnbc"],
    "tnbc": ["triple negative breast cancer", "triple-negative"],
    # EGFR (lung)
    "egfr mutation": ["egfr mutant", "egfr-mutated"],
    "egfr mutant": ["egfr mutation", "egfr-mutated"],
    "egfr-mutated": ["egfr mutation", "egfr mutant"],
    # ALK (lung)
    "alk+": ["alk-positive", "alk rearrangement"],
    "alk-positive": ["alk+", "alk rearrangement"],
    "alk rearrangement": ["alk+", "alk-positive"],
    # BRAF (melanoma, colorectal)
    "braf v600e": ["braf mutation", "braf-mutated"],
    "braf mutation": ["braf v600e", "braf-mutated"],
    # KRAS (lung, colorectal, pancreatic)
    "kras mutation": ["kras mutant", "kras g12c"],
    "kras g12c": ["kras mutation", "kras mutant"],
    # PD-L1 (checkpoint inhibitor eligibility, many solid tumors)
    "pd-l1": ["pd-l1 positive", "programmed death-ligand 1"],
    "pd-l1 positive": ["pd-l1+", "pd-l1"],
    "pd-l1+": ["pd-l1 positive", "pd-l1"],
    # BRCA1/2 (breast, prostate, pancreatic)
    "brca1": ["brca1 mutation", "brca1-mutated"],
    "brca2": ["brca2 mutation", "brca2-mutated"],
    "brca1/2": ["brca1", "brca2", "brca mutation"],
    "brca mutation": ["brca1/2", "brca1", "brca2"],
    # Prostate-specific
    "psa": ["prostate-specific antigen"],
    "gleason score": ["gleason grade"],
    # Microsatellite instability (colorectal and broader)
    "msi-h": ["microsatellite instability-high", "microsatellite instability high"],
    "microsatellite instability-high": ["msi-h"],
    # Stage/extent-of-disease phrasing
    "metastatic": ["stage iv", "advanced"],
    "stage iv": ["metastatic", "advanced"],
}


def load_synonym_table() -> dict[str, list[str]]:
    """Return the static synonym/alias table (module-level constant, no file I/O)."""
    return SYNONYM_TABLE


def expand_text(text: str, synonym_table: dict[str, list[str]] | None = None) -> str:
    """Append every alias for each matched key found in text (additive, not replacing) — LLD §1.4.

    Case-insensitive substring match on each table key against `text`. For every key found,
    each of its aliases is appended once (space-joined) to the end of the string — never
    replacing the original wording, never appending a duplicate, and never appending an alias
    that is already literally present in the text.
    """
    if synonym_table is None:
        synonym_table = SYNONYM_TABLE

    if not text:
        return text

    text_lower = text.lower()
    to_append: list[str] = []
    seen_lower: set[str] = set()

    for key, aliases in synonym_table.items():
        if key.lower() not in text_lower:
            continue
        for alias in aliases:
            alias_lower = alias.lower()
            if alias_lower in seen_lower:
                continue
            if alias_lower in text_lower:
                continue
            seen_lower.add(alias_lower)
            to_append.append(alias)

    if not to_append:
        return text

    return text + " " + " ".join(to_append)
