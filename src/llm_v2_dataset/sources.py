"""Bounded acquisition of catalogue evidence and immutable UTF-8 source files."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.robotparser import RobotFileParser


PG = "Project Gutenberg"
MIRROR = "https://gutenberg.pglaf.org/"
GENERATED = MIRROR + "cache/epub/"
CATALOGUE = GENERATED + "feeds/pg_catalog.csv.gz"
UK_MAIN = "https://www.mirrorservice.org/sites/ftp.ibiblio.org/pub/docs/books/gutenberg/"
DATA = Path("data")
RAW = DATA / "raw"
_lock = threading.Lock()
_last_request = {}
_backoff = {}
REGIONAL_HOSTS = {"gutenberg.net.au", "www.gutenberg.net.au", "fadedpage.com", "www.fadedpage.com"}
HOSTS = REGIONAL_HOSTS | {"gutenberg.pglaf.org", "www.mirrorservice.org"}


def _settings(config):
    return config.get("sources", {})


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        # Windows readers and antivirus scanners can briefly hold the old
        # manifest open. Keep the previous checkpoint intact until replacement.
        for attempt in range(9):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 8:
                    raise
                time.sleep(.15 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def _json(path, obj):
    _atomic(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode())


def record_status(source, status, detail):
    path = DATA / "source_status.json"
    with _lock:
        statuses = json.loads(path.read_text("utf-8")) if path.exists() else {}
        statuses[source] = {"status": status, "detail": detail}
        _json(path, statuses)


def _error(row, exc):
    path = DATA / "acquisition_errors.jsonl"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps({"at": _utc(), "id": row.get("document_id", ""),
                                     "source": row["source"], "error": str(exc)}) + "\n")


def _check_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password:
        raise ValueError("source origin is outside the verified HTTPS routes")
    if parsed.port not in (None, 443) or parsed.fragment:
        raise ValueError("unexpected port or fragment in source URL")
    if any(key.lower() not in {"id", "book","author","pid"} for key, _ in urllib.parse.parse_qsl(parsed.query)):
        raise ValueError("unexpected query parameter in source URL")
    return parsed


def _agent():
    email = os.environ.get("CONTACT_EMAIL", "").strip()
    return "llm_v2_dataset/0.1" + (f" (+mailto:{email})" if email else "")


def _pace(host, delay):
    with _lock:
        if time.monotonic() < _backoff.get(host, 0):
            raise OSError(f"{host} requested a retry delay")
        start = max(time.monotonic(), _last_request.get(host, 0) + delay)
        _last_request[host] = start
    time.sleep(max(0., start - time.monotonic()))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


@lru_cache(maxsize=12)
def _robot_policy(host):
    url = "https://" + host + "/robots.txt"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _agent()})
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=20) as response:
            payload = response.read(512001)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise OSError(f"unable to verify {host} robots policy (HTTP {exc.code})") from exc
    if len(payload) > 512000:
        raise OSError(f"overlong robots policy for {host}")
    if payload.lstrip().lower().startswith(b"<"):
        raise OSError(f"unexpected HTML response to {host} robots request")
    policy = RobotFileParser()
    policy.parse(payload.decode("utf-8-sig", "replace").splitlines())
    return policy


def _download(url, config, max_bytes):
    settings = _settings(config)
    timeout = settings.get("timeout_seconds", 45)
    opener = urllib.request.build_opener(_NoRedirect)
    for redirect in range(4):
        parsed = _check_url(url)
        host = parsed.hostname
        policy = _robot_policy(host)
        delay = max(.25, settings.get("delay_seconds", .5))
        if policy:
            if not policy.can_fetch("llm_v2_dataset", url):
                raise ValueError(f"disallowed by {host} robots policy")
            delay = max(delay, policy.crawl_delay("llm_v2_dataset") or 0)
        for attempt in range(2):
            _pace(host, delay)
            request = urllib.request.Request(url, headers={"User-Agent": _agent()})
            try:
                with opener.open(request, timeout=timeout) as response:
                    size = int(response.headers.get("Content-Length") or 0)
                    if size > max_bytes:
                        raise ValueError("response exceeds configured size limit")
                    data = response.read(max_bytes + 1)
                    if len(data) > max_bytes or (size and size != len(data)) or not data:
                        raise ValueError("incomplete, empty or oversized response")
                    reusable = "no-store" not in response.headers.get("Cache-Control", "").lower()
                    return data, url, reusable
            except urllib.error.HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308}:
                    url = urllib.parse.urljoin(url, exc.headers["Location"])
                    if _check_url(url).hostname.removeprefix("www.") != host.removeprefix("www."):
                        raise ValueError("redirect to a different archive") from exc
                    break
                if exc.code in {429, 503}:
                    header = exc.headers.get("Retry-After", "60")
                    wait = int(header) if header.isdigit() else 3600
                    with _lock:
                        _backoff[host] = time.monotonic() + max(1, wait)
                if exc.code not in {500, 502, 504} or attempt:
                    raise
            except (TimeoutError, urllib.error.URLError, ConnectionError):
                if attempt:
                    raise
            time.sleep(2)
    raise ValueError("too many redirects")


def _index(url):
    return RAW / "requests" / (_sha(url.encode()) + ".json")


def _retain(data, url, category, suffix, *, resolved=None, timestamp=None):
    digest = _sha(data)
    if not re.fullmatch(r"[a-z_]+", category) or not re.fullmatch(r"(?:\.[a-z0-9]+){1,3}", suffix):
        raise ValueError("invalid archive cache name")
    path = RAW / category / (digest + suffix)
    if path.exists() and _sha(path.read_bytes()) != digest:
        raise ValueError(f"raw object failed its recorded hash: {path}")
    if not path.exists():
        _atomic(path, data)
    record = {"raw_path": path.as_posix(), "raw_sha256": digest, "retrieved_at": timestamp or _utc(),
              "download_url": resolved or url, "requested_url": url}
    _json(_index(url), record)
    return record


def acquire(url, config, *, category="metadata", suffix=".html", max_bytes=4_000_000):
    """Use a previously verified response or fetch it once. Incomplete files never enter the index."""
    _check_url(url)
    index = _index(url)
    if index.exists():
        record = json.loads(index.read_text("utf-8"))
        path = Path(record["raw_path"])
        if not path.resolve().is_relative_to(RAW.resolve()) or _sha(path.read_bytes()) != record["raw_sha256"]:
            raise ValueError(f"corrupt raw cache for {url}")
        return record
    data, resolved, reusable = _download(url, config, max_bytes)
    if not reusable:
        raise ValueError("archive response forbids caching")
    return _retain(data, url, category, suffix, resolved=resolved)


def read_metadata(url, config, *, max_bytes=4_000_000):
    """Read discovery HTML, keeping no-store responses exclusively in memory."""
    if _index(url).exists():
        record = acquire(url, config, max_bytes=max_bytes)
        return Path(record["raw_path"]).read_bytes()
    data, resolved, reusable = _download(url, config, max_bytes)
    if reusable:
        _retain(data, url, "metadata", ".html", resolved=resolved)
    return data


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs).get("href", ""))


def _index_links(url, config):
    record = acquire(url, config)
    parser = _Links()
    parser.feed(Path(record["raw_path"]).read_text("utf-8"))
    return parser.links


def _catalogue(config):
    record = acquire(CATALOGUE, config, category="catalogue", suffix=".csv.gz", max_bytes=15_000_000)
    rows = []
    with gzip.open(record["raw_path"], "rt", encoding="utf-8-sig", newline="") as handle:
        for item in csv.DictReader(handle):
            if item["Type"] != "Text" or item["Language"] != "en":
                continue
            number = item["Text#"]
            rows.append({"document_id": "pg-" + number, "source": PG, "source_id": number,
                         "source_record_url": "https://www.gutenberg.org/ebooks/" + number,
                         "title": item["Title"], "authors": item["Authors"], "language": "en",
                         "subjects": item["Subjects"], "locc": item["LoCC"], "bookshelves": item["Bookshelves"],
                         "ebook_release": item["Issued"], "catalogue_sha256": record["raw_sha256"],
                         "catalogue_path": record["raw_path"], "catalogue_url": CATALOGUE})
    return rows


def pool_path(max_documents=None):
    return DATA / ("candidates.csv" if max_documents is None else f"candidates-trial-{max_documents}.csv")


def read_pool(max_documents=None):
    with pool_path(max_documents).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _save_pool(rows, limit):
    import io
    buffer = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row)) or ["document_id"]
    writer = csv.DictWriter(buffer, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _atomic(pool_path(limit), buffer.getvalue().encode())


def discover(config, *, max_documents=None):
    from . import evidence, overrides
    rows = []
    previous = {r["document_id"]: r for r in read_pool(max_documents)} if pool_path(max_documents).exists() else {}
    try:
        catalogue = _catalogue(config)
        rows.extend(evidence.enrich(catalogue, config))
        included = {r["document_id"] for r in rows}
        requested = {r["document_id"].strip() for r in overrides.read_rows("manifests/overrides.csv")}
        extra_ids = requested - included
        for item in catalogue:
            if item["document_id"] in extra_ids:
                topic, rule, tags = evidence.topic(item)
                item.update(primary_topic=topic, classification_rule=rule, secondary_tags=tags,
                            eligibility_status="review", eligibility_reason="manually nominated; evidence required")
                rows.append(item)
        active_ids = {r["document_id"] for r in rows}
        for old in previous.values():
            if old["source"] != PG or old["document_id"] in active_ids or not (old.get("raw_path") or old.get("rdf_path")):
                continue
            reason = "Previously acquired or inspected item no longer matches the current bibliographic evidence"
            rows.append({**old, "retired_evidence": "yes", "evidence_conflict": reason,
                         "evidence_review": "review", "eligibility_status": "review", "eligibility_reason": reason})
        record_status(PG, "catalogue available", f"{len(catalogue)} English text catalogue records, {len(active_ids)} active evidence candidates")
    except (OSError, ValueError, KeyError) as exc:
        record_status(PG, "discovery unavailable", str(exc))
        _error({"source": PG}, exc)
        if pool_path(max_documents).exists():
            rows.extend(row for row in read_pool(max_documents) if row.get("source") == PG)
    if _settings(config).get("regional", True):
        from . import regional
        rows.extend(regional.discover(config))
    imports = DATA / "imports" / "sources.csv"
    if imports.exists():
        with imports.open(encoding="utf-8-sig", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    ids = [row["document_id"] for row in rows]
    if any(not key for key in ids) or len(ids) != len(set(ids)):
        raise ValueError("empty or duplicate document ID in discovery and imports")
    # Restore only archive facts. New evidence and manual decisions must be
    # evaluated afresh even when the cached transcription is unchanged.
    for row in rows:
        old = previous.get(row["document_id"])
        if not old or row.get("retired_evidence") or row.get("local_file") or row.get("source_record_url") != old.get("source_record_url"):
            continue
        if row["source"] == PG and old.get("rdf_path") and row.get("catalogue_sha256") == old.get("catalogue_sha256"):
            _rdf(row, config)
            row.update(evidence.assess(row, config))
        if old.get("raw_path") and (row["source"] == PG or row.get("download_url") == old.get("requested_url")):
            for key in ("raw_path", "raw_sha256", "retrieved_at", "download_url", "requested_url", "media_type", "encoding"):
                if old.get(key):
                    row[key] = old[key]
    _save_pool(rows, max_documents)
    return rows


NS = {"dc": "http://purl.org/dc/terms/", "pg": "http://www.gutenberg.org/2009/pgterms/",
      "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"}
ABOUT = "{" + NS["rdf"] + "}about"


def _rdf(row, config):
    number = str(row["source_id"])
    if not number.isdigit():
        raise ValueError("invalid catalogue number")
    # Per-ebook RDF access is documented in PG's Offline Catalogs and Feeds guide.
    directory = GENERATED + number + "/"
    url = directory + "pg" + number + ".rdf"
    file = acquire(url, config, suffix=".rdf")
    tree = ET.parse(file["raw_path"])
    book = tree.find("pg:ebook", NS)
    if book is None or book.get(ABOUT) != f"ebooks/{number}":
        raise ValueError("RDF and catalogue book IDs differ")
    creators = book.findall("dc:creator/pg:agent", NS)
    contributors = []
    for field in book:
        agent = field.find("pg:agent", NS)
        role = field.tag.split("}")[-1]
        if agent is not None and role != "creator":
            contributors.append({"role": role, "name": agent.findtext("pg:name", "", NS),
                                 "death": agent.findtext("pg:deathdate", "", NS),
                                 "id": agent.get(ABOUT, "").rsplit("/", 1)[-1]})
    row.update(pg_creator_count=str(len(creators)), pg_contributors=json.dumps(contributors) if contributors else "",
               pg_author_id=creators[0].get(ABOUT, "").split("/")[-1] if len(creators)==1 else "",
               pg_author_death=creators[0].findtext("pg:deathdate","", NS) if len(creators)==1 else "",
               pg_author_name=creators[0].findtext("pg:name", "", NS) if len(creators)==1 else "",
               rights_statement=book.findtext("dc:rights", "", NS), jurisdiction="US", rights_evidence_url=url,
               rdf_url=url, rdf_path=file["raw_path"], rdf_sha256=file["raw_sha256"],
               pg_imprint=book.findtext("pg:marc260", "", NS) or book.findtext("pg:marc264", "", NS),
               pg_credit=book.findtext("pg:marc508", "", NS),
               language_evidence_url=url)
    descriptions = " ".join(el.text or "" for el in book.findall("dc:description", NS))
    row["work_alt_ids"] = "|".join(re.findall(r"also available as (?:eBook|ebook)\s*#(\d+)", descriptions, re.I))
    row["rdf_title"] = book.findtext("dc:title", "", NS)
    row["rdf_languages"] = "|".join(el.text or "" for el in book.findall("dc:language//rdf:value", NS))
    links = []
    for item in book.findall("dc:hasFormat/pg:file", NS):
        ref = item.get(ABOUT, "")
        fmt = " ".join(el.text or "" for el in item.findall("dc:format//rdf:value", NS)).lower()
        parsed = urllib.parse.urlsplit(ref)
        if parsed.hostname != "www.gutenberg.org" or "text/plain" not in fmt:
            continue
        prefix = f"/files/{number}/"
        if parsed.path.startswith(prefix) and parsed.path.endswith(".txt"):
            filename = parsed.path[len(prefix):]
            if re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
                directory_digits = "/".join(number[:-1]) or "0"
                charset = re.search(r"charset\s*=\s*([\w-]+)", fmt)
                encoding = charset[1] if charset else ""
                if encoding in {"utf-8","us-ascii","iso-8859-1"}:
                    links.append((encoding != "utf-8", UK_MAIN + directory_digits + "/" + number + "/" + filename,
                                  encoding))
    chosen = min(links) if links else (True, "", "utf-8")
    row["mirror_text_url"], row["mirror_encoding"] = chosen[1:]
    return row


def _pg_text(row, config):
    max_bytes = _settings(config).get("max_document_bytes", 14_000_000)
    url = row.get("mirror_text_url")
    if url:
        try:
            return acquire(url, config, category="books", suffix=".txt", max_bytes=max_bytes)
        except urllib.error.HTTPError as exc:
            if exc.code not in {404,410}:
                raise
    directory = GENERATED + str(row["source_id"]) + "/"
    available = set(_index_links(directory, config))
    stem = "pg" + str(row["source_id"])
    for name, suffix in [(stem + ".txt", ".txt"), (stem + ".txt.utf8", ".txt"),
                         (stem + "-images.html", ".html")]:
        if name in available:
            return acquire(directory + name, config, category="books", suffix=suffix, max_bytes=max_bytes)
    raise ValueError("no linked plain text or generated HTML in the mirror directory")


def _local_text(row, config):
    folder = DATA / "imports"
    path = (folder / row["local_file"]).resolve()
    if not path.is_relative_to(folder.resolve()) or path.suffix.lower() not in {".txt",".html",".htm"}:
        raise ValueError("import must be TXT or HTML inside data/imports")
    if path.stat().st_size > _settings(config).get("max_document_bytes", 14_000_000):
        raise ValueError("import exceeds configured file size")
    if not row.get("download_url") or not row.get("source_record_url"):
        raise ValueError("local import requires original source and download URLs")
    for key in ("download_url","source_record_url"):
        parsed = urllib.parse.urlsplit(row[key])
        query_keys = [k.lower() for k, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)]
        if (parsed.scheme not in {"https","http"} or not parsed.hostname or parsed.username or parsed.password
                or any(re.search(r"token|secret|password|signat|credential|api.?key|^x-amz", k) for k in query_keys)):
            raise ValueError("local import provenance must use a public credential-free URL")
    return _retain(path.read_bytes(), row["download_url"], "books", path.suffix.lower())


def fetch(config, rows, *, max_documents=None):
    """Resolve bounded candidate waves, then measure acquired supply against both margins."""
    from . import evidence, overrides
    cap = max_documents or _settings(config).get("max_documents", 320)
    candidates = [dict(row) for row in rows]
    corrected = {row["document_id"]: row for row in overrides.apply(candidates, config)}
    queue = [row for row in candidates
               if corrected[row["document_id"]].get("decision") != "exclude"
               and not row.get("retired_evidence")
               and (corrected[row["document_id"]].get("primary_topic") in config["topics"]
                    or corrected[row["document_id"]].get("decision") == "include")]
    queue.sort(key=lambda row: row["document_id"])
    totals = Counter()
    fetched = 0
    attempts = 0
    bound = _settings(config).get("max_candidates", 1200)
    if max_documents is not None:
        bound = min(bound, max(12, max_documents * 5))
    pending = []
    for row in queue:
        planned = corrected[row["document_id"]]
        if not row.get("raw_path") or row.get("local_file") or planned.get("eligibility_status") != "eligible":
            pending.append(row)
            continue
        path = Path(row["raw_path"])
        if not path.resolve().is_relative_to(RAW.resolve()) or _sha(path.read_bytes()) != row["raw_sha256"]:
            raise ValueError(f"{row['document_id']} retained raw file changed")
        fetched += 1
        for key in ("primary_topic","region"):
            totals[planned[key]] += path.stat().st_size

    def priority(row, projected):
        candidate = corrected[row["document_id"]]
        topic, region = candidate.get("primary_topic",""), candidate.get("region","")
        # Percentage of each desired marginal supply already present. Order ties by document ID.
        topic_ratio = projected[topic] / config["topics"].get(topic, .001)
        region_ratio = projected[region] / config["regions"].get(region, .001)
        return (candidate.get("decision") != "include",
                candidate.get("eligibility_status") != "eligible" and row["source"] != PG,
                topic_ratio + region_ratio, row["document_id"])

    def process(row):
        try:
            if row["source"] == PG and not row.get("local_file"):
                _rdf(row, config)
                row.update(evidence.assess(row, config))
            planned = overrides.apply([row], config)[0]
            if planned.get("eligibility_status") != "eligible":
                return 0
            if row.get("local_file"):
                result = _local_text(planned, config)
            elif row["source"] == PG:
                result = _pg_text(planned, config)
                encoding = planned.get("mirror_encoding", "utf-8") if result["download_url"] == planned.get("mirror_text_url") else "utf-8"
                media = "text/html" if result["raw_path"].endswith(".html") else "text/plain"
                row.update(media_type=media, encoding=encoding)
            else:
                suffix = ".html" if "html" in planned.get("media_type", "") else ".txt"
                result = acquire(planned["download_url"], config, category="books", suffix=suffix,
                                 max_bytes=_settings(config).get("max_document_bytes", 14_000_000))
            row.update(result)
            row.pop("acquisition_error", None)
            return Path(result["raw_path"]).stat().st_size
        except (ValueError, OSError, ET.ParseError) as exc:
            row["acquisition_error"] = str(exc)
            _error(row, exc)
            return 0

    workers = max(1, min(5, int(_settings(config).get("workers", 4))))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while pending and attempts < bound:
            slots = cap - fetched
            if slots <= 0:
                # A specific new inclusion can be investigated even when the
                # automatic pool is full. Bounded trials retain their hard cap.
                if max_documents is not None:
                    break
                pending = [r for r in pending if corrected[r["document_id"]].get("decision") == "include"]
                if not pending:
                    break
                slots = len(pending)
            count = min(len(pending), slots, workers * 2, bound - attempts)
            projected = totals.copy()
            batch = []
            for _ in range(count):
                index = min(range(len(pending)), key=lambda n: priority(pending[n], projected))
                row = pending.pop(index)
                batch.append(row)
                effective = corrected[row["document_id"]]
                # Within a concurrent wave book sizes are not known yet.
                # A provisional weight diversifies requests until exact sizes arrive.
                for key in ("primary_topic", "region"):
                    projected[effective.get(key)] += 350_000
            for row, size in zip(batch, executor.map(process, batch)):
                attempts += 1
                if size:
                    fetched += 1
                    effective = corrected[row["document_id"]]
                    totals[effective.get("primary_topic")] += size
                    totals[effective.get("region")] += size
            try:
                _save_pool(candidates, max_documents)
            except PermissionError:
                # Another process can keep a CSV open without delete sharing
                # on Windows. Receipts checkpoint every response independently.
                print("Candidate CSV temporarily locked; retained the previous checkpoint.", flush=True)
            print(f"Acquired {fetched}/{cap} documents after {attempts} candidate checks", flush=True)
    _save_pool(candidates, max_documents)
    pg = [r for r in candidates if r["source"] == PG]
    if pg:
        acquired = sum(bool(r.get("raw_path")) for r in pg)
        retired = sum(bool(r.get("retired_evidence")) for r in pg)
        errors = sum(bool(r.get("acquisition_error")) for r in pg)
        record_status(PG, "working" if acquired else "metadata only",
                      f"{len(pg) - retired} active candidates, {retired} retained for historical evidence review, "
                      f"{acquired} raw documents, {errors} item access errors.")
    return candidates
