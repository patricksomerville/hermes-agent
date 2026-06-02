#!/usr/bin/env python3
"""Status/preflight surface for media and local voice connectors."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

from tools.registry import registry, tool_error, tool_result


SECRET_ENV_NAMES = frozenset(
    {
        "CLOUDINARY_URL",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
        "VIMEO_ACCESS_TOKEN",
        "YOUTUBE_CLIENT_ID",
        "YOUTUBE_CLIENT_SECRET",
        "YOUTUBE_REFRESH_TOKEN",
        "GOOGLE_PHOTOS_CLIENT_ID",
        "GOOGLE_PHOTOS_CLIENT_SECRET",
        "GOOGLE_PHOTOS_REFRESH_TOKEN",
        "GEMINI_OMNI_API_KEY",
        "RUNWAY_API_KEY",
        "REPLICATE_API_TOKEN",
        "FAL_KEY",
        "ELEVENLABS_API_KEY",
        "MUX_TOKEN_ID",
        "MUX_TOKEN_SECRET",
        "FRAME_IO_ACCESS_TOKEN",
        "ASSEMBLYAI_API_KEY",
        "DEEPGRAM_API_KEY",
    }
)


def _get_env_value(name: str) -> str:
    try:
        from hermes_cli.config import get_env_value

        value = get_env_value(name)
    except Exception:
        value = os.getenv(name)
    return str(value or "").strip()


def _load_config() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _configured_envs(names: list[str]) -> list[str]:
    return [name for name in names if _get_env_value(name)]


def _group_ready(group: list[str]) -> bool:
    return all(_get_env_value(name) for name in group)


def _redacted_env_status(names: list[str]) -> dict[str, bool]:
    return {name: bool(_get_env_value(name)) for name in names}


def _is_local_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local")


def _local_model_status(config: dict[str, Any]) -> dict[str, Any]:
    model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
    provider = str(model_cfg.get("provider") or "").strip().lower()
    base_url = str(model_cfg.get("base_url") or _get_env_value("OPENAI_BASE_URL") or "").strip()
    configured = provider in {"custom", "lmstudio"} or _is_local_url(base_url)
    return {
        "configured": configured,
        "configured_via": "config.model" if configured else None,
        "provider": provider or None,
        "base_url_set": bool(base_url),
        "local_url": _is_local_url(base_url),
        "notes": [
            "Use Hermes Custom endpoint for Ollama, vLLM, llama.cpp, SGLang, LocalAI, and Aqua-hosted OpenAI-compatible servers.",
            "LM Studio is also listed as a first-class model provider in hermes model.",
        ],
    }


def _command_provider_config(config: dict[str, Any], name: str) -> dict[str, Any]:
    tts_cfg = config.get("tts") if isinstance(config.get("tts"), dict) else {}
    providers = tts_cfg.get("providers") if isinstance(tts_cfg.get("providers"), dict) else {}
    entry = providers.get(name)
    if isinstance(entry, dict):
        return entry
    legacy = tts_cfg.get(name)
    return legacy if isinstance(legacy, dict) else {}


def _local_voice_status(config: dict[str, Any]) -> dict[str, Any]:
    tts_cfg = config.get("tts") if isinstance(config.get("tts"), dict) else {}
    provider = str(tts_cfg.get("provider") or "").strip().lower()
    built_in_local = {"neutts", "kittentts", "piper"}
    command_names = ["orpheus", "vox", "voxcpm"]
    command_configured = {
        name: bool(str(_command_provider_config(config, name).get("command") or "").strip())
        for name in command_names
    }
    command_env = {
        "orpheus": bool(_get_env_value("ORPHEUS_TTS_COMMAND")),
        "vox": bool(_get_env_value("VOX_TTS_COMMAND") or _get_env_value("VOXCPM_TTS_COMMAND")),
    }
    configured = provider in built_in_local or any(command_configured.values()) or any(command_env.values())
    return {
        "configured": configured,
        "configured_via": "tts.provider" if provider in built_in_local or provider in command_names else None,
        "provider": provider or None,
        "built_in_local_providers": sorted(built_in_local),
        "command_providers": command_configured,
        "command_env": command_env,
        "notes": [
            "Orpheus and Vox/VoxCPM should be wired as Hermes command TTS providers so the exact local CLI/server command survives restarts.",
            "Use text_to_speech after media_connector_status confirms the command provider is configured.",
        ],
    }


SERVICE_PROFILES: dict[str, dict[str, Any]] = {
    "google_photos": {
        "label": "Google Photos",
        "kind": "media_library",
        "credential_groups": [["GOOGLE_PHOTOS_CLIENT_ID", "GOOGLE_PHOTOS_CLIENT_SECRET", "GOOGLE_PHOTOS_REFRESH_TOKEN"]],
        "capabilities": ["picker/import", "app-created uploads", "album/media metadata when scoped"],
        "guardrails": ["Drive access does not imply Photos access.", "Avoid promising full-library search/list behavior."],
    },
    "vimeo": {
        "label": "Vimeo",
        "kind": "publish_review",
        "credential_groups": [["VIMEO_ACCESS_TOKEN"]],
        "capabilities": ["upload", "transcode polling", "metadata/privacy", "folders", "review links"],
        "guardrails": ["Default uploads to private/unlisted unless the user names a publish target."],
    },
    "youtube": {
        "label": "YouTube Channel",
        "kind": "publish_channel",
        "credential_groups": [["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]],
        "capabilities": ["upload", "thumbnails", "captions", "playlist updates", "channel metadata"],
        "guardrails": ["Public YouTube read tools are not channel OAuth.", "Default publish status should be private or unlisted."],
    },
    "cloudinary": {
        "label": "Cloudinary",
        "kind": "asset_cdn",
        "credential_groups": [
            ["CLOUDINARY_URL"],
            ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"],
        ],
        "capabilities": ["upload", "transforms", "derived URLs", "metadata/search", "signed delivery"],
        "guardrails": ["Treat eager transformations as a spend/write path."],
    },
    "runway": {
        "label": "Runway",
        "kind": "paid_generation",
        "credential_groups": [["RUNWAY_API_KEY"]],
        "capabilities": ["generation", "task polling", "result fetch"],
        "guardrails": ["Check usage/balance and get explicit approval before generation."],
    },
    "replicate": {
        "label": "Replicate",
        "kind": "paid_generation",
        "credential_groups": [["REPLICATE_API_TOKEN"]],
        "capabilities": ["model prediction", "prediction polling", "cancel"],
        "guardrails": ["Log model slug, inputs, and prediction id for every run."],
    },
    "fal": {
        "label": "FAL.ai",
        "kind": "paid_generation",
        "credential_groups": [["FAL_KEY"]],
        "capabilities": ["image generation", "video generation", "remote model execution"],
        "guardrails": ["Paid generation path; require explicit creative intent."],
    },
    "gemini_omni": {
        "label": "Gemini Omni / Google Flow",
        "kind": "paid_generation",
        "credential_groups": [
            ["GEMINI_OMNI_API_URL", "GEMINI_OMNI_API_KEY"],
            ["GOOGLE_FLOW_HOME_URL"],
        ],
        "capabilities": [
            "Google Flow handoff packets",
            "any-input video generation/editing",
            "future direct API submission when Google publishes a stable endpoint",
        ],
        "guardrails": [
            "Current public path is Gemini App / Google Flow unless a direct API endpoint is explicitly configured and verified.",
            "Do not claim direct Gemini Omni API access from a normal GEMINI_API_KEY alone.",
            "Speech-changing, likeness-sensitive, public upload, and paid generation paths require explicit approval and provenance.",
        ],
    },
    "elevenlabs": {
        "label": "ElevenLabs",
        "kind": "paid_voice",
        "credential_groups": [["ELEVENLABS_API_KEY"]],
        "capabilities": ["voice listing", "TTS", "history/usage checks"],
        "guardrails": ["Do not clone or publish voices without permission and provenance."],
    },
    "mux": {
        "label": "Mux",
        "kind": "playback_infra",
        "credential_groups": [["MUX_TOKEN_ID", "MUX_TOKEN_SECRET"]],
        "capabilities": ["streamable assets", "HLS", "thumbnails", "webhooks"],
        "guardrails": ["Use for playback infrastructure, not editorial decision-making."],
    },
    "frame_io": {
        "label": "Frame.io",
        "kind": "review_collaboration",
        "credential_groups": [["FRAME_IO_ACCESS_TOKEN"]],
        "capabilities": ["review links", "comments", "version stacks"],
        "guardrails": ["Verify project/team destination before uploading client material."],
    },
    "assemblyai": {
        "label": "AssemblyAI",
        "kind": "paid_transcription",
        "credential_groups": [["ASSEMBLYAI_API_KEY"]],
        "capabilities": ["transcription", "word timestamps", "speaker labels", "summaries"],
        "guardrails": ["Use when local faster-whisper is not enough."],
    },
    "deepgram": {
        "label": "Deepgram",
        "kind": "paid_transcription",
        "credential_groups": [["DEEPGRAM_API_KEY"]],
        "capabilities": ["transcription", "captions", "speaker diarization", "word timing"],
        "guardrails": ["Use when local faster-whisper is not enough."],
    },
    "aqua_media": {
        "label": "Aqua Media Worker",
        "kind": "remote_local_worker",
        "credential_groups": [
            ["AQUA_MEDIA_SERVICE_URL"],
            ["AQUA_VIDEO_SERVICE_URL"],
            ["AQUA_VOICE_SERVICE_URL"],
        ],
        "capabilities": ["remote FFmpeg", "remote transcription", "local model/voice services"],
        "guardrails": ["Use MagicDNS/Bop Gun status checks first; do not run costly Aqua jobs without a named output plan."],
    },
}


WRITE_OPERATIONS = {
    "upload",
    "publish",
    "delete",
    "update",
    "update_metadata",
    "create_review_link",
    "transform",
    "eager_transform",
    "generate",
    "text_to_video",
    "image_to_video",
    "transcribe_paid",
    "remote_render",
}

COST_KINDS = {"paid_generation", "paid_voice", "paid_transcription", "asset_cdn", "publish_review", "publish_channel"}


def _status_for_profile(key: str, profile: dict[str, Any]) -> dict[str, Any]:
    groups = profile.get("credential_groups") or []
    configured_groups = [group for group in groups if _group_ready(group)]
    all_envs = sorted({name for group in groups for name in group})
    return {
        "service": key,
        "label": profile["label"],
        "kind": profile["kind"],
        "configured": bool(configured_groups),
        "configured_via": configured_groups,
        "env": _redacted_env_status(all_envs),
        "acceptable_credential_sets": groups,
        "capabilities": profile.get("capabilities", []),
        "guardrails": profile.get("guardrails", []),
    }


def _collect_status(service: str | None = None) -> dict[str, Any]:
    cfg = _load_config()
    requested = (service or "all").strip().lower().replace("-", "_")
    if requested and requested != "all" and requested not in SERVICE_PROFILES and requested not in {"local_voice", "local_llm"}:
        raise ValueError(f"unknown media connector service: {service}")

    statuses: dict[str, Any] = {}
    for key, profile in SERVICE_PROFILES.items():
        if requested in {"", "all", key}:
            statuses[key] = _status_for_profile(key, profile)

    if requested in {"", "all", "local_voice"}:
        statuses["local_voice"] = _local_voice_status(cfg)
    if requested in {"", "all", "local_llm"}:
        statuses["local_llm"] = _local_model_status(cfg)

    configured = sorted(key for key, value in statuses.items() if value.get("configured"))
    missing = sorted(key for key, value in statuses.items() if not value.get("configured"))
    return {
        "success": True,
        "services": statuses,
        "configured": configured,
        "missing": missing,
        "secrets_redacted": True,
    }


def _env_template() -> dict[str, Any]:
    keys = sorted(
        {name for profile in SERVICE_PROFILES.values() for group in profile.get("credential_groups", []) for name in group}
        | {"ORPHEUS_TTS_COMMAND", "VOX_TTS_COMMAND", "VOXCPM_TTS_COMMAND"}
    )
    return {
        "success": True,
        "env_template": [
            {
                "key": key,
                "secret": key in SECRET_ENV_NAMES,
                "configured": bool(_get_env_value(key)),
            }
            for key in keys
        ],
        "notes": [
            "Use tts.providers.<name>.command for Orpheus/Vox when possible; command env vars are convenience bootstrap values.",
            "Do not paste secret values into chat output; this tool reports only booleans.",
        ],
    }


def _preflight(service: str | None, operation: str | None) -> dict[str, Any]:
    if not service:
        raise ValueError("service is required for preflight")
    status = _collect_status(service)
    service_key = service.strip().lower().replace("-", "_")
    info = status["services"].get(service_key)
    if info is None:
        raise ValueError(f"unknown media connector service: {service}")
    op = (operation or "").strip().lower()
    profile = SERVICE_PROFILES.get(service_key, {})
    kind = str(info.get("kind") or profile.get("kind") or "")
    requires_approval = op in WRITE_OPERATIONS or kind in COST_KINDS
    ready = bool(info.get("configured"))
    return {
        "success": True,
        "service": service_key,
        "operation": op or None,
        "ready": ready,
        "requires_approval": requires_approval,
        "configured": ready,
        "missing": [] if ready else info.get("acceptable_credential_sets") or [],
        "guardrails": info.get("guardrails") or [],
        "recommendation": (
            "Ready after explicit approval for this write/cost path."
            if ready and requires_approval
            else "Ready for read/status work."
            if ready
            else "Configure one acceptable credential set before using this connector."
        ),
    }


def media_connector_status(
    action: str = "status",
    service: str | None = None,
    operation: str | None = None,
    **_: Any,
) -> str:
    """Report or preflight media connector readiness without revealing secrets."""
    try:
        normalized = (action or "status").strip().lower()
        if normalized == "status":
            return tool_result(_collect_status(service))
        if normalized == "env_template":
            return tool_result(_env_template())
        if normalized == "preflight":
            return tool_result(_preflight(service, operation))
        return tool_error(f"unknown action: {normalized}")
    except Exception as exc:
        return tool_error(str(exc))


MEDIA_CONNECTOR_STATUS_SCHEMA = {
    "name": "media_connector_status",
    "description": (
        "Check configured media, publishing, paid generation, transcription, "
        "local LLM, and local voice connectors without revealing secrets. Use "
        "before promising Google Photos, Vimeo, YouTube channel, Cloudinary, "
        "Runway, Replicate, FAL, Gemini Omni/Flow, ElevenLabs, Mux, Frame.io, "
        "Aqua, Orpheus, or Vox/VoxCPM behavior."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "preflight", "env_template"],
                "default": "status",
                "description": "status reports configured connectors; preflight checks one service/operation; env_template lists supported env keys.",
            },
            "service": {
                "type": "string",
                "description": "Optional service key such as cloudinary, vimeo, youtube, google_photos, runway, replicate, fal, gemini_omni, elevenlabs, mux, frame_io, assemblyai, deepgram, aqua_media, local_voice, or local_llm.",
            },
            "operation": {
                "type": "string",
                "description": "Optional operation for preflight, e.g. upload, publish, generate, transform, transcribe_paid, remote_render, or status.",
            },
        },
    },
}


registry.register(
    name="media_connector_status",
    toolset="media_connectors",
    schema=MEDIA_CONNECTOR_STATUS_SCHEMA,
    handler=lambda args, **kwargs: media_connector_status(**args),
    check_fn=lambda: True,
    emoji="🔌",
)
