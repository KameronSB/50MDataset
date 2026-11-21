"""Audit the preserved corpus and produce public reports without exporting book text."""

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .build import PARTITIONS, SEPARATOR, canonical, digest, file_hash
from .clean import extract
from .evidence import eligibility
from .overrides import read_rows


def read_json(path):
    return json.loads(path.read_bytes())


def write_json(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def require(condition, message):
    if not condition:
        raise ValueError(f"Integrity error: {message}")


def unique(rows):
    mapping = {r["document_id"]: r for r in rows}
    require(len(rows) == len(mapping) and "" not in mapping, "duplicate or missing document ID in manifest")
    return mapping


def validate(folder, *, check_report=False):
    config = read_json(folder / "config.json")
    inputs = read_json(folder / "inputs.json")
    require(digest(canonical(config).encode()) == inputs["config_sha256"], "configuration fingerprint")
    require(folder.name.endswith(digest(canonical(inputs).encode())[:16]), "build identifier")
    audit = unique(read_rows(folder / "audit.csv"))
    selected = unique(read_rows(folder / "selected_manifest.csv"))
    assignments = unique(read_rows(folder / "split_manifest.csv"))
    require(set(selected) == set(assignments) == {k for k, r in audit.items() if r["selection_status"] == "selected"},
            "selection, audit and split manifests disagree")
    recorded_raw = {key: r["raw_sha256"] for key, r in audit.items() if r.get("raw_sha256")}
    require(recorded_raw == inputs["raw_sha256"], "raw inventory differs from frozen inputs")
    for key, sha in recorded_raw.items():
        require(file_hash(audit[key]["raw_path"]) == sha, f"{key} raw bytes changed")
    for key, row in audit.items():
        if row.get("clean_sha256"):
            require(file_hash(row["clean_path"]) == row["clean_sha256"], f"{key} clean pool file changed")
    metadata = {(r[path], r[sha]) for r in audit.values()
                for path, sha in (("rdf_path", "rdf_sha256"), ("catalogue_path", "catalogue_sha256"))
                if r.get(path)}
    for path, sha in metadata:
        require(file_hash(path) == sha, f"{path} archived metadata changed")
    known_text = set()
    groups = defaultdict(set)
    groups_to_check = ["work_group_id", "duplicate_group_id", "overlap_group_id", "series_group_id"]
    if config["build"]["group_authors"]:
        groups_to_check.append("author_group_id")
    lengths = {}
    for key, row in selected.items():
        reasons = eligibility(row, config)
        require(not reasons and row.get("decision") != "exclude" and row.get("eligibility_status") == "eligible",
                f"{key} eligibility: {reasons}")
        require(row.get("source_record_url") and row.get("download_url") and row.get("retrieved_at"),
                f"{key} missing acquisition provenance")
        require(not any(row[k] != audit[key].get(k, "") for k in row), f"{key} audit metadata")
        cleaned = extract(row, Path(row["raw_path"]).read_bytes()).text
        sha = digest(cleaned.encode())
        require(sha not in known_text and sha == row["clean_sha256"], f"{key} repeated or mismatched text")
        known_text.add(sha)
        lengths[key] = len(cleaned)
        require(lengths[key] == int(row["char_count"]) == int(assignments[key]["char_count"]), f"{key} counts")
        for field in groups_to_check:
            if row.get(field):
                groups[field, row[field]].add(assignments[key]["split"])
    require(all(len(s) == 1 for s in groups.values()), "group spans partitions")
    counts, separators = {}, {}
    for name in ("corpus", *PARTITIONS):
        expected = {key for key in selected if name == "corpus" or assignments[key]["split"] == name}
        seen, txt_hash = set(), hashlib.sha256()
        chars = 0
        with (folder / f"{name}.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                key, text = row["document_id"], row.pop("text")
                require(key in expected and key not in seen, f"{name} unknown, misplaced or repeated ID {key}")
                require(set(row) <= set(selected[key]) and all(str(row.get(k, "")) == v for k, v in selected[key].items()),
                        f"{name}/{key} metadata differs from manifest")
                payload = text.encode()
                require(digest(payload) == selected[key]["clean_sha256"], f"{name}/{key} text mismatch")
                if seen:
                    txt_hash.update(SEPARATOR.encode())
                txt_hash.update(payload)
                chars += len(text)
                seen.add(key)
        require(seen == expected, f"{name} coverage")
        require(file_hash(folder / f"{name}.txt") == txt_hash.hexdigest(), f"{name}.txt text or separators")
        counts[name] = chars
        separators[name] = max(0, len(seen) - 1) * len(SEPARATOR)
    require(counts["corpus"] == sum(counts[p] for p in PARTITIONS) == sum(lengths.values()), "character reconciliation")
    result = {"integrity_valid": True, "build_id": folder.name, "raw_documents_verified": len(recorded_raw),
            "catalogue_and_item_metadata_files_verified": len(metadata),
            "selected_documents_verified": len(selected), "characters": counts, "export_separator_characters": separators}
    if check_report:
        stats = read_json(folder / "statistics.json")
        require(stats["integrity_valid"] and stats["build_id"] == folder.name, "statistics refer to a different build")
        require(stats["characters"] == counts["corpus"] and stats["documents"] == len(selected), "reported corpus totals")
        for name in PARTITIONS:
            require(stats["partitions"][name]["characters"] == counts[name], f"reported {name} count")
        result["targets_met"] = stats["targets_met"]
    return result


def composition(rows, field, targets=None):
    counts = Counter()
    for row in rows:
        counts[row[field]] += int(row["char_count"])
    if targets is None:
        return dict(sorted(counts.items()))
    total = sum(counts.values())
    output = {}
    for key, share in targets.items():
        pct = 100 * counts[key] / total if total else 0
        output[key] = dict(characters=counts[key], actual_pct=pct, target_pct=100 * share, deviation_pp=pct - 100 * share)
    return output


def summary(stats):
    return (f"{stats['build_id']}  |  {stats['characters']:,} characters, {stats['documents']} documents  |  "
            f"integrity_valid={stats['integrity_valid']}  targets_met={stats['targets_met']}")


def generate(folder):
    checks = validate(folder)
    config, inputs = (read_json(folder / name) for name in ("config.json", "inputs.json"))
    rows = read_rows(folder / "selected_manifest.csv")
    audit = read_rows(folder / "audit.csv")
    splits = unique(read_rows(folder / "split_manifest.csv"))
    total = checks["characters"]["corpus"]
    b = config["build"]
    topics = composition(rows, "primary_topic", config["topics"])
    regions = composition(rows, "region", config["regions"])
    size_ok = b["min_chars"] <= total <= b["max_chars"]
    composition_ok = all(abs(r["deviation_pp"]) <= b["tolerance_pp"] for table in (topics, regions) for r in table.values())
    parts = {}
    for name in PARTITIONS:
        subset = [r for r in rows if splits[r["document_id"]]["split"] == name]
        chars = checks["characters"][name]
        actual = 100 * chars / total if total else 0
        parts[name] = dict(documents=len(subset), characters=chars, actual_pct=actual,
                           target_pct=100 * config["splits"][name], deviation_pp=actual - 100 * config["splits"][name],
                           topics=composition(subset, "primary_topic"), regions=composition(subset, "region"))
    split_ok = all(abs(p["deviation_pp"]) <= b.get("split_tolerance_pp", 2) for p in parts.values())
    for r in rows:
        year = int(r["work_year"])
        r["decade"] = f"{year // 10 * 10}s"
        r["period"] = "1800–1849" if year < 1850 else "1850–1899" if year < 1900 else "1900–1945"
    authors = defaultdict(lambda: {"authors": "", "documents": 0, "characters": 0, "partitions": set()})
    for row in rows:
        if key := row.get("author_group_id"):
            a = authors[key]
            a["authors"] = row["authors"]
            a["documents"] += 1
            a["characters"] += int(row["char_count"])
            a["partitions"].add(splits[row["document_id"]]["split"])
    for a in authors.values():
        a["partitions"] = sorted(a["partitions"])
    source_file = folder / "source_status.json"
    if not source_file.exists():
        sources = {}
        for file in ("data/source_status.json", "data/regional_status.json"):
            if Path(file).is_file():
                sources.update(read_json(Path(file)))
        # Trial and full runs share a download cache. Derive the coverage of
        # this particular build from its frozen audit, even after another run.
        for name in ("Project Gutenberg", "Project Gutenberg Australia"):
            inventory = [r for r in audit if r["source"] == name]
            retained = sum(bool(r.get("raw_path")) for r in inventory)
            if retained:
                failures = sum(bool(r.get("acquisition_error")) for r in inventory)
                sources[name] = {"status": "working", "detail": f"{len(inventory):,} candidate records, "
                                 f"{retained:,} retained raw documents and {failures} item acquisition errors in this build."}
        write_json(source_file, sources)
    sources = read_json(source_file)
    review_reasons = Counter()
    for row in audit:
        if row["selection_status"] == "review":
            if row["source"] == "Project Gutenberg" and not row.get("rdf_path"):
                review_reasons["Item record has not been checked in the bounded acquisition run"] += 1
            else:
                review_reasons.update(sorted(set(row["selection_reason"].split(" | "))))
    stats = {
        "build_id": folder.name, "integrity_valid": True, "targets_met": size_ok and composition_ok and split_ok,
        "size_target_met": size_ok, "composition_targets_met": composition_ok, "partition_targets_met": split_ok, "characters": total,
        "target_characters": b["target_chars"], "shortfall_to_nominal": max(0, b["target_chars"] - total),
        "shortfall_to_lower_bound": max(0, b["min_chars"] - total), "documents": len(rows), "principal_authors": len(authors),
        "topics": topics, "regions": regions, "partitions": parts, "decades": composition(rows, "decade"),
        "historical_periods": composition(rows, "period"), "selected_source_characters": composition(rows, "source"),
        "author_concentration": sorted(authors.values(), key=lambda a: -a["characters"]),
        "review_reason_counts": dict(review_reasons.most_common()), "candidate_outcomes": dict(Counter(r["selection_status"] for r in audit)),
        "unfulfilled_inclusions": {r["document_id"]: r["selection_reason"] for r in audit if r.get("decision") == "include" and r["selection_status"] != "selected"},
        "unmatched_overrides": inputs.get("unmatched_overrides", []),
        "acquisition_errors": dict(Counter(r["acquisition_error"] for r in audit if r.get("acquisition_error"))),
        "retained_clean_documents": sum(bool(r.get("clean_sha256")) for r in audit),
        "retained_clean_characters_before_dedup": sum(int(r["char_count"]) for r in audit if r.get("clean_sha256")),
        "output_sha256": {name: file_hash(folder / name) for name in
                          ("corpus.jsonl", "train.jsonl", "validation.jsonl", "test.jsonl", "selected_manifest.csv", "split_manifest.csv")},
        "source_status": sources, "validation": checks, "configuration": config, "input_fingerprints": inputs,
    }
    write_json(folder / "statistics.json", stats)
    lines = [f"# Historical English corpus · {folder.name}", "", summary(stats), "",
             f"Requested {b['target_chars']:,} characters. Accepted band {b['min_chars']:,}–{b['max_chars']:,}. "
             f"Nominal shortfall {stats['shortfall_to_nominal']:,}. The selection contains {len(authors)} identified principal authors.", "",
             "| Category | Characters | Target | Actual | Difference |", "|---|---:|---:|---:|---:|"]
    for key, val in {**topics, **regions, **parts}.items():
        lines.append(f"| {key} | {val['characters']:,} | {val['target_pct']:.2f}% | {val['actual_pct']:.2f}% | {val['deviation_pp']:+.2f} pp |")
    for heading, mapping in (("Candidate decisions", stats["candidate_outcomes"]), ("Historical periods by character count", stats["historical_periods"]),
                             ("Decades by character count", stats["decades"]),
                             ("Sources by character count", stats["selected_source_characters"])):
        lines += ["", f"## {heading}", "", *[f"- {k} — {v:,}" for k, v in mapping.items()]]
    lines += ["", "## Review and coverage", ""]
    for key, count in review_reasons.most_common(5):
        lines.append(f"- {count} candidates — {key}")
    for k, v in sources.items():
        lines.append(f"- {k} — {v.get('detail', v.get('status', ''))}" if isinstance(v, dict) else f"- {k} — {v}")
    for reason, count in stats["acquisition_errors"].items():
        lines.append(f"- {count} acquisition errors — {reason}")
    lines += ["", "## Partition composition", "",
              "| Partition | Documents | UK | US | CA | AU | NZ | Export separator characters |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, part in parts.items():
        shares = [100 * part["regions"].get(k, 0) / max(1, part["characters"]) for k in ("UK", "US", "CA", "AU", "NZ")]
        lines.append(f"| {name} | {part['documents']} | " + " | ".join(f"{v:.2f}%" for v in shares)
                     + f" | {checks['export_separator_characters'][name]:,} |")
    if authors:
        a = stats["author_concentration"][0]
        lines += ["", f"The largest author group is {a['authors']} with {a['characters']:,} characters ({100*a['characters']/total:.2f}%)."]
    lines += ["", "The JSON report includes per-partition composition, author concentration, input hashes and export separator counts. "
              "See the repository README for cleaning, eligibility and overlap rules.", "",
              "Rebuild against the retained pool with the following command.", "",
              "```console", "uv run python -m llm_v2_dataset build --config config.toml --offline"
              + (f" --max-documents {inputs['max_documents']}" if inputs["max_documents"] is not None else ""), "```", ""]
    (folder / "report.md").write_bytes("\n".join(lines).encode())
    public = Path("reports") / folder.name
    public.mkdir(parents=True, exist_ok=True)
    for name in ("statistics.json", "report.md"):
        (public / name).write_bytes((folder / name).read_bytes())
    fields = ["document_id", "title", "authors", "work_year", "region", "primary_topic", "char_count", "source_record_url",
              "date_evidence_url", "region_evidence_url", "rights_evidence_url", "raw_sha256", "clean_sha256", "split"]
    with (public / "provenance.csv").open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({**r, "title": " ".join(r["title"].split()), "split": splits[r["document_id"]]["split"]})
    return stats
