"""Clean a retained pool, choose whole works, and freeze a reproducible build."""

import csv
import hashlib
import json
import re
import tempfile
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path

from .clean import CLEANING_VERSION, CleanError, extract

SEPARATOR = "\n\n"
PARTITIONS = ("train", "validation", "test")
_SHINGLE = re.compile(r"\bthe\b(?:[^\w]+[^\W_]+){7}", re.I)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _csv(path, rows, first):
    fields = list(first) + sorted({k for row in rows for k in row} - set(first))
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _save_clean(path, payload):
    if path.exists():
        if file_hash(path) != path.stem:
            raise ValueError(f"existing cleaned text hash mismatch: {path}")
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        name = Path(temp.name)
        try:
            temp.write(payload)
        finally:
            temp.close()
    try:
        name.replace(path)
    finally:
        name.unlink(missing_ok=True)


def _anchors(text):
    # Identical passages contribute the same fingerprints even after a change
    # in pagination. Hash sampling limits memory without a per-document cap.
    found = set()
    for match in _SHINGLE.finditer(text):
        words = " ".join(re.findall(r"\w+", match[0].casefold())).encode()
        key = hashlib.blake2b(words, digest_size=8).digest()
        if key[0] % 16 == 0:
            found.add(key)
    return found


class Groups:
    def __init__(self, ids):
        self.parents = {key: key for key in ids}

    def root(self, key):
        while self.parents[key] != key:
            self.parents[key] = self.parents[self.parents[key]]
            key = self.parents[key]
        return key

    def join(self, a, b):
        left, right = sorted((self.root(a), self.root(b)))
        self.parents[right] = left


def _normalize_groups(row):
    principal = (row.get("principal_author") or row.get("authors") or "").split(";")[0].strip().casefold()
    if not row.get("author_group_id") and principal not in {"", "anonymous", "unknown", "various", "anon."}:
        row["author_group_id"] = "name-" + digest(principal.encode())[:20]
    if not row.get("work_group_id"):
        title = " ".join(re.findall(r"\w+", row["title"].casefold()))
        author = row.get("author_group_id") or row["document_id"]
        row["work_group_id"] = "title-" + digest(canonical([author, title]).encode())[:20]


def _prepare(rows, scope_end):
    clean_dir = Path("data/clean")
    clean_dir.mkdir(parents=True, exist_ok=True)
    pool, fingerprints = {}, {}
    for row in rows:
        key = row["document_id"]
        if row.get("raw_path"):
            raw = Path(row["raw_path"])
            if not raw.resolve().is_relative_to(Path("data/raw").resolve()):
                raise ValueError(f"{key}: raw path outside data/raw")
            if not raw.is_file() or file_hash(raw) != row.get("raw_sha256"):
                raise ValueError(f"{key}: missing raw file or raw SHA-256 mismatch")
        if row.get("decision") == "exclude":
            row.update(selection_status="excluded", selection_reason="manual exclusion")
        elif row.get("eligibility_status") != "eligible":
            reason = row.get("eligibility_reason") or row.get("review_reason") or row.get("reason") or "eligibility evidence incomplete"
            row.update(selection_status="review", selection_reason=reason)
        elif not row.get("raw_path"):
            row.update(selection_status="unavailable", selection_reason=row.get("acquisition_error") or "eligible text has not been acquired")
        else:
            row["scope_end_year"] = scope_end
            try:
                cleaned = extract(row, raw.read_bytes())
            except CleanError as exc:
                row.update(selection_status="review", selection_reason=str(exc))
            else:
                payload = cleaned.text.encode("utf-8")
                sha = digest(payload)
                path = clean_dir / (sha + ".txt")
                _save_clean(path, payload)
                row.update(clean_path=path.as_posix(), clean_sha256=sha, char_count=len(cleaned.text),
                           decoded_source_chars=cleaned.before_chars, extraction_notes=cleaned.notes,
                           selection_status="available", selection_reason="available after cleaning")
                _normalize_groups(row)
                pool[key] = row
                fingerprints[key] = _anchors(cleaned.text)
        if row.get("decision") == "include" and key not in pool:
            row["selection_reason"] = "requested inclusion rejected: " + row["selection_reason"]
    return pool, fingerprints


def _deduplicate(pool, fingerprints):
    groups = Groups(pool)
    seen, inverted = {}, defaultdict(list)
    reasons = defaultdict(set)
    for key, row in pool.items():
        if key.startswith("pg-"):
            for alternate in re.findall(r"\d+", row.get("work_alt_ids") or ""):
                other = f"pg-{alternate}"
                if other in pool and other != key:
                    groups.join(key, other)
                    reasons[key].add("Gutenberg alternate edition")
                    reasons[other].add("Gutenberg alternate edition")
        for field in ("work_group_id", "duplicate_group_id", "clean_sha256"):
            value = row.get(field)
            if value:
                token = field, value
                if token in seen:
                    other = seen[token]
                    groups.join(key, other)
                    reasons[key].add(field)
                    reasons[other].add(field)
                seen[token] = key
        fp = fingerprints[key]
        matches = Counter(other for token in fp for other in inverted[token])
        for other, count in matches.items():
            smaller = min(len(fp), len(fingerprints[other]))
            if smaller >= 12 and count >= 0.8 * smaller:
                groups.join(key, other)
                reasons[key].add("sampled passage containment")
                reasons[other].add("sampled passage containment")
        for token in fp:
            inverted[token].append(key)
    clusters = defaultdict(list)
    for key in pool:
        clusters[groups.root(key)].append(key)
    unique = []
    for ids in clusters.values():
        keep = min(ids, key=lambda k: (pool[k].get("decision") != "include", -pool[k]["char_count"], k))
        unique.append(pool[keep])
        for key in ids:
            row = pool[key]
            row["overlap_group_id"] = min(ids)
            if key != keep:
                why = ", ".join(sorted(reasons[key]))
                prefix = "requested inclusion rejected: " if row.get("decision") == "include" else ""
                row.update(selection_status="duplicate", selection_reason=f"{prefix}group representative {keep} ({why})")
    return unique


def _dimensions(config):
    keys = list(config["topics"]) + list(config["regions"])
    shares = [config["topics"].get(k, config["regions"].get(k)) for k in keys]
    return {k: i for i, k in enumerate(keys)}, shares


def _select(config, pool, limit):
    options = config["build"]
    seed, target = options["seed"], options["target_chars"]
    minimum, maximum = options["min_chars"], options["max_chars"]
    tolerance = options["tolerance_pp"] / 100
    positions, shares = _dimensions(config)
    pool.sort(key=lambda r: digest(f"{seed}:{r['document_id']}".encode()))
    counts = [0] * len(shares)
    sizes = [r["char_count"] for r in pool]
    axes = [(positions[r["primary_topic"]], positions[r["region"]]) for r in pool]
    chosen, authors = set(), Counter()
    mandatory = {i for i, row in enumerate(pool) if row.get("decision") == "include"}
    total = 0

    def change(i, sign):
        nonlocal total
        n = sign * sizes[i]
        total += n
        for axis in axes[i]:
            counts[axis] += n
        authors[pool[i].get("author_group_id")] += sign
        if sign > 0:
            chosen.add(i)
        else:
            chosen.remove(i)

    for i in sorted(mandatory):
        change(i, 1)
    capacity = len(pool) if limit is None else max(limit, len(mandatory))
    remaining = set(range(len(pool))) - chosen
    # All available whole works are the best possible size if supply is short.
    if sum(sizes) <= target and capacity >= len(pool):
        return pool

    # Fill the two marginal deficits jointly. The per-character gain in
    # weighted squared error from an addition has this simple linear form.
    while remaining and total < target and len(chosen) < capacity:
        def rank(i):
            n = sizes[i]
            overshoot = max(0, total + n - maximum)
            gain = sum((2 * (shares[j] * target - counts[j]) - n) / (shares[j] * target) for j in axes[i])
            return (overshoot, -gain, authors[pool[i].get("author_group_id")], i)
        best = min(remaining, key=rank)
        if total >= minimum and abs(total + sizes[best] - target) >= abs(total - target):
            break
        if total < minimum and total + sizes[best] > maximum and total + sizes[best] - maximum >= minimum - total:
            break
        remaining.remove(best)
        change(best, 1)

    def score():
        if total == 0:
            return (minimum, float("inf"), float("inf"))
        errors = [abs(n / total - share) for n, share in zip(counts, shares)]
        # Keep soft margins and corpus size explicit. Once every margin fits,
        # improve the residual deviations and distance to the nominal target.
        return (max(0, minimum - total, total - maximum),
                sum(max(0, d - tolerance) ** 2 for d in errors),
                sum(d * d for d in errors) + ((total - target) / target) ** 2)

    # Fixed budget, deterministic candidates, whole-document changes only.
    for _ in range(12):
        current = score()
        best_score, move = current, None
        available = sorted(set(range(len(pool))) - chosen)
        for remove in [None, *sorted(chosen - mandatory)]:
            if remove is not None:
                change(remove, -1)
            adds = available if len(chosen) < capacity else []
            for add in [None, *adds]:
                if add is not None:
                    change(add, 1)
                measured = score()
                if measured < best_score:
                    best_score, move = measured, (remove, add)
                if add is not None:
                    change(add, -1)
            if remove is not None:
                change(remove, 1)
        if move is None:
            break
        remove, add = move
        if remove is not None:
            change(remove, -1)
        if add is not None:
            change(add, 1)
    return [pool[i] for i in sorted(chosen)]


def _split(config, selected):
    groups = Groups(row["document_id"] for row in selected)
    fields = ["work_group_id", "duplicate_group_id", "overlap_group_id", "series_group_id"]
    if config["build"].get("group_authors", True):
        fields.append("author_group_id")
    seen = {}
    for row in selected:
        for field in fields:
            if value := row.get(field):
                token = field, value
                if token in seen:
                    groups.join(seen[token], row["document_id"])
                seen[token] = row["document_id"]
    members = defaultdict(list)
    for row in selected:
        members[groups.root(row["document_id"])].append(row)
    positions, _ = _dimensions(config)
    size_axis = len(positions)
    vectors = {}
    for key, rows in members.items():
        counts = [0] * (size_axis + 1)
        for row in rows:
            n = row["char_count"]
            for axis in (positions[row["primary_topic"]], positions[row["region"]], size_axis):
                counts[axis] += n
        vectors[key] = counts
    seed = config["build"]["seed"]
    order = sorted(members, key=lambda k: (-vectors[k][-1], digest(f"{seed}:{k}".encode())))
    aggregate = [sum(col) for col in zip(*vectors.values())]
    partition_counts = {p: [0] * (size_axis + 1) for p in PARTITIONS}
    assignment, group_counts = {}, Counter()

    def change(part, key, sign):
        for i, n in enumerate(vectors[key]):
            partition_counts[part][i] += sign * n
        group_counts[part] += sign

    def cost(part):
        # Dominant weight on total characters. A smaller term rewards matching
        # the actual corpus mix even if its topic or regional targets were missed.
        portion = config["splits"][part]
        total = max(1, aggregate[-1])
        costs = [((n - full * portion) / total) ** 2 / portion
                 for n, full in zip(partition_counts[part], aggregate)]
        return costs[-1] + 0.1 * sum(costs[:-1])

    for index, key in enumerate(order):
        empty = [p for p in PARTITIONS if not group_counts[p]]
        choices = empty if len(order) >= 3 and len(order) - index == len(empty) else PARTITIONS
        ranks = []
        for part in choices:
            before = cost(part)
            change(part, key, 1)
            ranks.append((cost(part) - before, PARTITIONS.index(part), part))
            change(part, key, -1)
        chosen = min(ranks)[2]
        assignment[key] = chosen
        change(chosen, key, 1)
    # Refine the first fit with whole-group moves, retaining usable holdouts
    # when there are three or more independent groups.
    for _ in range(4):
        changed = False
        for key in order:
            old = assignment[key]
            if len(order) >= 3 and group_counts[old] == 1:
                continue
            before = cost(old)
            change(old, key, -1)
            remove_delta = cost(old) - before
            best, delta = old, 0
            for part in PARTITIONS:
                if part == old:
                    continue
                before = cost(part)
                change(part, key, 1)
                value = remove_delta + cost(part) - before
                change(part, key, -1)
                if value < delta - 1e-15:
                    best, delta = part, value
            changed |= best != old
            assignment[key] = best
            change(best, key, 1)
        if not changed:
            break
    return {row["document_id"]: (assignment[key], key)
            for key, rows in members.items() for row in rows}


def _write_exports(folder, selected, assignments):
    for name in ("corpus", *PARTITIONS):
        docs = [r for r in selected if name == "corpus" or assignments[r["document_id"]][0] == name]
        with (folder / f"{name}.jsonl").open("wb") as json_out, (folder / f"{name}.txt").open("wb") as txt_out:
            for index, row in enumerate(docs):
                payload = Path(row["clean_path"]).read_bytes()
                if index:
                    txt_out.write(SEPARATOR.encode())
                txt_out.write(payload)
                json_out.write((canonical({**row, "text": payload.decode("utf-8")}) + "\n").encode())
    with (folder / "samples.txt").open("w", encoding="utf-8", newline="\n") as out:
        for row in selected[::max(1, len(selected) // 8)][:8]:
            text = Path(row["clean_path"]).read_bytes().decode("utf-8")
            middle = len(text) // 2
            out.write(f"{row['document_id']}  {row['title']}  [offset {middle}]\n{text[middle:middle + 480]}\n\n")


def _inputs(config, rows, limit):
    manifest_files = sorted(Path("manifests").glob("*.csv"))
    catalogue = Path("data/candidates.csv" if limit is None else f"data/candidates-trial-{limit}.csv")
    if catalogue.is_file():
        manifest_files.append(catalogue)
    unmatched = []
    overrides = Path("manifests/overrides.csv")
    if overrides.is_file():
        with overrides.open(encoding="utf-8-sig", newline="") as handle:
            unmatched = sorted({r["document_id"] for r in csv.DictReader(handle)} - {r["document_id"] for r in rows})
    package = Path(__file__).parent
    return {
        "config_sha256": digest(canonical(config).encode()),
        "rows_sha256": digest(canonical(rows).encode()),
        "raw_sha256": {r["document_id"]: r["raw_sha256"] for r in rows if r.get("raw_sha256")},
        "manifest_sha256": {p.as_posix(): file_hash(p) for p in manifest_files},
        "unmatched_overrides": unmatched,
        "source_code_sha256": {p.name: file_hash(p) for p in sorted(package.glob("*.py"))},
        "cleaning_version": CLEANING_VERSION,
        "max_documents": limit,
    }


@contextmanager
def _stage(base):
    # Default mkdir inherits the project's ACL, including on Windows. All
    # staged files are flat, so cleanup never needs recursive deletion.
    folder = (base / (".building-" + uuid.uuid4().hex)).resolve()
    folder.mkdir()
    try:
        yield folder
    finally:
        if folder.is_dir() and folder.resolve().parent == base.resolve():
            for candidate in folder.iterdir():
                candidate.unlink()
            folder.rmdir()


def build(config, rows, *, max_documents=None):
    """Materialize a build using only public factual metadata and retained inputs.

    The caller loads config/overrides and evaluates hard eligibility first.
    A repeat independently regenerates the core files and checks each byte.
    """
    rows = sorted((dict(row) for row in rows), key=lambda r: r["document_id"])
    if any(not r["document_id"] for r in rows) or len({r["document_id"] for r in rows}) != len(rows):
        raise ValueError("empty or nonunique candidate ID")
    inputs = _inputs(config, rows, max_documents)
    label = "full" if max_documents is None else f"trial-{max_documents}"
    build_id = f"{label}-{digest(canonical(inputs).encode())[:16]}"
    base = Path("data/builds")
    base.mkdir(parents=True, exist_ok=True)
    target = base / build_id
    pool, fingerprints = _prepare(rows, config["build"]["year_max"])
    unique = _deduplicate(pool, fingerprints)
    selected = sorted(_select(config, unique, max_documents), key=lambda r: r["document_id"])
    assignments = _split(config, selected)
    for row in unique:
        if row["document_id"] in assignments:
            row.update(selection_status="selected", selection_reason=(
                "eligible manual inclusion" if row.get("decision") == "include" else "whole-document selection"))
        else:
            row.update(selection_status="reserve", selection_reason="available alternative outside this selection")
    split_manifest = [
        {"document_id": key, "split": part, "split_group_id": group, "char_count": pool[key]["char_count"]}
        for key, (part, group) in sorted(assignments.items())
    ]
    with _stage(base) as folder:
        _csv(folder / "audit.csv", rows, ["document_id", "source", "title", "selection_status", "selection_reason"])
        _csv(folder / "selected_manifest.csv", selected,
             ["document_id", "title", "authors", "primary_topic", "region", "char_count", "clean_sha256"])
        _csv(folder / "split_manifest.csv", split_manifest, ["document_id", "split", "split_group_id", "char_count"])
        for name, value in [("inputs", inputs), ("config", config)]:
            (folder / f"{name}.json").write_bytes((canonical(value) + "\n").encode())
        _write_exports(folder, selected, assignments)
        try:
            folder.rename(target)
        except OSError:
            if not target.is_dir():
                raise
            for candidate in folder.iterdir():
                original = target / candidate.name
                if not original.is_file() or file_hash(candidate) != file_hash(original):
                    raise ValueError(f"repeat offline output differs: {original}")
    return target
