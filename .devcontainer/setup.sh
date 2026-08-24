#!/usr/bin/env bash
# Runs once when the Codespace is created.
set -euo pipefail

echo "==> Installing howdoi-here (this is the slow part, ~1-2 min)..."
pip install --no-cache-dir -e ".[dev,api,mcp]"

echo "==> Indexing this repository..."
hdh index || true

cat <<'BANNER'

  howdoi-here is installed and this repo is indexed.

  Try it on this codebase:
      hdh how do i add support for a new language
      hdh how do i rank search results --why

  Prove the premise -- same question, different stacks:
      hdh how do i map a list -C tests/fixtures/rails_project
      hdh how do i map a list -C tests/fixtures/ts_project

  Inspect without calling a model:
      hdh context          # what hdh thinks this project is
      hdh doctor           # which backend is active
      hdh <question> --show-prompt

  No API key is set, so answers come from `offline` mode: ranked snippets
  from the real code. For full AI answers, add ANTHROPIC_API_KEY as a
  Codespaces secret and rebuild -- everything else works unchanged.

BANNER
