import json

import tools.media_connectors_tool as media_connectors
from toolsets import resolve_toolset


def _result(payload: str) -> dict:
    return json.loads(payload)


def test_media_connector_status_redacts_secret_values(monkeypatch):
    env = {
        "CLOUDINARY_URL": "cloudinary://api_key:super-secret@example",
        "VIMEO_ACCESS_TOKEN": "vimeo-secret",
    }
    monkeypatch.setattr(media_connectors, "_get_env_value", lambda name: env.get(name, ""))
    monkeypatch.setattr(media_connectors, "_load_config", lambda: {})

    result = _result(media_connectors.media_connector_status())
    dumped = json.dumps(result)

    assert result["success"] is True
    assert result["secrets_redacted"] is True
    assert result["services"]["cloudinary"]["configured"] is True
    assert result["services"]["vimeo"]["configured"] is True
    assert "super-secret" not in dumped
    assert "vimeo-secret" not in dumped


def test_media_connector_preflight_marks_write_and_cost_paths(monkeypatch):
    env = {"VIMEO_ACCESS_TOKEN": "token"}
    monkeypatch.setattr(media_connectors, "_get_env_value", lambda name: env.get(name, ""))
    monkeypatch.setattr(media_connectors, "_load_config", lambda: {})

    result = _result(
        media_connectors.media_connector_status(
            action="preflight",
            service="vimeo",
            operation="upload",
        )
    )

    assert result["ready"] is True
    assert result["requires_approval"] is True
    assert result["missing"] == []


def test_media_connector_tracks_gemini_omni_flow_handoff(monkeypatch):
    env = {"GOOGLE_FLOW_HOME_URL": "https://flow.google"}
    monkeypatch.setattr(media_connectors, "_get_env_value", lambda name: env.get(name, ""))
    monkeypatch.setattr(media_connectors, "_load_config", lambda: {})

    status = _result(media_connectors.media_connector_status(service="gemini_omni"))
    preflight = _result(
        media_connectors.media_connector_status(
            action="preflight",
            service="gemini_omni",
            operation="generate",
        )
    )

    assert status["services"]["gemini_omni"]["configured"] is True
    assert status["services"]["gemini_omni"]["env"]["GOOGLE_FLOW_HOME_URL"] is True
    assert preflight["ready"] is True
    assert preflight["requires_approval"] is True


def test_media_connector_local_voice_and_local_llm_from_config(monkeypatch):
    monkeypatch.setattr(media_connectors, "_get_env_value", lambda name: "")
    monkeypatch.setattr(
        media_connectors,
        "_load_config",
        lambda: {
            "model": {"provider": "custom", "base_url": "http://localhost:11434/v1"},
            "tts": {
                "provider": "orpheus",
                "providers": {
                    "orpheus": {
                        "type": "command",
                        "command": "orpheus --text-file {input_path} --out {output_path}",
                    }
                },
            },
        },
    )

    result = _result(media_connectors.media_connector_status(service="all"))

    assert result["services"]["local_llm"]["configured"] is True
    assert result["services"]["local_llm"]["local_url"] is True
    assert result["services"]["local_voice"]["configured"] is True
    assert result["services"]["local_voice"]["command_providers"]["orpheus"] is True


def test_media_connector_toolsets_are_resolvable():
    assert "media_connector_status" in resolve_toolset("media_connectors")
    assert "media_connector_status" in resolve_toolset("video_editing")
