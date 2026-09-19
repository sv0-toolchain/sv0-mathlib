#!/usr/bin/env python3
"""Exceptions registry check (the sv0-mathlib port of sv0-strings'
tools/check_exceptions.py; GOV-009/GOV-010 style governance).

`docs/exceptions.tsv` is the one register of everything this library ships
that falls short of, or sits outside, SPEC.md or its own gates: documented
deviations, beyond-spec modules, deferred requirements, advisory (non-
gating) checks, informational budgets, and open toolchain gaps with
workarounds. Every row has an approver, a rationale, and an expiration
trigger (or is `permanent`, a registered and sound decision rather than a
gap).

Checks (dependency-free, no toolchain needed):
  * exact header; unique `MX-nnn` entry ids; every column non-empty;
  * `kind` and `status` are from the allowed sets; `approver` is an email;
    `rationale` is substantive; `permanent` rows say so in `expiration`;
  * `reference` resolves: `deviations.md#N` names a numbered deviation that
    exists, `BUGS.md#N` names a `## N.` heading that exists, anything else
    must be an existing repo-relative path;
  * NON-WAIVABLE requirements never appear (the pinned accuracy budgets,
    whole-library backend parity, deterministic seeded property tests);
  * completeness: every numbered deviation in docs/deviations.md is
    referenced by a row, and every requirement the generated matrix marks
    neither `covered` nor `N/A` (out-of-scope Future) appears in a row;
  * a date in an `open` row's `expiration` (YYYY-MM-DD) may not be in the
    past.

`--write-md` also regenerates docs/exceptions.md from the TSV (scripts/ci
does this, like docs/api.md).
Exit 0 = OK; 1 = errors.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TSV = HERE / "docs" / "exceptions.tsv"
MD = HERE / "docs" / "exceptions.md"
DEVIATIONS = HERE / "docs" / "deviations.md"
BUGS = HERE / "BUGS.md"
MATRIX = HERE / "docs" / "requirement_test_matrix.md"

COLUMNS = ["entry", "requirements", "kind", "reference", "approver", "rationale", "expiration", "status"]
KINDS = {"deviation", "beyond-spec", "deferred", "advisory-gate", "informational-budget", "toolchain-gap"}
STATUSES = {"open", "permanent"}
NON_WAIVABLE = {"PERF-002", "COMPAT-001", "TEST-004"}
ID_RE = re.compile(r"^[A-Z]+(-[A-Za-z0-9]+)+$")


def deviation_numbers() -> set[int]:
    return {int(m.group(1)) for m in re.finditer(r"^(\d+)\. \*\*", DEVIATIONS.read_text(encoding="utf-8"), re.M)}


def bug_numbers() -> set[int]:
    return {int(m.group(1)) for m in re.finditer(r"^## (\d+)\. ", BUGS.read_text(encoding="utf-8"), re.M)}


def non_covered_requirements() -> set[str]:
    out = set()
    for line in MATRIX.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and ID_RE.match(cells[0]) and not cells[2].startswith(("covered", "N/A")):
            out.add(cells[0])
    return out


def load() -> tuple[list[str], list[dict[str, str]]]:
    with TSV.open(encoding="utf-8", newline="") as f:
        r = csv.DictReader(f, delimiter="\t")
        return list(r.fieldnames or []), list(r)


def check(rows: list[dict[str, str]]) -> list[str]:
    errs: list[str] = []
    devs, bugs = deviation_numbers(), bug_numbers()
    seen: set[str] = set()
    referenced_devs: set[int] = set()
    all_reqs: set[str] = set()
    today = datetime.date.today()

    for i, row in enumerate(rows, start=2):
        eid = row["entry"]
        where = f"exceptions.tsv:{i} ({eid or '<no id>'})"
        if not re.fullmatch(r"MX-\d{3}", eid or ""):
            errs.append(f"{where}: entry must look like MX-001")
        if eid in seen:
            errs.append(f"{where}: duplicate entry id")
        seen.add(eid)
        for col in COLUMNS:
            if not (row.get(col) or "").strip():
                errs.append(f"{where}: column {col!r} is empty")

        reqs = row["requirements"].split()
        if reqs != ["-"]:
            for rid in reqs:
                all_reqs.add(rid)
                if not ID_RE.match(rid):
                    errs.append(f"{where}: {rid!r} is not a requirement id")
                if rid in NON_WAIVABLE:
                    errs.append(f"{where}: {rid} is non-waivable and may never appear here")

        if row["kind"] not in KINDS:
            errs.append(f"{where}: kind {row['kind']!r} not in {sorted(KINDS)}")
        if "@" not in row["approver"]:
            errs.append(f"{where}: approver must be an identifiable person (an email)")
        if len(row["rationale"].strip()) < 40:
            errs.append(f"{where}: rationale too short (< 40 chars)")

        status = row["status"].strip()
        exp = row["expiration"]
        if status not in STATUSES:
            errs.append(f"{where}: status {status!r} not in {sorted(STATUSES)}")
        elif status == "permanent" and "permanent" not in exp.lower() and "n/a" not in exp.lower():
            errs.append(f"{where}: a permanent row must say so in expiration")
        elif status == "open":
            for d in re.findall(r"\b(\d{4}-\d{2}-\d{2})\b", exp):
                if datetime.date.fromisoformat(d) < today:
                    errs.append(f"{where}: expired on {d} and still open")

        ref = row["reference"].strip()
        m = re.fullmatch(r"(deviations\.md|BUGS\.md)#(\d+)", ref)
        if m:
            n = int(m.group(2))
            known = devs if m.group(1) == "deviations.md" else bugs
            if n not in known:
                errs.append(f"{where}: reference {ref} does not exist")
            if m.group(1) == "deviations.md":
                referenced_devs.add(n)
        else:
            path = ref.split("#")[0]
            if not (HERE / path).exists() and not (HERE / "docs" / path).exists():
                errs.append(f"{where}: reference {ref!r} is not a known anchor or an existing file")

    for n in sorted(devs - referenced_devs):
        errs.append(f"docs/deviations.md #{n} has no exceptions.tsv row referencing it")
    for rid in sorted(non_covered_requirements() - all_reqs):
        errs.append(f"{rid} is not `covered` in the requirement matrix but has no exceptions.tsv row")
    return errs


def render_md(rows: list[dict[str, str]]) -> str:
    out = ["# Exceptions registry", "",
           "Generated by `scripts/check_exceptions.py --write-md` from",
           "[`exceptions.tsv`](exceptions.tsv) — do not hand-edit. Everything this library ships",
           "that falls short of, or sits outside, SPEC.md or its own gates, each with an",
           "approver, a rationale and an expiration trigger (or `permanent`).", "",
           f"Non-waivable requirements (never registrable): {', '.join(sorted(NON_WAIVABLE))}.", "",
           "| Entry | Requirements | Kind | Reference | Status | Closes when |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        esc = lambda t: t.replace("|", "\\|")  # noqa: E731
        out.append(f"| {r['entry']} | {esc(r['requirements'])} | {r['kind']} | {esc(r['reference'])} "
                   f"| {r['status']} | {esc(r['expiration'])} |")
    out += ["", "## Rationale", ""]
    for r in rows:
        out.append(f"- **{r['entry']}** ({r['kind']}, {r['status']}): {r['rationale']}")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-md", action="store_true", help="regenerate docs/exceptions.md")
    args = ap.parse_args()

    header, rows = load()
    if header != COLUMNS:
        print(f"check_exceptions: header {header} != {COLUMNS}", file=sys.stderr)
        return 1
    errs = check(rows)
    if errs:
        for e in errs:
            print(f"check_exceptions: {e}", file=sys.stderr)
        print(f"check_exceptions: {len(errs)} error(s)", file=sys.stderr)
        return 1
    if args.write_md:
        MD.write_text(render_md(rows), encoding="utf-8")
    n_open = sum(1 for r in rows if r["status"] == "open")
    print(f"check_exceptions: OK — {len(rows)} registered exceptions ({n_open} open, "
          f"{len(rows) - n_open} permanent); every deviation is registered; "
          f"{len(non_covered_requirements())} non-covered requirement(s) registered; "
          "no non-waivable requirement waived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
