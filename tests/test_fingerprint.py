from __future__ import annotations

from pathlib import Path

from hdh import fingerprint


def test_python_project_is_detected_with_versions(py_project: Path) -> None:
    fp = fingerprint.build(py_project)
    assert fp.primary == "python"
    assert fp.runtimes["python"] == ">=3.11"
    assert "pyproject.toml" in fp.manifests
    assert {"FastAPI", "Pydantic", "SQLAlchemy"} <= set(fp.frameworks)
    assert fp.tools["test"] == "pytest"
    assert fp.tools["lint"] == "ruff"


def test_dependency_versions_are_pinned_not_guessed(py_project: Path) -> None:
    fp = fingerprint.build(py_project)
    assert fp.dep_version("pydantic") == ">=2.9"
    assert fp.dep_version("fastapi") == ">=0.110"
    assert fp.dep_version("nonexistent") is None


def test_typescript_project_is_detected(ts_project: Path) -> None:
    fp = fingerprint.build(ts_project)
    assert fp.primary == "typescript"
    assert fp.runtimes["typescript"] == ">=20"
    assert "React" in fp.frameworks
    assert fp.tools["test"] == "Vitest"
    assert fp.tools["lint"] == "ESLint"


def test_query_terms_are_disjoint_across_stacks(py_project: Path, ts_project: Path) -> None:
    """The whole premise: the same question expands differently per project."""
    py_terms = set(fingerprint.build(py_project).query_terms())
    ts_terms = set(fingerprint.build(ts_project).query_terms())
    assert "python" in py_terms and "python" not in ts_terms
    assert "typescript" in ts_terms and "typescript" not in py_terms
    assert not py_terms & ts_terms


def test_summary_is_human_readable(py_project: Path) -> None:
    summary = fingerprint.build(py_project).summary()
    assert summary.startswith("python >=3.11")
    assert "FastAPI" in summary


def test_empty_directory_degrades_gracefully(tmp_path: Path) -> None:
    fp = fingerprint.build(tmp_path)
    assert fp.primary is None
    assert fp.summary() == ""
    assert fp.query_terms() == []
    assert fp.to_dict()["deps"] == []


def test_vendor_directories_are_ignored(py_project: Path) -> None:
    noise = py_project / "node_modules" / "junk"
    noise.mkdir(parents=True)
    (noise / "a.py").write_text("x = 1")
    assert fingerprint.build(py_project).file_count == 2


def test_rails_project_is_detected(rails_project: Path) -> None:
    fp = fingerprint.build(rails_project)
    assert fp.primary == "ruby"
    assert fp.runtimes["ruby"] == "3.3.4"
    assert "Gemfile" in fp.manifests
    assert "Rails" in fp.frameworks
    assert fp.tools["test"] == "RSpec"
    assert fp.tools["lint"] == "RuboCop"
    assert fp.dep_version("rails") == "~> 7.1.3"


def test_app_framework_leads_the_summary(rails_project: Path) -> None:
    """Rails identifies the stack; Faraday and Puma do not. Order matters in the header."""
    fp = fingerprint.build(rails_project)
    assert fp.frameworks[0] == "Rails"
    assert fp.summary().startswith("ruby 3.3.4 · Rails")


def test_three_stacks_share_no_query_terms(
    rails_project: Path, py_project: Path, ts_project: Path
) -> None:
    rb = set(fingerprint.build(rails_project).query_terms())
    py = set(fingerprint.build(py_project).query_terms())
    ts = set(fingerprint.build(ts_project).query_terms())
    assert "ruby" in rb and "rails" in rb
    assert not (rb & py) and not (rb & ts) and not (py & ts)
