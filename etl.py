"""ETL entry point (HLD §1, LLD §3). Owns the full extract -> transform -> validate ->
store pipeline for the Oncology Trial Match project. Run with `python etl.py` (no CLI
args) once, before `streamlit run app.py`. All network I/O happens inside
`src.extract`; this module is orchestration glue only.
"""

from pathlib import Path

from src import extract, matching, storage, synonyms, transform, validate

RAW_DIR = Path("data/raw")
PROCESSED_DIR = Path("data/processed")
QUALITY_REPORT_PATH = PROCESSED_DIR / "quality_report.json"


def main() -> None:
    # 1. Extract — pulls/resumes all shortlisted conditions, checkpointing to data/raw/.
    raw_by_condition = extract.extract_all(raw_dir=RAW_DIR)

    # 2. Raw row count across all conditions (plain count; transform.py doesn't expose this).
    raw_row_count = sum(len(studies) for studies in raw_by_condition.values())

    # 3. Duplicate studies merged = raw records sharing an nct_id with an earlier-seen
    # record across the combined raw pull.
    seen_nct_ids: set[str] = set()
    distinct_nct_id_count = 0
    for studies in raw_by_condition.values():
        for raw_study in studies:
            nct_id = raw_study.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
            if nct_id not in seen_nct_ids:
                seen_nct_ids.add(nct_id)
                distinct_nct_id_count += 1
    duplicate_studies_merged = raw_row_count - distinct_nct_id_count

    # 4. Transform — flatten raw JSON into the three tables + composite text.
    studies_df, interventions_df, locations_df = transform.transform_all(
        raw_by_condition, synonyms.SYNONYM_TABLE
    )

    # 5. Validate — run all data quality checks; use the returned, cleaned DataFrames.
    report, studies_df, interventions_df, locations_df = validate.run_all_checks(
        studies_df, interventions_df, locations_df, raw_row_count, duplicate_studies_merged
    )

    # 6. Fit TF-IDF over the cleaned studies_df's composite_text, in that exact row order.
    vectorizer, matrix = matching.fit_vectorizer(studies_df["composite_text"].tolist())

    # 7. Write the three flat tables — same studies_df object/order used to fit the matrix.
    storage.write_tables(studies_df, interventions_df, locations_df, PROCESSED_DIR)

    # 8. Persist the TF-IDF artifacts.
    storage.write_tfidf_artifacts(vectorizer, matrix, PROCESSED_DIR)

    # 9. Write the quality report.
    validate.write_quality_report(report, QUALITY_REPORT_PATH)

    # 10. Print a concise run summary.
    print("=== ETL run summary ===")
    print(f"Raw rows pulled (all conditions): {raw_row_count}")
    for condition, studies in raw_by_condition.items():
        print(f"  {condition}: {len(studies)} raw rows")
    print(f"Duplicate studies merged: {duplicate_studies_merged}")
    print(f"Studies written: {len(studies_df)}")
    print(f"Interventions written: {len(interventions_df)}")
    print(f"Locations written: {len(locations_df)}")
    print(f"Overall quality status: {report['overall_status']}")
    print(f"Processed data written to: {PROCESSED_DIR.resolve()}")


if __name__ == "__main__":
    main()
