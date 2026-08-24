# howdoi-here

**`howdoi`, but it knows what repo you're standing in.**

[![CI](https://github.com/gusk/howdoi-here/actions/workflows/ci.yml/badge.svg)](https://github.com/gusk/howdoi-here/actions/workflows/ci.yml)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/gusk/howdoi-here)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

The original [`howdoi`](https://github.com/gleitz/howdoi) scraped Stack Overflow and printed
the top answer. It was great, and it had one structural flaw: it had no idea what you were
working on. Ask it how to map a list and it answers for *a* language, not *your* language —
and it has never heard of the convention your team argued about in a PR six months ago.

`hdh` fixes that. It reads your manifests to learn the stack, indexes your actual source and
your team's internal docs, and answers in the idiom of the codebase you're sitting in —
citing real files and real line numbers.

```console
$ hdh how do i map a list of rows into models

  ruby 3.3.4 · Rails · Faraday · Puma · RSpec · RuboCop — from Gemfile · via claude-cli

  Already solved — use UserImporter.call, which is exactly this:
  rows.map { |row| User.new(...) } (app/services/user_importer.rb:1).
  Build with User.new so validations run; only drop to insert_all
  (UserImporter.import!, app/services/user_importer.rb:15) on bulk paths already
  validated upstream. No for loops — Style/For fails the build.

      users = UserImporter.call(rows)
      # => rows.map { |row| User.new(id: row[:id].to_i, email: row[:email].downcase) }

      # Adding a field? Extend the map in UserImporter.call, e.g.:
      def self.call(rows)
        rows.map do |row|
          User.new(id: row[:id].to_i, email: row[:email].downcase, name: row[:name]&.strip)
        end
      end

  If you need a lookup Hash keyed off the rows instead of a list, use
  each_with_object({}), not reduce/inject.

  Sources: app/services/user_importer.rb:1, app/services/user_importer.rb:15,
  .hdh/knowledge/ruby-style.md:1
```

Nothing in that answer is generic. `UserImporter.call` and `import!` came from the repo. The
`User.new`-over-`insert_all` rule, the `Style/For` ban and the `each_with_object` preference
over `reduce` all came from the team's own knowledge base — none of them are things a model
would otherwise know about ACME. Run the same command in a TypeScript project and you get
`Array.map()` and `Vitest`, because that's what that repo is.

---

## No API key required. Ever.

This is a hard design constraint, not a nice-to-have. `hdh` picks the best backend available
and always has a floor that works with nothing at all:

| Priority | Backend      | Requires                          | You get                            |
| -------- | ------------ | --------------------------------- | ---------------------------------- |
| 1        | `anthropic`  | `ANTHROPIC_API_KEY` (if you have one) | Streamed answers via the SDK    |
| 2        | `claude-cli` | [Claude Code](https://claude.com/claude-code) installed | Full answers using its existing auth — **no key of your own** |
| 3        | `offline`    | *nothing*                         | Ranked snippets from your repo + team docs |

Check where you stand:

```console
$ hdh doctor
┌─ backends ──────────────────────────────────────────────────────────┐
│ backend              status       detail                            │
│ anthropic            unavailable  no ANTHROPIC_API_KEY in environment│
│ claude-cli (active)  ready        /usr/bin/claude · --model opus     │
│ offline              ready        retrieval only · no synthesis      │
└─────────────────────────────────────────────────────────────────────┘
  code chunks: 142 · knowledge chunks: 9
```

Offline mode isn't a degraded stub — contextual code search over your own repo is genuinely
useful on its own, and it's what keeps the test suite deterministic and the CI run free.

## Try it without installing anything

Click **[Open in GitHub Codespaces](https://codespaces.new/gusk/howdoi-here)**. You get a
browser terminal with `hdh` installed and this repo already indexed — nothing lands on your
machine, and it runs on your own free Codespaces quota, not the maintainer's.

**First boot takes a couple of minutes** while it pulls the image, installs the package and
builds the index. It isn't stuck; the terminal prints a banner when it's ready. Subsequent
starts are quick.

The banner lists what to run; the fastest way to see the point is:

```bash
hdh how do i map a list -C tests/fixtures/rails_project  # → rows.map { User.new }, RSpec, RuboCop
hdh how do i map a list -C tests/fixtures/ts_project     # → Array.map(), Vitest, ESLint
```

Same question. Different repo. Different answer — which is the entire idea.

A Codespace has no API key, so it runs in `offline` mode: real ranked snippets from real code,
no model. That's enough to evaluate the retrieval, and `--why` shows precisely what was
matched. For full AI answers, add `ANTHROPIC_API_KEY` as a
[Codespaces secret](https://docs.github.com/en/codespaces/managing-your-codespaces/managing-your-account-specific-secrets-for-your-codespaces)
and rebuild; nothing else changes.

## Install

Requires **Python 3.11+**. No API key, no account, no services.

```bash
git clone https://github.com/gusk/howdoi-here && cd howdoi-here

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install .
hdh doctor                       # confirm it works
```

Then ask it something — from this repo, or any other project on your machine:

```bash
hdh how do i retry a failed request
cd ~/some/other/project && hdh how do i map a list
```

The index builds itself on first use and updates incrementally after that.

Optional extras: `pip install ".[api]"` for the Anthropic SDK backend, `".[mcp]"` for the
MCP server, `".[dev]"` for the test suite.

> **If `hdh` isn't found**, your Python scripts directory isn't on `PATH`. Either activate a
> venv as above, or use the equivalent module form: `python -m hdh how do i map a list`.

## Usage

```bash
hdh how do i paginate a query        # bare words — no quotes, like howdoi
hdh "how do I paginate a query"      # quotes fine too

hdh <question> --why                 # show exactly what context was used
hdh <question> --offline             # skip the model entirely
hdh <question> --code                # print just the code block
hdh <question> --copy                # copy the answer to the clipboard
hdh <question> --show-prompt         # print the assembled prompt, call nothing
hdh <question> -C ../other-repo      # ask about a different project

hdh context [--json]                 # what hdh thinks this project is
hdh search <terms>                   # retrieval only
hdh index [--rebuild]                # refresh the index
hdh doctor                           # backend + index status
hdh mcp                              # serve to agents over MCP
```

`--why` is the honesty flag. It shows the keywords, the fingerprint terms, the FTS query and
every chunk that was retrieved with its score — so you can see whether an answer was grounded
or improvised:

```console
$ hdh how do i map a list of rows into models --why
┌─ why this answer ───────────────────────────────────────────────┐
│ question        how do i map a list of rows into models         │
│ keywords        map, list, rows, models                         │
│ context terms   ruby, rails, faraday, puma, sidekiq             │
│ code hits       4                                               │
│ knowledge hits  1                                               │
│ prompt chars    2010                                            │
└─────────────────────────────────────────────────────────────────┘
  K1 .hdh/knowledge/ruby-style.md:1                    score 1.32
  C1 app/services/user_importer.rb:1   UserImporter    score 4.48
  C2 app/services/user_importer.rb:15  self            score 3.89
  C3 app/clients/acme_client.rb:1      AcmeClient      score 0.93
```

## Team knowledge base

This is what makes it worth deploying past one laptop. Drop markdown into
`.hdh/knowledge/`, or point at a shared docs repo:

```toml
# .hdh/config.toml
knowledge_paths = ["docs", "../platform-runbooks"]
```

Internal docs are indexed alongside code and are explicitly labelled in the prompt as
outranking general best practice — so "all outbound HTTP goes through `AcmeClient.connection`"
beats whatever the model would otherwise have said about Faraday. Answers cite the doc by
path and line, which
means a wrong answer points at the doc that needs fixing.

Because knowledge sources are just directories, a team can keep one canonical repo of
conventions, runbooks and architecture decisions, and every engineer's `hdh` inherits it.

## MCP server

`hdh mcp` exposes the same engine to Claude Code and any other MCP client:

| Tool                  | Returns                                                         |
| --------------------- | --------------------------------------------------------------- |
| `project_fingerprint` | Languages, frameworks, pinned versions, tooling                  |
| `search_codebase`     | Ranked chunks from code and team docs                            |
| `project_context`     | The full assembled context block for a question                  |
| `reindex`             | Refresh after files change                                       |

```json
{ "mcpServers": { "howdoi-here": { "command": "hdh", "args": ["mcp"] } } }
```

These tools return **context, not answers**. The caller is already a model — handing it the
fingerprint and the real snippets beats nesting a second model call inside the tool, and
costs nothing.

## How it works

```
question ──▶ Fingerprint ──▶ Query expansion ──▶ Retrieval ──▶ Prompt ──▶ Backend ──▶ Answer
              manifests       + stack terms       BM25 rerank   assembly    (optional)  + citations
              (no LLM)        (no LLM)            (no LLM)      (no LLM)
```

| Module           | Responsibility                                                                |
| ---------------- | ----------------------------------------------------------------------------- |
| `fingerprint.py` | Parses `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `Gemfile`, `pom.xml`, `*.csproj` → languages, frameworks, **pinned versions**, test runner, linter |
| `chunker.py`     | Symbol-aware chunking — splits at function/class/heading boundaries            |
| `index.py`       | SQLite **FTS5** + `bm25()`, incremental by mtime+size                          |
| `retrieve.py`    | Expands the query with fingerprint terms, reranks by language/symbol/kind      |
| `answer.py`      | Assembles the prompt — the only module that can spend a token                  |
| `backends.py`    | anthropic → claude-cli → offline, auto-detected                                |
| `mcp_server.py`  | The same engine, exposed to agents                                             |

### Three decisions worth defending

**FTS5 instead of embeddings.** SQLite's full-text search ships in the Python standard
library. No vector database, no embedding API, no 200 MB wheel, no cold-start download, no
per-query cost. For keyword-shaped code search it is competitive with vectors, and it means
`hdh` works the second it's installed and keeps working on a plane. `Index.search()` is the
seam — a vector backend can implement the same signature without touching a caller.

**Deterministic context, probabilistic answer.** Everything before `answer.py` is pure
functions over the filesystem. That makes the interesting part fast, cacheable, and unit
testable without an API key — which is why CI can assert the core claim on every push:

```python
def test_three_stacks_retrieve_disjoint_context(
    rails_project, py_project, ts_project, tmp_path
):
    """One question, three repos, no overlap in what reaches the model."""
    assert langs == [{"ruby"}, {"python"}, {"typescript"}]
    assert not set.intersection(*langs)
```

**Fingerprint terms widen, never rescue.** If your own keywords match nothing, matching
everything tagged `python` is not an answer — it's a confident wrong one. `hdh` returns empty
instead, and says so.

## Configuration

All optional; see [`.hdh/config.toml`](.hdh/config.toml).

```toml
backend = "auto"                  # or "anthropic" | "claude-cli" | "offline"
model = "claude-opus-5"
max_snippets = 6
knowledge_paths = ["docs"]
exclude = []
```

Environment overrides: `HDH_BACKEND`, `HDH_MODEL`, `HDH_CLI_MODEL`.

## Development

```bash
pip install -e ".[dev,api,mcp]"
pytest -q          # 66 tests, no credentials needed
ruff check .
mypy
```

CI runs the suite on Python 3.11/3.12/3.13 (plus Windows and macOS on 3.13), and smoke-tests
the CLI with `ANTHROPIC_API_KEY` explicitly emptied to guarantee the no-credentials path
never rots.

## License

MIT — see [LICENSE](LICENSE).
