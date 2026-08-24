from __future__ import annotations

import pytest

from hdh import backends
from hdh.backends import BackendUnavailable, ClaudeCLIBackend, OfflineBackend


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


def test_offline_is_always_available() -> None:
    assert OfflineBackend().available()


def test_offline_refuses_to_synthesise() -> None:
    with pytest.raises(BackendUnavailable):
        list(OfflineBackend().stream("anything"))


def test_detect_falls_back_to_offline_with_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    assert backends.detect().name == "offline"


def test_detect_prefers_cli_over_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    assert backends.detect().name == "claude-cli"


def test_detect_prefers_api_key_over_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    assert backends.detect().name == "anthropic"


def test_explicit_preference_overrides_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends.shutil, "which", lambda _: "/usr/bin/claude")
    assert backends.detect("offline").name == "offline"


def test_unknown_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown backend"):
        backends.make("telepathy")


def test_cli_backend_reports_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backends.shutil, "which", lambda _: None)
    backend = ClaudeCLIBackend()
    assert not backend.available()
    with pytest.raises(BackendUnavailable, match="not on PATH"):
        list(backend.stream("hi"))


def test_survey_covers_every_backend() -> None:
    names = [i.name for i in backends.survey()]
    assert names == list(backends.ORDER)
    assert all(i.detail for i in backends.survey())


def test_system_prompt_encodes_the_product_promise() -> None:
    prompt = backends.SYSTEM_PROMPT.lower()
    assert "idiom" in prompt
    assert "path:line" in prompt
    assert "never give a generic answer" in prompt
