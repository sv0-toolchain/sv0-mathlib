#!/usr/bin/env python3
"""Requirement traceability gate: every requirement in SPEC.md's tables has
evidence, or a registered exception, or is Future-scoped. Dependency-free,
offline, no sv0 toolchain needed. Wired into scripts/ci.

Inputs (all checked in):
  docs/requirements.tsv   snapshot of SPEC.md's requirement tables
                          (scripts/extract_requirements.py; the SPEC is in
                          another repository, so CI works from the snapshot)
  test/**                 `REQ: <ID>` tags: test evidence
  docs/traceability.tsv   curated evidence for requirements verified by a
                          CI check or a process rather than a tagged test
  docs/exceptions.tsv     registered exceptions (docs/exceptions.md)

Rules:
  * every requirement has at least one of: a REQ-tagged test, a curated
    `check`/`process` row whose evidence path exists, a registered
    exception, or SPEC release `Future`;
  * the non-waivable requirements (PERF-002, COMPAT-001, TEST-004) need a
    test or a `check`; an exception or a manual process is not enough;
  * curated rows name a known requirement, a valid mechanism, and (for
    `check`/`process`) an existing path; a `future` row requires a Future
    release;
  * every REQ tag and every exceptions.tsv requirement id names a real
    requirement (typo detection);
  * scripts/run_unit_tests.py's REQUIRED_IDS is a subset of the SPEC
    snapshot with matching release labels.

`--write-md` regenerates docs/traceability.md (scripts/ci does this).
Exit 0 = OK; 1 = errors.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import run_unit_tests as rut  # noqa: E402 -- REQUIRED_IDS, REQ_TAG_RE, collect_req_tags

REQS = HERE / "docs" / "requirements.tsv"
CURATED = HERE / "docs" / "traceability.tsv"
EXCEPTIONS = HERE / "docs" / "exceptions.tsv"
OUT = HERE / "docs" / "traceability.md"

MECHANISMS = {"check", "process", "future"}
NON_WAIVABLE = {"PERF-002", "COMPAT-001", "TEST-004"}
CURATED_COLS = ["id", "mechanism", "evidence", "notes"]
REQ_COLS = ["id", "release", "section", "summary", "spec_commit"]


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        return list(r.fieldnames or []), list(r)


def build() -> tuple[list[str], list[dict]]:
    errs: list[str] = []
    header, reqs = read_tsv(REQS)
    if header != REQ_COLS:
        return [f"requirements.tsv header {header} != {REQ_COLS}"], []
    universe = {r["id"]: r for r in reqs}
    prefixes = {i.split("-")[0] for i in universe}

    tags = rut.collect_req_tags()
    for rid in sorted(tags):
        if rid not in universe:
            errs.append(f"REQ tag {rid} ({tags[rid][0]}) is not a requirement in docs/requirements.tsv")

    header, curated_rows = read_tsv(CURATED)
    if header != CURATED_COLS:
        return errs + [f"traceability.tsv header {header} != {CURATED_COLS}"], []
    curated: dict[str, list[dict[str, str]]] = {}
    for i, row in enumerate(curated_rows, start=2):
        rid, mech, ev = row["id"], row["mechanism"], row["evidence"].strip()
        where = f"traceability.tsv:{i} ({rid})"
        if rid not in universe:
            errs.append(f"{where}: not a requirement in docs/requirements.tsv")
            continue
        if mech not in MECHANISMS:
            errs.append(f"{where}: mechanism {mech!r} not in {sorted(MECHANISMS)}")
        if mech in ("check", "process"):
            if not ev or not (HERE / ev).exists():
                errs.append(f"{where}: evidence path {ev!r} does not exist")
        if mech == "future" and universe[rid]["release"] != "Future":
            errs.append(f"{where}: `future` requires SPEC release Future (is {universe[rid]['release']})")
        curated.setdefault(rid, []).append(row)

    _, exc_rows = read_tsv(EXCEPTIONS)
    exceptions: dict[str, list[str]] = {}
    for row in exc_rows:
        for rid in row["requirements"].split():
            if rid == "-":
                continue
            if rid.split("-")[0] in prefixes and rid not in universe:
                errs.append(f"exceptions.tsv {row['entry']}: {rid} is not a requirement in docs/requirements.tsv")
            if rid in universe:
                exceptions.setdefault(rid, []).append(row["entry"])

    for rid, rel in rut.REQUIRED_IDS.items():
        if rid not in universe:
            errs.append(f"run_unit_tests.py REQUIRED_IDS has {rid}, which is not in docs/requirements.tsv")
        elif universe[rid]["release"] != rel:
            errs.append(f"{rid}: REQUIRED_IDS release {rel} != SPEC release {universe[rid]['release']}")

    table: list[dict] = []
    for rid, r in universe.items():
        kinds: list[str] = []
        where: list[str] = []
        if rid in tags:
            kinds.append("test")
            where += tags[rid]
        for c in curated.get(rid, []):
            kinds.append(c["mechanism"])
            if c["evidence"].strip():
                where.append(c["evidence"].strip())
        if rid in exceptions:
            kinds.append("exception")
            where += exceptions[rid]
        if r["release"] == "Future" and "future" not in kinds:
            kinds.append("future")
        if not kinds:
            errs.append(f"{rid} ({r['release']}) has no test, check, process, exception, or Future scope")
        if rid in NON_WAIVABLE and not ({"test", "check"} & set(kinds)):
            errs.append(f"{rid} is non-waivable and needs a test or a check (has {kinds or 'none'})")
        table.append({**r, "kinds": kinds, "where": where})
    return errs, table


def render_md(table: list[dict]) -> str:
    out = ["# Requirement traceability", "",
           "Generated by `scripts/check_traceability.py --write-md` — do not hand-edit. Every",
           "requirement in SPEC.md's tables (snapshot: [`requirements.tsv`](requirements.tsv), SPEC",
           f"commit `{table[0]['spec_commit']}`) and the evidence that covers it:", "",
           "- **test**: a `REQ: <ID>` tag in `test/` (the per-requirement matrix is",
           "  [`requirement_test_matrix.md`](requirement_test_matrix.md));",
           "- **check**: an automated CI check ([`traceability.tsv`](traceability.tsv));",
           "- **process**: a manual process step, named there;",
           "- **exception**: registered in [`exceptions.md`](exceptions.md);",
           "- **future**: SPEC release `Future`.", "",
           "| ID | Release | Evidence | Where | Requirement |", "|---|---|---|---|---|"]
    for r in table:
        where = "; ".join(r["where"][:3]) + (f"; +{len(r['where']) - 3} more" if len(r["where"]) > 3 else "")
        esc = lambda t: t.replace("|", "\\|")  # noqa: E731
        out.append(f"| {r['id']} | {r['release']} | {', '.join(r['kinds'])} | {esc(where) or '—'} "
                   f"| {esc(r['summary'])} |")
    counts: dict[str, int] = {}
    for r in table:
        for k in set(r["kinds"]):
            counts[k] = counts.get(k, 0) + 1
    out += ["", f"{len(table)} requirements: " + ", ".join(f"{n} with {k}" for k, n in sorted(counts.items())) + "."]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-md", action="store_true", help="regenerate docs/traceability.md")
    args = ap.parse_args()
    errs, table = build()
    if errs:
        for e in errs:
            print(f"check_traceability: {e}", file=sys.stderr)
        print(f"check_traceability: {len(errs)} error(s)", file=sys.stderr)
        return 1
    if args.write_md:
        OUT.write_text(render_md(table), encoding="utf-8")
    only_manual = [r["id"] for r in table if set(r["kinds"]) <= {"process", "future"}]
    print(f"check_traceability: OK — {len(table)} SPEC requirements, all with evidence, a registered "
          f"exception, or Future scope; {len(only_manual)} rely on a manual process or Future scope "
          f"({', '.join(only_manual)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
