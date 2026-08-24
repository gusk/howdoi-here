"""Pluggable answer backends, ordered by capability, with a floor that always works.

Nothing here is required to run hdh. If a key exists we use the SDK; if the Claude Code
CLI is installed we borrow its existing auth; if neither, retrieval still answers the
question with real snippets from the repo. `hdh doctor` prints which rung you're on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass

SYSTEM_PROMPT = (
    "You are a senior engineer answering a teammate's question about the codebase they are "
    "standing in. You are given a project fingerprint and real snippets from their repository "
    "and internal docs.\n\n"
    "Rules:\n"
    "- Answer in the language, idiom, and dependency versions of THIS project. Never give a "
    "generic answer in a language the project does not use.\n"
    "- If the repo already solves this, say so and point at it as path:line.\n"
    "- Prefer the project's own conventions over textbook style, even if you would write it "
    "differently.\n"
    "- Lead with a short direct answer, then one focused code block, then a line starting with "
    "'Sources:' listing the path:line refs you actually used.\n"
    "- If the provided context does not cover it, say so plainly and answer from general "
    "knowledge of the detected stack, flagged as such.\n"
    "- Be concise. No preamble, no restating the question."
)


class BackendUnavailable(RuntimeError):
    pass


@dataclass
class BackendInfo:
    name: str
    available: bool
    detail: str


class Backend:
    name = "base"

    def available(self) -> bool:
        raise NotImplementedError

    def detail(self) -> str:
        return ""

    def stream(self, prompt: str, system: str = SYSTEM_PROMPT) -> Iterator[str]:
        raise NotImplementedError

    def info(self) -> BackendInfo:
        return BackendInfo(self.name, self.available(), self.detail())


class AnthropicBackend(Backend):
    """Anthropic SDK. Used when ANTHROPIC_API_KEY (or an `ant` OAuth profile) is present."""

    name = "anthropic"

    def __init__(self, model: str = "claude-opus-5", max_tokens: int = 4096):
        self.model = model
        self.max_tokens = max_tokens

    def _sdk(self):  # noqa: ANN202
        try:
            import anthropic
        except ImportError as e:
            raise BackendUnavailable("anthropic SDK not installed (pip install 'howdoi-here[api]')") from e
        return anthropic

    def available(self) -> bool:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def detail(self) -> str:
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return "no ANTHROPIC_API_KEY in environment"
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return "key found, but: pip install 'howdoi-here[api]'"
        return f"key found · {self.model}"

    def stream(self, prompt: str, system: str = SYSTEM_PROMPT) -> Iterator[str]:
        anthropic = self._sdk()
        client = anthropic.Anthropic()
        try:
            with client.messages.stream(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                yield from stream.text_stream
        except anthropic.NotFoundError as e:
            raise BackendUnavailable(f"model {self.model} not available: {e}") from e
        except anthropic.RateLimitError as e:
            raise BackendUnavailable(f"rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise BackendUnavailable(f"API error {e.status_code}: {e}") from e
        except anthropic.APIConnectionError as e:
            raise BackendUnavailable(f"connection failed: {e}") from e


class ClaudeCLIBackend(Backend):
    """Borrow the locally installed, already-authenticated Claude Code CLI.

    This is what makes hdh usable with zero credentials of its own: if you have Claude Code,
    you already have auth, and we shell out to it rather than asking you for a key.
    """

    name = "claude-cli"

    def __init__(self, model: str = "opus", timeout: int = 180):
        self.model = model
        self.timeout = timeout

    def _bin(self) -> str | None:
        return shutil.which("claude")

    def available(self) -> bool:
        return self._bin() is not None

    def detail(self) -> str:
        path = self._bin()
        return f"{path} · --model {self.model}" if path else "claude CLI not on PATH"

    def stream(self, prompt: str, system: str = SYSTEM_PROMPT) -> Iterator[str]:
        binary = self._bin()
        if not binary:
            raise BackendUnavailable("claude CLI not on PATH")
        cmd = [
            binary, "-p",
            "--model", self.model,
            "--system-prompt", system,
            "--output-format", "text",
            "--strict-mcp-config",
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as e:
            raise BackendUnavailable(f"could not launch claude CLI: {e}") from e

        assert proc.stdin and proc.stdout
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
            yield from proc.stdout
            if proc.wait(timeout=self.timeout) != 0:
                err = (proc.stderr.read() if proc.stderr else "").strip()
                raise BackendUnavailable(f"claude CLI exited {proc.returncode}: {err[:400]}")
        except subprocess.TimeoutExpired as e:
            proc.kill()
            raise BackendUnavailable(f"claude CLI timed out after {self.timeout}s") from e
        finally:
            if proc.poll() is None:
                proc.kill()


class OfflineBackend(Backend):
    """Always available. Answers with ranked snippets instead of prose."""

    name = "offline"

    def available(self) -> bool:
        return True

    def detail(self) -> str:
        return "retrieval only · no synthesis, no credentials"

    def stream(self, prompt: str, system: str = SYSTEM_PROMPT) -> Iterator[str]:
        raise BackendUnavailable("offline backend does not synthesise; render snippets instead")


ORDER = ("anthropic", "claude-cli", "offline")


def make(name: str, model: str = "claude-opus-5", cli_model: str = "opus") -> Backend:
    if name == "anthropic":
        return AnthropicBackend(model=model)
    if name == "claude-cli":
        return ClaudeCLIBackend(model=cli_model)
    if name == "offline":
        return OfflineBackend()
    raise ValueError(f"unknown backend {name!r} (expected one of {', '.join(ORDER)})")


def detect(preference: str = "auto", model: str = "claude-opus-5", cli_model: str = "opus") -> Backend:
    """First available backend in capability order; `preference` pins one explicitly."""
    if preference and preference != "auto":
        return make(preference, model, cli_model)
    for name in ORDER:
        backend = make(name, model, cli_model)
        if backend.available():
            return backend
    return OfflineBackend()


def survey(model: str = "claude-opus-5", cli_model: str = "opus") -> list[BackendInfo]:
    return [make(n, model, cli_model).info() for n in ORDER]
