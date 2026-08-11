#!/usr/bin/env bash
# Enforce the pipeline/site boundary (AD-2).
#
# The pipeline writes JSON to data/briefings/; the site reads it. Nothing else
# crosses. Neither half imports or reads the other's source.
#
# This is a cross-LANGUAGE boundary, which is why it is grep and not
# import-linter: site/ is TypeScript and cannot import Python, so a Python
# import graph analyzer would have nothing to analyze. Note also that a check
# for `import site` in Python would be worse than useless — `site` is a Python
# standard library module, so such a rule fires on legitimate code while
# catching none of the violations that can actually happen.
#
# Usage: scripts/check-boundary.sh
# Exits 0 when clean. Runs all three checks and reports every violation found
# before exiting 1 — it does not stop at the first one.

set -uo pipefail

violations=0

# Only our source. Vendored dependencies are not ours to police, and Astro in
# particular has its own internal "pipeline" concept whose imports would
# otherwise drown the signal in hundreds of false positives.
EXCLUDE=(
  --exclude-dir=node_modules
  --exclude-dir=dist
  --exclude-dir=.astro
  --exclude-dir=__pycache__
  --exclude-dir=.venv
)

report() {
  printf '\n  VIOLATION: %s\n' "$1"
  shift
  printf '%s\n' "$@" | sed 's/^/    /'
  violations=$((violations + 1))
}

# --- 1. Python in pipeline/ reading site files by path -----------------------
# The real Python-side violation mode: not an import, a filesystem read.
if [ -d pipeline ]; then
  hits=$(grep -rnE '''["'"'"']site/|["'"'"']site["'"'"']''' \
    --include='*.py' pipeline 2>/dev/null || true)
  if [ -n "$hits" ]; then
    report "pipeline/ references site/ by path" "$hits"
  fi
fi

# --- 2. site/ importing across the boundary ----------------------------------
if [ -d site ]; then
  hits=$(grep -rnE '''(import|from|require).*\.\./.*pipeline''' \
    --include='*.ts' --include='*.tsx' --include='*.js' --include='*.mjs' \
    --include='*.astro' --include='*.svelte' "${EXCLUDE[@]}" \
    site 2>/dev/null || true)
  if [ -n "$hits" ]; then
    report "site/ imports across the pipeline boundary" "$hits"
  fi
fi

# --- 3. site/ reading pipeline files by path ---------------------------------
# site/ may read data/briefings/ — that path contains no "pipeline/" substring,
# so it needs no allowance here.
if [ -d site ]; then
  hits=$(grep -rn 'pipeline/' \
    --include='*.ts' --include='*.tsx' --include='*.js' --include='*.mjs' \
    --include='*.astro' --include='*.svelte' "${EXCLUDE[@]}" \
    site 2>/dev/null || true)
  if [ -n "$hits" ]; then
    report "site/ references pipeline/ by path" "$hits"
  fi
fi

if [ "$violations" -gt 0 ]; then
  printf '\nBoundary check failed: %d violation(s).\n' "$violations"
  printf 'The pipeline writes data/briefings/; the site reads it. Nothing else crosses.\n\n'
  exit 1
fi

printf 'Boundary check passed: pipeline/ and site/ are independent.\n'
