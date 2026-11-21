"""Regenerate the public, factual Gutenberg/Wikidata matching table from frozen inputs."""
import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from .evidence import FACTS, normalized_title


WD = "https://www.wikidata.org/wiki/"
NATIONAL = {
    "NZ": r"new zealand(?:er)?", "AU": "australian", "CA": "canadian",
    "US": "american", "UK": "british|english|scottish|welsh",
}
COUNTRY = {"Q16": "CA", "Q408": "AU", "Q664": "NZ", "Q30": "US", "Q145": "UK", "Q174193": "UK", "Q161885": "UK"}
FIELDS = ("document_id title author_group_id expected_pg_author_id contributor_death_year "
          "work_group_id work_year date_basis date_evidence_url first_publication_status original_language "
          "region region_basis region_evidence_url curated_topic topic_basis").split()
QUERIES = Path("manifests/queries")
ENDPOINT = "https://query.wikidata.org/sparql"
KINDS = {"literary work", "written work", "non-fiction literary work", "narrative", "scientific literature",
         "novel", "novella", "short story", "short story collection", "long poem", "cookbook", "pamphlet",
         "scholarly work", "personal narrative", "article", "annual report", "autobiography", "essay", "book"}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def authority_index(rows):
    people = defaultdict(list)
    for r in rows:
        people[r["author"]].append(r)
    authority = {}
    lives = defaultdict(set)
    for url, person in people.items():
        dates = {(r["birth"][:4], r["death"][:4]) for r in person}
        if len(dates) != 1:
            continue
        birth, death = dates.pop()
        if not birth.isdigit() or not death.isdigit():
            continue
        countries = {r["citizenship"].split("/")[-1] for r in person}
        desc = person[0]["description"].lower()
        # Explicit professional association supersedes an empire-era passport.
        # Drop birthplace modifiers before looking for nationality adjectives.
        profession = re.sub(r"\b[a-z]+(?: [a-z]+)?[- ]born\b", "", desc)
        professional = {k for k,v in NATIONAL.items() if re.search(r"\b(?:" + v + r")\b", profession)}
        mapped = {COUNTRY.get(k, "") for k in countries}
        region = basis = ""
        if len(professional) == 1 and not re.search(r"\b(irish|french|german|italian|russian|indian|jamaican|south african|polish)\b", profession):
            region = professional.pop()
            basis = "Author association in Wikidata description: " + person[0]["description"]
        elif not professional and len(mapped) == 1 and mapped <= {"US", "CA", "AU", "NZ"}:
            region = mapped.pop()
            basis = "Single recorded author citizenship (Wikidata P27)"
        authority[url] = dict(birth=birth, death=death, region=region, basis=basis,
                              label=person[0]["label"], ids={r["pgAuthor"] for r in person})
        lives[birth, death].add(url)
    return authority, lives


def short_title(title):
    return normalized_title(re.split(r"\n|:|\s+[—–]\s+", title, maxsplit=1)[0])


def generate(catalogue, evidence_dir):
    authors, lives = authority_index(read_csv(evidence_dir / "authors.csv"))
    direct = defaultdict(set)
    by_title = defaultdict(set)
    for filename, joined in (("work-filtered.csv", True), ("works_by_title-filtered.csv", False)):
        for r in read_csv(evidence_dir / filename):
            item = (r["work"], r["author"], r["published"][:4], normalized_title(r["label"]))
            if joined:
                direct[r["pg"]].add(item)
            else:
                by_title[normalized_title(r["label"]), r["author"]].add(item)
    regional_path = Path("manifests/nz_evidence.csv")
    regional = {r["document_id"]:r for r in read_csv(regional_path)} if regional_path.exists() else {}
    output = []
    with gzip.open(catalogue, "rt", encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream)
        for r in rows:
            if r["Language"] != "en" or r["Type"] != "Text":
                continue
            ident = "pg-" + r["Text#"]
            full, short = normalized_title(r["Title"]), short_title(r["Title"])
            # Ignore separate named editor/translator credits here. RDF is checked again after acquisition.
            lead = r["Authors"].split(";")[0]
            lifespan = re.search(r"(\d{4})-(\d{4})\b", lead)
            if not lifespan:
                continue
            surname = normalized_title(lead.split(",")[0])
            extra = regional.get(ident)
            lookup = lives[lifespan.groups()].copy()
            if extra:
                # A reviewed source sometimes differs by one year on birth. A unique
                # surname + exact death year + independent RDF ID check remain mandatory.
                birth, death = lifespan.groups()
                for nearby in (int(birth)-1, int(birth)+1):
                    lookup.update(lives[str(nearby), death])
            people = {p for p in lookup if surname in normalized_title(authors[p]["label"]).split() or
                      (" " + surname + " ") in (" " + normalized_title(authors[p]["label"]) + " ")}
            linked = {item for item in direct[r["Text#"]] if item[3] in {short, full} and item[1] in people}
            mode = "Linked Gutenberg ID P2034, matching title, creator and original English-language work P407"
            if not linked:
                linked = set().union(*(by_title[name, p] for name in {short,full} for p in people))
                mode = "Matching catalogue title and named creator on original-English work P407"
            if re.search(r"\b(?:vol(?:ume)?\.?|part|book)\s+(?:\d+|[ivxlcdm]+|one|two|three|four)\b", r["Title"], re.I):
                linked = {item for item in linked if item[3] == full}
            if len(linked) == 1:
                work, person, date, _ = linked.pop()
                work_id = work.split("/")[-1]
                basis, date_url = mode + "; publication date P577", WD + work_id
            elif extra and len(people) == 1:
                person, date = next(iter(people)), extra["work_year"]
                work_id = "pg-title-" + hashlib.sha256((person + "|" + short).encode()).hexdigest()[:16]
                basis, date_url = extra["date_basis"], extra["date_evidence_url"]
            else:
                continue
            a = authors[person]
            if len(a["ids"]) != 1 or not date.isdigit() or not int(a["birth"]) + 8 <= int(date) <= int(a["death"]):
                continue
            qid = person.split("/")[-1]
            region = a["region"]
            region_basis, region_url = a["basis"], WD + qid
            if extra:
                region, region_basis, region_url = "NZ", extra["region_basis"], extra["region_evidence_url"]
                date, basis, date_url = extra["work_year"], extra["date_basis"], extra["date_evidence_url"]
            if not region or not 1800 <= int(date) <= 1945:
                continue
            output.append(dict(zip(FIELDS, (
                ident, r["Title"].replace("\r\n","\n").replace("\r","\n"), qid, next(iter(a["ids"])), a["death"], work_id, date,
                basis, date_url, "published", "en", region, region_basis, region_url,
                extra.get("primary_topic", "") if extra else "", extra.get("classification_rule","") if extra else ""
            ))))
    return output


def query(query_text, output):
    """Immutable cache by exact SPARQL query, with sequential, paced requests."""
    if output.exists():
        return
    contact = os.environ.get("CONTACT_EMAIL", "")
    agent = "llm_v2_dataset/1.0 historical literature research" + (f" (+mailto:{contact})" if contact else "")
    data = urllib.parse.urlencode({"query":query_text}).encode()
    request = urllib.request.Request(ENDPOINT, data=data, headers={"User-Agent":agent, "Accept":"text/csv"})
    # WDQS advertised a one-request/minute cap during the original acquisition.
    # No parallel queries. An explicit longer Retry-After ends this refresh.
    time.sleep(61)
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read(25_000_001)
            if len(body) > 25_000_000 or "csv" not in response.headers.get("Content-Type", ""):
                raise ValueError("Wikidata returned an oversized or unexpected response")
    except urllib.error.HTTPError as err:
        raise RuntimeError(f"Wikidata HTTP {err.code}. Resume after {err.headers.get('Retry-After','the service recovers')}.") from err
    temporary = output.with_suffix(".part")
    temporary.write_bytes(body)
    temporary.replace(output)


def verify_works(rows, folder, download):
    """Verify unique creator/date and an explicit work-level class in the authority."""
    ids = sorted({r["work_group_id"] for r in rows if r["date_evidence_url"].startswith(WD)})
    template = (QUERIES / "work-types.rq").read_text("ascii")
    types = defaultdict(set)
    inputs = []
    for i in range(0,len(ids),3000):
        values = " ".join("wd:" + ident for ident in ids[i:i+3000])
        sparql = template.replace("WORK_IDS", values)
        path = folder / ("types-" + hashlib.sha256(sparql.encode()).hexdigest()[:16] + ".csv")
        if download:
            query(sparql, path)
        inputs.append(path)
        for e in read_csv(path):
            types[e["work"].split("/")[-1]].add((e["kindLabel"],e["published"][:4],e["author"].split("/")[-1]))
    kept = []
    for row in rows:
        if row["date_evidence_url"].startswith(WD):
            claims = types[row["work_group_id"]]
            kinds = {k for k,_,_ in claims}
            if not kinds & KINDS or any(re.search(r"edition|translation|part of|unfinished|book series|periodical", k) for k in kinds):
                continue
            if {(y,a) for _,y,a in claims} != {(row["work_year"],row["author_group_id"])}:
                continue
        kept.append(row)
    return kept, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--evidence-dir", type=Path, default=Path("data/raw/evidence"))
    parser.add_argument("--download", action="store_true", help="Retrieve missing queries. Use a new --evidence-dir to refresh.")
    args = parser.parse_args()
    if args.download:
        from .cli import load_env
        load_env()
    args.evidence_dir.mkdir(parents=True, exist_ok=True)
    inputs = []
    for name in ("authors","work-filtered","works_by_title-filtered"):
        path = args.evidence_dir / (name + ".csv")
        if args.download:
            query((QUERIES / (name + ".rq")).read_text("ascii"), path)
        inputs.append(path)
    result, more = verify_works(generate(args.catalogue, args.evidence_dir), args.evidence_dir, args.download)
    temp = FACTS.with_suffix(".tmp")
    with temp.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(result)
    temp.replace(FACTS)
    inputs.extend([*more,args.catalogue, Path("manifests/nz_evidence.csv"), *sorted(QUERIES.glob("*.rq")), FACTS])
    fingerprints = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs if p.exists()}
    provenance = {"endpoint": ENDPOINT, "licence": "Wikidata structured data, CC0", "sha256":fingerprints}
    FACTS.with_suffix(".inputs.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(result)} verified identifier/title candidates to {FACTS}")


if __name__ == "__main__":
    main()
