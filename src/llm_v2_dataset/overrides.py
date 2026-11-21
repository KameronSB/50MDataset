"""Apply persistent, evidenced edits to a copy of the discovered facts."""

import csv
import json
from pathlib import Path

from .evidence import eligibility

EDITABLE = set("""
    title authors principal_author author_group_id expected_pg_author_id work_group_id duplicate_group_id
    work_year edition_year composition_year date_basis date_evidence_url date_status
    version_basis version_evidence_url region region_basis region_evidence_url
    primary_topic classification_rule document_type subjects tags language original_language
    language_evidence_url translator translation_year translation_evidence_url
    rights_statement jurisdiction rights_basis rights_evidence_url uk_rights_evidence_url
    contributor_death_year contributor_basis contributor_evidence_url evidence_review
    first_publication_status extraction_start extraction_end encoding
    issuing_institution issuer_region issuer_evidence_url rights_scope
""".split())
EVIDENCE_FOR = {
    "work_year": "date_evidence_url", "edition_year": "version_evidence_url",
    "region": "region_evidence_url", "contributor_death_year": "contributor_evidence_url",
    "translation_year": "translation_evidence_url", "primary_topic": "classification_rule",
    "authors": "contributor_evidence_url", "expected_pg_author_id": "contributor_evidence_url",
    "rights_statement": "rights_evidence_url",
    "issuer_region": "issuer_evidence_url", "issuing_institution": "issuer_evidence_url",
    "rights_scope": "rights_evidence_url",
}


def read_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def apply(rows, config):
    overrides = {}
    for entry in read_rows("manifests/overrides.csv"):
        key = entry["document_id"].strip()
        if not key or key in overrides:
            raise ValueError(f"Missing or duplicate override ID {key!r}")
        changes = json.loads(entry.get("corrections_json") or "{}")
        if not isinstance(changes, dict) or set(changes) - EDITABLE:
            raise ValueError(f"{key} has unknown correction fields")
        changes.update({k: v.strip() for k, v in entry.items() if k in EDITABLE and v.strip()})
        if any(not isinstance(value, (str, int)) for value in changes.values()):
            raise ValueError(f"{key} expects text or year corrections")
        decision = (entry.get("decision") or "auto").strip().lower()
        if decision not in {"auto", "include", "exclude"}:
            raise ValueError(f"{key} has invalid override decision {decision!r}")
        overrides[key] = (changes, decision, entry.get("notes", ""))
    output = []
    for candidate in rows:
        changes, decision, notes = overrides.get(candidate["document_id"], ({}, "auto", ""))
        row = {**candidate, **{k: str(v) for k, v in changes.items()}, "decision": decision}
        if notes:
            row["override_notes"] = notes
        reasons = eligibility(row, config)
        for field, support in EVIDENCE_FOR.items():
            if field in changes and str(changes[field]) != str(candidate.get(field, "")) and not changes.get(support):
                reasons.append(f"override to {field} needs an explicit {support}")
        row["eligibility_reason"] = " | ".join(reasons)
        row["eligibility_status"] = "review" if reasons else "eligible"
        output.append(row)
    return output
