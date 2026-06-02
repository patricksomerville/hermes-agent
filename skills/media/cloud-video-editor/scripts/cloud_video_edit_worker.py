#!/usr/bin/env python3
"""Render Hermes video edit jobs with ffmpeg.

Given a job JSON file, this worker writes a deterministic preview MP4 plus the
review artifacts an editor-facing agent needs: thumbnail, stills, EDL,
review packet, Remotion props, local HTML review page, and a runnable Remotion
starter project.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


OUTPUT_PRESETS = {
    "landscape": (1920, 1080),
    "wide": (1920, 1080),
    "youtube": (1920, 1080),
    "vertical": (1080, 1920),
    "portrait": (1080, 1920),
    "reel": (1080, 1920),
    "reels": (1080, 1920),
    "short": (1080, 1920),
    "shorts": (1080, 1920),
    "story": (1080, 1920),
    "tiktok": (1080, 1920),
    "square": (1080, 1080),
    "feed": (1080, 1080),
}

_DRAWTEXT_SUPPORTED: bool | None = None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("ffmpeg is required for cloud video editing jobs")
    return binary


def _ffprobe() -> str | None:
    return shutil.which("ffprobe")


def _drawtext_supported() -> bool:
    global _DRAWTEXT_SUPPORTED
    if _DRAWTEXT_SUPPORTED is not None:
        return _DRAWTEXT_SUPPORTED
    try:
        result = subprocess.run(
            [_ffmpeg(), "-hide_banner", "-filters"],
            check=True,
            capture_output=True,
            text=True,
        )
        _DRAWTEXT_SUPPORTED = " drawtext " in result.stdout
    except Exception:
        _DRAWTEXT_SUPPORTED = False
    return _DRAWTEXT_SUPPORTED


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def output_profile(job: dict[str, Any]) -> dict[str, Any]:
    plan = job.get("edit_plan") if isinstance(job.get("edit_plan"), dict) else {}
    output = plan.get("output") if isinstance(plan.get("output"), dict) else {}
    preset_name = str(output.get("preset") or plan.get("preset") or plan.get("format") or "landscape").lower()
    preset = OUTPUT_PRESETS.get(preset_name, OUTPUT_PRESETS["landscape"])
    width = _int(output.get("width") or job.get("width"), preset[0])
    height = _int(output.get("height") or job.get("height"), preset[1])
    fps = _clamp(_int(output.get("fps") or job.get("fps"), 30), 1, 120)
    background = str(output.get("background") or output.get("background_color") or "black")
    return {
        "preset": preset_name if preset_name in OUTPUT_PRESETS else "custom",
        "width": width,
        "height": height,
        "fps": fps,
        "background": background,
    }


def _escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", "\\n")
    )


def _font_arg() -> str:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return f":fontfile='{candidate}'"
    return ""


def text_overlay_filter(text: str, profile: dict[str, Any], placement: str = "title") -> str | None:
    if not _drawtext_supported():
        return None
    escaped = _escape_drawtext(text)
    font = _font_arg()
    if placement == "lower_third":
        x_expr = "(w-text_w)/2"
        y_expr = "h-(text_h*3)"
        size_expr = max(32, int(profile["height"] * 0.045))
    else:
        x_expr = "(w-text_w)/2"
        y_expr = "(h-text_h)/2"
        size_expr = max(42, int(profile["height"] * 0.07))
    return (
        f"drawtext=text='{escaped}'{font}:fontsize={size_expr}:fontcolor=white:"
        "box=1:boxcolor=black@0.45:boxborderw=28:"
        f"x={x_expr}:y={y_expr}"
    )


def normalize_filter(profile: dict[str, Any]) -> str:
    width = profile["width"]
    height = profile["height"]
    fps = profile["fps"]
    background = profile["background"]
    return (
        f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={background},"
        f"fps={fps},format=yuv420p,setsar=1"
    )


def is_title_clip(clip: dict[str, Any]) -> bool:
    return str(clip.get("type") or "").lower() in {"title", "title_card", "card"}


def render_title_clip(clip: dict[str, Any], output_path: Path, profile: dict[str, Any]) -> None:
    duration = max(0.1, _float(clip.get("duration"), 2.0))
    text = str(clip.get("text") or clip.get("title") or clip.get("label") or "")
    background = str(clip.get("background") or clip.get("color") or profile["background"])
    vf = [normalize_filter(profile)]
    if text:
        overlay = text_overlay_filter(text, profile, placement="title")
        if overlay:
            vf.append(overlay)
    _run(
        [
            _ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={background}:s={profile['width']}x{profile['height']}:d={duration}:r={profile['fps']}",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration}",
            "-vf",
            ",".join(vf),
            "-t",
            str(duration),
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            str(output_path),
        ]
    )


def _clip_source(clip: dict[str, Any], job: dict[str, Any]) -> str:
    source = clip.get("source") or clip.get("path") or clip.get("file") or clip.get("source_path")
    if not source:
        source = job.get("source") or job.get("source_path")
    if not source:
        raise ValueError(f"clip is missing source: {clip}")
    return os.path.expanduser(str(source))


def _has_audio(path: Path) -> bool:
    ffprobe = _ffprobe()
    if not ffprobe:
        return False
    try:
        result = _run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ]
        )
        return bool((result.stdout or "").strip())
    except Exception:
        return False


def render_source_clip(
    clip: dict[str, Any],
    output_path: Path,
    profile: dict[str, Any],
    job: dict[str, Any],
) -> None:
    source = _clip_source(clip, job)
    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"source video does not exist: {source}")

    start = clip.get("start")
    end = clip.get("end")
    duration = clip.get("duration")
    args = [_ffmpeg(), "-y"]
    if start is not None:
        args.extend(["-ss", str(start)])
    args.extend(["-i", source])
    use_silent_audio = bool(clip.get("mute", False)) or not _has_audio(source_path)
    if use_silent_audio:
        args.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"])
    if duration is None and start is not None and end is not None:
        duration = max(0.1, _float(end, 0.0) - _float(start, 0.0))
    if duration is not None:
        args.extend(["-t", str(duration)])

    vf = [normalize_filter(profile)]
    overlay_text = clip.get("label") or clip.get("text_overlay") or clip.get("caption")
    if overlay_text:
        overlay = text_overlay_filter(str(overlay_text), profile, placement="lower_third")
        if overlay:
            vf.append(overlay)

    args.extend(
        [
            "-vf",
            ",".join(vf),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
        ]
    )
    if use_silent_audio:
        args.extend(["-map", "0:v:0", "-map", "1:a:0", "-shortest", "-c:a", "aac", "-b:a", "160k"])
    else:
        args.extend(["-map", "0:v:0", "-map", "0:a:0", "-c:a", "aac", "-b:a", "160k"])
    args.append(str(output_path))
    _run(args)


def render_thumbnail(final_output: Path, output_dir: Path) -> Path | None:
    thumbnail = output_dir / "final.jpg"
    duration = _media_duration(final_output) or 0.0
    seek = 0.2 if duration <= 1 else min(max(duration * 0.35, 0.2), max(duration - 0.1, 0.2))
    try:
        _run(
            [
                _ffmpeg(),
                "-y",
                "-ss",
                f"{seek:.3f}",
                "-i",
                str(final_output),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(thumbnail),
            ]
        )
    except Exception:
        return None
    return thumbnail if thumbnail.exists() else None


def _probe(path: Path) -> dict[str, Any]:
    ffprobe = _ffprobe()
    if not ffprobe:
        return {}
    try:
        result = _run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height,avg_frame_rate,duration",
                "-of",
                "json",
                str(path),
            ]
        )
        return json.loads(result.stdout or "{}")
    except Exception:
        return {}


def _media_duration(path: Path) -> float | None:
    ffprobe = _ffprobe()
    if not ffprobe:
        return None
    try:
        result = _run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ]
        )
        return max(0.0, float((result.stdout or "0").strip()))
    except Exception:
        return None


def _seconds_to_timecode(seconds: float, fps: int) -> str:
    frames_total = max(0, int(round(seconds * fps)))
    frames = frames_total % fps
    seconds_total = frames_total // fps
    secs = seconds_total % 60
    minutes_total = seconds_total // 60
    mins = minutes_total % 60
    hours = minutes_total // 60
    return f"{hours:02d}:{mins:02d}:{secs:02d}:{frames:02d}"


def _timeline_duration(clip: dict[str, Any], part_path: Path) -> float:
    if clip.get("duration") is not None:
        return max(0.0, _float(clip.get("duration"), 0.0))
    if clip.get("start") is not None and clip.get("end") is not None:
        return max(0.0, _float(clip.get("end"), 0.0) - _float(clip.get("start"), 0.0))
    probed = _media_duration(part_path)
    if probed is not None:
        return probed
    return 0.0


def render_review_stills(timeline: list[dict[str, Any]], output_dir: Path) -> dict[str, str]:
    review_dir = output_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    stills: dict[str, str] = {}
    for item in timeline:
        part = Path(str(item.get("part") or ""))
        if not part.exists():
            continue
        duration = _float(item.get("duration_seconds"), 0.0)
        seek = min(max(duration / 2, 0.05), 0.5) if duration else 0.05
        still_path = review_dir / f"clip_{int(item['index']):04d}.jpg"
        try:
            _run(
                [
                    _ffmpeg(),
                    "-y",
                    "-ss",
                    f"{seek:.3f}",
                    "-i",
                    str(part),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(still_path),
                ]
            )
        except Exception:
            continue
        if still_path.exists():
            item["review_still"] = str(still_path)
            stills[str(item["index"])] = str(still_path)
    return stills


def write_edl(timeline: list[dict[str, Any]], output_dir: Path, profile: dict[str, Any]) -> Path:
    fps = int(profile["fps"])
    lines = ["TITLE: HERMES_EDIT", "FCM: NON-DROP FRAME", ""]
    for item in timeline:
        index = int(item["index"]) + 1
        duration = _float(item.get("duration_seconds"), 0.0)
        record_in = _float(item.get("timeline_start"), 0.0)
        record_out = _float(item.get("timeline_end"), record_in + duration)
        source_in = _float(item.get("source_start_seconds"), 0.0)
        source_out = source_in + duration
        reel = "AX" if item.get("type") in {"title", "title_card", "card"} else Path(str(item.get("source") or "SOURCE")).stem
        reel = "".join(ch for ch in reel.upper() if ch.isalnum() or ch in {"_", "-"})[:8] or "SOURCE"
        lines.append(
            f"{index:03d}  {reel:<8} V     C        "
            f"{_seconds_to_timecode(source_in, fps)} {_seconds_to_timecode(source_out, fps)} "
            f"{_seconds_to_timecode(record_in, fps)} {_seconds_to_timecode(record_out, fps)}"
        )
        label = item.get("label") or item.get("source")
        if label:
            lines.append(f"* FROM CLIP NAME: {label}")
        lines.append("")
    edl_path = output_dir / "timeline.edl"
    edl_path.write_text("\n".join(lines), encoding="utf-8")
    return edl_path


def write_review_packet(
    output_dir: Path,
    profile: dict[str, Any],
    timeline: list[dict[str, Any]],
    final_output: Path,
    thumbnail: Path | None,
    edl_path: Path,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    packet = {
        "version": 1,
        "job_output": str(final_output),
        "thumbnail": str(thumbnail) if thumbnail else None,
        "edl": str(edl_path),
        "output_profile": profile,
        "timeline": timeline,
        "cuts": [
            {
                "index": int(item["index"]),
                "label": item.get("label"),
                "source": item.get("source"),
                "timeline_start": item.get("timeline_start"),
                "timeline_end": item.get("timeline_end"),
                "review_still": item.get("review_still"),
                "current_choice": item.get("source") or item.get("label"),
                "candidates": item.get("candidates") or [],
            }
            for item in timeline
        ],
    }
    duration_seconds = sum(_float(item.get("duration_seconds"), 0.0) for item in timeline)
    remotion_props = {
        "composition": "HermesVideoReview",
        "fps": profile["fps"],
        "width": profile["width"],
        "height": profile["height"],
        "durationInFrames": max(1, int(round(duration_seconds * int(profile["fps"])))),
        "src": str(final_output),
        "reviewPacket": packet,
    }
    packet_path = output_dir / "review_packet.json"
    remotion_props_path = output_dir / "remotion_props.json"
    _write_json(packet_path, packet)
    _write_json(remotion_props_path, remotion_props)
    return packet_path, remotion_props_path, packet, remotion_props


def _relative_artifact(path: str | None, output_dir: Path) -> str:
    if not path:
        return ""
    try:
        return str(Path(path).resolve().relative_to(output_dir.resolve()))
    except Exception:
        return path


def write_review_html(
    output_dir: Path,
    profile: dict[str, Any],
    timeline: list[dict[str, Any]],
    final_output: Path,
    thumbnail: Path | None,
    review_packet_path: Path,
    remotion_props_path: Path,
    edl_path: Path,
) -> Path:
    width = int(profile["width"])
    height = int(profile["height"])
    video_style = (
        f"aspect-ratio: {width} / {height}; "
        f"max-width: min(100%, calc(72vh * {width} / {height}));"
    )
    rows = []
    for item in timeline:
        still = _relative_artifact(item.get("review_still"), output_dir)
        label = html.escape(str(item.get("label") or item.get("source") or f"Clip {item['index']}"))
        timing = f"{_float(item.get('timeline_start'), 0.0):.2f}s - {_float(item.get('timeline_end'), 0.0):.2f}s"
        still_html = f'<img src="{html.escape(still)}" alt="{label}">' if still else "<div class='missing'>No still</div>"
        rows.append(
            "<article class='clip'>"
            f"{still_html}"
            f"<div><h2>{int(item['index']) + 1:02d}. {label}</h2>"
            f"<p>{html.escape(timing)}</p>"
            f"<code>{html.escape(str(item.get('source') or item.get('type') or 'source'))}</code>"
            "</div></article>"
        )
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hermes Video Review</title>
  <style>
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #111; color: #f2f2f2; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    video {{ width: 100%; max-height: 72vh; background: #000; border: 1px solid #333; display: block; margin: 0 auto; }}
    .links {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 16px 0 24px; }}
    .links a {{ color: #9bd3ff; text-decoration: none; border: 1px solid #31506a; padding: 6px 9px; border-radius: 4px; }}
    .clip {{ display: grid; grid-template-columns: 180px 1fr; gap: 14px; align-items: center; border-top: 1px solid #2a2a2a; padding: 14px 0; }}
    .clip img {{ width: 180px; aspect-ratio: 16 / 9; object-fit: cover; background: #000; }}
    h1 {{ font-size: 22px; margin: 0 0 16px; }}
    h2 {{ font-size: 15px; margin: 0 0 6px; }}
    p, code {{ color: #bdbdbd; }}
    code {{ font-size: 12px; overflow-wrap: anywhere; }}
    .missing {{ width: 180px; aspect-ratio: 16 / 9; display: grid; place-items: center; background: #202020; color: #888; }}
  </style>
</head>
<body>
  <main>
    <h1>Hermes Video Review</h1>
    <video controls style="{html.escape(video_style)}" poster="{html.escape(_relative_artifact(str(thumbnail) if thumbnail else None, output_dir))}" src="{html.escape(_relative_artifact(str(final_output), output_dir))}"></video>
    <nav class="links">
      <a href="{html.escape(_relative_artifact(str(review_packet_path), output_dir))}">review_packet.json</a>
      <a href="{html.escape(_relative_artifact(str(remotion_props_path), output_dir))}">remotion_props.json</a>
      <a href="{html.escape(_relative_artifact(str(edl_path), output_dir))}">timeline.edl</a>
    </nav>
    {''.join(rows)}
  </main>
</body>
</html>
"""
    review_html = output_dir / "review.html"
    review_html.write_text(body, encoding="utf-8")
    return review_html


def _copy_asset(src: Path | None, dest: Path) -> str | None:
    if not src or not src.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return str(dest)


def write_remotion_project(
    output_dir: Path,
    profile: dict[str, Any],
    timeline: list[dict[str, Any]],
    final_output: Path,
    thumbnail: Path | None,
    packet: dict[str, Any],
    remotion_props: dict[str, Any],
) -> Path:
    project_dir = output_dir / "remotion-review"
    src_dir = project_dir / "src"
    public_dir = project_dir / "public"
    assets_dir = public_dir / "assets"
    review_assets_dir = assets_dir / "review"
    src_dir.mkdir(parents=True, exist_ok=True)
    review_assets_dir.mkdir(parents=True, exist_ok=True)

    _copy_asset(final_output, assets_dir / "final.mp4")
    if thumbnail:
        _copy_asset(thumbnail, assets_dir / "final.jpg")

    remotion_timeline = []
    for item in timeline:
        copied = None
        if item.get("review_still"):
            copied = _copy_asset(Path(str(item["review_still"])), review_assets_dir / Path(str(item["review_still"])).name)
        remotion_item = dict(item)
        if copied:
            remotion_item["review_still"] = f"assets/review/{Path(copied).name}"
        remotion_timeline.append(remotion_item)

    remotion_packet = dict(packet)
    remotion_packet["job_output"] = "assets/final.mp4"
    remotion_packet["thumbnail"] = "assets/final.jpg" if thumbnail else None
    remotion_packet["timeline"] = remotion_timeline
    remotion_packet["cuts"] = [
        {
            **cut,
            "review_still": remotion_timeline[int(cut["index"])].get("review_still") if int(cut["index"]) < len(remotion_timeline) else cut.get("review_still"),
        }
        for cut in packet.get("cuts", [])
    ]
    remotion_project_props = {
        **remotion_props,
        "src": "assets/final.mp4",
        "reviewPacket": remotion_packet,
    }
    _write_json(public_dir / "review_packet.json", remotion_packet)
    _write_json(public_dir / "remotion_props.json", remotion_project_props)

    (project_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "hermes-video-review",
                "private": True,
                "type": "module",
                "scripts": {
                    "studio": "remotion studio src/index.ts",
                    "render": "remotion render src/index.ts HermesVideoReview out/review.mp4",
                },
                "dependencies": {
                    "@remotion/cli": "^4.0.0",
                    "remotion": "^4.0.0",
                    "react": "^19.0.0",
                    "react-dom": "^19.0.0",
                },
                "devDependencies": {
                    "typescript": "^5.6.0",
                    "@types/react": "^19.0.0",
                    "@types/react-dom": "^19.0.0",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (project_dir / "tsconfig.json").write_text(
        json.dumps(
            {
                "compilerOptions": {
                    "jsx": "react-jsx",
                    "module": "ESNext",
                    "moduleResolution": "Bundler",
                    "resolveJsonModule": True,
                    "strict": True,
                    "target": "ES2020",
                },
                "include": ["src", "public/**/*.json"],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (src_dir / "index.ts").write_text(
        "import {registerRoot} from 'remotion';\nimport {Root} from './Root';\n\nregisterRoot(Root);\n",
        encoding="utf-8",
    )
    (src_dir / "Root.tsx").write_text(
        """import React from 'react';
import {Composition} from 'remotion';
import reviewProps from '../public/remotion_props.json';
import {ReviewComposition} from './ReviewComposition';

export const Root: React.FC = () => {
  const props = reviewProps as any;

  return (
    <Composition
      id="HermesVideoReview"
      component={ReviewComposition}
      durationInFrames={props.durationInFrames}
      fps={props.fps}
      height={props.height}
      width={props.width}
      defaultProps={props}
    />
  );
};
""",
        encoding="utf-8",
    )
    (src_dir / "ReviewComposition.tsx").write_text(
        """import React from 'react';
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  Sequence,
  staticFile,
  useCurrentFrame,
} from 'remotion';

type TimelineItem = {
  index: number;
  label?: string | null;
  review_still?: string | null;
  timeline_start?: number | null;
  timeline_end?: number | null;
};

type ReviewProps = {
  fps: number;
  src: string;
  reviewPacket: {
    timeline: TimelineItem[];
  };
};

export const ReviewComposition: React.FC<ReviewProps> = ({fps, src, reviewPacket}) => {
  const frame = useCurrentFrame();
  const seconds = frame / fps;
  const active = reviewPacket.timeline.find((item) => {
    const start = item.timeline_start ?? 0;
    const end = item.timeline_end ?? start;
    return seconds >= start && seconds < end;
  });

  return (
    <AbsoluteFill style={{backgroundColor: '#080808'}}>
      <OffthreadVideo src={staticFile(src)} style={{height: '100%', objectFit: 'contain', width: '100%'}} />
      <div
        style={{
          background: 'linear-gradient(180deg, rgba(0,0,0,0.72), rgba(0,0,0,0))',
          color: 'white',
          fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif',
          fontSize: 28,
          left: 0,
          padding: 28,
          position: 'absolute',
          right: 0,
          top: 0,
        }}
      >
        {active ? `${String(active.index + 1).padStart(2, '0')} · ${active.label ?? 'Review cut'}` : 'Hermes Video Review'}
      </div>
      {reviewPacket.timeline.map((item) => {
        const start = Math.max(0, Math.round((item.timeline_start ?? 0) * fps));
        const duration = Math.max(1, Math.round(((item.timeline_end ?? 0) - (item.timeline_start ?? 0)) * fps));
        return (
          <Sequence key={item.index} from={start} durationInFrames={duration}>
            {item.review_still ? (
              <Img
                src={staticFile(item.review_still)}
                style={{
                  border: '2px solid rgba(255,255,255,0.65)',
                  bottom: 32,
                  height: 144,
                  objectFit: 'cover',
                  position: 'absolute',
                  right: 32,
                }}
              />
            ) : null}
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
""",
        encoding="utf-8",
    )
    (project_dir / "README.md").write_text(
        """# Hermes Video Review

This is a generated Remotion review project for a Hermes video edit job.

```bash
npm install
npm run studio
npm run render
```

The canonical data is in `public/remotion_props.json` and `public/review_packet.json`.
""",
        encoding="utf-8",
    )
    return project_dir


def _concat_files(parts: list[Path], output_path: Path) -> None:
    if len(parts) == 1:
        shutil.copy2(parts[0], output_path)
        return
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        list_path = Path(handle.name)
        for part in parts:
            quoted = str(part).replace("'", "'\\''")
            handle.write(f"file '{quoted}'\n")
    try:
        _run(
            [
                _ffmpeg(),
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-c:a",
                "aac",
                "-b:a",
                "160k",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
    finally:
        list_path.unlink(missing_ok=True)


def render_job(job: dict[str, Any], job_path: Path) -> dict[str, Any]:
    output_dir = Path(job.get("output_dir") or job_path.parent).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    started = time.time()
    _write_json(status_path, {"status": "running", "started_at": started})

    profile = output_profile(job)
    plan = job.get("edit_plan") if isinstance(job.get("edit_plan"), dict) else {}
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        clips = [{"source": job.get("source") or job.get("source_path")}]

    parts_dir = output_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    timeline: list[dict[str, Any]] = []

    try:
        for index, raw_clip in enumerate(clips):
            clip = raw_clip if isinstance(raw_clip, dict) else {"source": raw_clip}
            part_path = parts_dir / f"part_{index:04d}.mp4"
            if is_title_clip(clip):
                render_title_clip(clip, part_path, profile)
            else:
                render_source_clip(clip, part_path, profile, job)
            parts.append(part_path)
            duration_seconds = _timeline_duration(clip, part_path)
            timeline_start = sum(_float(item.get("duration_seconds"), 0.0) for item in timeline)
            timeline_end = timeline_start + duration_seconds
            timeline.append(
                {
                    "index": index,
                    "type": clip.get("type") or "source",
                    "source": clip.get("source") or clip.get("path") or clip.get("file"),
                    "start": clip.get("start"),
                    "end": clip.get("end"),
                    "duration": clip.get("duration"),
                    "duration_seconds": duration_seconds,
                    "timeline_start": timeline_start,
                    "timeline_end": timeline_end,
                    "source_start_seconds": _float(clip.get("start"), 0.0),
                    "source_end_seconds": _float(clip.get("end"), _float(clip.get("start"), 0.0) + duration_seconds),
                    "label": clip.get("label") or clip.get("text") or clip.get("title"),
                    "part": str(part_path),
                    "candidates": clip.get("candidates") if isinstance(clip.get("candidates"), list) else [],
                }
            )

        final_output = output_dir / str(job.get("output_name") or "final.mp4")
        _concat_files(parts, final_output)
        thumbnail = render_thumbnail(final_output, output_dir)
        review_stills = render_review_stills(timeline, output_dir)
        edl_path = write_edl(timeline, output_dir, profile)
        review_packet_path, remotion_props_path, packet, remotion_props = write_review_packet(
            output_dir,
            profile,
            timeline,
            final_output,
            thumbnail,
            edl_path,
        )
        review_html_path = write_review_html(
            output_dir,
            profile,
            timeline,
            final_output,
            thumbnail,
            review_packet_path,
            remotion_props_path,
            edl_path,
        )
        remotion_project_path = write_remotion_project(
            output_dir,
            profile,
            timeline,
            final_output,
            thumbnail,
            packet,
            remotion_props,
        )
        artifacts = {
            "review_packet": str(review_packet_path),
            "remotion_props": str(remotion_props_path),
            "edl": str(edl_path),
            "review_html": str(review_html_path),
            "remotion_project": str(remotion_project_path),
            "review_stills": review_stills,
        }
        render_plan = {
            "job_id": job.get("job_id") or output_dir.name,
            "status": "complete",
            "output": str(final_output),
            "thumbnail": str(thumbnail) if thumbnail else None,
            "output_profile": profile,
            "timeline": timeline,
            "artifacts": artifacts,
            "remotion": {
                "composition": "HermesVideoReview",
                "fps": profile["fps"],
                "width": profile["width"],
                "height": profile["height"],
                "timeline": timeline,
                "props": str(remotion_props_path),
                "project": str(remotion_project_path),
            },
            "probe": _probe(final_output),
        }
        _write_json(output_dir / "render_plan.json", render_plan)
        status = {
            "status": "complete",
            "started_at": started,
            "finished_at": time.time(),
            "output_path": str(final_output),
            "thumbnail_path": str(thumbnail) if thumbnail else None,
            "render_plan_path": str(output_dir / "render_plan.json"),
            "review_packet_path": str(review_packet_path),
            "remotion_props_path": str(remotion_props_path),
            "edl_path": str(edl_path),
            "review_html_path": str(review_html_path),
            "remotion_project_path": str(remotion_project_path),
        }
        _write_json(status_path, status)
        return status
    except Exception as exc:
        status = {
            "status": "failed",
            "started_at": started,
            "finished_at": time.time(),
            "error": str(exc),
        }
        _write_json(status_path, status)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a Hermes cloud video edit job")
    parser.add_argument("job_json", help="Path to the job JSON file")
    args = parser.parse_args(argv)
    try:
        job_path = Path(args.job_json).expanduser().resolve()
        job = json.loads(job_path.read_text(encoding="utf-8"))
        render_job(job, job_path)
        return 0
    except Exception as exc:
        print(f"cloud_video_edit_worker failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
