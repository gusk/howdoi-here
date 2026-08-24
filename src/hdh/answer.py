"""Prompt assembly: turn deterministic context into one well-shaped request.

Everything upstream is pure functions over the filesystem, so this module is the only
place a token is ever spent -- which is what makes the rest of the pipeline testable.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from hdh.backends import Backend, BackendUnavailable
from hdh.fingerprint import Fingerprint
from hdh.index import Hit
from hdh.retrieve import Retrieval

MAX_SNIPPET_LINES = 40
MAX_KNOWLEDGE_LINES = 30


def _clip(body: str, limit: int) -> str:
    lines = body.splitlines()
    if len(lines) <= limit:
        return body
    return "\n".join(lines[:limit]) + f"\n... ({len(lines) - limit} more lines)"


def _fence(hit: Hit, limit: int) -> str:
    lang = "" if hit.lang in ("text", "markdown") else hit.lang
    return f"```{lang}\n{_clip(hit.body, limit)}\n```"


def project_block(fp: Fingerprint) -> str:
    lines = [f"Summary: {fp.summary() or 'unknown'}"]
    if fp.languages:
        lines.append(
            "Languages: "
            + ", ".join(f"{lang} ({n} files)" for lang, n in fp.languages[:4])
        )
    if fp.runtimes:
        lines.append("Runtimes: " + ", ".join(f"{k} {v}" for k, v in fp.runtimes.items()))
    if fp.frameworks:
        lines.append("Frameworks: " + ", ".join(fp.frameworks[:8]))
    if fp.tools:
        lines.append("Tooling: " + ", ".join(f"{k}={v}" for k, v in fp.tools.items()))
    if fp.deps:
        top = [str(d) for d in fp.deps[:25]]
        lines.append("Dependencies: " + ", ".join(top))
    if fp.manifests:
        lines.append("Detected from: " + ", ".join(fp.manifests))
    return "\n".join(lines)


def build_prompt(question: str, fp: Fingerprint, r: Retrieval) -> str:
    parts = ["# Project context\n" + project_block(fp)]

    if r.knowledge:
        blocks = [
            f"## [K{i}] {h.ref}" + (f" - {h.symbol}" if h.symbol else "")
            + f"\n{_clip(h.body, MAX_KNOWLEDGE_LINES)}"
            for i, h in enumerate(r.knowledge, 1)
        ]
        parts.append(
            "# Team knowledge base (internal docs; these outrank general best practice)\n"
            + "\n\n".join(blocks)
        )

    if r.code:
        blocks = [
            f"## [C{i}] {h.ref}" + (f" - {h.symbol}" if h.symbol else "")
            + f"\n{_fence(h, MAX_SNIPPET_LINES)}"
            for i, h in enumerate(r.code, 1)
        ]
        parts.append("# How this repository already does related things\n" + "\n\n".join(blocks))

    if r.empty:
        parts.append(
            "# Retrieved context\n(No matching code or docs were found in this repository. "
            "Answer from the project fingerprint above and say that the repo had no example.)"
        )

    parts.append(f"# Question\n{question}")
    return "\n\n".join(parts)


@dataclass
class Answer:
    text: str
    backend: str
    retrieval: Retrieval
    fingerprint: Fingerprint
    prompt: str


def stream_answer(
    backend: Backend, question: str, fp: Fingerprint, r: Retrieval
) -> tuple[str, Iterator[str]]:
    """Returns the assembled prompt and a lazy token stream."""
    prompt = build_prompt(question, fp, r)
    return prompt, backend.stream(prompt)


def collect(backend: Backend, question: str, fp: Fingerprint, r: Retrieval) -> Answer:
    prompt, stream = stream_answer(backend, question, fp, r)
    try:
        text = "".join(stream)
    except BackendUnavailable:
        raise
    return Answer(text.strip(), backend.name, r, fp, prompt)
