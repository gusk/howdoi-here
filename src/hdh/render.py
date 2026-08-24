"""Terminal presentation. Rich where it helps, plain where it would get in the way."""

from __future__ import annotations

from collections.abc import Iterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from hdh.backends import BackendInfo
from hdh.fingerprint import Fingerprint
from hdh.index import Hit
from hdh.retrieve import Retrieval

console = Console()
err = Console(stderr=True)

DIM = "dim"
ACCENT = "cyan"


def context_line(fp: Fingerprint, backend: str) -> None:
    summary = fp.summary() or "no project detected"
    source = ", ".join(fp.manifests) or "file extensions"
    console.print(
        Text("  ", end="")
        + Text(summary, style=ACCENT)
        + Text(f"  — from {source} · via {backend}", style=DIM)
    )
    console.print()


def stream_markdown(chunks: Iterator[str]) -> str:
    """Render progressively; Markdown needs the whole buffer, so re-render as it grows."""
    buf = ""
    with Live(console=console, refresh_per_second=12, vertical_overflow="visible") as live:
        for chunk in chunks:
            buf += chunk
            live.update(Markdown(buf.strip()) if buf.strip() else Text(""))
        live.update(Markdown(buf.strip()) if buf.strip() else Text("(empty response)"))
    return buf


def plain(chunks: Iterator[str]) -> str:
    buf = ""
    for chunk in chunks:
        buf += chunk
        console.file.write(chunk)
        console.file.flush()
    if not buf.endswith("\n"):
        console.file.write("\n")
    return buf


def snippet(hit: Hit, label: str = "") -> None:
    lang = hit.lang if hit.lang not in ("text", "markdown") else "text"
    title = Text(hit.ref, style=ACCENT)
    if hit.symbol:
        title += Text(f"  {hit.symbol}", style=DIM)
    if label:
        title = Text(f"{label} ", style="bold") + title
    console.print(
        Panel(
            Syntax(hit.body, lang, line_numbers=True, start_line=hit.start, theme="ansi_dark",
                   word_wrap=False),
            title=title,
            title_align="left",
            border_style=DIM,
            padding=(0, 1),
        )
    )


def offline_answer(r: Retrieval, fp: Fingerprint) -> None:
    if r.empty:
        err.print(
            "[yellow]No matches in the index.[/] Try `hdh index` first, or rephrase — "
            f"searched for: {', '.join(r.keywords) or '(nothing)'}"
        )
        return
    console.print(
        Text("Offline mode — ranked from your codebase, no model involved.", style="yellow")
    )
    console.print()
    if r.knowledge:
        console.print(Text("Team knowledge", style="bold"))
        for i, hit in enumerate(r.knowledge, 1):
            snippet(hit, f"K{i}")
    if r.code:
        console.print(Text("From this repository", style="bold"))
        for i, hit in enumerate(r.code, 1):
            snippet(hit, f"C{i}")


def why(r: Retrieval, fp: Fingerprint, prompt: str | None = None) -> None:
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style=DIM, no_wrap=True)
    table.add_column()
    table.add_row("question", r.question)
    table.add_row("keywords", ", ".join(r.keywords) or "-")
    table.add_row("context terms", ", ".join(r.context_terms) or "-")
    table.add_row("fts match", (r.match_expr[:160] + "…") if len(r.match_expr) > 160 else r.match_expr)
    table.add_row("code hits", str(len(r.code)))
    table.add_row("knowledge hits", str(len(r.knowledge)))
    if prompt:
        table.add_row("prompt chars", str(len(prompt)))
    console.print(Panel(table, title=Text("why this answer", style=ACCENT), title_align="left",
                        border_style=DIM))
    for i, hit in enumerate(r.knowledge, 1):
        console.print(Text(f"  K{i} ", style="bold") + Text(hit.ref, style=ACCENT)
                      + Text(f"  score {-hit.score:.2f}", style=DIM))
    for i, hit in enumerate(r.code, 1):
        console.print(Text(f"  C{i} ", style="bold") + Text(hit.ref, style=ACCENT)
                      + Text(f"  {hit.symbol or '-'}  score {-hit.score:.2f}", style=DIM))
    console.print()


def fingerprint_table(fp: Fingerprint) -> None:
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style=DIM, no_wrap=True)
    table.add_column()
    table.add_row("root", fp.root)
    table.add_row("summary", fp.summary() or "-")
    table.add_row("languages", ", ".join(f"{k} ({v})" for k, v in fp.languages) or "-")
    table.add_row("runtimes", ", ".join(f"{k} {v}" for k, v in fp.runtimes.items()) or "-")
    table.add_row("frameworks", ", ".join(fp.frameworks) or "-")
    table.add_row("tooling", ", ".join(f"{k}={v}" for k, v in fp.tools.items()) or "-")
    table.add_row("manifests", ", ".join(fp.manifests) or "-")
    table.add_row("source files", str(fp.file_count))
    table.add_row("dependencies", str(len(fp.deps)))
    table.add_row("query terms", ", ".join(fp.query_terms()) or "-")
    console.print(Panel(table, title=Text("project fingerprint", style=ACCENT),
                        title_align="left", border_style=DIM))


def doctor(infos: list[BackendInfo], active: str, counts: dict[str, int], index_exists: bool) -> None:
    table = Table(box=None, pad_edge=False)
    table.add_column("backend", style="bold", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("detail", style=DIM)
    for info in infos:
        mark = "[green]ready[/]" if info.available else "[red]unavailable[/]"
        name = f"{info.name} [cyan](active)[/]" if info.name == active else info.name
        table.add_row(name, mark, info.detail)
    console.print(Panel(table, title=Text("backends", style=ACCENT), title_align="left",
                        border_style=DIM))
    state = (
        f"code chunks: {counts.get('code', 0)} · knowledge chunks: {counts.get('knowledge', 0)}"
        if index_exists else "[yellow]no index yet — run `hdh index`[/]"
    )
    console.print(f"  {state}")
