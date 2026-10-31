"""Custom auxiliary headers follow route identity through actual SDK requests."""
import json

import httpx
import pytest
import yaml

import agent.auxiliary_client as aux

URL = "https://proxy.example.test:443/v1"
HEADER = "offline-unusable-route"


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    cfg = {
        "model": {"provider": "custom:second", "model": "offline", "base_url": URL},
        "custom_providers": [
            {"name": "first", "base_url": URL, "api_key": "offline-key",
             "extra_headers": {"X-Route": "wrong-identity"}},
            {"name": "second", "base_url": URL, "api_key": "offline-key",
             "extra_headers": {"X-Route": HEADER, "X-Only-Second": "yes"},
             "extra_body": {"cost_ceiling": "standard"}},
        ],
        "fallback_model": None,
        "auxiliary": {"transient_retries": 0},
    }

    def write():
        (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
        # Config loading and resolution remain real; only transport is intercepted.
        aux._aux_unhealthy_until.clear()
        aux._aux_unhealthy_logged_at.clear()

    write()
    return cfg, write


def response(request, seen):
    seen.append(request)
    return httpx.Response(200, json={
        "id": "offline", "object": "chat.completion", "created": 1,
        "model": "offline", "choices": [{"index": 0, "message": {
            "role": "assistant", "content": "intercepted"}, "finish_reason": "stop"}],
    }, request=request)


def test_named_and_anonymous_routes_keep_selected_identity(config):
    for provider in ("custom:second", "custom"):
        kwargs = {} if provider != "custom" else {
            "explicit_base_url": URL, "explicit_api_key": "offline-key"}
        client, model = aux.resolve_provider_client(
            provider, model="offline", api_mode="chat_completions", **kwargs)
        seen = []
        old = client._client
        client._client = httpx.Client(transport=httpx.MockTransport(lambda req: response(req, seen)))
        client.chat.completions.create(model=model, messages=[{"role": "user", "content": "offline"}])
        assert seen[0].headers["X-Route"] == HEADER
        assert seen[0].headers["X-Only-Second"] == "yes"
        assert seen[0].headers["Authorization"] == "Bearer offline-key"
        assert "cost_ceiling" not in json.loads(seen[0].content)
        client.close()
        old.close()


@pytest.mark.parametrize("url", [
    "http://proxy.example.test/v1", "https://proxy.example.test:444/v1",
    "https://proxy.example.test/v1-other", "https://proxy.example.test/V1",
    "https://proxy.example.test.evil.test/v1", "https://unrelated.test/v1",
])
def test_custom_headers_do_not_cross_endpoint_boundary(config, url):
    client, _ = aux.resolve_provider_client(
        "custom", model="offline", explicit_base_url=url,
        explicit_api_key="offline-key", api_mode="chat_completions")
    assert "X-Route" not in client.default_headers
    assert "X-Only-Second" not in client.default_headers
    client.close()


def test_user_headers_keep_existing_auxiliary_precedence(config):
    cfg, write = config
    cfg["model"]["default_headers"] = {"X-Route": "global"}
    cfg["model"]["extra_headers"] = {"X-Route": "alias"}
    write()
    client, _ = aux.resolve_provider_client("custom:second", model="offline", api_mode="chat_completions")
    assert client.default_headers["X-Route"] == "alias"
    assert client.default_headers["X-Only-Second"] == "yes"
    client.close()


@pytest.mark.parametrize("provider, expected", [("custom:second", HEADER), ("custom:first", "wrong-identity")])
@pytest.mark.asyncio
async def test_public_sync_async_calls_keep_headers_without_inheriting_body(config, monkeypatch, provider, expected):
    seen = []
    original = aux._create_openai_client

    def create(*args, **kwargs):
        client = original(*args, **kwargs)
        old = client._client
        client._client = httpx.Client(transport=httpx.MockTransport(lambda req: response(req, seen)))
        old.close()
        return client

    import openai
    original_async = openai.AsyncOpenAI

    class InterceptedAsyncOpenAI(original_async):
        def __init__(self, **kwargs):
            kwargs.pop("http_client", None)
            super().__init__(**kwargs, http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(lambda req: response(req, seen))))

    monkeypatch.setattr(aux, "_create_openai_client", create)
    monkeypatch.setattr(openai, "AsyncOpenAI", InterceptedAsyncOpenAI)
    kwargs = dict(task="session_search", provider=provider, model="offline",
                  messages=[{"role": "user", "content": "offline"}], timeout=5)
    assert aux.call_llm(**kwargs).choices[0].message.content == "intercepted"
    assert (await aux.async_call_llm(**kwargs)).choices[0].message.content == "intercepted"
    assert len(seen) == 2
    for request in seen:
        assert request.headers["X-Route"] == expected
        assert ("X-Only-Second" in request.headers) == (provider == "custom:second")
        assert "cost_ceiling" not in json.loads(request.content)


def test_main_runtime_route_and_named_mismatch(config):
    client, _ = aux.resolve_provider_client(
        "custom", model="offline", main_runtime={
            "provider": "custom", "model": "offline", "base_url": URL,
            "api_key": "offline-key"}, api_mode="chat_completions")
    assert client.default_headers["X-Route"] == HEADER
    client.close()
    # Naming a provider cannot transfer its headers onto an unrelated route.
    assert not aux._custom_provider_default_headers("https://unrelated.test/v1", "custom:second")
