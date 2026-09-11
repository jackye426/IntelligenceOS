"""Resilience of the OpenRouter chat wrapper.

Regression: a provider returning empty content surfaced downstream as
json.loads("") failing with "Expecting value: line 1 column 1 (char 0)" — an
error that reads like a JSON bug in our code rather than a missing response.
About a third of one 242-video batch failed this way.
"""

from __future__ import annotations

import pytest

from marketing_pipeline.shared import openrouter_client as oc


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, content, finish_reason="stop"):
        self.choices = [_Choice(content, finish_reason)]


def _client_returning(sequence, calls):
    class _Completions:
        def create(self, **_kw):
            calls.append(1)
            item = sequence[min(len(calls) - 1, len(sequence) - 1)]
            return _Resp(*item) if isinstance(item, tuple) else _Resp(item)

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return _Client()


def test_retries_until_content_arrives(monkeypatch):
    calls: list = []
    monkeypatch.setattr(oc, "_get_client", lambda: _client_returning(["", "", '{"ok":1}'], calls))
    monkeypatch.setattr(oc.time, "sleep", lambda *_: None)
    assert oc.chat_completion(system="s", user="u") == '{"ok":1}'
    assert len(calls) == 3


def test_persistent_emptiness_raises_a_diagnosable_error(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        oc, "_get_client", lambda: _client_returning([("", "length")], calls)
    )
    monkeypatch.setattr(oc.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError) as err:
        oc.chat_completion(system="s", user="u", attempts=3)
    message = str(err.value)
    assert "empty content" in message
    assert "finish_reason='length'" in message, "the caller needs the provider's reason"
    assert len(calls) == 3


def test_first_success_makes_no_extra_calls(monkeypatch):
    calls: list = []
    monkeypatch.setattr(oc, "_get_client", lambda: _client_returning(['{"ok":1}'], calls))
    assert oc.chat_completion(system="s", user="u") == '{"ok":1}'
    assert len(calls) == 1
