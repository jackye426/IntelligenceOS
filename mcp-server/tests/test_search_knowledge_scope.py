from __future__ import annotations

from tools import search_knowledge as module


class _Result:
    data = []


class _Rpc:
    def execute(self):
        return _Result()


class _Client:
    def __init__(self):
        self.params = None

    def rpc(self, _name, params):
        self.params = params
        return _Rpc()


def test_search_knowledge_is_docmap_scoped(monkeypatch):
    client = _Client()
    monkeypatch.setattr(module, "embed_text", lambda _query: [0.0])
    monkeypatch.setattr(module, "get_client", lambda: client)
    monkeypatch.setattr(module, "log_tool_call", lambda **_kwargs: None)

    assert module.search_knowledge("hooks") == []
    assert client.params["filter_owner_scope"] == "docmap"
