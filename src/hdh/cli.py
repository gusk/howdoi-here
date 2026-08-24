"""hdh — howdoi, but it knows what repo you're standing in."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from hdh import __version__, backends, config, fingerprint, render
from hdh.answer import build_prompt
from hdh.backends import BackendUnavailable
from hdh.index import Index
from hdh.index import build as build_index
from hdh.retrieve import retrieve

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Ask how to do something, answered in the idiom of the repo you're in.",
    context_settings={"help_option_names": ["-h", "--help"]},
)

SUBCOMMANDS = {"ask", "index", "context", "search", "doctor", "mcp"}
CODE_BLOCK = re.compile(r"```[\w+-]*\n(.*?)```", re.S)


def _load(path: Path | None) -> config.Config:
    return config.load(config.find_root(path.resolve() if path else None))


def _fingerprint(cfg: config.Config) -> fingerprint.Fingerprint:
    return fingerprint.build(cfg.root, cfg.exclude)


def _ensure_index(cfg: config.Config, quiet: bool = False) -> Index:
    fresh = not cfg.index_path.exists()
    index = Index(cfg.index_path)
    if fresh:
        if not quiet:
            render.err.print("[dim]no index found — building one (first run only)…[/]")
        with render.console.status("[dim]indexing…[/]", spinner="dots"):
            stats = build_index(
                index, cfg.root, cfg.knowledge_dirs, cfg.exclude, cfg.chunk_lines
            )
        if not quiet:
            render.err.print(
                f"[dim]indexed {stats.files} files → {stats.chunks} chunks[/]"
            )
    return index


def _copy(text: str) -> bool:
    cmds = (["clip"], ["pbcopy"], ["xclip", "-selection", "clipboard"], ["wl-copy"])
    for cmd in cmds:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text, text=True, check=True)
                return True
            except (OSError, subprocess.CalledProcessError):
                continue
    return False


@app.command()
def ask(
    words: Annotated[list[str], typer.Argument(help="Your question. No quotes needed.")],
    backend: Annotated[str | None, typer.Option("--backend", "-b",
        help="anthropic | claude-cli | offline (default: best available)")] = None,
    offline: Annotated[bool, typer.Option("--offline", help="Skip the model; rank snippets only.")] = False,
    show_why: Annotated[bool, typer.Option("--why", help="Show the context that produced this.")] = False,
    code_only: Annotated[bool, typer.Option("--code", "-c", help="Print only the first code block.")] = False,
    num: Annotated[int | None, typer.Option("-n", help="Max code snippets to retrieve.")] = None,
    copy: Annotated[bool, typer.Option("--copy", help="Copy the answer to the clipboard.")] = False,
    show_prompt: Annotated[bool, typer.Option("--show-prompt", help="Print the assembled prompt and exit.")] = False,
    path: Annotated[Path | None, typer.Option("--path", "-C", help="Run against another directory.")] = None,
) -> None:
    """Ask a question, answered in the context of this project."""
    question = " ".join(words).strip()
    if not question:
        raise typer.BadParameter("ask what?")

    cfg = _load(path)
    if backend:
        cfg.backend = backend
    fp = _fingerprint(cfg)
    index = _ensure_index(cfg, quiet=code_only)

    r = retrieve(index, fp, question, num or cfg.max_snippets, cfg.max_knowledge)

    if show_prompt:
        render.console.print(build_prompt(question, fp, r))
        raise typer.Exit()

    chosen = backends.OfflineBackend() if offline else backends.detect(
        cfg.backend, cfg.model, cfg.cli_model
    )

    if show_why:
        render.why(r, fp, build_prompt(question, fp, r))

    if chosen.name == "offline":
        if not code_only:
            render.context_line(fp, "offline")
        render.offline_answer(r, fp)
        raise typer.Exit()

    if not code_only:
        render.context_line(fp, chosen.name)

    prompt = build_prompt(question, fp, r)
    try:
        stream = chosen.stream(prompt)
        text = render.plain(stream) if code_only else render.stream_markdown(stream)
    except BackendUnavailable as e:
        render.err.print(f"[red]{chosen.name} unavailable:[/] {e}")
        render.err.print("[dim]falling back to offline retrieval…[/]\n")
        render.offline_answer(r, fp)
        raise typer.Exit(1) from None

    if code_only and (m := CODE_BLOCK.search(text)):
        text = m.group(1).rstrip()
    if copy and text.strip():
        render.err.print("[dim]copied to clipboard[/]" if _copy(text)
                         else "[yellow]no clipboard tool found[/]")


@app.command(name="index")
def index_cmd(
    rebuild: Annotated[bool, typer.Option("--rebuild", help="Discard and reindex everything.")] = False,
    path: Annotated[Path | None, typer.Option("--path", "-C")] = None,
) -> None:
    """Build or refresh the code + knowledge index."""
    cfg = _load(path)
    with Index(cfg.index_path) as index, render.console.status("[dim]indexing…[/]", spinner="dots"):
        stats = build_index(
            index, cfg.root, cfg.knowledge_dirs, cfg.exclude, cfg.chunk_lines, rebuild
        )
        counts = index.counts()
    kdirs = ", ".join(str(d.relative_to(cfg.root)) if d.is_relative_to(cfg.root) else str(d)
                      for d in cfg.knowledge_dirs)
    render.console.print(
        f"[green]indexed[/] {stats.files} changed files → {stats.chunks} chunks"
        + (f", removed {stats.removed} stale" if stats.removed else "")
        + (f", skipped {stats.skipped}" if stats.skipped else "")
    )
    render.console.print(
        f"[dim]total: {counts.get('code', 0)} code · {counts.get('knowledge', 0)} knowledge"
        + (f" · knowledge dirs: {kdirs}" if kdirs else " · no knowledge dirs configured")
        + f" · {cfg.index_path}[/]"
    )


@app.command()
def context(
    json_out: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    path: Annotated[Path | None, typer.Option("--path", "-C")] = None,
) -> None:
    """Show what hdh thinks this project is."""
    cfg = _load(path)
    fp = _fingerprint(cfg)
    if json_out:
        import json

        render.console.print_json(json.dumps(fp.to_dict()))
    else:
        render.fingerprint_table(fp)


@app.command()
def search(
    words: Annotated[list[str], typer.Argument(help="Terms to search for.")],
    num: Annotated[int, typer.Option("-n", help="Max results.")] = 8,
    kind: Annotated[str | None, typer.Option("--kind", help="code | knowledge")] = None,
    path: Annotated[Path | None, typer.Option("--path", "-C")] = None,
) -> None:
    """Retrieval only — see what context a question would pull in."""
    cfg = _load(path)
    fp = _fingerprint(cfg)
    index = _ensure_index(cfg)
    r = retrieve(index, fp, " ".join(words), num, num)
    if kind == "code":
        r.knowledge = []
    elif kind == "knowledge":
        r.code = []
    render.offline_answer(r, fp)


@app.command()
def doctor(
    path: Annotated[Path | None, typer.Option("--path", "-C")] = None,
) -> None:
    """Show which backends are available and whether an index exists."""
    cfg = _load(path)
    active = backends.detect(cfg.backend, cfg.model, cfg.cli_model)
    exists = cfg.index_path.exists()
    counts: dict[str, int] = {}
    if exists:
        with Index(cfg.index_path) as index:
            counts = index.counts()
    render.doctor(backends.survey(cfg.model, cfg.cli_model), active.name, counts, exists)
    render.console.print(f"  [dim]root: {cfg.root}[/]")


@app.command()
def mcp(
    path: Annotated[Path | None, typer.Option("--path", "-C")] = None,
) -> None:
    """Serve this project's knowledge to agents over MCP (stdio)."""
    from hdh.mcp_server import serve

    serve(_load(path))


def _version(value: bool) -> None:
    if value:
        render.console.print(f"hdh {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True)] = False,
) -> None:
    pass


def main() -> None:
    """Entry point. Bare words imply `ask`, so `hdh how do i map a list` just works."""
    argv = sys.argv[1:]
    if argv and argv[0] not in SUBCOMMANDS and not argv[0].startswith("-"):
        sys.argv.insert(1, "ask")
    app()


if __name__ == "__main__":
    main()
