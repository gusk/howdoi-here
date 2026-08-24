from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
_IGNORE = shutil.ignore_patterns("index.db", "__pycache__", "*.pyc")


def _copy(name: str, tmp_path: Path) -> Path:
    dest = tmp_path / name
    shutil.copytree(FIXTURES / name, dest, ignore=_IGNORE)
    return dest


@pytest.fixture
def py_project(tmp_path: Path) -> Path:
    """A FastAPI/Pydantic project that maps rows with comprehensions."""
    return _copy("py_project", tmp_path)


@pytest.fixture
def ts_project(tmp_path: Path) -> Path:
    """A React/Zod project that maps rows with Array.map()."""
    return _copy("ts_project", tmp_path)


@pytest.fixture
def rails_project(tmp_path: Path) -> Path:
    """A Rails project that maps rows with Enumerable and bans `for` loops."""
    return _copy("rails_project", tmp_path)
