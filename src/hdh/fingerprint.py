"""Deterministic project detection: what language, framework, and versions is this?

No LLM, no network. Extension histogram + manifest parsing, ~50ms on a large repo.
Everything downstream (query expansion, retrieval, prompt) is grounded in this.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".hdh", "node_modules", "vendor", "dist", "build", "target",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".next", ".nuxt", "coverage", "htmlcov", "bin", "obj", ".idea", ".vscode",
}

EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".rs": "rust", ".rb": "ruby", ".java": "java", ".kt": "kotlin",
    ".cs": "csharp", ".php": "php", ".swift": "swift", ".scala": "scala",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".sh": "shell", ".bash": "shell", ".sql": "sql", ".lua": "lua", ".ex": "elixir",
}

FRAMEWORKS = {
    "django": "Django", "flask": "Flask", "fastapi": "FastAPI", "starlette": "Starlette",
    "pydantic": "Pydantic", "sqlalchemy": "SQLAlchemy", "pandas": "pandas", "numpy": "NumPy",
    "polars": "Polars", "celery": "Celery", "boto3": "boto3", "httpx": "httpx",
    "requests": "requests", "click": "Click", "typer": "Typer", "rich": "Rich",
    "react": "React", "next": "Next.js", "vue": "Vue", "svelte": "Svelte",
    "@angular/core": "Angular", "express": "Express", "fastify": "Fastify",
    "@nestjs/core": "NestJS", "prisma": "Prisma", "drizzle-orm": "Drizzle",
    "zod": "Zod", "tailwindcss": "Tailwind", "axios": "axios", "lodash": "Lodash",
    "gin-gonic/gin": "Gin", "labstack/echo": "Echo", "gorm.io/gorm": "GORM",
    "spf13/cobra": "Cobra", "tokio": "Tokio", "axum": "Axum", "serde": "Serde",
    "actix-web": "Actix", "rails": "Rails", "sinatra": "Sinatra",
    "spring-boot-starter": "Spring Boot",
}

TEST_TOOLS = {
    "pytest": "pytest", "tox": "tox",
    "jest": "Jest", "vitest": "Vitest", "mocha": "Mocha", "@playwright/test": "Playwright",
    "cypress": "Cypress", "testify": "testify", "rspec": "RSpec", "minitest": "Minitest",
    "junit": "JUnit", "xunit": "xUnit", "nunit": "NUnit",
}

LINT_TOOLS = {
    "ruff": "ruff", "black": "black", "flake8": "flake8", "pylint": "pylint",
    "mypy": "mypy", "pyright": "pyright", "isort": "isort",
    "eslint": "ESLint", "prettier": "Prettier", "@biomejs/biome": "Biome",
    "golangci-lint": "golangci-lint", "rubocop": "RuboCop",
}

LOCKFILE_PM = {
    "uv.lock": "uv", "poetry.lock": "poetry", "Pipfile.lock": "pipenv",
    "pdm.lock": "pdm", "requirements.txt": "pip",
    "pnpm-lock.yaml": "pnpm", "yarn.lock": "yarn", "package-lock.json": "npm",
    "bun.lockb": "bun", "Cargo.lock": "cargo", "go.sum": "go modules", "Gemfile.lock": "bundler",
}

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*([<>=!~^].*)?$")
_PEP508 = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[[^\]]*\])?\s*(.*)$")
_GEM = re.compile(r"gem\s+['\"]([\w-]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?")
_PKG_REF = re.compile(r"<PackageReference\s+Include=\"([^\"]+)\"(?:\s+Version=\"([^\"]+)\")?")


@dataclass(frozen=True)
class Dep:
    name: str
    version: str | None = None
    dev: bool = False

    def __str__(self) -> str:
        return f"{self.name} {self.version}".strip() if self.version else self.name


@dataclass
class Fingerprint:
    root: str
    languages: list[tuple[str, int]] = field(default_factory=list)
    deps: list[Dep] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    runtimes: dict[str, str] = field(default_factory=dict)
    tools: dict[str, str] = field(default_factory=dict)
    manifests: list[str] = field(default_factory=list)
    file_count: int = 0

    @property
    def primary(self) -> str | None:
        return self.languages[0][0] if self.languages else None

    def dep_version(self, name: str) -> str | None:
        return next((d.version for d in self.deps if d.name.lower() == name.lower()), None)

    def summary(self) -> str:
        """One-line context header, e.g. 'python >=3.11 - FastAPI - pytest - ruff'."""
        parts: list[str] = []
        if self.primary:
            rt = self.runtimes.get(self.primary)
            parts.append(f"{self.primary} {rt}".strip() if rt else self.primary)
        parts += self.frameworks[:3]
        parts += [v for k, v in self.tools.items() if k in ("test", "lint")]
        return " · ".join(dict.fromkeys(p for p in parts if p))

    def query_terms(self) -> list[str]:
        """Terms injected into retrieval so 'map a list' finds *this* stack's idiom."""
        terms = [lang for lang, _ in self.languages[:2]]
        terms += [f.lower().split()[0] for f in self.frameworks[:4]]
        return list(dict.fromkeys(t for t in terms if t))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["deps"] = [str(x) for x in self.deps]
        d["primary"] = self.primary
        d["summary"] = self.summary()
        return d


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def scan_languages(
    root: Path, exclude: list[str] | None = None
) -> tuple[list[tuple[str, int]], int]:
    counts: dict[str, int] = {}
    total = 0
    extra = set(exclude or [])
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORE_DIRS and d not in extra and not d.startswith(".")
        ]
        for fn in filenames:
            if lang := EXT_LANG.get(Path(fn).suffix.lower()):
                counts[lang] = counts.get(lang, 0) + 1
                total += 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])), total


def _parse_pyproject(path: Path, fp: Fingerprint) -> None:
    try:
        data = tomllib.loads(_read(path))
    except tomllib.TOMLDecodeError:
        return
    proj = data.get("project", {})
    if req := proj.get("requires-python"):
        fp.runtimes["python"] = str(req)
    specs: list[tuple[str, bool]] = [(s, False) for s in proj.get("dependencies", []) or []]
    for group in (proj.get("optional-dependencies") or {}).values():
        specs += [(s, True) for s in group]
    poetry = data.get("tool", {}).get("poetry", {})
    for name, spec in (poetry.get("dependencies") or {}).items():
        if name == "python":
            if isinstance(spec, str):
                fp.runtimes.setdefault("python", spec)
        else:
            fp.deps.append(Dep(name, spec if isinstance(spec, str) else None))
    for spec, dev in specs:
        if m := _PEP508.match(str(spec)):
            fp.deps.append(Dep(m.group(1), (m.group(2) or "").strip() or None, dev))
    for tool in data.get("tool", {}):
        if tool in LINT_TOOLS:
            fp.tools.setdefault("lint", LINT_TOOLS[tool])
        if tool in TEST_TOOLS:
            fp.tools.setdefault("test", TEST_TOOLS[tool])


def _parse_requirements(path: Path, fp: Fingerprint) -> None:
    for raw in _read(path).splitlines():
        line = raw.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        if m := _REQ_LINE.match(line):
            fp.deps.append(Dep(m.group(1), (m.group(2) or "").strip() or None))


def _parse_package_json(path: Path, fp: Fingerprint) -> None:
    try:
        data = json.loads(_read(path) or "{}")
    except json.JSONDecodeError:
        return
    for key, dev in (("dependencies", False), ("devDependencies", True)):
        for name, ver in (data.get(key) or {}).items():
            fp.deps.append(Dep(name, str(ver), dev))
    if node := (data.get("engines") or {}).get("node"):
        fp.runtimes["javascript"] = fp.runtimes["typescript"] = str(node)
    if pm := data.get("packageManager"):
        fp.tools.setdefault("package manager", str(pm).split("@")[0])
    for name, body in (data.get("scripts") or {}).items():
        if name.startswith("test"):
            for tool, label in TEST_TOOLS.items():
                if tool in str(body):
                    fp.tools.setdefault("test", label)


def _parse_go_mod(path: Path, fp: Fingerprint) -> None:
    text = _read(path)
    if m := re.search(r"^go\s+([\d.]+)", text, re.M):
        fp.runtimes["go"] = m.group(1)
    for name, ver in re.findall(r"^\s*([\w./-]+)\s+(v[\w.\-+]+)", text, re.M):
        fp.deps.append(Dep(name, ver))


def _parse_cargo(path: Path, fp: Fingerprint) -> None:
    try:
        data = tomllib.loads(_read(path))
    except tomllib.TOMLDecodeError:
        return
    if edition := data.get("package", {}).get("edition"):
        fp.runtimes["rust"] = f"edition {edition}"
    for key, dev in (("dependencies", False), ("dev-dependencies", True)):
        for name, spec in (data.get(key) or {}).items():
            ver = spec if isinstance(spec, str) else (spec or {}).get("version")
            fp.deps.append(Dep(name, ver, dev))


def _parse_gemfile(path: Path, fp: Fingerprint) -> None:
    for name, ver in _GEM.findall(_read(path)):
        fp.deps.append(Dep(name, ver or None))


def _parse_csproj(path: Path, fp: Fingerprint) -> None:
    text = _read(path)
    if m := re.search(r"<TargetFramework>([^<]+)<", text):
        fp.runtimes["csharp"] = m.group(1)
    for name, ver in _PKG_REF.findall(text):
        fp.deps.append(Dep(name, ver or None))


def _parse_pom(path: Path, fp: Fingerprint) -> None:
    text = _read(path)
    if m := re.search(r"<maven\.compiler\.(?:release|source)>([^<]+)<", text):
        fp.runtimes["java"] = m.group(1)
    for aid, ver in re.findall(
        r"<artifactId>([^<]+)</artifactId>\s*(?:<version>([^<]+)</version>)?", text
    ):
        fp.deps.append(Dep(aid, ver or None))


MANIFESTS = {
    "pyproject.toml": _parse_pyproject,
    "requirements.txt": _parse_requirements,
    "package.json": _parse_package_json,
    "go.mod": _parse_go_mod,
    "Cargo.toml": _parse_cargo,
    "Gemfile": _parse_gemfile,
    "pom.xml": _parse_pom,
}


def build(root: Path, exclude: list[str] | None = None) -> Fingerprint:
    fp = Fingerprint(root=str(root))
    fp.languages, fp.file_count = scan_languages(root, exclude)

    for name, parser in MANIFESTS.items():
        if (path := root / name).is_file():
            fp.manifests.append(name)
            parser(path, fp)
    for csproj in sorted(root.glob("*.csproj"))[:3]:
        fp.manifests.append(csproj.name)
        _parse_csproj(csproj, fp)

    for lock, pm in LOCKFILE_PM.items():
        if (root / lock).is_file():
            fp.tools.setdefault("package manager", pm)
            break

    seen: dict[str, Dep] = {}
    for d in fp.deps:
        seen.setdefault(d.name.lower(), d)
    fp.deps = sorted(seen.values(), key=lambda d: d.name.lower())

    for d in fp.deps:
        key = d.name.lower()
        label = FRAMEWORKS.get(key) or next(
            (v for k, v in FRAMEWORKS.items() if "/" in k and k in key), None
        )
        if label:
            fp.frameworks.append(label)
        if t := TEST_TOOLS.get(key):
            fp.tools.setdefault("test", t)
        if lint := LINT_TOOLS.get(key):
            fp.tools.setdefault("lint", lint)
    fp.frameworks = list(dict.fromkeys(fp.frameworks))

    if (root / "Dockerfile").is_file():
        fp.tools.setdefault("container", "Docker")
    if (root / ".github" / "workflows").is_dir():
        fp.tools.setdefault("ci", "GitHub Actions")
    return fp
