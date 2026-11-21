"""Command-line stages. All relative data paths are relative to the configuration."""

import argparse
import json
import math
import os
import re
import sys
import tomllib
from pathlib import Path

from . import build, overrides, report, sources


def load_config(path):
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    for table in ("topics", "regions", "splits"):
        shares = config[table].values()
        if not all(0 < x <= 1 for x in shares) or not math.isclose(sum(shares), 1, abs_tol=1e-9):
            raise ValueError(f"{table} requires positive shares summing to one")
    if set(config["splits"]) != set(build.PARTITIONS):
        raise ValueError("splits requires train, validation and test")
    b = config["build"]
    if not (0 < b["min_chars"] <= b["target_chars"] <= b["max_chars"] and 0 <= b["tolerance_pp"] <= 100):
        raise ValueError("Invalid target or acceptance band")
    if not 0 <= b.get("split_tolerance_pp", 2) <= 100 or b["year_min"] > b["year_max"]:
        raise ValueError("Invalid historical date interval")
    return config


def load_env():
    path = Path(".env")
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                key, sep, value = line.partition("=")
                if sep and key.strip() in {"CONTACT_EMAIL", "DIGITALNZ_API_KEY"}:
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["discover", "fetch", "build", "validate", "report", "run"])
    parser.add_argument("--config", type=Path, default=Path("config.toml"))
    parser.add_argument("--max-documents", type=int, metavar="N", help="use a separate bounded trial pool")
    parser.add_argument("--offline", action="store_true", help="require a stage that only reads saved inputs")
    parser.add_argument("--build-id", help="report or validate an existing frozen build")
    args = parser.parse_args(argv)
    limit = args.max_documents
    if limit is not None and limit < 1:
        parser.error("--max-documents must be positive")
    if args.offline and args.command not in {"build", "report", "validate"}:
        parser.error("offline stages are build, report and validate")
    build_id_pattern = r"(?:full|trial-[1-9][0-9]*)-[0-9a-f]{16}"
    if args.build_id and (args.command not in {"report", "validate"} or not re.fullmatch(build_id_pattern, args.build_id)):
        parser.error("--build-id must name a build for report or validate")
    try:
        path = args.config.resolve()
        config = load_config(path)
        os.chdir(path.parent)
        load_env()
        label = "full" if limit is None else f"trial-{limit}"
        catalogue = Path("data/candidates.csv" if limit is None else f"data/candidates-{label}.csv")
        latest = Path(f"data/builds/latest-{label}.txt")
        if args.command in {"discover", "run"}:
            rows = sources.discover(config, max_documents=limit)
            print(f"Discovered {len(rows):,} candidates in {catalogue}", flush=True)
        elif args.command in {"fetch", "build"}:
            rows = overrides.read_rows(catalogue)
        if args.command in {"fetch", "run"}:
            rows = sources.fetch(config, rows, max_documents=limit)
            print(f"Retained {sum(bool(r.get('raw_path')) for r in rows):,} raw documents", flush=True)
        if args.command in {"build", "run"}:
            # CSV defines the canonical field set and text representation for both entry points.
            rows = overrides.read_rows(catalogue)
            folder = build.build(config, overrides.apply(rows, config), max_documents=limit)
            stats = report.generate(folder)
            sources._atomic(latest, (folder.name + "\n").encode())
            print(report.summary(stats), flush=True)
        elif args.command in {"report", "validate"}:
            identifier = args.build_id or latest.read_text(encoding="utf-8").strip()
            if not re.fullmatch(build_id_pattern, identifier):
                raise ValueError("Invalid build identifier in latest-build pointer")
            folder = Path("data/builds") / identifier
            if args.command == "report":
                print(report.summary(report.generate(folder)))
            else:
                checks = report.validate(folder, check_report=True)
                print(json.dumps(checks, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"Dataset stage failed: {exc}", file=sys.stderr)
        return 1
