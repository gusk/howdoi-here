from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT_MARKERS = (".git", ".hdh", "pyproject.toml", "package.json", "go.mod", "Cargo.toml")
CONFIG_NAME = "config.toml"


def find_root(start: Path | None = None) -> Path:
    """Nearest ancestor holding a project marker; cwd if none."""
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if any((candidate / m).exists() for m in ROOT_MARKERS):
            return candidate
    return cur


@dataclass
class Config:
    root: Path
    backend: str = "auto"
    model: str = "claude-opus-5"
    cli_model: str = "opus"
    max_snippets: int = 6
    max_knowledge: int = 3
    chunk_lines: int = 45
    knowledge_paths: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @property
    def hdh_dir(self) -> Path:
        return self.root / ".hdh"

    @property
    def index_path(self) -> Path:
        return self.hdh_dir / "index.db"

    @property
    def knowledge_dirs(self) -> list[Path]:
        dirs = [self.hdh_dir / "knowledge"]
        dirs += [Path(p).expanduser() if Path(p).is_absolute() else self.root / p
                 for p in self.knowledge_paths]
        return [d for d in dirs if d.is_dir()]


_ENV = {
    "HDH_BACKEND": "backend",
    "HDH_MODEL": "model",
    "HDH_CLI_MODEL": "cli_model",
}


def load(root: Path | None = None) -> Config:
    root = root or find_root()
    cfg = Config(root=root)
    path = root / ".hdh" / CONFIG_NAME
    if path.is_file():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        for key, value in {**data, **data.get("hdh", {})}.items():
            if hasattr(cfg, key) and not isinstance(value, dict):
                setattr(cfg, key, value)
    for env, attr in _ENV.items():
        if value := os.environ.get(env):
            setattr(cfg, attr, value)
    return cfg
