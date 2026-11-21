"""Selective regional discovery. Bibliographies identify works; catalogue links locate files."""

import json
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin

AU = "https://gutenberg.net.au/pgaus.html"
CA = "https://www.fadedpage.com/allbooks.php"
BANFIELD = "https://adb.anu.edu.au/biography/banfield-edmund-james-56"
ADAM = "https://www.biographi.ca/en/bio/adam_graeme_mercer_14E.html"


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.href = ""
        self.label = []
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href", "")
            self.label = []

    def handle_data(self, data):
        if self.href:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((" ".join("".join(self.label).split()), self.href))
            self.href = ""


def page(url, config):
    from .sources import read_metadata

    return read_metadata(url, config, max_bytes=12_000_000).decode("utf-8", "replace")


def australian(config):
    catalogue = Links(page(AU, config)).links
    record = urljoin(AU, next(link for label, link in catalogue if label.lower() == "my tropic isle"))
    index, section = urldefrag(record)
    html = page(index, config)
    start = html.index(f'id="{section}"')
    entry = next(part for part in re.findall(r"<li\b[^>]*>(.*?)</li>", html[start:], re.I | re.S)
                 if re.match(r"\s*My Tropic Isle--", part, re.I))
    text_url = urljoin(index, next(link for label, link in Links(entry).links if label == "Text"))
    return dict(
        document_id="pga-e00004", source="Project Gutenberg Australia", source_id="e00004",
        title="My Tropic Isle", authors="Edmund James Banfield", author_group_id="Q583409",
        work_group_id="banfield-my-tropic-isle", region="AU", region_evidence_url=BANFIELD,
        region_basis="Spent his writing career in Queensland, including the work's original newspaper articles.",
        work_year="1911", edition_year="1911", date_basis="First book publication in the Australian Dictionary of Biography.",
        date_evidence_url=BANFIELD, version_basis="The retained title page credits Banfield and T. Fisher Unwin, 1911.",
        version_evidence_url=text_url, language="en", original_language="en", language_evidence_url=text_url,
        primary_topic="science_natural_history", classification_rule="ADB naturalist biography and title-page contents on island species.",
        subjects="Queensland; natural history; island life", document_type="natural history",
        rights_statement="Australian public-domain archive policy; item carries no separate copyrighted-item notice.",
        jurisdiction="Australia", rights_evidence_url="https://gutenberg.net.au/licence.html",
        rights_basis="Lifetime book publication in 1911. Named sole writer died in 1923. Historical prose only, photographs omitted.",
        uk_rights_evidence_url="https://www.gov.uk/copyright/how-long-copyright-lasts",
        contributor_death_year="1923", contributor_basis="Banfield on the original title page and ADB biography.",
        contributor_evidence_url=BANFIELD, evidence_review="verified", first_publication_status="published",
        source_record_url=record, download_url=text_url, media_type="text/plain", encoding="cp1252",
        extraction_start="MY TROPIC ISLE", extraction_end="Project Gutenberg Australia",
    )


def canadian(config):
    catalogue = Links(page(CA, config)).links
    title, href = next((label, link) for label, link in catalogue if label.startswith("The Canadian North-west:"))
    record = urljoin(CA, href)
    html = page(record, config)
    label, link = next((label, href) for label, href in Links(html).links if label.endswith(".txt"))
    if "public domain in Canada" not in html:
        raise ValueError("Canadian rights statement changed")
    return dict(
        document_id="fp-" + label[:-4], source="Faded Page", source_id=label[:-4], title=unescape(title),
        authors="Graeme Mercer Adam", author_group_id="Q5592341", work_year="1885", region="CA",
        work_group_id="adam-canadian-north-west", region_evidence_url=ADAM, date_evidence_url=ADAM,
        date_basis="The Dictionary of Canadian Biography dates the work to 1885.",
        region_basis="Written during Adam's Canadian publishing career.", primary_topic="history",
        classification_rule="Record lists history among the subject tags.",
        rights_statement="Public domain in Canada", jurisdiction="Canada", rights_evidence_url=record,
        source_record_url=record, download_url=urljoin(record, link), evidence_review="review",
        acquisition_note="Linked TXT returned the record HTML on the direct automated request. Edition and text boundaries unresolved.",
    )


def discover(config):
    rows, status = [], {}
    for name, adapter in (("Project Gutenberg Australia", australian), ("Faded Page", canadian)):
        try:
            row = adapter(config)
            rows.append(row)
            status[name] = {"status": "discovered", "detail": row.get("acquisition_note", "Resolved author's catalogue entry and text link.")}
        except (OSError, ValueError, StopIteration, RuntimeError) as exc:
            status[name] = {"status": "unavailable", "detail": str(exc) or "Expected catalogue link missing"}
    status["DigitalNZ"] = {"status": "discovery only", "detail": "Developer landing page returned an empty 202 response in the access check. No API integration."}
    status["NZETC"] = {"status": "unavailable for automatic use", "detail": "Web archive collection with item-specific permissions. No eligible text route verified."}
    Path("data").mkdir(exist_ok=True)
    Path("data/regional_status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    return rows
