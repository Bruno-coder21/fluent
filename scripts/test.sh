#!/usr/bin/env bash
# Run fluent's tests in a throwaway uv environment (nothing is installed in the repo).
# Uses Hermes's managed Python 3.14 when it is available, so tests match the runtime.
set -euo pipefail
cd "$(dirname "$0")/.."
HERMES_PY="$(ls -d "${HERMES_HOME:-$HOME/.hermes}"/tools/python-3.14*/bin/python3 2>/dev/null | head -1 || true)"
PY="${FLUENT_PY:-${HERMES_PY:-3.14}}"
export PYTHONDONTWRITEBYTECODE=1
exec uv run --no-project --python "$PY" --with "pytest>=8,<10" \
  python -m pytest -q -p no:cacheprovider "$@"
