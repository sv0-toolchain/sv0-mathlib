#!/usr/bin/env python3
"""Diagnostic (not yet a CI gate): checks whether `sv0vm` (the SML/NJ
bytecode interpreter) produces a consistent result across repeated runs
of the SAME, FIXED `.sv0b` file.

scripts/check_vm_emitter_determinism.py already tested the other half
of this question and got a clean negative on this repo's own CI runner
(ubuntu-22.04/amd64/SML-NJ-110.99.9): the native VM emitter's `.sv0b`
output is byte-identical across 30 repeated invocations, for sv0-mathlib
itself and two smaller sv0c fixtures. That rules out "the bytecode
itself varies between builds" as the source of the intermittent
`frac_floor_of_nonneg` abort in scripts/run_fixture_parity.py's VM leg
(BUGS.md, "Per-fixture value check") -- at least for those inputs, in a
single CI job's environment.

If the bytecode is provably stable, but running it through `sv0vm`
still sometimes gives a different result, the remaining source has to
be in EXECUTION, not emission: something in the interpreter itself
(src/interpreter/interpreter.sml) that isn't deterministic given
identical input -- GC-timing-dependent behavior, an uninitialized read,
a stateful global reused incorrectly across VM stack frames, etc.

This script builds the EXACT program scripts/run_fixture_parity.py
would check (reusing its own `generate()` so this isn't a different,
weaker repro) once, holds the resulting `.sv0b` bytes fixed, and runs
`sv0vm` against that SAME file N times, comparing exit codes and
(for a `sv0 contract violation`) the violation message.

Usage: python3 scripts/check_vm_interpreter_determinism.py [--rounds N] [--toolchain-root DIR]
Exit 0 = every round agreed; 1 = a divergence found; 2 = a hard failure.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "scripts"))
import run_fixture_parity as rfp  # noqa: E402 -- reuse its exact program generator


def find_toolchain_root() -> Path:
    env = os.environ.get("SV0_TOOLCHAIN_ROOT")
    if env:
        return Path(env)
    if (HERE.parent / "sv0c").is_dir():
        return HERE.parent
    return HERE.parent / "sv0-toolchain"


def build_fixed_sv0b(toolchain_root: Path, tmp: Path) -> Path:
    with (rfp.FIXTURES / "rounding.csv").open() as f:
        rounding_rows = list(csv.DictReader(f))
    with (rfp.FIXTURES / "trig.csv").open() as f:
        trig_rows = list(csv.DictReader(f))
    src, checks, skipped = rfp.generate(rounding_rows, trig_rows)
    project = rfp.stage_project(src, tmp)

    emitter = toolchain_root / "build" / "sv0-megatu-vm-native"
    if not emitter.is_file():
        raise SystemExit(f"check_vm_interpreter_determinism: missing {emitter}")
    b_path = tmp / "fixed.sv0b"
    proc = subprocess.run([str(emitter)], stdout=b_path.open("wb"), stderr=subprocess.PIPE,
                          env={**os.environ, "SV0_DRV_REQUEST": f"--project {project}"})
    if proc.returncode != 0 or b_path.stat().st_size == 0:
        raise SystemExit(f"check_vm_interpreter_determinism: emit-vm failed:\n"
                         f"{proc.stderr.decode(errors='replace')}")
    print(f"check_vm_interpreter_determinism: built fixed .sv0b ({b_path.stat().st_size} bytes, "
          f"{len(checks)} checks, {len(skipped)} skipped)")
    return b_path


def run_once(toolchain_root: Path, b_path: Path, trace: bool = False) -> tuple[str, str]:
    sv0vm = toolchain_root / "sv0vm"
    env = {**os.environ, "SV0B": str(b_path)}
    if trace:
        env["SV0VM_TRACE_F64"] = "1"
    proc = subprocess.run(["sml"], stdin=(sv0vm / "scripts" / "run_sv0b.sml").open(),
                          capture_output=True, text=True, cwd=sv0vm, env=env)
    out = proc.stdout + proc.stderr
    if trace:
        trace_path = Path(tempfile.gettempdir()) / "vm_interpreter_trace.log"
        lines = [ln for ln in out.splitlines() if ln.startswith("SV0VM_TRACE ")]
        trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
        print(f"check_vm_interpreter_determinism: trace captured ({len(lines)} f64 ops, "
              f"sha256={digest}) -> {trace_path}")
    cv = re.search(r"sv0 contract violation: (.+)", out)
    m = re.search(r"vm_exit:(-?\d+)", out)
    if cv:
        return ("CONTRACT_VIOLATION", cv.group(1).strip())
    if m:
        return ("EXIT", m.group(1))
    return ("NO_EXIT", out[-300:])


def print_host_info() -> None:
    """Correlating signal for the leading theory (a CPU-feature-dependent
    difference in SML/NJ's own generated machine code): if a divergence
    is ever caught, knowing which physical host produced it -- not just
    that SOME job did -- is what would actually confirm or kill that
    theory, since GitHub's runner fleet is not guaranteed to be uniform
    hardware. Best-effort; never fails the run if unavailable."""
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        model = next((ln.split(":", 1)[1].strip() for ln in cpuinfo.splitlines()
                     if ln.startswith("model name")), "unknown")
        flags_line = next((ln for ln in cpuinfo.splitlines() if ln.startswith("flags")), "")
        flags = set(flags_line.split(":", 1)[1].split()) if ":" in flags_line else set()
        fp_flags = sorted(f for f in flags if f in
                          {"fma", "avx", "avx2", "avx512f", "sse4_1", "sse4_2"})
        print(f"check_vm_interpreter_determinism: host CPU model={model!r} "
              f"fp-relevant-flags={fp_flags}")
    except Exception as e:  # noqa: BLE001 -- best-effort diagnostic, never fatal
        print(f"check_vm_interpreter_determinism: host CPU info unavailable ({e})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--toolchain-root", type=Path, default=find_toolchain_root())
    args = ap.parse_args()

    print_host_info()
    with tempfile.TemporaryDirectory(prefix="sv0mathlib_vmdet_") as tmp:
        b_path = build_fixed_sv0b(args.toolchain_root, Path(tmp))
        results = [run_once(args.toolchain_root, b_path) for _ in range(args.rounds)]
        # One additional TRACED run, kept separate from the N above so the
        # extra stderr I/O tracing does can't itself perturb the timing-
        # sensitive measurement those N rounds are trying to characterize.
        # Its own result/hash is printed regardless of pass/fail below --
        # this is the artifact to pull and diff between a failing CI job
        # and a passing one (see BUGS.md).
        traced_result = run_once(args.toolchain_root, b_path, trace=True)
        print(f"check_vm_interpreter_determinism: traced run result: {traced_result}")

    counts = Counter(results)
    if len(counts) == 1:
        kind, detail = results[0]
        print(f"check_vm_interpreter_determinism: {args.rounds}/{args.rounds} agree "
              f"({kind}{': ' + detail if kind != 'EXIT' else ' ' + detail})")
        print("check_vm_interpreter_determinism: PASS")
        return 0

    print(f"check_vm_interpreter_determinism: MISMATCH — {len(counts)} distinct result(s) "
          f"across {args.rounds} runs of the SAME fixed .sv0b file:", file=sys.stderr)
    for (kind, detail), n in counts.most_common():
        print(f"  {n:3d}x  {kind}: {detail}", file=sys.stderr)
    print("check_vm_interpreter_determinism: FAIL — the interpreter itself is "
          "nondeterministic given identical bytecode", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
