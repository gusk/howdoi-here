"""The premise, asserted: the same question retrieves different context per project."""

from __future__ import annotations

from pathlib import Path

import pytest

from hdh import fingerprint
from hdh.index import Index
from hdh.index import build as build_index
from hdh.retrieve import build_match, expand, keywords, retrieve

QUESTION = "how do i map a list of rows"


def _prepare(root: Path, db: Path, knowledge: bool = False) -> tuple[Index, fingerprint.Fingerprint]:
    index = Index(db)
    kdirs = [root / ".hdh" / "knowledge"] if knowledge else []
    build_index(index, root, kdirs)
    return index, fingerprint.build(root)


def test_keywords_strip_question_scaffolding() -> None:
    assert keywords("how do i map a list") == ["map", "list"]
    assert keywords("What is the best way to retry a request?") == ["retry", "request"]
    assert keywords("???") == []


def test_expansion_adds_stack_neutral_synonyms() -> None:
    expanded = expand(["map", "list"])
    assert {"comprehension", "array", "slice"} <= set(expanded)
    assert expanded[0] == "map"


def test_match_expression_quotes_terms_safely() -> None:
    assert build_match(['a"b']) == '"a""b"'
    assert build_match([]) == ""


def test_same_question_yields_python_context(py_project: Path, tmp_path: Path) -> None:
    index, fp = _prepare(py_project, tmp_path / "py.db")
    r = retrieve(index, fp, QUESTION)
    assert r.code
    top = r.code[0]
    assert top.lang == "python"
    assert top.path == "src/loaders.py"
    assert "for r in rows" in top.body
    assert "python" in r.context_terms


def test_same_question_yields_typescript_context(ts_project: Path, tmp_path: Path) -> None:
    index, fp = _prepare(ts_project, tmp_path / "ts.db")
    r = retrieve(index, fp, QUESTION)
    assert r.code
    top = r.code[0]
    assert top.lang == "typescript"
    assert top.path == "src/transform.ts"
    assert ".map(" in top.body
    assert "typescript" in r.context_terms


def test_retrieved_context_is_disjoint_across_projects(
    py_project: Path, ts_project: Path, tmp_path: Path
) -> None:
    """One question, two repos, zero overlap in what gets sent to the model."""
    py_index, py_fp = _prepare(py_project, tmp_path / "a.db")
    ts_index, ts_fp = _prepare(ts_project, tmp_path / "b.db")

    py_langs = {h.lang for h in retrieve(py_index, py_fp, QUESTION).code}
    ts_langs = {h.lang for h in retrieve(ts_index, ts_fp, QUESTION).code}

    assert py_langs == {"python"}
    assert ts_langs == {"typescript"}
    assert not py_langs & ts_langs


def test_team_knowledge_outranks_code(py_project: Path, tmp_path: Path) -> None:
    index, fp = _prepare(py_project, tmp_path / "k.db", knowledge=True)
    r = retrieve(index, fp, "should i use map or a comprehension")
    assert r.knowledge, "expected the style guide to be retrieved"
    assert "comprehension" in r.knowledge[0].body.lower()
    assert r.knowledge[0].path.endswith("python-style.md")


def test_internal_convention_beats_general_knowledge(py_project: Path, tmp_path: Path) -> None:
    """A question about HTTP should surface the team's retry rule, not just httpx usage."""
    index, fp = _prepare(py_project, tmp_path / "h.db", knowledge=True)
    r = retrieve(index, fp, "how do i make an outbound http request")
    assert any("with_retry" in h.body for h in r.all_hits)


def test_tests_are_deprioritised_unless_asked(py_project: Path, tmp_path: Path) -> None:
    (py_project / "src" / "test_loaders.py").write_text(
        "def test_load_users():\n    assert load_users([]) == []\n"
    )
    index, fp = _prepare(py_project, tmp_path / "t.db")
    ranked = retrieve(index, fp, "load users")
    assert ranked.code and "test_loaders" not in ranked.code[0].path

    asked = retrieve(index, fp, "how do i test load users")
    assert any("test_loaders" in h.path for h in asked.code)


def test_no_matches_is_not_an_error(py_project: Path, tmp_path: Path) -> None:
    index, fp = _prepare(py_project, tmp_path / "n.db")
    r = retrieve(index, fp, "zzzqqq unmatchable gibberish")
    assert r.empty
    assert r.keywords


@pytest.mark.parametrize("limit", [1, 3, 5])
def test_limits_are_honoured(py_project: Path, tmp_path: Path, limit: int) -> None:
    index, fp = _prepare(py_project, tmp_path / f"l{limit}.db")
    assert len(retrieve(index, fp, "users rows map", max_code=limit).code) <= limit


def test_same_question_yields_ruby_context(rails_project: Path, tmp_path: Path) -> None:
    index, fp = _prepare(rails_project, tmp_path / "rb.db")
    r = retrieve(index, fp, QUESTION)
    assert r.code
    top = r.code[0]
    assert top.lang == "ruby"
    assert top.path == "app/services/user_importer.rb"
    assert "rows.map" in top.body
    assert "ruby" in r.context_terms


def test_three_stacks_retrieve_disjoint_context(
    rails_project: Path, py_project: Path, ts_project: Path, tmp_path: Path
) -> None:
    """One question, three repos, no overlap in what reaches the model."""
    langs = []
    for name, root in (("rb", rails_project), ("py", py_project), ("ts", ts_project)):
        index, fp = _prepare(root, tmp_path / f"{name}.db")
        langs.append({h.lang for h in retrieve(index, fp, QUESTION).code})

    assert langs == [{"ruby"}, {"python"}, {"typescript"}]
    assert not set.intersection(*langs)


def test_rails_team_convention_is_retrieved(rails_project: Path, tmp_path: Path) -> None:
    index, fp = _prepare(rails_project, tmp_path / "rbk.db", knowledge=True)
    r = retrieve(index, fp, "should i use a for loop or map")
    assert r.knowledge
    assert "Style/For" in r.knowledge[0].body or "for` loop" in r.knowledge[0].body
