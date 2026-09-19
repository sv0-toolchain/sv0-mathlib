#!/usr/bin/env python3
"""Fixture provenance gate for test/fixtures/random.csv: recompiles the
independent C oracle (docs/random_oracle.c), runs it, and fails if its
output differs from the checked-in CSV. Pure C, deterministic, no sv0
toolchain needed. To refresh after an intentional change:
  cc -std=c99 -O0 docs/random_oracle.c -o /tmp/random_oracle && /tmp/random_oracle > test/fixtures/random.csv
Exit 0 = CSV matches the oracle; 1 = drift; 2 = the oracle failed to build/run."""

from __future__ import annotations

import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def main() -> int:
    csv_path = HERE / "test" / "fixtures" / "random.csv"
    with tempfile.TemporaryDirectory(prefix="sv0mathlib_randoracle_") as tmp:
        exe = Path(tmp) / "random_oracle"
        cc = subprocess.run(["cc", "-std=c99", "-O0", "-w", str(HERE / "docs" / "random_oracle.c"),
                             "-o", str(exe)], capture_output=True, text=True)
        if cc.returncode != 0:
            print(f"check_random_oracle: oracle failed to compile:\n{cc.stderr}", file=sys.stderr)
            return 2
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        if run.returncode != 0:
            print(f"check_random_oracle: oracle exited {run.returncode}:\n{run.stderr}", file=sys.stderr)
            return 2
    want = csv_path.read_text(encoding="utf-8")
    if run.stdout == want:
        print(f"check_random_oracle: PASS ({want.count(chr(10)) - 1} rows match the C oracle)")
        return 0
    diff = difflib.unified_diff(want.splitlines(), run.stdout.splitlines(),
                                "test/fixtures/random.csv", "docs/random_oracle.c output", lineterm="")
    print("check_random_oracle: FAIL — random.csv drifted from the oracle:", file=sys.stderr)
    print("\n".join(list(diff)[:40]), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
