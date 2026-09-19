#!/usr/bin/env python3
"""Snapshot SPEC.md's requirement tables into docs/requirements.tsv.

SPEC.md lives in a separate repository (sv4u/project-specs), which CI does
not check out, so the requirement universe is checked in as a snapshot and
scripts/check_traceability.py works offline against it. Re-run this after
the SPEC changes:

  python3 scripts/extract_requirements.py [--spec PATH]

PATH defaults to $SV0_MATHLIB_SPEC, then ~/Documents/project-specs/
sv0-mathlib/SPEC.md. Only `| ID | Release | Requirement | Verification |`
rows with a `PREFIX-NNN` id are taken (the BL-*, AD-*, and OQ-* ids are
backlog items, decisions and open questions, not requirements). The SPEC's
git commit is recorded on every row, so the snapshot names its source.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "docs" / "requirements.tsv"
COLUMNS = ["id", "release", "section", "summary", "spec_commit"]
ROW_RE = re.compile(r"^\|\s*([A-Z]+-\d{3})\s*\|\s*([A-Za-z0-9.]+)\s*\|\s*(.*?)\s*\|")
SKIP_PREFIXES = ("BL-", "AD-", "OQ-")


def summarize(text: str, limit: int = 110) -> str:
    text = re.sub(r"`", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + " ..."


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", type=Path, default=Path(
        os.environ.get("SV0_MATHLIB_SPEC")
        or Path.home() / "Documents" / "project-specs" / "sv0-mathlib" / "SPEC.md"))
    args = ap.parse_args()
    if not args.spec.is_file():
        print(f"extract_requirements: no SPEC at {args.spec} (pass --spec or set SV0_MATHLIB_SPEC)",
              file=sys.stderr)
        return 2

    git = subprocess.run(["git", "-C", str(args.spec.parent), "log", "-1", "--format=%h", "--", args.spec.name],
                         capture_output=True, text=True)
    commit = git.stdout.strip() or "unknown"

    rows, section, seen = [], "", set()
    for line in args.spec.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") or line.startswith("### "):
            section = line.lstrip("# ").strip()
        m = ROW_RE.match(line)
        if not m or m.group(1).startswith(SKIP_PREFIXES):
            continue
        rid = m.group(1)
        if rid in seen:
            print(f"extract_requirements: duplicate requirement id {rid}", file=sys.stderr)
            return 1
        seen.add(rid)
        rows.append([rid, m.group(2), section, summarize(m.group(3)), commit])

    order = {}
    for r in rows:
        order.setdefault(r[0].split("-")[0], len(order))
    rows.sort(key=lambda r: (order[r[0].split("-")[0]], int(r[0].split("-")[1])))
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(COLUMNS)
        w.writerows(rows)
    print(f"extract_requirements: wrote {len(rows)} requirements from SPEC commit {commit} to "
          f"{OUT.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
