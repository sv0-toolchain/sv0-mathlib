#!/usr/bin/env python3
"""Diagnostic (not yet a CI gate): checks whether the native VM bytecode
emitter (`build/sv0-megatu-vm-native`) produces byte-identical `.sv0b`
output across repeated invocations on the SAME input, on THIS machine.

Context: `scripts/run_fixture_parity.py`'s VM leg is advisory because a
`frac_floor_of_nonneg` contract abort shows up intermittently under
SML/NJ 110.99.9 (this repo's CI runner) even after fixing a real,
confirmed codec bug in sv0vm (BUGS.md, "Per-fixture value check") --
re-running CI against byte-identical toolchain commits produced one
clean pass and one abort. The leading remaining suspect, flagged since
2026-08-30 and never confirmed or ruled out, is that the native VM
emitter's own `.sv0b` output is nondeterministic (e.g. a hash-map/set
iteration order that isn't stable across process invocations) --
meaning the SAME sv0 source can legitimately compile to two different
(but both "valid") bytecode layouts, and only one of them happens to
trip a latent decode edge case.

This script tests that hypothesis directly, the same way the codec bug
itself was finally cracked: get real signal from the actual target
environment instead of reasoning about it. It re-invokes the emitter
N times against the SAME project and diffs the raw bytes. Ten
repeated local runs on this developer's own machine (arm64/macOS) came
back byte-identical every time -- if this script ALSO comes back clean
here in CI (ubuntu-22.04/amd64/SML-NJ-110.99.9, the actual environment
where the intermittent failure has been observed), that's real evidence
against the emitter-determinism theory and this project's own comment
in run_fixture_parity.py should be revisited; if it catches a mismatch,
the byte-offset report below is the concrete repro this bug has never
had.

Usage: python3 scripts/check_vm_emitter_determinism.py [--rounds N] [--toolchain-root DIR]
Exit 0 = every round produced byte-identical output; 1 = a mismatch
found (see stderr for the first differing byte offset and surrounding
context in both the majority and minority outputs); 2 = a hard failure
(missing emitter, a run itself failed).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def find_toolchain_root() -> Path:
    env = os.environ.get("SV0_TOOLCHAIN_ROOT")
    if env:
        return Path(env)
    if (HERE.parent / "sv0c").is_dir():
        return HERE.parent  # submodule of sv0-toolchain
    return HERE.parent / "sv0-toolchain"  # legacy sibling layout


def emit_once(emitter: Path, request: str) -> bytes:
    proc = subprocess.run([str(emitter)], capture_output=True,
                          env={**os.environ, "SV0_DRV_REQUEST": request})
    if proc.returncode != 0 or not proc.stdout:
        raise SystemExit(
            f"check_vm_emitter_determinism: emitter run failed (exit {proc.returncode}) "
            f"for request {request!r}:\n{proc.stderr.decode(errors='replace')}"
        )
    return proc.stdout


def first_diff(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n  # one is a strict prefix of the other


def hexdump_around(data: bytes, offset: int, radius: int = 16) -> str:
    lo = max(0, offset - radius)
    hi = min(len(data), offset + radius)
    chunk = data[lo:hi]
    return " ".join(f"{b:02x}" for b in chunk) + f"  (offset {lo}..{hi}, mismatch at {offset})"


def check_request(emitter: Path, request: str, rounds: int) -> bool:
    outputs = [emit_once(emitter, request) for _ in range(rounds)]
    digests = [hashlib.sha256(o).hexdigest() for o in outputs]
    counts = Counter(digests)
    if len(counts) == 1:
        print(f"check_vm_emitter_determinism: {request!r} — {rounds}/{rounds} "
              f"byte-identical ({outputs[0].__len__()} bytes, sha256={digests[0][:16]}...)")
        return True

    majority_digest, majority_n = counts.most_common(1)[0]
    majority_idx = digests.index(majority_digest)
    minority_idx = next(i for i, d in enumerate(digests) if d != majority_digest)
    print(f"check_vm_emitter_determinism: {request!r} — MISMATCH: "
          f"{len(counts)} distinct output(s) across {rounds} runs "
          f"({dict(counts)})", file=sys.stderr)
    off = first_diff(outputs[majority_idx], outputs[minority_idx])
    print(f"  first differing byte at offset {off} (comparing run #{majority_idx+1} "
          f"[majority] vs run #{minority_idx+1} [minority]):", file=sys.stderr)
    print(f"  majority: {hexdump_around(outputs[majority_idx], off)}", file=sys.stderr)
    print(f"  minority: {hexdump_around(outputs[minority_idx], off)}", file=sys.stderr)
    print(f"  lengths: majority={len(outputs[majority_idx])} "
          f"minority={len(outputs[minority_idx])}", file=sys.stderr)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--toolchain-root", type=Path, default=find_toolchain_root())
    args = ap.parse_args()

    emitter = args.toolchain_root / "build" / "sv0-megatu-vm-native"
    if not emitter.is_file():
        print(f"check_vm_emitter_determinism: missing {emitter} — build sv0-toolchain first",
              file=sys.stderr)
        return 2

    # sv0-mathlib itself (the project actually implicated in the observed
    # intermittent failure) plus a couple of the toolchain's own smaller
    # fixtures, in case the nondeterminism (if real) is size/shape-dependent.
    requests = [f"--project {HERE}"]
    small_fixtures = [
        args.toolchain_root / "sv0c" / "test" / "integration" / "contracts" / "contracts.sv0",
        args.toolchain_root / "sv0c" / "test" / "vm-parity" / "programs" / "vmf_f64_arith.sv0",
    ]
    for f in small_fixtures:
        if f.is_file():
            requests.append(str(f))

    ok = True
    for req in requests:
        if not check_request(emitter, req, args.rounds):
            ok = False

    if ok:
        print(f"check_vm_emitter_determinism: PASS ({len(requests)} request(s), "
              f"{args.rounds} rounds each, all byte-identical)")
        return 0
    print("check_vm_emitter_determinism: FAIL (see mismatch report(s) above)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
