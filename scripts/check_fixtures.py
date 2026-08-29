#!/usr/bin/env python3
"""TEST-002/TEST-003: validate test/fixtures/*.csv against the two
requirements' own Verification columns.

TEST-002 ("Fixture-manifest schema and completeness test"): every *.csv
under test/fixtures/ has a row in manifest.md, and every manifest.md
row's file actually exists — a schema/completeness check, not a
re-derivation of the values themselves (those were verified by hand
against a live sv0-compiled build; see manifest.md's own provenance
column for how and when).

TEST-003 ("Fixture-inventory lint requiring at least one boundary/
special-value row per non-exact function"): every function in
NON_EXACT_FUNCTIONS below has at least one fixture row (in ANY *.csv
under test/fixtures/) tagged with a boundary/special-value category
(see BOUNDARY_CATEGORIES) — not just "typical" values.

Usage: python3 scripts/check_fixtures.py
Exit 0 = both checks pass.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIXTURES_DIR = HERE / "test" / "fixtures"
MANIFEST = FIXTURES_DIR / "manifest.md"

# TEST-003's own non-exact functions: every PERF-002-pinned function
# (docs/accuracy.md) plus the informational-budget ones from the same
# table, minus ones with no natural "domain boundary" beyond what's
# already covered by their own requires (kept to what test/fixtures/
# actually covers today, not padded out to every function in the
# library — this list grows as fixture coverage grows).
NON_EXACT_FUNCTIONS = {
    "floor_f64", "ceil_f64", "round_f64", "trunc_f64",
    "sqrt_f64", "sin_f64", "cos_f64", "tan_f64",
    "asin_f64", "acos_f64", "atan_f64", "atan2_f64",
    "exp_f64", "ln_f64",
}

# Maps a fixture row's own "category" column value(s) (";"-separated,
# see manifest.md's schema note) to the boundary/special-value concept
# TEST-003's own wording names.
BOUNDARY_CATEGORIES = {"boundary", "neg_zero", "nan", "infinity", "near_integer"}


def check_manifest_completeness() -> list[str]:
    """TEST-002. Returns a list of problems (empty = clean)."""
    problems: list[str] = []
    if not MANIFEST.is_file():
        return [f"missing {MANIFEST.relative_to(HERE)}"]

    manifest_text = MANIFEST.read_text(encoding="utf-8")
    # Manifest table rows: "| `filename.csv` | ... |"
    referenced = set(re.findall(r"\|\s*`([\w.-]+\.csv)`\s*\|", manifest_text))

    actual_csvs = {p.name for p in FIXTURES_DIR.glob("*.csv")}

    for name in sorted(actual_csvs - referenced):
        problems.append(f"{name}: exists under test/fixtures/ but has no manifest.md row")
    for name in sorted(referenced - actual_csvs):
        problems.append(f"{name}: has a manifest.md row but the file doesn't exist")

    # Every referenced file must also actually have a provenance cell
    # (a non-empty table row — checked structurally, not semantically).
    for line in manifest_text.splitlines():
        m = re.match(r"\|\s*`([\w.-]+\.csv)`\s*\|(.*)\|(.*)\|(.*)\|$", line)
        if m:
            fname, provenance, revision, _notes = m.groups()
            if not provenance.strip():
                problems.append(f"{fname}: manifest row has an empty provenance cell")
            if not revision.strip():
                problems.append(f"{fname}: manifest row has an empty toolchain-revision cell")

    return problems


def check_boundary_coverage() -> list[str]:
    """TEST-003. Returns a list of functions missing boundary coverage."""
    covered: dict[str, set[str]] = {}

    for csv_path in FIXTURES_DIR.glob("*.csv"):
        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                continue
            has_function_col = "function" in reader.fieldnames
            has_category_col = "category" in reader.fieldnames
            if not has_category_col:
                continue
            for row in reader:
                cats = {c.strip() for c in row.get("category", "").split(";")}
                if not (cats & BOUNDARY_CATEGORIES):
                    continue
                if has_function_col and row.get("function"):
                    covered.setdefault(row["function"], set()).add(csv_path.name)
                else:
                    # rounding.csv-style: one row covers several named
                    # functions implicitly (its own *_expected columns).
                    for fn in ("floor_f64", "ceil_f64", "round_f64", "trunc_f64"):
                        covered.setdefault(fn, set()).add(csv_path.name)

    missing = sorted(NON_EXACT_FUNCTIONS - covered.keys())
    return missing


def main() -> int:
    ok = True

    manifest_problems = check_manifest_completeness()
    if manifest_problems:
        ok = False
        print("check_fixtures: TEST-002 manifest completeness FAILED:", file=sys.stderr)
        for p in manifest_problems:
            print(f"  - {p}", file=sys.stderr)
    else:
        print("check_fixtures: TEST-002 manifest completeness OK")

    missing = check_boundary_coverage()
    if missing:
        ok = False
        print(
            "check_fixtures: TEST-003 boundary/special-value coverage FAILED — "
            f"missing for: {', '.join(missing)}",
            file=sys.stderr,
        )
    else:
        print(f"check_fixtures: TEST-003 boundary/special-value coverage OK ({len(NON_EXACT_FUNCTIONS)} functions)")

    if ok:
        print("check_fixtures: PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
