#!/usr/bin/env python3
"""Hermes sound collage editing tool.

Submits deterministic FFmpeg jobs for overlapping speech montage, sound
design, and reviewable audio collages.
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
WORKER_PATH = (
    PROJECT_ROOT
    / "skills"
    / "media"
    / "sound-collage-editor"
    / "scripts"
    / "sound_collage_worker.py"
)


def _jobs_root() -> Path:
    configured = os.environ.get("HERMES_SOUND_COLLAGE_JOBS_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return get_hermes_home() / "sound-collage-jobs"


def _fetch_root() -> Path:
    configured = os.environ.get("HERMES_SOUND_COLLAGE_FETCH_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return get_hermes_home() / "sound-collage-fetches"


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


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def _probe_source(source: str | None) -> str:
    if not source:
        return tool_error("source is required for probe")
    binary = _ffprobe()
    if not binary:
        return tool_error("ffprobe is required to probe sound files")
    path = Path(source).expanduser()
    if not path.exists() or not path.is_file():
        return tool_error(f"source not found: {source}")
    try:
        raw = subprocess.check_output(
            [
                binary,
                "-v",
                "error",
                "-show_entries",
                "format=duration,size,format_name:stream=codec_type,codec_name,sample_rate,channels",
                "-of",
                "json",
                str(path),
            ],
            text=True,
        )
        probe = json.loads(raw)
    except Exception as exc:
        return tool_error(f"failed to probe source: {exc}")
    streams = probe.get("streams") if isinstance(probe.get("streams"), list) else []
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    fmt = probe.get("format") if isinstance(probe.get("format"), dict) else {}
    duration = None
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        pass
    return tool_result(
        {
            "success": True,
            "source": str(path.resolve()),
            "decodable": bool(audio_streams),
            "audio_stream_count": len(audio_streams),
            "duration_seconds": duration,
            "format": fmt,
            "audio_streams": audio_streams,
            "notes": [
                "sound_collage_edit can use any source ffmpeg can decode.",
                "For a whole-file edit, submit with source/source_path and no clips.",
            ],
        }
    )


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


def _copy_artifacts(status: dict[str, Any], dest_dir: Path) -> dict[str, str]:
    copied: dict[str, str] = {}
    artifacts = status.get("artifacts")
    if isinstance(artifacts, dict):
        for key, value in artifacts.items():
            copied_path = _copy_if_present(value, dest_dir)
            if copied_path:
                copied[str(key)] = copied_path
    else:
        for key in (
            "output_path",
            "wav_path",
            "timeline_path",
            "review_html_path",
            "spectrogram_path",
        ):
            copied_path = _copy_if_present(status.get(key), dest_dir)
            if copied_path:
                copied[key] = copied_path
    return copied


def _new_job_id() -> str:
    return f"sound-{int(time.time())}-{uuid.uuid4().hex[:8]}"


def _submit(args: dict[str, Any]) -> str:
    collage_plan = args.get("collage_plan")
    if not isinstance(collage_plan, dict):
        clips = args.get("clips")
        if isinstance(clips, list):
            collage_plan = {"clips": clips}
        elif args.get("source") or args.get("source_path"):
            source = args.get("source") or args.get("source_path")
            clip = {
                "source": source,
                "start": args.get("start"),
                "duration": args.get("duration"),
                "end": args.get("end"),
                "label": args.get("label") or Path(str(source)).stem,
                "role": args.get("role") or "source",
                "gain": args.get("gain"),
                "fade_in": args.get("fade_in"),
                "fade_out": args.get("fade_out"),
                "fade_curve": args.get("fade_curve"),
                "notes": args.get("notes") or "Whole-file source edit.",
            }
            collage_plan = {"clips": [clip], "project_type": args.get("project_type") or "whole_file"}
        else:
            return tool_error("collage_plan, clips, or source must be provided")
    if not WORKER_PATH.exists():
        return tool_error(f"sound collage worker is missing: {WORKER_PATH}")

    job_id = str(args.get("job_id") or _new_job_id())
    output_dir = _job_dir(job_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id,
        "title": args.get("title") or collage_plan.get("title") or "Hermes Sound Collage",
        "collage_plan": collage_plan,
        "clips": args.get("clips"),
        "output_dir": str(output_dir),
        "output_name": args.get("output_name") or "sound_collage",
        "default_overlap": args.get("default_overlap"),
        "defaults": args.get("defaults") if isinstance(args.get("defaults"), dict) else None,
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
            "timeline_path": str(output_dir / "timeline.json"),
            "review_html_path": str(output_dir / "review.html"),
        }
    )


def _status(args: dict[str, Any]) -> str:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return tool_error("job_id is required for status")
    output_dir = _job_dir(job_id)
    if not output_dir.exists():
        return tool_error(f"unknown sound collage job: {job_id}")

    status = _read_json(output_dir / "status.json") or {"status": "unknown"}
    timeline = _read_json(output_dir / "timeline.json")
    result: dict[str, Any] = {
        "success": True,
        "job_id": job_id,
        "job_dir": str(output_dir),
        "status": status.get("status", "unknown"),
        "details": status,
        "timeline": timeline,
    }
    if args.get("fetch_output"):
        fetch_dir = _fetch_root() / job_id
        result["fetched_output"] = _copy_if_present(status.get("output_path"), fetch_dir)
        result["fetched_artifacts"] = _copy_artifacts(status, fetch_dir)
    return tool_result(result)


def _cancel(args: dict[str, Any]) -> str:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        return tool_error("job_id is required for cancel")
    output_dir = _job_dir(job_id)
    pid_path = output_dir / "pid"
    if not pid_path.exists():
        return tool_error(f"no pid recorded for sound collage job: {job_id}")
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except Exception as exc:
        return tool_error(f"failed to cancel sound collage job {job_id}: {exc}")
    status_path = output_dir / "status.json"
    status_path.write_text(
        json.dumps({"status": "cancelled", "cancelled_at": time.time(), "pid": pid}, indent=2),
        encoding="utf-8",
    )
    return tool_result(success=True, job_id=job_id, status="cancelled")


def sound_collage_edit(
    action: str = "submit",
    job_id: str | None = None,
    collage_plan: dict[str, Any] | None = None,
    clips: list[dict[str, Any]] | None = None,
    fetch_output: bool = False,
    **kwargs: Any,
) -> str:
    """Submit, inspect, fetch, or cancel a Hermes sound collage job."""
    args = {
        "action": action,
        "job_id": job_id,
        "collage_plan": collage_plan,
        "clips": clips,
        "fetch_output": fetch_output,
        **kwargs,
    }
    normalized = str(args.get("action") or "submit").strip().lower()
    if normalized == "submit":
        return _submit(args)
    if normalized == "probe":
        return _probe_source(args.get("source") or args.get("source_path"))
    if normalized in {"status", "fetch", "fetch_output"}:
        args["fetch_output"] = bool(args.get("fetch_output") or normalized.startswith("fetch"))
        return _status(args)
    if normalized == "cancel":
        return _cancel(args)
    return tool_error(f"unknown action: {normalized}")


SOUND_COLLAGE_EDIT_SCHEMA = {
    "name": "sound_collage_edit",
    "description": (
        "Submit and track background audio montage jobs for overlapping speech, "
        "voice collage, sound design, soundscapes, podcast-style essay edits, "
        "and reviewable MP3/WAV/spectrogram/timeline artifacts. Use this for "
        "Voice Memo-style collage where overlap, slight offsets, fades, and "
        "transcript labels are editorial structure rather than cleanup."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["probe", "submit", "status", "fetch", "cancel"],
                "description": "probe a sound file, submit a new job, check status, fetch outputs, or cancel a job",
                "default": "submit",
            },
            "job_id": {"type": "string", "description": "Existing job id for status/fetch/cancel"},
            "title": {"type": "string", "description": "Human-readable title for review artifacts"},
            "source": {
                "type": "string",
                "description": "Optional source sound/media path for probe or whole-file editing. Any ffmpeg-decodable audio file is acceptable.",
            },
            "source_path": {"type": "string", "description": "Alias for source"},
            "start": {"type": "number", "description": "Optional start time in seconds for whole-file source edits"},
            "duration": {"type": "number", "description": "Optional duration in seconds for whole-file source edits"},
            "end": {"type": "number", "description": "Optional end time in seconds for whole-file source edits"},
            "label": {"type": "string", "description": "Optional label for a whole-file source edit"},
            "role": {"type": "string", "description": "Optional role for a whole-file source edit, e.g. voice, bed, ambience, music, source"},
            "gain": {"type": "number", "description": "Optional volume multiplier for a whole-file source edit"},
            "fade_in": {"type": "number", "description": "Optional fade-in duration in seconds for a whole-file source edit"},
            "fade_out": {"type": "number", "description": "Optional fade-out duration in seconds for a whole-file source edit"},
            "fade_curve": {"type": "string", "description": "Optional FFmpeg afade curve such as qsin or tri"},
            "fetch_output": {
                "type": "boolean",
                "description": "When checking status, copy MP3/WAV/timeline/review/spectrogram artifacts into the local fetch cache.",
                "default": False,
            },
            "collage_plan": {
                "type": "object",
                "description": (
                    "Structured audio edit plan. Use clips with source path, start, "
                    "duration or end, optional timeline_start/at/offset, overlap, "
                    "gain, fade_in, fade_out, fade_curve, role, label, speaker, "
                    "text/transcript, rivet words, and notes. If timeline_start "
                    "is omitted, clips are laid down with intentional attention-"
                    "switch overlap using default_overlap; default fades are "
                    "stretched across that switch point."
                ),
            },
            "clips": {
                "type": "array",
                "description": "Shortcut for collage_plan.clips.",
                "items": {"type": "object"},
            },
            "default_overlap": {
                "type": "number",
                "description": "Default seconds of overlap when a clip omits timeline_start or overlap. The default is tuned as an attention-switch crossfade window.",
                "default": 0.65,
            },
            "defaults": {
                "type": "object",
                "description": "Optional default gain, overlap, fade_in, fade_out, fade_curve, min_fade, attention_switch_ratio, min_transition_fade, and max_transition_fade values.",
            },
            "output_name": {"type": "string", "description": "Output basename or .mp3/.wav filename"},
            "project_type": {
                "type": "string",
                "description": "Optional project type marker such as whole_file, collage, episode, soundscape, or long_project.",
            },
            "notes": {"type": "string", "description": "Creative/editorial notes kept with the job"},
        },
        "required": ["action"],
    },
}


registry.register(
    name="sound_collage_edit",
    toolset="sound_design",
    schema=SOUND_COLLAGE_EDIT_SCHEMA,
    handler=lambda args, **kwargs: sound_collage_edit(**args),
    check_fn=lambda: WORKER_PATH.exists(),
    emoji="🎧",
)
