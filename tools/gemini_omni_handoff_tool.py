#!/usr/bin/env python3
"""Gemini Omni handoff packets for creative video editing."""

from __future__ import annotations

import html
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from tools.registry import registry, tool_error, tool_result


def _handoff_root() -> Path:
    configured = os.environ.get("HERMES_GEMINI_OMNI_HANDOFF_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return get_hermes_home() / "gemini-omni-handoffs"


def _new_handoff_id() -> str:
    return f"omni-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def _safe_handoff_dir(handoff_id: str) -> Path:
    return _handoff_root() / Path(handoff_id).name


def _path_status(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {"path": None, "exists": False}
    path = Path(str(path_value)).expanduser()
    return {
        "path": str(path.resolve()) if path.exists() else str(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "is_dir": path.is_dir(),
    }


def _normalize_assets(assets: Any) -> list[dict[str, Any]]:
    if assets is None:
        return []
    if not isinstance(assets, list):
        raise ValueError("assets must be a list")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(assets):
        if isinstance(item, str):
            raw = {"path": item}
        elif isinstance(item, dict):
            raw = dict(item)
        else:
            raise ValueError(f"asset {index} must be an object or path string")
        path_value = raw.get("path") or raw.get("source") or raw.get("source_path")
        path_info = _path_status(path_value)
        normalized.append(
            {
                "index": index,
                "path": path_info["path"],
                "exists": path_info["exists"],
                "kind": str(raw.get("kind") or raw.get("type") or "reference"),
                "role": str(raw.get("role") or "reference"),
                "label": str(raw.get("label") or Path(str(path_value or f"asset_{index}")).stem),
                "notes": str(raw.get("notes") or ""),
                "start": raw.get("start"),
                "duration": raw.get("duration"),
                "transcript": raw.get("transcript") or raw.get("text"),
            }
        )
    return normalized


def _direct_api_configured() -> bool:
    return bool(os.environ.get("GEMINI_OMNI_API_URL") and os.environ.get("GEMINI_OMNI_API_KEY"))


def _flow_prompt(payload: dict[str, Any]) -> str:
    lines = [
        f"# {payload['title']}",
        "",
        "Gemini Omni task: create or revise a coherent video using the attached references.",
        "",
        "## Creative Brief",
        payload.get("brief") or "",
        "",
        "## Instruction",
        payload.get("prompt") or "",
        "",
        "## Output Spec",
        json.dumps(payload.get("output_spec") or {}, indent=2),
        "",
        "## Assets",
    ]
    for asset in payload.get("assets") or []:
        lines.append(
            f"- {asset['label']} [{asset['kind']} / {asset['role']}]: {asset['path']}"
            + (f" -- {asset['notes']}" if asset.get("notes") else "")
        )
        if asset.get("transcript"):
            lines.append(f"  transcript: {asset['transcript']}")
    if payload.get("revision_instructions"):
        lines.extend(["", "## Revision Instructions", str(payload["revision_instructions"])])
    lines.extend(
        [
            "",
            "## Editing Notes",
            "Maintain continuity across turns. Preserve intentional audio rhythm, source identity, and editorial logic unless the revision asks for a change.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _write_review(path: Path, payload: dict[str, Any], artifacts: dict[str, str]) -> None:
    rows = []
    for asset in payload.get("assets") or []:
        rows.append(
            "<tr>"
            f"<td>{asset['index']}</td>"
            f"<td>{html.escape(asset['label'])}</td>"
            f"<td>{html.escape(asset['kind'])}</td>"
            f"<td>{html.escape(asset['role'])}</td>"
            f"<td>{'yes' if asset['exists'] else 'no'}</td>"
            f"<td>{html.escape(str(asset['path'] or ''))}</td>"
            "</tr>"
        )
    body = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(payload['title'])}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 32px; color: #151515; background: #f7f7f4; }}
pre {{ white-space: pre-wrap; background: white; border: 1px solid #d6d6d0; padding: 16px; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
td, th {{ border: 1px solid #d6d6d0; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #ecece6; }}
.meta {{ color: #555; }}
</style>
<h1>{html.escape(payload['title'])}</h1>
<p class="meta">Gemini Omni / Google Flow handoff packet. Direct API configured: {'yes' if payload['direct_api_configured'] else 'no'}.</p>
<p><a href="{html.escape(Path(artifacts['handoff_json']).name)}">handoff JSON</a> · <a href="{html.escape(Path(artifacts['flow_prompt']).name)}">Flow prompt</a> · <a href="{html.escape(Path(artifacts['api_request']).name)}">API request draft</a></p>
<h2>Prompt</h2>
<pre>{html.escape(payload.get('prompt') or '')}</pre>
<h2>Assets</h2>
<table>
<thead><tr><th>#</th><th>Label</th><th>Kind</th><th>Role</th><th>Exists</th><th>Path</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""
    path.write_text(body, encoding="utf-8")


def _prepare(args: dict[str, Any]) -> str:
    prompt = str(args.get("prompt") or "").strip()
    brief = str(args.get("brief") or "").strip()
    if not prompt and not brief:
        return tool_error("prompt or brief is required")
    handoff_id = str(args.get("handoff_id") or _new_handoff_id())
    handoff_dir = _safe_handoff_dir(handoff_id)
    handoff_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "handoff_id": handoff_id,
        "created_at": time.time(),
        "title": str(args.get("title") or "Gemini Omni Handoff"),
        "brief": brief,
        "prompt": prompt,
        "revision_instructions": args.get("revision_instructions") or "",
        "assets": _normalize_assets(args.get("assets")),
        "output_spec": args.get("output_spec") if isinstance(args.get("output_spec"), dict) else {},
        "editing_suite_project": args.get("editing_suite_project") or args.get("project_path"),
        "notes": args.get("notes") or "",
        "target_surfaces": ["Google Flow", "Gemini App", "future Gemini Omni API"],
        "direct_api_configured": _direct_api_configured(),
        "direct_api_status": (
            "configured but not invoked by Hermes until Google documents a stable Gemini Omni API"
            if _direct_api_configured()
            else "not configured; current public path is Google Flow/Gemini app handoff"
        ),
        "guardrails": [
            "Do not claim a direct Gemini Omni developer API unless GEMINI_OMNI_API_URL and GEMINI_OMNI_API_KEY are configured and verified.",
            "Generated or edited video should retain provenance metadata and be treated as AI-generated media.",
            "Speech-changing and likeness-sensitive edits require explicit approval and source provenance.",
        ],
    }

    handoff_json = handoff_dir / "omni_handoff.json"
    flow_prompt = handoff_dir / "flow_prompt.md"
    api_request = handoff_dir / "api_request_draft.json"
    review_html = handoff_dir / "review.html"
    handoff_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    flow_prompt.write_text(_flow_prompt(payload), encoding="utf-8")
    api_request.write_text(
        json.dumps(
            {
                "model": "gemini-omni-flash",
                "contents": {
                    "prompt": payload["prompt"],
                    "brief": payload["brief"],
                    "assets": payload["assets"],
                    "output_spec": payload["output_spec"],
                },
                "note": "Draft only until Google publishes a stable Gemini Omni developer API.",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    artifacts = {
        "handoff_json": str(handoff_json),
        "flow_prompt": str(flow_prompt),
        "api_request": str(api_request),
        "review_html": str(review_html),
    }
    _write_review(review_html, payload, artifacts)
    return tool_result(
        {
            "success": True,
            "handoff_id": handoff_id,
            "handoff_dir": str(handoff_dir),
            "direct_api_configured": payload["direct_api_configured"],
            "artifacts": artifacts,
            "missing_assets": [asset for asset in payload["assets"] if not asset["exists"]],
            "next_steps": [
                "Open flow_prompt.md in Google Flow/Gemini Omni and attach the listed source assets.",
                "Keep omni_handoff.json with the editing-suite project as the provenance and revision packet.",
                "When Google exposes a stable Gemini Omni API, wire api_request_draft.json into the direct submission path.",
            ],
        }
    )


def _status(args: dict[str, Any]) -> str:
    handoff_id = str(args.get("handoff_id") or "").strip()
    if not handoff_id:
        return tool_error("handoff_id is required for status")
    handoff_dir = _safe_handoff_dir(handoff_id)
    if not handoff_dir.exists():
        return tool_error(f"unknown Gemini Omni handoff: {handoff_id}")
    handoff = handoff_dir / "omni_handoff.json"
    payload = {}
    if handoff.exists():
        try:
            payload = json.loads(handoff.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    return tool_result(
        {
            "success": True,
            "handoff_id": handoff_id,
            "handoff_dir": str(handoff_dir),
            "direct_api_configured": _direct_api_configured(),
            "artifacts": {
                "handoff_json": str(handoff),
                "flow_prompt": str(handoff_dir / "flow_prompt.md"),
                "api_request": str(handoff_dir / "api_request_draft.json"),
                "review_html": str(handoff_dir / "review.html"),
            },
            "handoff": payload,
        }
    )


def gemini_omni_handoff(
    action: str = "prepare",
    handoff_id: str | None = None,
    prompt: str | None = None,
    brief: str | None = None,
    assets: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> str:
    """Prepare or inspect a Gemini Omni / Google Flow editing handoff."""
    args = {
        "action": action,
        "handoff_id": handoff_id,
        "prompt": prompt,
        "brief": brief,
        "assets": assets,
        **kwargs,
    }
    normalized = str(action or "prepare").strip().lower()
    if normalized in {"prepare", "package", "handoff"}:
        return _prepare(args)
    if normalized == "status":
        return _status(args)
    return tool_error(f"unknown action: {normalized}")


GEMINI_OMNI_HANDOFF_SCHEMA = {
    "name": "gemini_omni_handoff",
    "description": (
        "Prepare Gemini Omni / Google Flow creative editing handoff packets. "
        "Use for any-input video generation or conversational video edits when "
        "direct Gemini Omni API access is not yet verified. Produces Flow-ready "
        "prompts, asset manifests, review HTML, and an API request draft for "
        "future direct integration."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["prepare", "status"],
                "description": "prepare a new handoff packet or inspect an existing one",
                "default": "prepare",
            },
            "handoff_id": {"type": "string", "description": "Existing or caller-specified handoff id"},
            "title": {"type": "string", "description": "Human-readable title for the handoff"},
            "brief": {"type": "string", "description": "Creative brief and editorial intent"},
            "prompt": {"type": "string", "description": "Gemini Omni / Google Flow instruction prompt"},
            "revision_instructions": {"type": "string", "description": "Multi-turn edit instructions to preserve continuity"},
            "assets": {
                "type": "array",
                "description": "Reference media assets with path/source, kind, role, label, notes, start, duration, and transcript.",
                "items": {"type": "object"},
            },
            "output_spec": {
                "type": "object",
                "description": "Expected duration, aspect ratio, resolution, style, audio policy, delivery target, and other output constraints.",
            },
            "editing_suite_project": {"type": "string", "description": "Optional Patrick's Editing Room project path or id"},
            "notes": {"type": "string", "description": "Operator notes kept in the handoff packet"},
        },
        "required": ["action"],
    },
}


registry.register(
    name="gemini_omni_handoff",
    toolset="video_editing",
    schema=GEMINI_OMNI_HANDOFF_SCHEMA,
    handler=lambda args, **kwargs: gemini_omni_handoff(**args),
    check_fn=lambda: True,
    emoji="✨",
)
