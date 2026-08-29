#!/usr/bin/env python3
"""TEST-001: run every test/unit/*.sv0 file as its own small standalone
sv0 program (SPEC.md §16.1's own convention — "each test is a small
`fn main() -> i32` binary") and generate the requirement-to-test matrix
SPEC.md's own Verification column asks for.

Why each test file is its OWN compile, not one combined with the others:
sv0's `--project <dir>` links every `.sv0` file under `dir` into one
translation unit, and a translation unit can have only one `fn main()`.
Multiple `test/unit/*_test.sv0` files, each with their own `main()`, are
each compiled in a FRESH temp directory containing a symlink to `lib/`
plus a copy of just that one test file — proven to work (no other
project file's `main()` is pulled in).

Requirement-ID coverage: this script also greps every file under `test/`
(not just `.sv0` — `test/unit/conv_review.md` documents the CONV-*
requirements that are policy/review items, not runtime assertions) for
`REQ: <ID>` tags, cross-references them against the fixed list of
requirement IDs TEST-001 puts in scope (Sections 8, 11, 12, 13, 15, 17
of SPEC.md — CONV-*, ARITH-*, MOD-*, TRIG-*, PERF-*, POLAR-*), and fails
if any in-scope ID has zero coverage. PERF-003 is Future-scoped (not
yet implementable — no Tier 2 exists) and is excluded from the
"uncovered" failure the same way CPLX-007 was until this session's
accuracy work unblocked it; it's still LISTED in the matrix, just
marked N/A rather than counted as a failure.

Usage: python3 scripts/run_unit_tests.py [--matrix-only]
  --matrix-only   skip compiling/running; only (re)generate the matrix
                  doc from the current REQ tags (fast iteration).
Exit 0 = every test passed AND every in-scope ID is covered.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
TEST_UNIT = HERE / "test" / "unit"
LIB = HERE / "lib"
MATRIX_OUT = HERE / "docs" / "requirement_test_matrix.md"

# The exact ID list TEST-001 puts in scope: SPEC.md Sections 8 (CONV-*),
# 11 (ARITH-*), 12 (MOD-*), 13 (TRIG-*), 15 (PERF-*), 17 (POLAR-*).
# Hand-transcribed from SPEC.md's own requirement tables (not generated
# from a checked-in copy of SPEC.md — this repo doesn't vendor the spec,
# see README's "Deviations from SPEC.md" #2) — re-check this list by
# hand against SPEC.md's Sections 8/11/12/13/15/17 if either drifts.
REQUIRED_IDS: dict[str, str] = {
    "CONV-001": "F0",
    "CONV-002": "F0",
    "CONV-003": "R0.2",
    "CONV-004": "F0",
    "CONV-005": "F0",
    "CONV-006": "F0",
    "CONV-007": "F0",
    "CONV-008": "R0.1",
    "CONV-009": "R0.1",
    "CONV-010": "R0.1",
    "ARITH-001": "F0",
    "ARITH-002": "F0",
    "ARITH-003": "F0",
    "ARITH-004": "F0",
    "ARITH-005": "R0.1",
    "ARITH-006": "R0.1",
    "ARITH-007": "R0.1",
    "ARITH-008": "R0.1",
    "ARITH-009": "R0.1",
    "ARITH-010": "R0.1",
    "MOD-001": "R0.1",
    "MOD-002": "R0.1",
    "MOD-003": "R0.1",
    "MOD-004": "R0.1",
    "MOD-005": "R0.2",
    "MOD-006": "R0.2",
    "MOD-007": "R0.2",
    "TRIG-001": "R0.2",
    "TRIG-002": "R0.2",
    "TRIG-003": "R0.2",
    "TRIG-004": "R0.2",
    "TRIG-005": "R0.2",
    "TRIG-006": "R0.2",
    "TRIG-007": "R0.2",
    "PERF-001": "R0.1",
    "PERF-002": "R0.2",
    "PERF-003": "Future",
    "PERF-004": "R0.1",
    "PERF-005": "R0.2",
    "POLAR-001": "R0.3",
    "POLAR-002": "R0.3",
    "POLAR-003": "R0.3",
    "POLAR-004": "R0.3",
    "POLAR-005": "R0.3",
}
FUTURE_IDS = {rid for rid, rel in REQUIRED_IDS.items() if rel == "Future"}

# Deliberately, explicitly deferred with rationale (SPEC.md §21.5's own
# R1-gate wording for open questions) — NOT silently accepted as
# "coverage," and not the same thing as an ID nobody got to yet.
# CONV-010: `--project`-mode has no `--contract-mode` flag today (see
# test/unit/conv_review.md's own CONV-010 section for the full
# investigation) — genuinely untestable with current tooling, not
# unimplemented on this library's own side.
ALLOWED_UNCOVERED = {"CONV-010"}

REQ_TAG_RE = re.compile(r"REQ:\s*([A-Z]+-\d+)")


def find_native_compiler(toolchain_root: Path) -> Path:
    return toolchain_root / "build" / "sv0-megatu-compiler-native"


def run_one_test(sv0_file: Path, toolchain_root: Path, runtime_dir: Path) -> tuple[bool, str]:
    """Compile+run a single test/unit/*.sv0 file in its own temp project
    (lib/ symlinked in, this one file copied alongside). Returns
    (passed, message)."""
    compiler = find_native_compiler(toolchain_root)
    if not compiler.is_file():
        return False, f"missing native compiler at {compiler}"

    with tempfile.TemporaryDirectory(prefix="sv0mathlib_unit_") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "lib").symlink_to(LIB)
        # BUGS.md #17: the native compiler's --project file discovery is
        # order-sensitive in a way that has nothing to do with imports —
        # a top-level file or directory that sorts ALPHABETICALLY BEFORE
        # "lib" makes the whole compile fail with exit code 2 and ZERO
        # diagnostic output (reproduced with `aaa.sv0`/`kkk.sv0` vs.
        # `mmm.sv0`/`zzz.sv0`, and with a subdirectory named `aaa/` vs.
        # `tests/`). "under_test" sorts after "lib" (u > l) and is
        # deliberately verbose so nobody renames it to something shorter
        # without noticing this comment.
        under_test = tmp_path / "under_test"
        under_test.mkdir()
        shutil.copy(sv0_file, under_test / sv0_file.name)

        emitted_c = tmp_path / "out.c"
        proc = subprocess.run(
            [str(compiler), "--project", str(tmp_path)],
            stdout=emitted_c.open("wb"),
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            return False, f"compile failed: {proc.stderr.decode(errors='replace')[:400]}"

        binary = tmp_path / "test_bin"
        cc = subprocess.run(
            [
                "cc", "-std=c99", "-O0", "-w",
                "-I", str(runtime_dir),
                str(emitted_c), str(runtime_dir / "sv0_runtime.c"),
                "-o", str(binary),
            ],
            capture_output=True,
        )
        if cc.returncode != 0:
            return False, f"cc failed: {cc.stderr.decode(errors='replace')[:400]}"

        run = subprocess.run([str(binary)], capture_output=True)
        if run.returncode != 0:
            return False, f"exit {run.returncode}"
        return True, "ok"


def collect_req_tags() -> dict[str, list[str]]:
    """REQ id -> list of "path:line" locations across everything under test/."""
    coverage: dict[str, list[str]] = {}
    for path in sorted((HERE / "test").rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in REQ_TAG_RE.finditer(line):
                rid = m.group(1)
                coverage.setdefault(rid, []).append(
                    f"{path.relative_to(HERE)}:{lineno}"
                )
    return coverage


def write_matrix(coverage: dict[str, list[str]], test_results: dict[str, tuple[bool, str]]) -> list[str]:
    """Write docs/requirement_test_matrix.md; return the list of
    uncovered, non-Future in-scope IDs."""
    uncovered: list[str] = []
    lines = [
        "# Requirement-to-test matrix (TEST-001)",
        "",
        "Generated by `scripts/run_unit_tests.py` — do not hand-edit.",
        "Covers SPEC.md Sections 8 (CONV-*), 11 (ARITH-*), 12 (MOD-*), 13",
        "(TRIG-*), 15 (PERF-*), and 17 (POLAR-*), per TEST-001's own scope.",
        "",
        "| ID | Release | Status | Location(s) |",
        "|---|---|---|---|",
    ]
    for rid in sorted(REQUIRED_IDS, key=lambda r: (r.split("-")[0], int(r.split("-")[1]))):
        rel = REQUIRED_IDS[rid]
        locs = coverage.get(rid, [])
        if rid in FUTURE_IDS:
            status = "N/A (Future)"
        elif locs:
            status = "covered"
        elif rid in ALLOWED_UNCOVERED:
            status = "deferred (see test/unit/conv_review.md)"
        else:
            status = "**UNCOVERED**"
            uncovered.append(rid)
        loc_str = "; ".join(locs) if locs else "—"
        lines.append(f"| {rid} | {rel} | {status} | {loc_str} |")

    lines.append("")
    lines.append("## Test runs")
    lines.append("")
    lines.append("| Test file | Result |")
    lines.append("|---|---|")
    for name, (passed, msg) in sorted(test_results.items()):
        lines.append(f"| `{name}` | {'PASS' if passed else 'FAIL — ' + msg} |")
    lines.append("")

    MATRIX_OUT.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return uncovered


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--matrix-only", action="store_true")
    p.add_argument(
        "--toolchain-root",
        type=Path,
        default=Path(__import__("os").environ.get("SV0_TOOLCHAIN_ROOT", HERE.parent / "sv0-toolchain")),
    )
    args = p.parse_args()

    test_results: dict[str, tuple[bool, str]] = {}
    ok = True

    if not args.matrix_only:
        if not TEST_UNIT.is_dir():
            print(f"run_unit_tests: no {TEST_UNIT}", file=sys.stderr)
            return 1
        runtime_dir = args.toolchain_root / "sv0c" / "runtime"
        for sv0_file in sorted(TEST_UNIT.glob("*.sv0")):
            passed, msg = run_one_test(sv0_file, args.toolchain_root, runtime_dir)
            test_results[sv0_file.name] = (passed, msg)
            status = "PASS" if passed else f"FAIL ({msg})"
            print(f"run_unit_tests: {sv0_file.name}: {status}")
            if not passed:
                ok = False

    coverage = collect_req_tags()
    uncovered = write_matrix(coverage, test_results)
    print(f"run_unit_tests: matrix written to {MATRIX_OUT.relative_to(HERE)}")

    if uncovered:
        print(
            f"run_unit_tests: {len(uncovered)} in-scope requirement ID(s) uncovered: "
            + ", ".join(uncovered),
            file=sys.stderr,
        )
        ok = False

    if ok:
        print("run_unit_tests: PASS")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
