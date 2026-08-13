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
#
# Strips // line comments and /* */ block comments (preserving line counts,
# by replacing each block comment's content with just its own embedded
# newlines, via perl) before matching "pipeline/" -- a bare substring match
# on the raw file also fires on prose in comments/docstrings that merely
# *mention* "pipeline/" while explaining the boundary itself (e.g. "this
# file must never import from pipeline/", or "pipeline/domain's own
# documented range"), which this codebase's comments do extensively and
# which are not real code references.
#
# An earlier version of this fix excluded whole lines whose trimmed content
# started with `//` or `*` -- that missed two real cases an adversarial
# review caught: (1) a real violation on the SAME line as a trailing
# comment (e.g. `import x from "pipeline/y"; // ...`), which a whole-line
# exclusion let through since the line also matched the comment-start
# pattern; (2) a real violation on a continuation line that happens to
# start with `*` for an unrelated reason (e.g. a multiplication operator
# spanning two lines: `x\n  * fetchWeight("pipeline/secret")`), which a
# bare `^\s*\*` heuristic cannot distinguish from a JSDoc continuation
# line. Stripping comment *content* rather than excluding whole *lines*
# closes both gaps: a real violation survives even next to a stripped
# comment on the same line, and a non-comment line is never touched by the
# stripping at all regardless of what character it starts with.
#
# Confirmed via tests/test_boundary_check.py, whose test_clean_tree_passes/
# test_a_clean_site_with_only_briefings_json_references_passes regressed
# silently across several stories once prose-in-comments became common,
# with nothing catching it until this fix (Story 4.6).
if [ -d site ]; then
  hits=""
  while IFS= read -r -d '' file; do
    file_hits=$(perl -0777 -pe 's{/\*.*?\*/}{ join("", ($& =~ /\n/g)) }gse' "$file" \
      | sed -E 's#//.*$##' \
      | grep -nE 'pipeline/' \
      | sed "s#^#${file}:#")
    if [ -n "$file_hits" ]; then
      hits="${hits}${hits:+$'\n'}${file_hits}"
    fi
  done < <(find site \
    \( -name node_modules -o -name dist -o -name .astro -o -name __pycache__ -o -name .venv \) -prune -o \
    \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.mjs' -o -name '*.astro' -o -name '*.svelte' \) \
    -type f -print0)
  if [ -n "$hits" ]; then
    report "site/ references pipeline/ by path" "$hits"
  fi
fi

# --- 4. site/ referencing an AI/embedding/ingestion provider (AD-1) ----------
# Story 3.6: the site's whole point is that it makes no AI, embedding, or
# ingestion call at build time or request time -- its only input is the
# static JSON the pipeline already wrote under data/briefings/. This is a
# tripwire for Epic 4 (which hasn't been built yet, so nothing fires today),
# not a claim that this list covers every future violation.
if [ -d site ]; then
  # Bare provider names, not narrower variants like "cohere_embed" or
  # "ANTHROPIC_API_KEY" -- a bare name already matches those (and any other
  # casing/punctuation variant, e.g. "cohere-embed") since this is a
  # case-insensitive substring search, and a narrower pattern only risks
  # missing a variant it didn't anticipate.
  hits=$(grep -rniE \
    'anthropic|cohere|gdelt|newsapi' \
    --include='*.ts' --include='*.tsx' --include='*.js' --include='*.mjs' \
    --include='*.astro' --include='*.svelte' "${EXCLUDE[@]}" \
    site 2>/dev/null || true)
  if [ -n "$hits" ]; then
    report "site/ references an AI/embedding/ingestion provider (AD-1)" "$hits"
  fi
fi

if [ "$violations" -gt 0 ]; then
  printf '\nBoundary check failed: %d violation(s).\n' "$violations"
  printf 'The pipeline writes data/briefings/; the site reads it. Nothing else crosses.\n\n'
  exit 1
fi

printf 'Boundary check passed: pipeline/ and site/ are independent.\n'
