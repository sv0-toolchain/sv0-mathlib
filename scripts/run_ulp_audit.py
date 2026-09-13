#!/usr/bin/env python3
"""Wires docs/ulp_audit_harness.c into scripts/ci as an automated
regression gate — PERF-001's "generated-doc freshness" and PERF-002's
"CI fails on any regression past the pinned bound" acceptance criteria.

Until now the harness was checked in but run by hand (its own header
comment said so): a toolchain change or an accidental precision
regression in lib/trig.sv0 / lib/complex.sv0 could silently widen a
function's measured ULP error and nobody would notice until someone
happened to re-run the harness manually.

This script:
  1. Compiles `lib/` via the native compiler (`--project`), strips the
     trivial fallback `main` sv0 emits for a project with no `fn main`,
     and appends `docs/ulp_audit_harness.c` in the same translation unit
     (the harness's own usage comment documents this exact recipe).
  2. Compiles the result against the system libm and runs it.
  3. Parses each `audit_report` line (`name max_ulp=... budget=... PASS|FAIL`)
     and checks it against an explicit allowlist:
       - Every function NOT in ACCEPTED_INFORMATIONAL_FAILURES must PASS
         its own printed budget outright, or this is a regression.
       - `ln_complex`/`pow_complex` are documented, understood, informational
         FAILs (see docs/accuracy.md's own notes: a real-but-tiny residual,
         and a system-libm reference-quality artifact, respectively, both
         confirmed against an independent arbitrary-precision reference)
         -- these are allowed to stay FAIL, but only up to a recorded
         ceiling a little above their last-measured value. A jump past
         the ceiling is a real regression signal even though the nominal
         PASS/FAIL field was already FAIL before and after.

Usage: python3 scripts/run_ulp_audit.py [--toolchain-root DIR]
Exit 0 = no regression (every function within its budget, or within its
recorded informational ceiling); 1 = a real regression or a hard failure
(missing compiler, compile error, etc).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LIB = HERE / "lib"
HARNESS = HERE / "docs" / "ulp_audit_harness.c"

# Functions whose measured ULP error is EXPECTED to exceed its printed
# budget -- a documented, understood residual (see docs/accuracy.md),
# not a bug. The ceiling is a little above the last-measured value: room
# for harmless platform/compiler noise, tight enough that a genuine
# regression (the error growing meaningfully worse) still trips this.
ACCEPTED_INFORMATIONAL_FAILURES = {
    # measured 14 ULP against an informational 3 ULP budget -- see
    # docs/accuracy.md's ln_complex notes (real residual, not chased
    # further since CPLX-007 has no SPEC-pinned ULP requirement).
    "ln_complex": 20.0,
    # measured 38329 ULP against an informational 5 ULP budget -- see
    # docs/accuracy.md's pow_complex notes (the reference itself,
    # system libm's cpow/cexp, is not correctly rounded here; this
    # library's result was independently confirmed CLOSER to an
    # arbitrary-precision truth at 2 of 3 spot-checked points).
    "pow_complex": 45000.0,
}

REPORT_RE = re.compile(
    r"^(?P<name>\S+)\s+max_ulp=(?P<max_ulp>[\d.]+)\s+at x=\S+\s+y=\S+\s+"
    r"n=(?P<n>\d+)\s+nan_mismatch=(?P<nan_mismatch>\d+)\s+budget=(?P<budget>\d+)\s+"
    r"(?P<status>PASS|FAIL)\s*$"
)


def find_toolchain_root() -> Path:
    env = os.environ.get("SV0_TOOLCHAIN_ROOT")
    if env:
        return Path(env)
    if (HERE.parent / "sv0c").is_dir():
        return HERE.parent  # submodule of sv0-toolchain
    return HERE.parent / "sv0-toolchain"  # legacy sibling layout


def build_and_run(toolchain_root: Path, tmp: Path) -> str:
    compiler = toolchain_root / "build" / "sv0-megatu-compiler-native"
    runtime = toolchain_root / "sv0c" / "runtime"
    if not compiler.is_file():
        raise SystemExit(f"run_ulp_audit: missing {compiler} — build sv0-toolchain first")

    lib_c = tmp / "mathlib_lib.c"
    proc = subprocess.run([str(compiler), "--project", str(LIB)],
                          stdout=lib_c.open("wb"), stderr=subprocess.PIPE)
    if proc.returncode != 0 or lib_c.stat().st_size == 0:
        raise SystemExit(f"run_ulp_audit: emit-c failed:\n{proc.stderr.decode(errors='replace')}")

    lines = lib_c.read_text(encoding="utf-8").splitlines()
    if not lines[-1].strip().startswith("int main("):
        raise SystemExit(
            "run_ulp_audit: expected the trailing fallback `int main(void) "
            "{ return 0; }` sv0 emits for a project with no fn main -- "
            "lib/ now has one, or the emitted-C shape changed. Update this "
            "script's stripping logic (see docs/ulp_audit_harness.c's own "
            "usage comment) before trusting its output."
        )
    stripped = tmp / "mathlib_stripped.c"
    stripped.write_text("\n".join(lines[:-1]) + "\n" + HARNESS.read_text(encoding="utf-8"),
                        encoding="utf-8")

    binary = tmp / "ulp_audit_bin"
    cc = subprocess.run(["cc", "-std=c99", "-O2", "-w", "-I", str(runtime),
                         str(stripped), str(runtime / "sv0_runtime.c"), "-lm",
                         "-o", str(binary)], capture_output=True)
    if cc.returncode != 0:
        raise SystemExit(f"run_ulp_audit: cc failed:\n{cc.stderr.decode(errors='replace')}")

    run = subprocess.run([str(binary)], capture_output=True, text=True)
    if run.returncode != 0:
        raise SystemExit(f"run_ulp_audit: harness binary exited {run.returncode}:\n{run.stdout}{run.stderr}")
    return run.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolchain-root", type=Path, default=find_toolchain_root())
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        output = build_and_run(args.toolchain_root, Path(tmpdir))

    seen = set()
    regressions = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        m = REPORT_RE.match(line)
        if not m:
            print(f"run_ulp_audit: warning — unparsed harness line: {line!r}")
            continue
        name = m.group("name")
        max_ulp = float(m.group("max_ulp"))
        status = m.group("status")
        nan_mismatch = int(m.group("nan_mismatch"))
        seen.add(name)
        print(line)

        ceiling = ACCEPTED_INFORMATIONAL_FAILURES.get(name)
        if ceiling is not None:
            if max_ulp > ceiling:
                regressions.append(
                    f"{name}: measured {max_ulp:.4f} ULP, past its recorded "
                    f"informational ceiling of {ceiling} — this is worse than "
                    f"the documented residual in docs/accuracy.md, re-audit "
                    f"before raising the ceiling"
                )
        elif status != "PASS" or nan_mismatch != 0:
            regressions.append(
                f"{name}: {status} (max_ulp={max_ulp:.4f}, nan_mismatch={nan_mismatch}) "
                f"— not in the accepted-informational-failure allowlist, this is a real regression"
            )

    expected = set(ACCEPTED_INFORMATIONAL_FAILURES) | {
        "sqrt_f64", "sin_f64", "cos_f64", "tan_f64", "asin_f64", "acos_f64",
        "atan_f64", "atan2_f64", "exp_f64", "ln_f64",
        "sinh_f64", "cosh_f64", "tanh_f64", "hypot_f64", "exp_complex",
    }
    missing = expected - seen
    if missing:
        raise SystemExit(
            f"run_ulp_audit: harness didn't report on {sorted(missing)} — "
            f"the harness's own main() changed without updating this script's "
            f"expected-function set, or a sweep silently didn't run"
        )

    if regressions:
        print(f"\nrun_ulp_audit: {len(regressions)} regression(s):")
        for r in regressions:
            print(f"  - {r}")
        return 1

    print(f"\nrun_ulp_audit: PASS ({len(seen)} functions audited, no regression)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
