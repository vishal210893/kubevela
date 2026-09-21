#!/usr/bin/env bash
# Resolves !include directives for local theme files and outputs
# self-contained .puml files ready for rendering.
#
# Usage:
#   ./build.sh                    # builds all .puml files under docs/architecture/
#   ./build.sh component/system-context.puml   # builds a single file
#
# Output goes to docs/architecture/.build/ mirroring the source structure.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/.build"

resolve_includes() {
  local src_file="$1"
  local src_dir
  src_dir="$(dirname "$src_file")"

  while IFS= read -r line; do
    # Match local !include (relative paths), skip stdlib includes like <C4/...>
    if [[ "$line" =~ ^[[:space:]]*\!include[[:space:]]+(\.\.?/.+)$ ]]; then
      local inc_path="${BASH_REMATCH[1]}"
      local resolved="${src_dir}/${inc_path}"
      if [[ -f "$resolved" ]]; then
        echo "' --- Begin included: ${inc_path} ---"
        cat "$resolved"
        echo ""
        echo "' --- End included: ${inc_path} ---"
      else
        echo "' WARNING: Could not resolve include: ${inc_path}"
        echo "$line"
      fi
    else
      echo "$line"
    fi
  done < "$src_file"
}

build_file() {
  local src_file="$1"
  local rel_path="${src_file#"${SCRIPT_DIR}/"}"
  local out_file="${BUILD_DIR}/${rel_path}"

  mkdir -p "$(dirname "$out_file")"
  resolve_includes "$src_file" > "$out_file"
  echo "  Built: .build/${rel_path}"
}

# Clean previous build
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

if [[ $# -gt 0 ]]; then
  # Build specific file(s)
  for arg in "$@"; do
    src="${SCRIPT_DIR}/${arg}"
    if [[ -f "$src" ]]; then
      build_file "$src"
    else
      echo "Error: ${arg} not found" >&2
      exit 1
    fi
  done
else
  # Build all .puml files (excluding theme and .build dir)
  find "$SCRIPT_DIR" -name '*.puml' -not -path '*/.build/*' -not -name 'guidewire-theme.puml' | sort | while read -r f; do
    build_file "$f"
  done
fi

echo ""
echo "Output: docs/architecture/.build/"
echo "Render with: plantuml docs/architecture/.build/**/*.puml"
