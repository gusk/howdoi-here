from __future__ import annotations

from hdh import chunker

PY = '''\
import os


def alpha(a, b):
    """First."""
    total = a + b
    for i in range(10):
        total += i
    return total


class Beta:
    def gamma(self):
        return 1

    def delta(self):
        return 2
'''

TS = """\
export interface User {
  id: number;
}

export function loadUsers(rows) {
  return rows.map((r) => r.id);
}

export const activeEmails = (users) => users.filter((u) => u.ok);
"""

MD = """\
# Title

Intro text.

## Collections

Use comprehensions, never map().

## HTTP

Always retry.
"""


def test_symbols_are_recognised_across_languages() -> None:
    assert chunker._symbol_at("def alpha(a, b):") == "alpha"
    assert chunker._symbol_at("class Beta:") == "Beta"
    assert chunker._symbol_at("export function loadUsers(rows) {") == "loadUsers"
    assert chunker._symbol_at("const go = async (x) => {") == "go"
    assert chunker._symbol_at("func (s *Server) Handle(w http.ResponseWriter) {") == "Handle"
    assert chunker._symbol_at("pub async fn fetch(url: &str) {") == "fetch"
    assert chunker._symbol_at("export interface User {") == "User"
    assert chunker._symbol_at("    total = a + b") is None


def test_code_chunks_carry_symbols_and_line_numbers() -> None:
    chunks = chunker.chunk_text("m.py", PY, "python")
    assert chunks
    assert {c.symbol for c in chunks} & {"alpha", "Beta", "gamma", "delta"}
    for c in chunks:
        assert c.start >= 1 and c.end >= c.start
        assert c.lang == "python" and c.kind == "code"
    assert chunks[0].ref.startswith("m.py:")


def test_chunks_cover_the_file_without_gaps() -> None:
    chunks = chunker.chunk_text("m.py", PY, "python")
    assert chunks[0].start == 1
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        assert nxt.start == prev.end + 1


def test_typescript_chunking() -> None:
    chunks = chunker.chunk_text("t.ts", TS, "typescript")
    assert any("loadUsers" in c.body for c in chunks)
    assert all(c.lang == "typescript" for c in chunks)


def test_markdown_splits_on_headings() -> None:
    chunks = chunker.chunk_text("k.md", MD, "markdown", kind="knowledge")
    symbols = [c.symbol for c in chunks]
    assert "Collections" in symbols
    assert "HTTP" in symbols
    assert all(c.kind == "knowledge" for c in chunks)


def test_max_lines_is_respected() -> None:
    body = "\n".join(f"x{i} = {i}" for i in range(200))
    chunks = chunker.chunk_text("big.py", body, "python", max_lines=20)
    assert len(chunks) >= 10
    assert all(c.end - c.start < 20 for c in chunks)


def test_empty_and_whitespace_input() -> None:
    assert chunker.chunk_text("e.py", "", "python") == []
    assert chunker.chunk_text("e.py", "\n\n\n", "python") == []


def test_lang_for_extensions(tmp_path) -> None:  # noqa: ANN001
    assert chunker.lang_for(tmp_path / "a.py") == "python"
    assert chunker.lang_for(tmp_path / "a.tsx") == "typescript"
    assert chunker.lang_for(tmp_path / "a.md") == "markdown"
    assert chunker.lang_for(tmp_path / "a.unknown") == "text"
