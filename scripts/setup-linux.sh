#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

UV_VERSION="0.13.6"
PYTHON_VERSION="$(tr -d '[:space:]' < .python-version)"

usage() {
  cat <<'EOF'
Usage: ./scripts/setup-linux.sh [--install-uv] [--sync] [--test]
  --install-uv  Install the pinned uv version to ~/.local/bin.
  --sync        Download the pinned Python and sync all project groups.
  --test        Run Ruff, Pyright and pytest after syncing.
EOF
}

install_uv=0
sync=0
test=0
for arg in "$@"; do
  case "$arg" in
    --install-uv) install_uv=1 ;;
    --sync) sync=1 ;;
    --test) test=1; sync=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if (( install_uv )); then
  curl --proto '=https' --tlsv1.2 -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv ${UV_VERSION} is required. Run with --install-uv or install it manually." >&2
  exit 1
fi
if [[ "$(uv --version | awk '{print $2}')" != "$UV_VERSION" ]]; then
  echo "Expected uv ${UV_VERSION}; found $(uv --version)." >&2
  exit 1
fi

if (( sync )); then
  uv python install "$PYTHON_VERSION"
  uv lock
  uv sync --all-groups
fi

if (( test )); then
  uv run ruff check .
  uv run pyright
  uv run pytest
fi
