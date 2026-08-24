"""Symbol-aware chunking.

A chunk should be a thing a human would point at — a function, a class, a section of a
runbook — not an arbitrary N-line window. Boundaries are found with per-language symbol
regexes; a regex beats a parser here because it degrades gracefully on any language and
costs nothing to add a new one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hdh.fingerprint import EXT_LANG

MIN_LINES = 6
DEFAULT_MAX_LINES = 45
MAX_DOC_LINES = 80

_SYMBOL_SOURCES = (
    r"(?:async\s+)?def\s+(?P<py>\w+)",
    r"class\s+(?P<cls>\w+)",
    r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(?P<fn>\w+)",
    r"(?:export\s+)?(?:const|let|var)\s+(?P<arrow>\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>",
    r"func\s+(?:\([^)]*\)\s*)?(?P<go>\w+)",
    r"(?:pub\s+)?(?:async\s+)?fn\s+(?P<rs>\w+)",
    r"(?:export\s+)?(?:interface|type|struct|enum|impl|trait|module)\s+(?P<ty>\w+)",
    r"(?:public|private|protected|internal|static|final|abstract|\s)+"
    r"[\w<>\[\],.]+\s+(?P<jvm>\w+)\s*\([^;{]*\)\s*\{",
)
SYMBOL_RE = re.compile(r"^[ \t]{0,8}(?:" + "|".join(_SYMBOL_SOURCES) + r")")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*#*$")
DECORATOR_RE = re.compile(r"^[ \t]{0,8}[@\[]")

DOC_EXT = {".md", ".markdown", ".rst", ".txt", ".mdx", ".adoc"}


@dataclass(frozen=True)
class Chunk:
    path: str
    lang: str
    kind: str
    symbol: str
    start: int
    end: int
    body: str

    @property
    def ref(self) -> str:
        return f"{self.path}:{self.start}"


def lang_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in DOC_EXT:
        return "markdown"
    return EXT_LANG.get(suffix, "text")


def _symbol_at(line: str) -> str | None:
    m = SYMBOL_RE.match(line)
    if not m:
        return None
    return next((v for v in m.groupdict().values() if v), None)


def _emit(
    path: str, lang: str, kind: str, symbol: str, lines: list[str], start: int
) -> Chunk | None:
    body = "\n".join(lines).strip("\n")
    if not body.strip():
        return None
    return Chunk(path, lang, kind, symbol, start, start + len(lines) - 1, body)


def _chunk_code(
    path: str, lang: str, kind: str, lines: list[str], max_lines: int
) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    start = 1
    symbol = ""
    pending = ""

    for i, line in enumerate(lines, 1):
        found = _symbol_at(line)
        # A decorator/attribute run belongs to the symbol it precedes, not the one above.
        boundary = found and len(buf) >= MIN_LINES and not DECORATOR_RE.match(lines[i - 2] if i > 1 else "")
        if boundary or len(buf) >= max_lines:
            if chunk := _emit(path, lang, kind, symbol or pending, buf, start):
                chunks.append(chunk)
            buf, start, symbol = [], i, found or ""
        elif found and not symbol:
            symbol = found
        if found:
            pending = found
        buf.append(line)

    if chunk := _emit(path, lang, kind, symbol or pending, buf, start):
        chunks.append(chunk)
    return chunks


def _chunk_doc(path: str, kind: str, lines: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf: list[str] = []
    start = 1
    heading = ""
    trail = ""

    def has_body(block: list[str]) -> bool:
        """A heading with nothing under it is not a chunk — it would outrank real prose."""
        return any(x.strip() and not HEADING_RE.match(x) for x in block)

    for i, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if (m and has_body(buf)) or len(buf) >= MAX_DOC_LINES:
            if chunk := _emit(path, "markdown", kind, heading or trail, buf, start):
                chunks.append(chunk)
            buf, start = [], i
            heading = m.group(2) if m else trail
        elif m and not heading:
            heading = m.group(2)
        if m:
            trail = m.group(2)
        buf.append(line)

    if chunk := _emit(path, "markdown", kind, heading or trail, buf, start):
        chunks.append(chunk)
    return chunks


def chunk_text(
    rel_path: str,
    text: str,
    lang: str,
    kind: str = "code",
    max_lines: int = DEFAULT_MAX_LINES,
) -> list[Chunk]:
    lines = text.splitlines()
    if not lines:
        return []
    if lang == "markdown":
        return _chunk_doc(rel_path, kind, lines)
    return _chunk_code(rel_path, lang, kind, lines, max_lines)


def chunk_file(
    path: Path, root: Path, kind: str = "code", max_lines: int = DEFAULT_MAX_LINES
) -> list[Chunk]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()
    return chunk_text(rel, text, lang_for(path), kind, max_lines)
