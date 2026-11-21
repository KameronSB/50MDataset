"""Factual catalogue joins, transparent subject rules and conservative text eligibility."""
import csv
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit


UK_TERM = "https://www.gov.uk/copyright/how-long-copyright-lasts"
FACTS = Path("manifests/work_evidence.csv")
TOPICS = {
    "letters_diaries_memoirs": ("form", r"\b(autobiograph(?:y|ies|ical)|memoirs?|diaries|diary|correspondence|personal narratives?|reminiscences)\b"),
    "fiction": ("subject", r"\b(fiction|novels?|short stories|fairy tales|fantasy fiction)\b"),
    "practical_technical": ("form", r"\b(handbooks?|manuals?|cookbooks?|cookery|recipes|how to|textbooks?)\b"),
    "travel_exploration": ("subject", r"\b(description and travel|travel writing|voyages and travels|discovery and exploration|explorers|journeys|travelers)\b"),
}


def topic(row):
    """Prefer bibliographic form/subject, then a relevant Library of Congress class."""
    title = row.get("title", "").lower()
    subjects = row.get("subjects", "").lower()
    parts = [x.strip() for x in subjects.split(";")]
    lead = row.get("authors","").split(";")[0].strip().lower()
    shelves = row.get("bookshelves", "").lower()
    fiction = (any(re.search(r"\b(fiction|short stories|fairy tales|humorous stories)\b", x) for x in parts)
               or re.search(r"category: (?:novels|short stories|science-fiction)\b", shelves)
               or row.get("work_kind") in {"novel", "novella", "short story", "short story collection", "collection of short stories"})
    matches = []
    for key, (kind, pattern) in TOPICS.items():
        field = subjects + (" " + title if kind == "form" else "")
        if key == "letters_diaries_memoirs" and ("description and travel" in subjects or re.search(
            r"memoirs of (?:the court|the .*?(?:association|society|institute|academy|museum))", title
        )):
            field = subjects
        if re.search(pattern, field):
            matches.append((key, "catalogue " + kind))
    # A fictional diary or a novel about a cook is still a work of fiction.
    if lead and lead in parts and re.search(r" -- biography\b", subjects):
        matches.insert(0, ("letters_diaries_memoirs", "principal author is a named subject of the biographical text"))
    if fiction:
        matches.insert(0, ("fiction", "fictional work form, subject or catalogue bookshelf"))
    if re.search(r"\b(natural history|animal behavior|entomology|ornithology|geology|botany|zoology)\b", subjects):
        matches.append(("science_natural_history", "natural-science subject"))
    for code in re.split(r"[;, ]+", row.get("locc", "").upper()):
        if not code:
            continue
        if re.match(r"^[QR]", code):
            matches.append(("science_natural_history", "LoCC " + code))
        elif re.match(r"^[ST]", code):
            matches.append(("practical_technical", "LoCC " + code))
        elif re.match(r"^[DEF]", code) and re.search(r"\bhistory\b| -- biography\b|\bcivilization\b", subjects):
            matches.append(("history", "historical subject and LoCC " + code))
        elif re.match(r"^(B|H|J|L)", code):
            matches.append(("essays_philosophy_economics_society", "LoCC " + code))
    if not matches and "essays" in subjects:
        matches.append(("essays_philosophy_economics_society", "catalogue essays subject"))
    if not matches:
        return "", "", ""
    primary, rule = matches[0]
    return primary, "pg-subject-v2: " + rule, "|".join(dict.fromkeys(x for x, _ in matches[1:] if x != primary))


def normalized_title(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", value))


def enrich(rows, config=None):
    """Select English catalogue matches from the frozen factual crosswalk."""
    if not FACTS.exists():
        raise FileNotFoundError(f"Missing published factual crosswalk: {FACTS}")
    with FACTS.open(encoding="utf-8", newline="") as stream:
        facts = {r["document_id"]: r for r in csv.DictReader(stream)}
    enriched = []
    for row in rows:
        fact = facts.get(row["document_id"])
        if not fact:
            continue
        if normalized_title(fact["title"]) != normalized_title(row.get("title","")):
            continue
        result = {**row, **{k: v for k, v in fact.items() if v and k != "title"}}
        kind, rule, tags = topic(result)
        result.update(primary_topic=fact.get("curated_topic") or kind, classification_rule=fact.get("topic_basis") or rule, secondary_tags=tags)
        result["language_evidence_url"] = result["source_record_url"]
        result["work_group_id"] = fact["work_group_id"]
        result["eligibility_status"] = "review"
        enriched.append(result)
    return enriched


def year(value):
    return int(str(value)) if re.fullmatch(r"[0-9]{4}", str(value)) else 0


def public_reference(value):
    try:
        parts = urlsplit(value or "")
        query_keys = [k.lower() for k, _ in parse_qsl(parts.query, keep_blank_values=True)]
        return (parts.scheme in {"http", "https"} and bool(parts.hostname) and not parts.username and not parts.password
                and not any(re.search(r"token|secret|password|signat|credential|api.?key|^x-amz", k) for k in query_keys))
    except ValueError:
        return False


def eligibility(row, config):
    reasons = []
    cfg = config["build"]
    for key in ("document_id", "source", "title", "authors", "date_basis", "version_basis", "region_basis",
                "classification_rule", "rights_statement", "jurisdiction", "rights_basis", "contributor_basis",
                "work_group_id"):
        if not str(row.get(key) or "").strip():
            reasons.append("missing " + key)
    for key in ("source_record_url", "date_evidence_url", "version_evidence_url", "region_evidence_url",
                "language_evidence_url", "rights_evidence_url", "uk_rights_evidence_url", "contributor_evidence_url"):
        if not public_reference(row.get(key)):
            reasons.append("missing/invalid " + key)
    if row.get("evidence_review") != "verified":
        reasons.append("evidence review incomplete")
    if row.get("first_publication_status") != "published":
        reasons.append("historical publication unverified")
    if row.get("language") != "en":
        reasons.append("English catalogue evidence required")
    if row.get("region") not in config["regions"] or row.get("primary_topic") not in config["topics"]:
        reasons.append("unresolved region or topic")
    lo, hi = cfg["year_min"], cfg["year_max"]
    if not lo <= year(row.get("work_year")) <= hi:
        reasons.append("work year unresolved or outside scope")
    if row.get("edition_year") and not year(row.get("work_year")) <= year(row["edition_year"]) <= hi:
        reasons.append("edition date outside eligible range")
    if row.get("original_language") != "en":
        if not (row.get("translator") and public_reference(row.get("translation_evidence_url"))
                and year(row.get("work_year")) <= year(row.get("translation_year")) <= hi):
            reasons.append("English original or dated translator evidence required")
    death = year(row.get("contributor_death_year"))
    official = row.get("document_type") == "anonymous_official" and row.get("source") != "Project Gutenberg"
    if official:
        issuer = (row.get("issuing_institution") or "").strip()
        statement = row.get("rights_statement") or ""
        rights_link = row.get("rights_evidence_url") or ""
        if (not issuer or (row.get("authors") or "").strip().casefold() not in {issuer.casefold(), "anonymous"}
                or row.get("issuer_region") != row.get("region") or not public_reference(row.get("issuer_evidence_url"))):
            reasons.append("anonymous official item needs verified issuer identity and jurisdiction")
        if (row.get("rights_scope") != "issuer_cc0_complete_text" or not re.search(r"\bCC0\b", statement, re.I)
                or not public_reference(rights_link) or (urlsplit(rights_link).hostname or "").endswith("creativecommons.org")):
            reasons.append("official item needs item-specific issuer CC0 dedication covering the entire historical text")
    elif not death or death + 70 >= cfg["rights_year"]:
        reasons.append("text contributor term unresolved")
    if row.get("source") == "Project Gutenberg":
        if row.get("rdf_languages") and row["rdf_languages"] != "en":
            reasons.append("English-only item RDF and catalogue language disagree")
        if row.get("pg_creator_count") != "1" or not row.get("pg_author_id") or row.get("pg_author_id") != row.get("expected_pg_author_id"):
            reasons.append("PG creator identity/count mismatch")
        if not death or year(row.get("pg_author_death")) != death:
            reasons.append("author death-year evidence disagrees")
        if not re.search(r"public domain in the (?:united states|usa)", row.get("rights_statement", ""), re.I):
            reasons.append("PG item lacks US public-domain statement")
        try:
            extra = json.loads(row.get("pg_contributors") or "[]")
            if not isinstance(extra, list) or any(c.get("role") not in {"ill", "pht", "egr"} for c in extra):
                reasons.append("unreviewed textual contributors")
        except (AttributeError, ValueError, TypeError):
            reasons.append("invalid PG contributor record")
        if re.search(r"\b(abridged|adapted|adaptation|extracts?|selections from|retold|retelling)\b", row["title"], re.I):
            reasons.append("version needs editorial review")
    else:
        rights = row.get("rights_statement") or ""
        if (not re.search(r"\b(public[ -]domain|CC0)\b", rights, re.I)
                or re.search(r"\b(all rights reserved|non[ -]?commercial|permission required|in copyright|not (?:in (?:the )?)?public domain)\b", rights, re.I)):
            reasons.append("archive reuse terms unresolved or restricted")
    if re.search(r"\b(peter pan|peter and wendy)\b", row.get("title",""), re.I) and "barrie" in row.get("authors","").lower():
        reasons.append("UK perpetual royalty review: Copyright, Designs and Patents Act 1988, Schedule 6")
    if row.get("evidence_conflict"):
        reasons.append(row["evidence_conflict"])
    return reasons


def assess(row, config):
    """Finish the single-author archive/work match after reading the item RDF."""
    row = dict(row)
    if row.get("source") == "Project Gutenberg" and row.get("expected_pg_author_id") and row.get("pg_author_id"):
        row.update(
            version_basis="Original-English work matched by title and author to PG transcription; no added text contributor in record",
            version_evidence_url=row["source_record_url"], contributor_evidence_url=row["source_record_url"],
            contributor_basis="Single textual creator in item RDF, independently matched death year in authority facts; text-only export",
            rights_basis="Published historical English work; PG item US statement and named text contributor screened against usual UK term",
            uk_rights_evidence_url=UK_TERM, evidence_review="verified",
        )
        dates = set(re.findall(r"\b(?:1[789]|20)\d{2}\b", row.get("pg_imprint", "")))
        if len(dates) == 1:
            row["edition_year"] = next(iter(dates))
            row["version_basis"] = "Print source imprint in PG item RDF: " + row["pg_imprint"]
        elif len(dates) > 1:
            row["evidence_conflict"] = "multiple print source dates require review"
    reasons = eligibility(row, config)
    row["eligibility_status"] = "review" if reasons else "eligible"
    row["eligibility_reason"] = "; ".join(reasons)
    return row
