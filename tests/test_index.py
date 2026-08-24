from __future__ import annotations

from pathlib import Path

import pytest

from hdh.index import Index
from hdh.index import build as build_index


@pytest.fixture
def index(tmp_path: Path) -> Index:
    with Index(tmp_path / "idx" / "index.db") as idx:
        yield idx


def test_build_indexes_code(index: Index, py_project: Path) -> None:
    stats = build_index(index, py_project)
    assert stats.files == 2
    assert stats.chunks > 0
    assert index.counts()["code"] == stats.chunks


def test_search_finds_the_right_symbol(index: Index, py_project: Path) -> None:
    build_index(index, py_project)
    hits = index.search('"load_users" OR "comprehension"')
    assert hits
    assert hits[0].path == "src/loaders.py"
    assert hits[0].start >= 1


def test_knowledge_is_indexed_separately(index: Index, py_project: Path) -> None:
    build_index(index, py_project, knowledge_dirs=[py_project / ".hdh" / "knowledge"])
    counts = index.counts()
    assert counts.get("knowledge", 0) > 0
    hits = index.search('"comprehensions"', kind="knowledge")
    assert hits and hits[0].kind == "knowledge"


def test_reindex_is_incremental(index: Index, py_project: Path) -> None:
    first = build_index(index, py_project)
    again = build_index(index, py_project)
    assert again.files == 0
    assert index.counts()["code"] == first.chunks


def test_changed_file_is_reindexed_without_duplicates(index: Index, py_project: Path) -> None:
    build_index(index, py_project)
    before = index.counts()["code"]
    target = py_project / "src" / "loaders.py"
    target.write_text(target.read_text() + "\n\ndef zeta():\n    return 42\n")
    stats = build_index(index, py_project)
    assert stats.files == 1
    assert index.counts()["code"] >= before
    assert len(index.search('"zeta"')) >= 1
    paths = {r["path"] for r in index.conn.execute("SELECT path FROM files")}
    assert len(paths) == 2


def test_deleted_file_is_pruned(index: Index, py_project: Path) -> None:
    build_index(index, py_project)
    (py_project / "src" / "retry.py").unlink()
    stats = build_index(index, py_project)
    assert stats.removed == 1
    assert not index.search('"with_retry"')


def test_rebuild_clears_everything(index: Index, py_project: Path) -> None:
    build_index(index, py_project)
    stats = build_index(index, py_project, rebuild=True)
    assert stats.files == 2


def test_malformed_query_returns_empty_not_crash(index: Index, py_project: Path) -> None:
    build_index(index, py_project)
    assert index.search("AND OR ((") == []


def test_lang_and_kind_filters(index: Index, py_project: Path) -> None:
    build_index(index, py_project, knowledge_dirs=[py_project / ".hdh" / "knowledge"])
    assert all(h.lang == "python" for h in index.search('"users"', lang="python"))
    assert all(h.kind == "code" for h in index.search('"users"', kind="code"))


def test_index_dir_ignores_its_own_database(tmp_path: Path) -> None:
    """The db holds full source text; committing it would leak a whole codebase."""
    db = tmp_path / ".hdh" / "index.db"
    with Index(db):
        pass
    ignore = db.parent / ".gitignore"
    assert ignore.exists()
    body = ignore.read_text()
    assert "index.db" in body
    # config and knowledge stay committable -- sharing those is the point
    assert "config.toml" not in body
    assert "knowledge" not in body


def test_existing_gitignore_is_not_clobbered(tmp_path: Path) -> None:
    hdh = tmp_path / ".hdh"
    hdh.mkdir()
    (hdh / ".gitignore").write_text("custom rules\n")
    with Index(hdh / "index.db"):
        pass
    assert (hdh / ".gitignore").read_text() == "custom rules\n"
