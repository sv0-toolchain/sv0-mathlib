#!/usr/bin/env python3
"""Accuracy regression gate for lib/stats.sv0 (the stats analogue of
scripts/run_ulp_audit.py).

libm has no reference for these reductions, so the reference here is EXACT:
each data set the C harness (docs/stats_accuracy_harness.c) generates is
re-computed in integer/rational arithmetic and rounded once. The harness
runs the sv0-emitted `Stats` accumulator on the same values; this script
measures the error in ULPs of the exact result and fails if any
(function, family) pair exceeds its budget below.

The `cancel` family's sum and mean are graded differently: its exact total is tiny
next to sum(|x|), so ULPs of the RESULT would measure the problem's
conditioning, not the algorithm. There the error is reported in units of
eps * sum(|x|), which compensated summation keeps near 1 while a naive
running sum reaches well over 1 (printed alongside for comparison).

Usage: python3 scripts/run_stats_accuracy.py [--toolchain-root DIR] [--report]
Exit 0 = every budget held; 1 = a regression or a hard failure.
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LIB = HERE / "lib"
HARNESS = HERE / "docs" / "stats_accuracy_harness.c"

EPS = 2.0 ** -53  # unit roundoff

# (function, family) -> maximum allowed error in ULPs of the exact result
# (`sum`/`mean` on `cancel`: in units of eps * sum(|x|) / eps * mean(|x|)). Set from measurement with
# headroom; see docs/accuracy.md.
# Measured maxima (2026-09-19, arm64 macOS): sum 0 everywhere; mean 5 / 0 / 0.2 /
# 0 (uniform / offset / cancel / stream); variance 13 / 10 / 8 / 44; stddev
# 6 / 5 / 3 / 20; min and max 0. Budgets are roughly 2x for platform noise.
BUDGETS: dict[tuple[str, str], float] = {
    **{("sum", f): 1.0 for f in ("uniform", "offset", "stream")},
    ("sum", "cancel"): 0.5,
    ("mean", "uniform"): 16.0, ("mean", "offset"): 2.0,
    ("mean", "cancel"): 1.0, ("mean", "stream"): 2.0,
    **{(fn, f): 32.0 for fn in ("varp", "vars") for f in ("uniform", "offset", "cancel")},
    ("varp", "stream"): 96.0, ("vars", "stream"): 96.0,
    **{(fn, f): 16.0 for fn in ("sdp", "sds") for f in ("uniform", "offset", "cancel")},
    ("sdp", "stream"): 48.0, ("sds", "stream"): 48.0,
    **{(fn, f): 0.0 for fn in ("min", "max") for f in ("uniform", "offset", "cancel", "stream")},
}

FUNCS = ["sum", "mean", "varp", "vars", "sdp", "sds", "min", "max"]


def find_toolchain_root() -> Path:
    env = os.environ.get("SV0_TOOLCHAIN_ROOT")
    if env:
        return Path(env)
    if (HERE.parent / "sv0c").is_dir():
        return HERE.parent
    return HERE.parent / "sv0-toolchain"


def build_and_run(toolchain_root: Path, tmp: Path) -> str:
    compiler = toolchain_root / "build" / "sv0-megatu-compiler-native"
    runtime = toolchain_root / "sv0c" / "runtime"
    if not compiler.is_file():
        raise SystemExit(f"run_stats_accuracy: missing {compiler} — build sv0-toolchain first")
    lib_c = tmp / "mathlib_lib.c"
    proc = subprocess.run([str(compiler), "--project", str(LIB)],
                          stdout=lib_c.open("wb"), stderr=subprocess.PIPE)
    if proc.returncode != 0 or lib_c.stat().st_size == 0:
        raise SystemExit(f"run_stats_accuracy: emit-c failed:\n{proc.stderr.decode(errors='replace')}")
    lines = lib_c.read_text(encoding="utf-8").splitlines()
    if not lines[-1].strip().startswith("int main("):
        raise SystemExit("run_stats_accuracy: expected the trailing fallback `int main` sv0 emits "
                         "for a project with no `fn main`; the emitted-C shape changed (see "
                         "scripts/run_ulp_audit.py, which strips it the same way)")
    src = tmp / "stats_acc.c"
    src.write_text("\n".join(lines[:-1]) + "\n" + HARNESS.read_text(encoding="utf-8"), encoding="utf-8")
    binary = tmp / "stats_acc_bin"
    cc = subprocess.run(["cc", "-std=c99", "-O2", "-w", "-I", str(runtime), str(src),
                         str(runtime / "sv0_runtime.c"), "-lm", "-o", str(binary)],
                        capture_output=True)
    if cc.returncode != 0:
        raise SystemExit(f"run_stats_accuracy: cc failed:\n{cc.stderr.decode(errors='replace')}")
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    if run.returncode != 0:
        raise SystemExit(f"run_stats_accuracy: harness exited {run.returncode}:\n{run.stderr}")
    return run.stdout


def exact_reference(xs: list[float]) -> dict[str, float]:
    n = len(xs)
    shift = 1074  # every finite double is an integer multiple of 2**-1074
    ints = [int(Fraction(x) * (1 << shift)) for x in xs]
    total = sum(ints)
    sq = sum(v * v for v in ints)
    scale = 1 << shift
    numer = n * sq - total * total  # n^2 * population variance * 2^(2*shift)
    varp = Fraction(numer, n * n * scale * scale)
    vars_ = Fraction(numer, n * (n - 1) * scale * scale)
    return {
        "sum": float(Fraction(total, scale)),
        "mean": float(Fraction(total, n * scale)),
        "varp": float(varp),
        "vars": float(vars_),
        "sdp": math.sqrt(float(varp)),
        "sds": math.sqrt(float(vars_)),
        "min": min(xs),
        "max": max(xs),
    }


def ulps(got: float, ref: float) -> float:
    if ref == 0.0:
        return 0.0 if got == 0.0 else math.inf
    return abs(got - ref) / math.ulp(ref)


def parse(output: str):
    lines = output.splitlines()
    i = 0
    while i < len(lines):
        head = lines[i].split()
        if not head or head[0] != "SET":
            raise SystemExit(f"run_stats_accuracy: unexpected harness line: {lines[i][:80]!r}")
        family, n = head[1], int(head[2])
        got = dict(zip(FUNCS, (float.fromhex(t) for t in head[3:])))
        xs = [float.fromhex(t) for t in lines[i + 1].split()]
        if len(xs) != n:
            raise SystemExit(f"run_stats_accuracy: set of {n} values printed {len(xs)}")
        yield family, xs, got
        i += 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--toolchain-root", type=Path, default=find_toolchain_root())
    ap.add_argument("--report", action="store_true", help="print measured maxima only; do not gate")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="sv0mathlib_statsacc_") as tmp:
        output = build_and_run(args.toolchain_root, Path(tmp))

    worst: dict[tuple[str, str], float] = {}
    naive_worst = 0.0
    nsets: dict[str, int] = {}
    for family, xs, got in parse(output):
        nsets[family] = nsets.get(family, 0) + 1
        ref = exact_reference(xs)
        for fn in FUNCS:
            if family == "cancel" and fn in ("sum", "mean"):
                mag = math.fsum(abs(x) for x in xs) / (1 if fn == "sum" else len(xs))
                err = abs(got[fn] - ref[fn]) / (EPS * mag)
                if fn == "sum":
                    naive = 0.0
                    for x in xs:
                        naive += x
                    naive_worst = max(naive_worst, abs(naive - ref[fn]) / (EPS * mag))
            else:
                err = ulps(got[fn], ref[fn])
            key = (fn, family)
            worst[key] = max(worst.get(key, 0.0), err)

    fams = ["uniform", "offset", "cancel", "stream"]
    print("run_stats_accuracy: max error (ULPs of the exact result; cancel sum/mean in eps*sum|x| resp. eps*mean|x|)")
    print(f"  {'function':<8}" + "".join(f"{f:>10}" for f in fams))
    for fn in FUNCS:
        print(f"  {fn:<8}" + "".join(f"{worst.get((fn, f), float('nan')):>10.3f}" for f in fams))
    print(f"  data sets: {nsets}; naive running sum on `cancel` reaches {naive_worst:.1f} eps*sum|x| "
          f"(compensated: {worst[('sum', 'cancel')]:.3f})")

    if args.report:
        return 0
    bad = []
    for key, err in sorted(worst.items()):
        budget = BUDGETS.get(key)
        if budget is None:
            bad.append(f"{key[0]}/{key[1]}: measured {err:.3f} with no budget recorded")
        elif err > budget:
            bad.append(f"{key[0]}/{key[1]}: measured {err:.3f} > budget {budget}")
    if bad:
        print("run_stats_accuracy: FAIL", file=sys.stderr)
        for b in bad:
            print(f"  - {b}", file=sys.stderr)
        return 1
    print(f"run_stats_accuracy: PASS ({len(worst)} function/family pairs within budget)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
