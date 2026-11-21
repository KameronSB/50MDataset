# llm_v2_dataset

A Python pipeline for assembling a whole-document corpus of English writing first published in 1800–1945. The target is 50 million cleaned Unicode characters across training, validation and test. Each work counts toward one topic and one region. The original Shakespeare corpus, tokenizer and model are outside this repository.

## Train from a clone

This revision includes the [frozen dataset](data/releases/full-b5da4f869f5b1869/). Cloning or pulling it gives you all three splits. Each UTF-8 JSONL line contains one document. Pass its `text` field to your tokenizer.

```python
import json
from pathlib import Path

release = Path("data/releases/full-b5da4f869f5b1869")  # relative to the clone root

def documents(split):
    with (release / f"{split}.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)["text"]
```

Use `documents("train")` for tokenizer fitting and model training, `documents("validation")` during development, and `documents("test")` for final evaluation. The adjacent `split_manifest.csv` records document assignments and `statistics.json` contains the release checksums.

## Build results

Release `full-b5da4f869f5b1869` contains **49,802,774 cleaned characters in 140 documents by 98 identified principal authors**. All regional and topic shares are within the two-percentage-point tolerance. The largest absolute deviation is 1.76 points. [Measured report](reports/full-b5da4f869f5b1869/report.md) | [JSON statistics and hashes](reports/full-b5da4f869f5b1869/statistics.json) | [Selected works and sources](reports/full-b5da4f869f5b1869/provenance.csv)

| Partition | Documents | Characters | Share |
|---|---:|---:|---:|
| Train | 125 | 44,741,185 | 89.84% |
| Validation | 8 | 2,528,648 | 5.08% |
| Test | 7 | 2,532,941 | 5.09% |

| Primary topic | Target | Achieved |
|---|---:|---:|
| Fiction | 30% | 30.47% |
| Science and natural history | 20% | 18.24% |
| History | 16% | 16.33% |
| Letters, diaries and memoirs | 14% | 13.98% |
| Travel and exploration | 10% | 10.16% |
| Essays, philosophy, economics and society | 6% | 6.22% |
| Practical and technical | 4% | 4.60% |

Regional shares by characters are UK 40.13% (target 40%), US 29.98% (target 30%), CA 11.75% (target 12%), AU 9.90% (target 10%), NZ 8.24% (target 8%).

The release inventory contains 2,013 records, 506 with retained source bytes. The cleaner retained 310 documents. Deduplication set aside 6, and selection left 164 in reserve. Project Gutenberg supplied 49,360,760 selected characters and its Australian counterpart supplied 442,014. Five Gutenberg items had no supported linked format. Other eligible works filled the corpus.

The separate ten-document trial measured 4,456,834 characters. During review we corrected edition and work dates, identified incomplete or overlapping texts and withheld unresolved contributors. These decisions are preserved in [the override ledger](manifests/overrides.csv). [Trial report](reports/trial-10-14198ee31c0366cc/report.md)

Integrity validation passed on Windows. The build reconciled all four text exports and verified 613 catalogue and item metadata files. Repeating the offline build reproduced the build ID, selected corpus, partitions and manifests byte for byte. The unsplit JSONL SHA-256 is `7b1470a8c98481865dbc3d9674c15dad39eb213a5b961b66a402a4ca979ba56e`. Preserve the local data directory to replay this release.

## Rebuild from the repository root

Install Python 3.11+ and uv. The package uses the standard library at runtime. These commands work in Windows PowerShell and Ubuntu shells. [uv project guide](https://docs.astral.sh/uv/guides/projects/)

```console
uv sync --locked
uv run python -m llm_v2_dataset run --config config.toml --max-documents 10
uv run python -m llm_v2_dataset run --config config.toml
```

Supply a real contact address if desired. Use `Copy-Item .env.example .env` in PowerShell or `cp .env.example .env` on Ubuntu. Edit the ignored `.env` and set `CONTACT_EMAIL`. The default pipeline works without credentials.

```console
uv run python -m llm_v2_dataset discover --config config.toml
uv run python -m llm_v2_dataset fetch --config config.toml
uv run python -m llm_v2_dataset build --config config.toml --offline
uv run python -m llm_v2_dataset report --config config.toml
uv run python -m llm_v2_dataset validate --config config.toml
```

`run` performs all stages and validates before updating the latest-build pointer. Repeating it resumes from the retained files. A trial uses its own candidates CSV, build ID and pointer. Use the same `--max-documents N` on later stages to use that trial. With a synced environment, `uv run --offline --no-sync python -m llm_v2_dataset build --offline` also prevents uv itself from contacting a package index.

## Read the files

| Path | Contents |
|---|---|
| `data/raw/` | Original bytes, request receipts and permitted catalogue and enrichment snapshots |
| `data/candidates.csv` | Generated discovery inventory, bibliographic evidence, record links and acquisition facts |
| `manifests/overrides.csv` | Owner-maintained decisions and corrections |
| `data/clean/<sha256>.txt` | Separately retained UTF-8 text from works that passed eligibility and extraction, including reserves and duplicates |
| `data/builds/latest-full.txt` | Directory name of the most recently validated full build |
| `data/builds/<id>/corpus.jsonl` | Canonical unsplit corpus, one document with metadata and text per line |
| `train.jsonl`, `validation.jsonl`, `test.jsonl` | Frozen partitions within that same directory |
| `corpus.txt`, `train.txt`, `validation.txt`, `test.txt` | UTF-8 text exports with two LF characters between adjacent documents |
| `selected_manifest.csv`, `split_manifest.csv`, `audit.csv` | Selected works, group assignments, and decisions for the full candidate pool |
| `inputs.json`, `config.json`, `statistics.json`, `report.md`, `samples.txt` | Input fingerprints, configuration, measurements and local excerpts |
| `reports/<id>/` | Shareable statistics, Markdown and factual provenance CSV, without book text |

The total is the sum of Python `len(text)` across the decoded JSONL text fields. It includes punctuation, spaces and retained line endings. Export separators, JSON syntax and metadata have their own accounting. Training the eventual tokenizer should use only `train.jsonl`.

## Where the books come from

- **Project Gutenberg.** Discovery filters the official catalogue for English text locally. The Project Gutenberg Literary Archive Foundation mirror supplies the compressed CSV and item RDF. The downloader follows a text reference from the RDF through the UK Mirror Service directory mapping, or looks for a linked plain-text file on the foundation mirror. Requests have host pacing, timeouts, size limits and bounded retries. Completed responses have checksums and download receipts. The ordinary search website is outside the automated route. [Catalogue guide](https://www.gutenberg.org/ebooks/offline_catalogs.html) · [Bibliographic records](https://www.gutenberg.org/help/bibliographic_record.html) · [Automation policy](https://www.gutenberg.org/policy/robot_access.html) · [Mirrors](https://www.gutenberg.org/help/mirroring.html) · [Foundation mirror feed](https://gutenberg.pglaf.org/cache/epub/feeds/)
- **Project Gutenberg Australia.** A selective adapter follows the Australiana index to Banfield's author entry and its genuine text link for *My Tropic Isle*. The 1911 title page, a Queensland writing career, the book's natural-history contents and the author's death in 1923 support the record. The adapter can be extended with other evidenced works. [Australiana](https://gutenberg.net.au/pgaus.html) · [Australian Dictionary of Biography](https://adb.anu.edu.au/biography/banfield-edmund-james-56) · [Archive licence](https://gutenberg.net.au/licence.html)
- **Faded Page.** The public book index and the record for Graeme Mercer Adam's *The Canadian North-west* were accessible. Its linked TXT download returned the record page during the automated check. The work stays in review. Its date and literary association have an independent Canadian source. Metadata marked `no-store` is parsed in memory. [Book record](https://www.fadedpage.com/showbook.php?pid=20121201) · [Dictionary of Canadian Biography](https://www.biographi.ca/en/bio/adam_graeme_mercer_14E.html) · [Canadian rights policy](https://www.fadedpage.com/copyright.php)
- **New Zealand sources.** Te Ara and National Library records supplement dates and literary affiliations for works found in Gutenberg. DigitalNZ provides discovery metadata subject to its API terms. Its developer landing page returned an empty HTTP 202 to the local probe. NZETC moved into the National Library web archive in 2024, with noncommercial and item-specific terms. Neither supplies automatic full-text downloads here. [Te Ara](https://teara.govt.nz/en) · [DigitalNZ API](https://digitalnz.org/developers/getting-started) · [API terms](https://digitalnz.org/about/terms-of-use/developer-api-terms-of-use) · [NZETC collection conditions](https://natlib.govt.nz/a-z/new-zealand-electronic-text-collection-nzetc)

## From catalogue to eligible work

1. Join catalogue identifiers, author identities and work titles to the frozen factual crosswalk in `manifests/`. Enrichment uses Wikidata work-publication, original-language and author evidence, supplemented by regional bibliographies. Discovery still reads the live or cached archive catalogue. The generated candidates CSV retains the catalogue subjects, classification rule and references for review. [Wikidata data access](https://www.wikidata.org/wiki/Wikidata:Data_access)
2. Use historical work publication for the date window. The PG ebook release date is stored separately. The automatic match requires a work-level entity with one distinct recorded publication year and creator, an English original, and matching Gutenberg title and author evidence. The authority record can miss an earlier serial or printing. Independently researched bibliographies and editorial corrections take precedence. A record with a single identifiable print imprint can provide an edition year. For other records, the version basis is the matched original-English work, item transcription and credited text contributors. The pipeline leaves an unverified edition year empty. The default rule for letters and diaries requires eligible historical publication. Composition dates alone do not admit unpublished or later edited material.
3. Use evidenced professional or literary affiliation, or an unambiguous recorded author citizenship. A regional bibliography can resolve a colonial citizenship label. The automated Gutenberg route uses identified authors. For a manually reviewed anonymous official document, attribute the work to the jurisdiction of the issuing institution. The local route uses `document_type=anonymous_official`, a named `issuing_institution`, matching `issuer_region`, an `issuer_evidence_url` and an item-specific CC0 dedication covering the whole text (`rights_scope=issuer_cc0_complete_text`). Other anonymous cases remain in review. Translations need translator identity, evidence for the English version and a qualifying date. Unresolved contributor records require review. A translation retains the evidenced principal author's regional attribution.
4. Give each work one primary topic, with source subjects and secondary matches retained. The rules use bibliographic form, subject headings and Library of Congress class. Fiction headings resolve fictional diaries and historical novels. Example nonfiction signals include personal narratives, technical manuals, voyages, and scientific classes. A historical setting alone supplies no history classification. The public provenance table makes these decisions inspectable by title.
5. Screen the archive's item rights statement separately from the UK use decision. The usual UK term for written works is 70 years after the author's death. The pipeline also checks publication, language, the credited text contributors, version evidence and source restrictions. The default PG path requires a single matched creator, an item-specific US statement and no unresolved added text contributors. The resulting eligibility flag describes this project's evidence screen. Special rights, anonymous works, unknown contributors, modern editorial matter and disputed editions can require further review. Source texts retain their individual rights status. [GOV.UK duration guidance](https://www.gov.uk/copyright/how-long-copyright-lasts) · [Gutenberg terms](https://www.gutenberg.org/policy/permission.html)

The reviewed release ships the factual work crosswalk so routine builds need no live Wikidata query. The SPARQL queries and input SHA-256 values are in [manifests](manifests/). To regenerate the match table from the original retained snapshots, run the following command. To refresh from Wikidata deliberately, add `--download --evidence-dir data/raw/evidence-refresh` to use a new snapshot directory. Preserve the prior crosswalk with Git when versioning a refresh.

```console
uv run python -m llm_v2_dataset.crosswalk data/raw/catalogue/66847ed72335833379699bd2c3d0ae1c1180521c43d405a7ab9b28e28e1afd8e.csv.gz
```

## Cleaning and partitioning

Decoding is strict. The cleaner normalizes Unicode to NFC, line endings to LF and form feeds to paragraph breaks. It removes bounded archive wrappers and recognized modern production notes. It preserves spelling, case, punctuation, paragraphs and hard-wrapped lines. HTML imports retain body text and structural breaks and require reviewed bounds. Broken decoding, uncertain notes and suspicious editorial credits go to review. Illustrations are absent from plain text. Transcription and undetected editorial differences remain possible.

Deduplication considers matching cleaned SHA-256 values, known work or alternate-edition groups and sampled eight-word passages starting at “the”. It checks containment against the smaller fingerprint set, requiring at least 12 fingerprints and 80% overlap. One representative survives a cluster. Short extracts, heavy OCR changes, paraphrases and translated overlap can escape detection.

Selection uses whole documents and actual character lengths. A seeded greedy pass scores both topic and regional deficits, then bounded additions, removals and swaps improve the size and composition errors. Configuration defaults are 49–51 million characters, two percentage points of tolerance per margin, and seed 42. There are no topic-by-region cell quotas or decade quotas. Author breadth breaks comparable choices.

The splitter joins connected work, duplicate and known principal-author groups, then assigns whole groups against 90/5/5 character targets, with a smaller preference for similar composition. Unknown authors have independent document identities. The allocation is frozen inside each version. The input fingerprint includes the configuration, applied pool, manifests and code. Repeating an offline build regenerates the core files and compares them byte for byte. Preserving the original source cache and code version is necessary to reproduce that exact ID. Fresh downloads carry new retrieval timestamps and may contain revisions. A fresh checkout may also investigate different works because acquisition resumes from any eligible material already retained in the local pool. The published provenance CSV identifies the exact release selection.

## Curate or extend a build

Inspect `data/candidates.csv` for source facts, then `audit.csv` in the current build for the final selection reason. Edit `manifests/overrides.csv` by stable `document_id`. Use `auto`, `exclude` or `include`. Nonblank columns correct specific fields. Additional corrections go in the `corrections_json` object, using normal CSV quoting. For a corrected region, enter the region, explicitly supply its evidence URL and describe the affiliation in `region_basis`. For a corrected topic, give `primary_topic` and `classification_rule`. Exclusions take precedence and requested inclusions still pass eligibility, extraction and deduplication. Each build reports rejected inclusions and unknown override IDs.

To add a locally obtained source, place the original file in `data/imports/` and add a UTF-8 row to `data/imports/sources.csv`. Supply a unique ID, the relative `local_file`, source and download references, title, authors, group IDs, language, work date, region, topic, contributor and rights evidence. The required evidence fields are listed in [evidence.py](src/llm_v2_dataset/evidence.py). State the media type, encoding and reviewed start/end lines where appropriate. Re-run `discover` and `fetch`, then `build --offline`. To change decisions on already downloaded materials, `build --offline` suffices.

Git tracks the frozen training release under `data/releases/` alongside the code, factual provenance and reports. Raw downloads, the preparation cache, intermediate builds, local imports and credentials stay local. The source texts retain their individual rights status.
