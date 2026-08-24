# howdoi-here Conventions

## Adding a language

Language support is three small edits, all data rather than code:

1. Add the file extension to `EXT_LANG` in `src/hdh/fingerprint.py`.
2. Add its manifest parser to `MANIFESTS` in the same module.
3. Add a symbol regex to `_SYMBOL_SOURCES` in `src/hdh/chunker.py`.

Do not add a tree-sitter dependency for this. The regex approach degrades gracefully on
unknown syntax, and a wrong chunk boundary costs a little retrieval quality rather than
crashing the indexer.

## Retrieval invariants

Fingerprint terms may widen a thin result set, never rescue an empty one. If the user's
own keywords match nothing, returning everything tagged "python" is worse than returning
nothing — see `retrieve()` in `src/hdh/retrieve.py`.

## Backends

Never make a credential required. Every feature must degrade to something useful when no
API key and no Claude CLI are present. `OfflineBackend.available()` returns True
unconditionally and that is deliberate.
