from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hdh import fingerprint
from hdh.answer import build_prompt, collect, project_block
from hdh.backends import Backend
from hdh.cli import app
from hdh.index import Index
from hdh.index import build as build_index
from hdh.retrieve import retrieve

runner = CliRunner()


class FakeBackend(Backend):
    name = "fake"

    def __init__(self) -> None:
        self.seen = ""

    def available(self) -> bool:
        return True

    def stream(self, prompt: str, system: str = ""):  # noqa: ANN201
        self.seen = prompt
        yield "use a comprehension"


def _retrieval(root: Path, db: Path):  # noqa: ANN202
    index = Index(db)
    build_index(index, root, [root / ".hdh" / "knowledge"])
    fp = fingerprint.build(root)
    return fp, retrieve(index, fp, "how do i map a list of rows")


def test_project_block_carries_versions(py_project: Path) -> None:
    block = project_block(fingerprint.build(py_project))
    assert "pydantic >=2.9" in block
    assert "Detected from: pyproject.toml" in block


def test_prompt_contains_fingerprint_snippets_and_question(py_project: Path, tmp_path: Path) -> None:
    fp, r = _retrieval(py_project, tmp_path / "p.db")
    prompt = build_prompt("how do i map a list of rows", fp, r)
    assert "# Project context" in prompt
    assert "# Question" in prompt
    assert "src/loaders.py:" in prompt
    assert "```python" in prompt
    assert "FastAPI" in prompt


def test_prompt_labels_knowledge_as_authoritative(py_project: Path, tmp_path: Path) -> None:
    fp, r = _retrieval(py_project, tmp_path / "k.db")
    prompt = build_prompt("should i use map or a comprehension", fp, r)
    assert "Team knowledge base" in prompt
    assert "outrank general best practice" in prompt


def test_empty_retrieval_is_stated_explicitly(py_project: Path, tmp_path: Path) -> None:
    index = Index(tmp_path / "e.db")
    build_index(index, py_project)
    fp = fingerprint.build(py_project)
    r = retrieve(index, fp, "zzzqqq unmatchable")
    prompt = build_prompt("zzzqqq unmatchable", fp, r)
    assert "No matching code or docs" in prompt


def test_collect_routes_prompt_through_backend(py_project: Path, tmp_path: Path) -> None:
    fp, r = _retrieval(py_project, tmp_path / "c.db")
    backend = FakeBackend()
    answer = collect(backend, "how do i map a list of rows", fp, r)
    assert answer.text == "use a comprehension"
    assert answer.backend == "fake"
    assert "src/loaders.py" in backend.seen


# -- CLI --------------------------------------------------------------------


def test_context_json_is_machine_readable(py_project: Path) -> None:
    result = runner.invoke(app, ["context", "--json", "-C", str(py_project)])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["primary"] == "python"
    assert "FastAPI" in data["frameworks"]


def test_doctor_lists_backends(py_project: Path) -> None:
    result = runner.invoke(app, ["doctor", "-C", str(py_project)])
    assert result.exit_code == 0
    for name in ("anthropic", "claude-cli", "offline"):
        assert name in result.stdout


def test_index_command_reports_counts(py_project: Path) -> None:
    result = runner.invoke(app, ["index", "-C", str(py_project)])
    assert result.exit_code == 0
    assert "indexed" in result.stdout


def test_offline_ask_needs_no_credentials(py_project: Path) -> None:
    result = runner.invoke(
        app, ["ask", "how", "do", "i", "map", "a", "list", "--offline", "-C", str(py_project)]
    )
    assert result.exit_code == 0
    assert "loaders.py" in result.stdout


def test_show_prompt_exits_before_calling_a_model(py_project: Path) -> None:
    result = runner.invoke(
        app, ["ask", "map", "a", "list", "--show-prompt", "-C", str(py_project)]
    )
    assert result.exit_code == 0
    assert "# Project context" in result.stdout


def test_search_subcommand(py_project: Path) -> None:
    result = runner.invoke(app, ["search", "retry", "-C", str(py_project)])
    assert result.exit_code == 0
    assert "retry.py" in result.stdout
