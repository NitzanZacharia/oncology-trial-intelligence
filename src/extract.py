"""All network I/O for the pipeline, owned exclusively by `etl.py` (HLD §1, LLD §3.1).

Pulls recruiting studies per shortlisted cancer type from the ClinicalTrials.gov API v2,
paginating via pageToken/nextPageToken, and writes one raw JSON checkpoint per condition
under /data/raw — the resume mechanism described in HLD §1.
"""

import json
import os
import time
from pathlib import Path
from typing import Iterator

import requests

CANCER_TYPE_SHORTLIST: list[str] = [
    "breast", "lung", "prostate", "colorectal",
    "pancreatic", "melanoma", "leukemia", "lymphoma",
]  # fixed iteration order — also the "first-seen" order for dedupe (LLD §2.2)

FIELDS: list[str] = [
    # identification
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.identificationModule.officialTitle",
    # status
    "protocolSection.statusModule.overallStatus",
    "protocolSection.statusModule.startDateStruct.date",
    "protocolSection.statusModule.primaryCompletionDateStruct.date",
    "protocolSection.statusModule.studyFirstPostDateStruct.date",
    "protocolSection.statusModule.lastUpdatePostDateStruct.date",
    # sponsor
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.class",
    "protocolSection.sponsorCollaboratorsModule.leadSponsor.name",
    # conditions
    "protocolSection.conditionsModule.conditions",
    "protocolSection.conditionsModule.keywords",
    # design
    "protocolSection.designModule.studyType",
    "protocolSection.designModule.phases",
    "protocolSection.designModule.enrollmentInfo.count",
    "protocolSection.designModule.enrollmentInfo.type",
    # arms/interventions
    "protocolSection.armsInterventionsModule.interventions.type",
    "protocolSection.armsInterventionsModule.interventions.name",
    # eligibility
    "protocolSection.eligibilityModule.eligibilityCriteria",
    "protocolSection.eligibilityModule.sex",
    "protocolSection.eligibilityModule.minimumAge",
    "protocolSection.eligibilityModule.maximumAge",
    "protocolSection.eligibilityModule.healthyVolunteers",
    # contacts/locations
    "protocolSection.contactsLocationsModule.locations.facility",
    "protocolSection.contactsLocationsModule.locations.city",
    "protocolSection.contactsLocationsModule.locations.state",
    "protocolSection.contactsLocationsModule.locations.country",
]

_MAX_RETRIES = 5
_BASE_BACKOFF_S = 1.0


def raw_checkpoint_path(condition: str, raw_dir: Path) -> Path:
    """Return the /data/raw/<condition>.json path for a given shortlisted condition."""
    return Path(raw_dir) / f"{condition}.json"


def has_checkpoint(condition: str, raw_dir: Path) -> bool:
    """Return True if a raw checkpoint for this condition already exists (resume check)."""
    return raw_checkpoint_path(condition, raw_dir).exists()


def fetch_condition_page(
    condition: str,
    page_token: str | None,
    fields: list[str],
    page_size: int,
    base_url: str,
) -> dict:
    """Fetch one page of GET /api/v2/studies for a condition; returns raw JSON response.
    On HTTP 429, retries with exponential backoff (not just the fixed 1.2s inter-request
    delay) — the fixed delay paces normal requests, this retry is the actual rate-limit
    error handling for when pacing alone wasn't enough."""
    params: dict[str, str | int] = {
        "query.cond": condition,
        "filter.overallStatus": "RECRUITING",
        "pageSize": page_size,
    }
    if fields:
        params["fields"] = ",".join(fields)
    if page_token is not None:
        params["pageToken"] = page_token

    delay = _BASE_BACKOFF_S
    for attempt in range(_MAX_RETRIES):
        response = requests.get(base_url, params=params, timeout=30)

        if response.status_code == 429:
            if attempt == _MAX_RETRIES - 1:
                response.raise_for_status()
            retry_after = response.headers.get("Retry-After")
            wait_s = float(retry_after) if retry_after is not None else delay
            time.sleep(wait_s)
            delay *= 2
            continue

        response.raise_for_status()
        return response.json()


def paginate_condition(
    condition: str,
    fields: list[str] = FIELDS,
    page_size: int = 500,
    request_delay_s: float = 1.2,
    base_url: str = "https://clinicaltrials.gov/api/v2/studies",
) -> Iterator[dict]:
    """Yield every raw study record for a condition, following pageToken/nextPageToken."""
    page_token: str | None = None
    first_request = True

    while True:
        if not first_request:
            time.sleep(request_delay_s)
        first_request = False

        response = fetch_condition_page(
            condition=condition,
            page_token=page_token,
            fields=fields,
            page_size=page_size,
            base_url=base_url,
        )

        for study in response.get("studies", []):
            yield study

        page_token = response.get("nextPageToken")
        if not page_token:
            break


def write_raw_checkpoint(condition: str, studies: list[dict], raw_dir: Path) -> None:
    """Write the concatenated pages for one condition to /data/raw/<condition>.json.

    Written atomically (write to a temp file in the same directory, then os.replace) so
    that a crash/kill mid-write can never leave a truncated file that `has_checkpoint`
    would then mistake for a complete, valid checkpoint on the next resume run — the
    resume mechanism (HLD §1) relies on file *existence* alone as the "done" signal, so a
    partially-written file must never be observable at its final path.
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_checkpoint_path(condition, raw_dir)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(studies, f, indent=2)
    os.replace(tmp_path, path)


def load_raw_checkpoint(condition: str, raw_dir: Path) -> list[dict]:
    """Load a previously written /data/raw/<condition>.json checkpoint."""
    path = raw_checkpoint_path(condition, raw_dir)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_all(
    conditions: list[str] = CANCER_TYPE_SHORTLIST,
    raw_dir: Path = Path("data/raw"),
    fields: list[str] = FIELDS,
) -> dict[str, list[dict]]:
    """Orchestrate the full extract stage: skip conditions with an existing checkpoint
    (resume), pull the rest, return {condition: [raw studies]}."""
    raw_dir = Path(raw_dir)
    results: dict[str, list[dict]] = {}

    for condition in conditions:
        if has_checkpoint(condition, raw_dir):
            results[condition] = load_raw_checkpoint(condition, raw_dir)
            continue

        studies = list(paginate_condition(condition, fields=fields))
        write_raw_checkpoint(condition, studies, raw_dir)
        results[condition] = studies

    return results
