#!/usr/bin/env bash
# Install rlo-sdk (stage-8, pinned) into a private venv for the W1 guard. Idempotent.
# Owned by AMP / baseline (BD-183). W1 must not edit this file.
set -u
PIN="9af276f4e4864274a6414794aad55a8c1e5bcf19"
VENV="${AMP_RLO_VENV:-$HOME/.cache/amp-rlo-venv}"
MARK="$VENV/.pinned-$PIN"
[ -f "$MARK" ] && exit 0
PY="$(command -v python3.12 || command -v python3.11 || command -v python3.10 || command -v python3)"
"$PY" -m venv "$VENV" >/dev/null 2>&1 || exit 1
"$VENV/bin/pip" install -q "rlo-sdk[sensor] @ git+https://github.com/cogito5170/rlo-SDK@$PIN" >/dev/null 2>&1 || exit 1
"$VENV/bin/python" -c "import rlo.hooks" >/dev/null 2>&1 || exit 1
touch "$MARK"
