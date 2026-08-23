#!/usr/bin/env bash
# Install sv0-mathlib git hooks.
#
# Uses git's `core.hooksPath` so the tracked scripts/git-hooks/ directory is the
# single source of truth — edits take effect immediately, no copies to keep in
# sync. Re-run any time (idempotent). Hooks are bypassable with `--no-verify`
# or `SV0_SKIP_HOOKS=1`. Mirrors sv0-toolchain's own install-git-hooks.sh.
#
# Usage: ./scripts/install-git-hooks.sh   (from anywhere; resolves its own root)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$ROOT/scripts/git-hooks"

[[ -d "$HOOKS_DIR" ]] || { echo "install-git-hooks: missing $HOOKS_DIR" >&2; exit 1; }
[[ -f "$HOOKS_DIR/commit-msg" ]] || { echo "install-git-hooks: missing commit-msg hook" >&2; exit 1; }
chmod +x "$HOOKS_DIR/commit-msg"
chmod +x "$ROOT/scripts/verify_commit_msg_no_ai_signoff.py"

git -C "$ROOT" config core.hooksPath scripts/git-hooks
echo "installed: core.hooksPath=scripts/git-hooks"

# Sanity: the AI-signoff verifier must pass its own corpus.
python3 "$ROOT/scripts/verify_commit_msg_no_ai_signoff.py" --selftest >/dev/null \
  && echo "verified: commit-msg AI-signoff checker selftest OK"

echo "done. hooks active: commit-msg (no AI sign-off)."
echo "bypass once with --no-verify, or all hooks with SV0_SKIP_HOOKS=1."
