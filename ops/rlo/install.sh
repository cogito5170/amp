#!/usr/bin/env bash
# Install rlo-sdk (0.8.1, pinned) into a private venv for the W1 guard. Idempotent.
# Owned by AMP / baseline (BD-183). W1 must not edit this file.
set -u
PIN="8131a2be206c732aa0e38fdbb7a1e650c1c331ca"
VENV="${AMP_RLO_VENV:-$HOME/.cache/amp-rlo-venv}"
MARK="$VENV/.pinned-$PIN"
[ -f "$MARK" ] && exit 0
PY="$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)"
"$PY" -m venv "$VENV" >/dev/null 2>&1 || exit 1
"$VENV/bin/pip" install -q "rlo-sdk[sensor] @ git+https://github.com/cogito5170/rlo-SDK@$PIN" >/dev/null 2>&1 || exit 1
"$VENV/bin/python" -c "import rlo.hooks" >/dev/null 2>&1 || exit 1
touch "$MARK"
