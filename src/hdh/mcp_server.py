"""MCP server: expose the retrieval engine to any agent.

Design note: the MCP tools return *context*, not a synthesised answer. The caller is
already an LLM — handing it the fingerprint and the real snippets is strictly better than
nesting a second model call inside the tool, and it costs nothing.
"""

from __future__ import annotations

import json

from hdh import fingerprint
from hdh.answer import build_prompt
from hdh.config import Config
from hdh.index import Index
from hdh.index import build as build_index
from hdh.retrieve import retrieve


def _hit_dict(h) -> dict:  # noqa: ANN001
    return {
        "ref": h.ref, "path": h.path, "lines": [h.start, h.end],
        "symbol": h.symbol, "lang": h.lang, "kind": h.kind, "body": h.body,
    }


def serve(cfg: Config) -> None:
    # The SDK renamed its high-level server in 2.0; both generations are in the wild and
    # expose the same .tool()/.run() surface, so support whichever is installed.
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2.0
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server  # type: ignore[no-redef]  # mcp 1.x
        except ImportError as e:  # pragma: no cover
            raise SystemExit(
                "MCP support not installed. Install with: pip install 'howdoi-here[mcp]'"
            ) from e

    mcp = Server("howdoi-here")

    def _index() -> Index:
        index = Index(cfg.index_path)
        if not cfg.index_path.exists() or not index.counts():
            build_index(index, cfg.root, cfg.knowledge_dirs, cfg.exclude, cfg.chunk_lines)
        return index

    @mcp.tool()
    def project_fingerprint() -> str:
        """Detect this project's languages, frameworks, pinned dependency versions, and tooling."""
        return json.dumps(fingerprint.build(cfg.root, cfg.exclude).to_dict(), indent=2)

    @mcp.tool()
    def search_codebase(query: str, limit: int = 8, kind: str = "") -> str:
        """Search this project's code and team knowledge base. kind: '', 'code', or 'knowledge'."""
        fp = fingerprint.build(cfg.root, cfg.exclude)
        with _index() as index:
            r = retrieve(index, fp, query, limit, limit)
        hits = r.knowledge if kind == "knowledge" else r.code if kind == "code" else r.all_hits
        return json.dumps(
            {"query": query, "keywords": r.keywords, "context_terms": r.context_terms,
             "results": [_hit_dict(h) for h in hits]},
            indent=2,
        )

    @mcp.tool()
    def project_context(question: str, max_snippets: int = 6) -> str:
        """Assemble full grounded context for a question: fingerprint + repo snippets + team docs.

        Returns the same context block hdh would send to a model — use it to answer in this
        project's idiom rather than generically.
        """
        fp = fingerprint.build(cfg.root, cfg.exclude)
        with _index() as index:
            r = retrieve(index, fp, question, max_snippets, cfg.max_knowledge)
        return build_prompt(question, fp, r)

    @mcp.tool()
    def reindex(rebuild: bool = False) -> str:
        """Refresh the index after files change."""
        with Index(cfg.index_path) as index:
            stats = build_index(
                index, cfg.root, cfg.knowledge_dirs, cfg.exclude, cfg.chunk_lines, rebuild
            )
            counts = index.counts()
        return json.dumps({"changed_files": stats.files, "new_chunks": stats.chunks,
                           "removed": stats.removed, "totals": counts})

    mcp.run()
