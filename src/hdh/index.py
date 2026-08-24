"""SQLite FTS5 index over code chunks and team knowledge.

Why not embeddings: FTS5 ships in the Python stdlib, needs no API key, no model download,
and no service. Cold start is instant and it works on a plane. `Searcher` is the seam --
a vector backend can implement the same `search()` signature without touching callers.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from hdh.chunker import DOC_EXT, Chunk, chunk_file, lang_for
from hdh.fingerprint import EXT_LANG, IGNORE_DIRS

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    digest TEXT NOT NULL,
    kind TEXT NOT NULL,
    lang TEXT NOT NULL,
    chunks INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    path UNINDEXED,
    lang UNINDEXED,
    kind UNINDEXED,
    symbol,
    body,
    start_line UNINDEXED,
    end_line UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

# bm25 takes one weight per column; symbol matches count for more than body matches.
BM25_WEIGHTS = (0.0, 0.0, 0.0, 4.0, 1.0, 0.0, 0.0)

INDEXABLE_EXT = set(EXT_LANG) | DOC_EXT
MAX_FILE_BYTES = 400_000


@dataclass
class Hit:
    path: str
    lang: str
    kind: str
    symbol: str
    body: str
    start: int
    end: int
    score: float

    @property
    def ref(self) -> str:
        return f"{self.path}:{self.start}"


@dataclass
class IndexStats:
    files: int = 0
    chunks: int = 0
    skipped: int = 0
    removed: int = 0


# The index holds the full text of the user's source. Committing it would leak a whole
# codebase as an opaque blob, so the index directory ignores its own database. Config and
# knowledge/ are deliberately left committable -- sharing those is the point.
SELF_IGNORE = "index.db\nindex.db-*\ncache/\n"


def _self_ignore(hdh_dir: Path) -> None:
    ignore = hdh_dir / ".gitignore"
    try:
        if not ignore.exists():
            ignore.write_text(SELF_IGNORE, encoding="utf-8")
    except OSError:
        pass


def _digest(path: Path) -> str:
    st = path.stat()
    return hashlib.blake2b(f"{st.st_mtime_ns}:{st.st_size}".encode(), digest_size=8).hexdigest()


class Index:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _self_ignore(db_path.parent)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Index:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- writing ---------------------------------------------------------

    def _replace(self, rel: str, digest: str, kind: str, lang: str, chunks: list[Chunk]) -> None:
        self.conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
        self.conn.executemany(
            "INSERT INTO chunks (path, lang, kind, symbol, body, start_line, end_line)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(c.path, c.lang, c.kind, c.symbol, c.body, c.start, c.end) for c in chunks],
        )
        self.conn.execute(
            "INSERT INTO files (path, digest, kind, lang, chunks) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(path) DO UPDATE SET digest=excluded.digest, kind=excluded.kind,"
            " lang=excluded.lang, chunks=excluded.chunks",
            (rel, digest, kind, lang, len(chunks)),
        )

    def drop(self, rel: str) -> None:
        self.conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))
        self.conn.execute("DELETE FROM files WHERE path = ?", (rel,))

    def known(self) -> dict[str, str]:
        return {r["path"]: r["digest"] for r in self.conn.execute("SELECT path, digest FROM files")}

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT kind, COUNT(*) n FROM chunks GROUP BY kind")
        return {r["kind"]: r["n"] for r in rows}

    # -- reading ---------------------------------------------------------

    def search(
        self, match: str, limit: int = 20, kind: str | None = None, lang: str | None = None
    ) -> list[Hit]:
        sql = (
            "SELECT path, lang, kind, symbol, body, start_line, end_line,"
            " bm25(chunks, ?, ?, ?, ?, ?, ?, ?) AS score"
            " FROM chunks WHERE chunks MATCH ?"
        )
        params: list[object] = [*BM25_WEIGHTS, match]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if lang:
            sql += " AND lang = ?"
            params.append(lang)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
        return [
            Hit(
                r["path"], r["lang"], r["kind"], r["symbol"], r["body"],
                r["start_line"], r["end_line"], r["score"],
            )
            for r in rows
        ]


def _walk(root: Path, exclude: set[str]) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and d not in exclude and not d.startswith(".")
        ]
        for fn in filenames:
            if Path(fn).suffix.lower() in INDEXABLE_EXT:
                out.append(Path(dirpath) / fn)
    return out


def build(
    index: Index,
    root: Path,
    knowledge_dirs: list[Path] | None = None,
    exclude: list[str] | None = None,
    max_lines: int = 45,
    rebuild: bool = False,
) -> IndexStats:
    """Incremental by (mtime, size); `rebuild=True` forces a full reindex."""
    stats = IndexStats()
    if rebuild:
        index.conn.execute("DELETE FROM chunks")
        index.conn.execute("DELETE FROM files")

    known = index.known()
    seen: set[str] = set()
    targets: list[tuple[Path, Path, str]] = [(p, root, "code") for p in _walk(root, set(exclude or []))]
    for kdir in knowledge_dirs or []:
        targets += [(p, kdir, "knowledge") for p in _walk(kdir, set(exclude or []))]

    for path, base, kind in targets:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                stats.skipped += 1
                continue
            digest = _digest(path)
        except OSError:
            stats.skipped += 1
            continue

        anchor = root if path.is_relative_to(root) else base
        rel = path.relative_to(anchor).as_posix()
        if kind == "knowledge" and not path.is_relative_to(root):
            rel = f"{base.name}/{path.relative_to(base).as_posix()}"
        seen.add(rel)

        if known.get(rel) == digest:
            continue
        chunks = [
            Chunk(rel, c.lang, kind, c.symbol, c.start, c.end, c.body)
            for c in chunk_file(path, anchor, kind, max_lines)
        ]
        if not chunks:
            stats.skipped += 1
            continue
        index._replace(rel, digest, kind, lang_for(path), chunks)
        stats.files += 1
        stats.chunks += len(chunks)

    for stale in set(known) - seen:
        index.drop(stale)
        stats.removed += 1

    index.conn.commit()
    return stats
