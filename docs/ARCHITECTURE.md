# Architecture

## The thesis

A question like *"how do I map a list"* has no correct answer in the abstract. It has a
correct answer **in a repository** — one that depends on the language, the framework, the
pinned library versions, the linter rules, and whatever the team decided in a PR last spring.

`hdh` treats the repository as the missing half of the question. Everything in the design
follows from that.

## Pipeline

```
                 ┌──────────── all deterministic, no tokens spent ────────────┐
question ──▶ Fingerprint ──▶ Query expansion ──▶ Retrieval ──▶ Prompt assembly ──▶ Backend ──▶ Answer
             manifests +      keywords +          FTS5 BM25     fingerprint +       optional     + citations
             extensions       stack terms         + rerank      snippets + docs
```

The dotted region is pure functions over the filesystem: same inputs, same outputs, no
network, no credentials, no model. Only the final step can fail for reasons outside the
machine, and it is optional.

That split is the main architectural decision in the project. It buys three things:

1. **Testability** — the core claim is asserted in CI without an API key.
2. **Speed** — a fingerprint is ~50 ms; retrieval is a single SQLite query.
3. **A working floor** — with no backend at all, retrieval alone still answers usefully.

## Modules

| Module | Input | Output | Notes |
| --- | --- | --- | --- |
| `config.py` | cwd | `Config` | Walks up for a project marker; merges `.hdh/config.toml` and `HDH_*` env |
| `fingerprint.py` | repo root | `Fingerprint` | Extension histogram + 7 manifest parsers |
| `chunker.py` | file text | `list[Chunk]` | Symbol-aware boundaries, per-language regexes |
| `index.py` | chunks | SQLite FTS5 | Incremental by `(mtime, size)`; `bm25()` ranking |
| `retrieve.py` | question + fingerprint | `Retrieval` | Expansion, two-stage query, rerank |
| `answer.py` | `Retrieval` | prompt string | The only token-spending seam |
| `backends.py` | prompt | token stream | anthropic → claude-cli → offline |
| `render.py` | anything | terminal | Rich; degrades to plain for `--code` |
| `mcp_server.py` | MCP calls | JSON | Returns context, not answers |

## Design decisions

### FTS5 over embeddings

**Chosen:** SQLite FTS5 with `bm25()` ranking, from the standard library.

Embeddings are the reflexive choice for retrieval, and for prose they are usually right. For
code they are less obviously right and considerably more expensive to operate:

| | FTS5 | Embeddings |
| --- | --- | --- |
| Dependencies | none (stdlib) | vector store + model |
| Cold start | instant | model download or API round-trip |
| Cost per query | 0 | tokens or hosted service |
| Works offline | yes | usually not |
| Identifier matching (`with_retry`) | exact | approximate |
| Conceptual matching ("make it resilient") | weak | strong |

Code search is unusually keyword-shaped — people search for identifiers they half-remember,
and exact symbol matching is a feature rather than a limitation. The synonym layer in
`retrieve.SYNONYMS` covers the common conceptual gap ("map" → "comprehension", "transform")
at a fraction of the operational cost.

`Index.search()` is deliberately the only retrieval entry point, so a vector backend can be
added later behind the same signature without touching `retrieve.py` or above.

### Regex chunking over tree-sitter

**Chosen:** per-language symbol regexes in `chunker._SYMBOL_SOURCES`.

A parser gives exact boundaries for languages it supports and nothing for languages it
doesn't. A regex gives good boundaries everywhere and degrades to a fixed-size window on
syntax it doesn't recognise. Since a mis-placed boundary costs a little retrieval quality
rather than an exception, the failure modes favour the cheaper tool. Adding a language is one
line in a tuple, not a grammar dependency.

### Fingerprint terms widen, never rescue

An early version ORed the fingerprint terms into the main FTS query. A question with no real
matches then matched every file containing the word "python" and produced a confident,
grounded-looking, entirely irrelevant answer.

The rule now (`retrieve.retrieve`):

> Fingerprint terms may widen a thin result set. They may never rescue an empty one.

If the user's own keywords match nothing, `hdh` returns empty and says so. This is asserted by
`test_no_matches_is_not_an_error`.

### Credentials are never required

`OfflineBackend.available()` returns `True` unconditionally, and `backends.detect()` cannot
return `None`. Every feature must have a useful behaviour with no key and no CLI present.

`claude-cli` exists because the overlap between "developers who would like this" and
"developers with Claude Code already installed and authenticated" is large — and asking those
people for an API key they don't need is a needless barrier. CI runs the smoke test with
`ANTHROPIC_API_KEY` explicitly emptied so this path cannot silently rot.

### MCP returns context, not answers

The obvious MCP design exposes `ask(question) -> answer`, which would nest a model call
inside a tool the calling model invoked. `hdh mcp` instead exposes `project_context(question)`
returning the assembled fingerprint + snippets. The caller is already a model; giving it
grounded context is strictly better than giving it another model's summary of that context,
and it costs nothing.

## Data model

```python
Chunk(path, lang, kind, symbol, start, end, body)   # kind: "code" | "knowledge"
Hit(...same..., score)                              # score: raw bm25, negative-better
Retrieval(question, keywords, context_terms, code, knowledge, match_expr)
Fingerprint(languages, deps, frameworks, runtimes, tools, manifests, file_count)
```

`kind` is the only thing separating source from team documentation in the index. They compete
on the same ranking, and knowledge gets a modest boost plus an explicit "these outrank general
best practice" label in the prompt.

## Ranking

`bm25()` supplies the base score with symbol matches weighted 4× body matches. `retrieve._rerank`
then applies multiplicative adjustments:

| Signal | Factor | Why |
| --- | --- | --- |
| Language matches primary | ×1.6 | A Python answer in a Python repo |
| Markdown / text | ×1.15 | Prose explains intent |
| Symbol contains a keyword | ×1.4 | `with_retry` for "retry" |
| Test file, tests not asked about | ×0.55 | Tests are usually not the example wanted |
| Test file, tests asked about | ×1.25 | …unless they are |
| Team knowledge | ×1.3 | Internal beats general |

Then `_dedupe` caps hits per file so one large file can't monopolise the context window.

## Extending

**A language:** add the extension to `EXT_LANG`, a manifest parser to `MANIFESTS`
(`fingerprint.py`), and a symbol regex to `_SYMBOL_SOURCES` (`chunker.py`).

**A backend:** subclass `backends.Backend` with `available()`, `detail()` and `stream()`, then
add it to `backends.ORDER`. Ordering is capability-descending; the last entry must always be
unconditionally available.

**A retrieval strategy:** implement `search()` with the signature in `index.Index` and swap the
construction site. Nothing above `index.py` knows FTS5 exists.

## What this deliberately does not do

- **Rewrite your code.** It answers questions and cites; edits are yours.
- **Upload your repository.** Only the retrieved snippets reach a model, and only when a
  backend is configured. `--show-prompt` prints exactly what would be sent, and `--offline`
  sends nothing at all.
- **Guess at semantics it can't verify.** No call-graph analysis, no type inference. The
  fingerprint reports what the manifests actually say.
