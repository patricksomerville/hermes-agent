#!/usr/bin/env python3
"""Hermes cloud video editing tool.

This tool submits deterministic video edit jobs to the bundled FFmpeg worker
and returns render metadata shaped for Remotion review/composition flows.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home
from tools.registry import registry, tool_error, tool_result


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKER_PATH = PROJECT_ROOT / "skills" / "media" / "cloud-video-editor" / "scripts" / "cloud_video_edit_worker.py"


def _jobs_root() -> Path:
    configured = os.environ.get("HERMES_VIDEO_EDIT_JOBS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return get_hermes_home() / "video-edit-jobs"


def _fetch_root() -> Path:
    configured = os.environ.get("HERMES_VIDEO_EDIT_FETCH_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return get_hermes_home() / "video-edit-fetches"


def _job_dir(job_id: str) -> Path:
    safe = Path(job_id).name
    return _jobs_root() / safe


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
    except Exception:
        return None
    return None


def _copy_if_present(path_value: Any, dest_dir: Path) -> str | None:
    if not path_value:
        return None
    src = Path(str(path_value)).expanduser()
    if not src.exists() or not src.is_file():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return str(dest)


def _copy_path_if_present(path_value: Any, dest_dir: Path) -> str | None:
    if not path_value:
        return None
    src = Path(str(path_value)).expanduser()
    if not src.exists():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.is_dir():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        return str(dest)
    return _copy_if_present(src, dest_dir)


def _copy_render_artifacts(render_plan: dict[str, Any] | None, dest_dir: Path) -> dict[str, Any]:
    if not isinstance(render_plan, dict):
        return {}
    artifacts = render_plan.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    copied: dict[str, Any] = {}
    for key in ("review_packet", "remotion_props", "edl", "review_html", "remotion_project"):
        copied_path = _copy_path_if_present(artifacts.get(key), dest_dir)
        if copied_path:
            copied[key] = copied_path
    stills = artifacts.get("review_stills")
    if isinstance(stills, dict):
        copied_stills = {}
        for index, path_value in stills.items():
            copied_path = _copy_path_if_present(path_value, dest_dir / "review")
            if copied_path:
                copied_stills[str(index)] = copied_path
        if copied_stills:
            copied["review_stills"] = copied_stills
    return copied


def _new_job_id() -> str:
    return f"video-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def _submit(args: dict[str, Any]) -> str:
    edit_plan = args.get("edit_plan")
    if not isinstance(edit_plan, dict):
        return tool_error("edit_plan must be an object")
    if not WORKER_PATH.exists():
        return tool_error(f"video edit worker is missing: {WORKER_PATH}")

    job_id = str(args.get("job_id") or _new_job_id())
    output_dir = _job_dir(job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id,
        "source": args.get("source") or args.get("source_path"),
        "source_path": args.get("source_path") or args.get("source"),
        "edit_plan": edit_plan,
        "output_dir": str(output_dir),
        "output_name": args.get("output_name") or "final.mp4",
        "width": args.get("width"),
        "height": args.get("height"),
        "fps": args.get("fps"),
        "notes": args.get("notes") or "",
    }
    job_json = output_dir / "job.json"
    job_json.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")

    stdout = open(output_dir / "worker.stdout.log", "ab")
    stderr = open(output_dir / "worker.stderr.log", "ab")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(WORKER_PATH), str(job_json)],
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
    finally:
        stdout.close()
        stderr.close()

    (output_dir / "pid").write_text(str(proc.pid), encoding="utf-8")
    status_path = output_dir / "status.json"
    if not status_path.exists():
        status_path.write_text(
            json.dumps({"status": "queued", "pid": proc.pid, "submitted_at": time.time()}, indent=2),
            encoding="utf-8",
        )
    return tool_result(
        {
            "success": True,
            "job_id": job_id,
            "status": "queued",
            "pid": proc.pid,
            "job_dir": str(output_dir),
            "status_path": str(status_path),
            "render_plan_path": str(output_dir / "render_plan.json"),
        }
    )


def _status(args: dict[str, Any]) -> str:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return tool_error("job_id is required for status")
    output_dir = _job_dir(job_id)
    if not output_dir.exists():
        return tool_error(f"unknown video edit job: {job_id}")

    status = _read_json(output_dir / "status.json") or {"status": "unknown"}
    render_plan = _read_json(output_dir / "render_plan.json")
    result: dict[str, Any] = {
        "success": True,
        "job_id": job_id,
        "job_dir": str(output_dir),
        "status": status.get("status", "unknown"),
        "details": status,
        "render_plan": render_plan,
    }
    if args.get("fetch_output"):
        fetch_dir = _fetch_root() / job_id
        result["fetched_output"] = _copy_if_present(status.get("output_path"), fetch_dir)
        result["fetched_thumbnail"] = _copy_if_present(status.get("thumbnail_path"), fetch_dir)
        if render_plan:
            render_copy = _copy_if_present(output_dir / "render_plan.json", fetch_dir)
            result["fetched_render_plan"] = render_copy
            result["fetched_artifacts"] = _copy_render_artifacts(render_plan, fetch_dir)
    return tool_result(result)


def _cancel(args: dict[str, Any]) -> str:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return tool_error("job_id is required for cancel")
    output_dir = _job_dir(job_id)
    pid_path = output_dir / "pid"
    if not pid_path.exists():
        return tool_error(f"no pid recorded for video edit job: {job_id}")
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception as exc:
        return tool_error(f"failed to cancel video edit job {job_id}: {exc}")
    status_path = output_dir / "status.json"
    status_path.write_text(
        json.dumps({"status": "cancelled", "cancelled_at": time.time(), "pid": pid}, indent=2),
        encoding="utf-8",
    )
    return tool_result(success=True, job_id=job_id, status="cancelled")


def cloud_video_edit(
    action: str = "submit",
    job_id: str | None = None,
    edit_plan: dict[str, Any] | None = None,
    source: str | None = None,
    source_path: str | None = None,
    fetch_output: bool = False,
    **kwargs: Any,
) -> str:
    """Submit, inspect, fetch, or cancel a Hermes video edit job."""
    args = {
        "action": action,
        "job_id": job_id,
        "edit_plan": edit_plan,
        "source": source,
        "source_path": source_path,
        "fetch_output": fetch_output,
        **kwargs,
    }
    normalized = str(args.get("action") or "submit").strip().lower()
    if normalized == "submit":
        return _submit(args)
    if normalized in {"status", "fetch", "fetch_output"}:
        args["fetch_output"] = bool(args.get("fetch_output") or normalized.startswith("fetch"))
        return _status(args)
    if normalized == "cancel":
        return _cancel(args)
    return tool_error(f"unknown action: {normalized}")


CLOUD_VIDEO_EDIT_SCHEMA = {
    "name": "cloud_video_edit",
    "description": (
        "Submit and track deterministic background video edit/render jobs. "
        "Use for trims, selects, title cards, labels, vertical/square/social "
        "exports, thumbnails, review stills, review HTML, EDL, and generated "
        "Remotion review project handoff. Status results include render_plan "
        "metadata for browser cut-review UIs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["submit", "status", "fetch", "cancel"],
                "description": "submit a new job, check status, fetch outputs, or cancel a job",
                "default": "submit",
            },
            "job_id": {"type": "string", "description": "Existing job id for status/fetch/cancel"},
            "source": {"type": "string", "description": "Optional default source video path"},
            "source_path": {"type": "string", "description": "Alias for source"},
            "fetch_output": {
                "type": "boolean",
                "description": "When checking status, copy the MP4, thumbnail, render plan, review packet, review HTML, EDL, Remotion props/project, and review stills into the local fetch cache.",
                "default": False,
            },
            "edit_plan": {
                "type": "object",
                "description": (
                    "Structured edit plan. Supports output presets "
                    "landscape/wide/youtube, vertical/portrait/reel/shorts/story/tiktok, "
                    "and square/feed. clips may be source clips with start/end/duration/label/mute "
                    "or title cards like {'type':'title_card','text':'Act One','duration':2}."
                ),
            },
            "output_name": {"type": "string", "description": "Output MP4 filename, default final.mp4"},
            "notes": {"type": "string", "description": "Creative/editorial notes kept with the job"},
        },
        "required": ["action"],
    },
}


registry.register(
    name="cloud_video_edit",
    toolset="video_editing",
    schema=CLOUD_VIDEO_EDIT_SCHEMA,
    handler=lambda args, **kwargs: cloud_video_edit(**args),
    check_fn=lambda: WORKER_PATH.exists(),
    emoji="🎬",
)
