#!/usr/bin/env python3
"""Render Hermes sound collage jobs with FFmpeg.

This worker is built for deliberate overlapping speech, montage, sound beds,
and reviewable audio artifacts. It avoids hard waveform cliffs by applying
short fades to every source segment before mixing.
"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_OVERLAP_SECONDS = 0.65
DEFAULT_EDGE_FADE_IN_SECONDS = 0.12
DEFAULT_EDGE_FADE_OUT_SECONDS = 0.22
DEFAULT_MIN_FADE_SECONDS = 0.04
DEFAULT_MIN_TRANSITION_FADE_SECONDS = 0.22
DEFAULT_MAX_TRANSITION_FADE_SECONDS = 1.25
DEFAULT_ATTENTION_SWITCH_RATIO = 0.9
DEFAULT_FADE_CURVE = "qsin"
FADE_CURVES = {
    "tri",
    "qsin",
    "esin",
    "hsin",
    "log",
    "ipar",
    "qua",
    "cub",
    "squ",
    "cbr",
    "par",
    "exp",
    "iqsin",
    "ihsin",
    "dese",
    "desi",
    "losi",
    "sinc",
    "isinc",
    "nofade",
    "qsin2",
    "hsin2",
    "nofade",
}


def _ffmpeg() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("ffmpeg is required for sound collage jobs")
    return binary


def _ffprobe() -> str:
    binary = shutil.which("ffprobe")
    if not binary:
        raise RuntimeError("ffprobe is required for sound collage jobs")
    return binary


def _run(cmd: list[str], *, capture: bool = False) -> str:
    if capture:
        return subprocess.check_output(cmd, text=True)
    subprocess.run(cmd, check=True)
    return ""


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _media_duration(path: Path) -> float:
    raw = _run(
        [
            _ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture=True,
    ).strip()
    return max(0.0, float(raw or 0.0))


def _clip_duration(source: Path, clip: dict[str, Any]) -> float:
    start = _num(clip.get("start"), 0.0)
    if clip.get("duration") is not None:
        return max(0.02, _num(clip.get("duration"), 0.02))
    if clip.get("end") is not None:
        return max(0.02, _num(clip.get("end"), start + 0.02) - start)
    return max(0.02, _media_duration(source) - start)


def _escape_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _has_value(mapping: dict[str, Any], key: str) -> bool:
    return mapping.get(key) is not None


def _fade_curve(value: Any, default: str = DEFAULT_FADE_CURVE) -> str:
    curve = str(value or default).strip().lower()
    return curve if curve in FADE_CURVES else default


def _normalize_clip(job: dict[str, Any], clip: dict[str, Any], index: int, cursor: float) -> tuple[dict[str, Any], float]:
    defaults = job.get("defaults") if isinstance(job.get("defaults"), dict) else {}
    source = Path(str(clip.get("source") or clip.get("source_path") or "")).expanduser()
    if not source.exists() or not source.is_file():
        raise RuntimeError(f"clip {index} source not found: {source}")

    duration = _clip_duration(source, clip)
    overlap = _num(clip.get("overlap"), _num(defaults.get("overlap"), _num(job.get("default_overlap"), DEFAULT_OVERLAP_SECONDS)))
    explicit_at = clip.get("timeline_start", clip.get("at", clip.get("offset")))
    if explicit_at is None:
        timeline_start = 0.0 if index == 0 else max(0.0, cursor - overlap)
    else:
        timeline_start = max(0.0, _num(explicit_at, 0.0))

    min_fade = _num(defaults.get("min_fade"), DEFAULT_MIN_FADE_SECONDS)
    fade_in_explicit = _has_value(clip, "fade_in") or _has_value(defaults, "fade_in")
    fade_out_explicit = _has_value(clip, "fade_out") or _has_value(defaults, "fade_out")
    fade_in = max(min_fade, _num(clip.get("fade_in"), _num(defaults.get("fade_in"), DEFAULT_EDGE_FADE_IN_SECONDS)))
    fade_out = max(min_fade, _num(clip.get("fade_out"), _num(defaults.get("fade_out"), DEFAULT_EDGE_FADE_OUT_SECONDS)))
    fade_in = min(fade_in, duration / 2)
    fade_out = min(fade_out, duration / 2)
    fade_curve = _fade_curve(clip.get("fade_curve") or defaults.get("fade_curve"))

    normalized = {
        "index": index,
        "source": str(source.resolve()),
        "label": str(clip.get("label") or source.stem),
        "role": str(clip.get("role") or "voice"),
        "source_start": max(0.0, _num(clip.get("start"), 0.0)),
        "duration": duration,
        "timeline_start": timeline_start,
        "timeline_end": timeline_start + duration,
        "gain": max(0.0, _num(clip.get("gain"), _num(defaults.get("gain"), 1.0))),
        "fade_in": fade_in,
        "fade_out": fade_out,
        "fade_curve": fade_curve,
        "speaker": str(clip.get("speaker") or clip.get("character") or ""),
        "text": str(clip.get("text") or clip.get("transcript") or ""),
        "rivet": str(clip.get("rivet") or clip.get("rivet_word") or clip.get("join_word") or ""),
        "notes": str(clip.get("notes") or ""),
        "_fade_in_explicit": fade_in_explicit,
        "_fade_out_explicit": fade_out_explicit,
    }
    return normalized, timeline_start + duration


def _apply_attention_switch_fades(timeline: list[dict[str, Any]], job: dict[str, Any]) -> None:
    defaults = job.get("defaults") if isinstance(job.get("defaults"), dict) else {}
    ratio = _num(defaults.get("attention_switch_ratio"), _num(job.get("attention_switch_ratio"), DEFAULT_ATTENTION_SWITCH_RATIO))
    min_transition = _num(defaults.get("min_transition_fade"), _num(job.get("min_transition_fade"), DEFAULT_MIN_TRANSITION_FADE_SECONDS))
    max_transition = _num(defaults.get("max_transition_fade"), _num(job.get("max_transition_fade"), DEFAULT_MAX_TRANSITION_FADE_SECONDS))

    for index in range(1, len(timeline)):
        previous = timeline[index - 1]
        current = timeline[index]
        overlap = max(0.0, float(previous["timeline_end"]) - float(current["timeline_start"]))
        current["attention_switch_from"] = previous["label"] if overlap > 0.02 else ""
        current["attention_switch_overlap"] = overlap
        previous["attention_switch_to"] = current["label"] if overlap > 0.02 else previous.get("attention_switch_to", "")
        previous["attention_switch_overlap"] = max(float(previous.get("attention_switch_overlap") or 0.0), overlap)
        if overlap <= 0.02:
            continue
        desired = min(max(overlap * ratio, min_transition), max_transition)
        desired = min(desired, float(previous["duration"]) / 2, float(current["duration"]) / 2)
        if not previous.get("_fade_out_explicit"):
            previous["fade_out"] = desired
        if not current.get("_fade_in_explicit"):
            current["fade_in"] = desired

    for clip in timeline:
        clip.pop("_fade_in_explicit", None)
        clip.pop("_fade_out_explicit", None)
        clip.setdefault("attention_switch_from", "")
        clip.setdefault("attention_switch_to", "")
        clip.setdefault("attention_switch_overlap", 0.0)


def _make_filter(timeline: list[dict[str, Any]], output_wav: Path) -> list[str]:
    filter_parts: list[str] = []
    labels: list[str] = []
    for clip in timeline:
        idx = int(clip["index"])
        delay_ms = int(round(float(clip["timeline_start"]) * 1000))
        duration = float(clip["duration"])
        fade_out_start = max(0.0, duration - float(clip["fade_out"]))
        source_start = float(clip["source_start"])
        gain = float(clip["gain"])
        curve = _fade_curve(clip.get("fade_curve"))
        label = f"a{idx}"
        labels.append(f"[{label}]")
        chain = (
            f"[{idx}:a]"
            f"atrim=start={source_start:.6f}:duration={duration:.6f},"
            "asetpts=PTS-STARTPTS,"
            "aresample=48000,"
            "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
            f"volume={gain:.6f},"
            f"afade=t=in:st=0:d={float(clip['fade_in']):.6f}:curve={curve},"
            f"afade=t=out:st={fade_out_start:.6f}:d={float(clip['fade_out']):.6f}:curve={curve},"
            f"adelay={delay_ms}|{delay_ms}"
            f"[{label}]"
        )
        filter_parts.append(chain)
    if len(labels) == 1:
        mix = f"{labels[0]}acompressor=threshold=-18dB:ratio=2.2:attack=10:release=120,alimiter=limit=0.95[out]"
    else:
        mix = (
            "".join(labels)
            + f"amix=inputs={len(labels)}:normalize=0:duration=longest:dropout_transition=0,"
            "highpass=f=35,lowpass=f=15500,"
            "acompressor=threshold=-18dB:ratio=2.2:attack=10:release=120,"
            "alimiter=limit=0.95[out]"
        )
    filter_parts.append(mix)
    return ["-filter_complex", ";".join(filter_parts), "-map", "[out]", "-ar", "48000", "-ac", "2", str(output_wav)]


def _write_review_html(path: Path, title: str, timeline: list[dict[str, Any]], artifacts: dict[str, str]) -> None:
    rows = []
    for clip in timeline:
        rows.append(
            "<tr>"
            f"<td>{clip['index']}</td>"
            f"<td>{html.escape(clip['label'])}</td>"
            f"<td>{html.escape(clip['role'])}</td>"
            f"<td>{html.escape(clip.get('speaker') or '')}</td>"
            f"<td>{html.escape(clip.get('rivet') or '')}</td>"
            f"<td>{clip['timeline_start']:.2f}</td>"
            f"<td>{clip['duration']:.2f}</td>"
            f"<td>{clip['fade_in']:.3f}/{clip['fade_out']:.3f} {html.escape(clip.get('fade_curve') or '')}</td>"
            f"<td>{clip.get('attention_switch_overlap', 0.0):.3f}</td>"
            "</tr>"
        )
    body = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 32px; background: #f7f7f4; color: #151515; }}
audio {{ width: 100%; margin: 16px 0 24px; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
td, th {{ border: 1px solid #d6d6d0; padding: 8px; text-align: left; }}
th {{ background: #ecece6; }}
.meta {{ color: #555; }}
</style>
<h1>{html.escape(title)}</h1>
<p class="meta">Hermes sound collage review. Overlap is intentional; every clip has fades.</p>
<audio controls src="{html.escape(Path(artifacts['mp3']).name)}"></audio>
<p><a href="{html.escape(Path(artifacts['timeline']).name)}">timeline.json</a> ·
<a href="{html.escape(Path(artifacts['plan']).name)}">collage_plan.json</a> ·
<a href="{html.escape(Path(artifacts['spectrogram']).name)}">spectrogram</a></p>
<table>
<thead><tr><th>#</th><th>Label</th><th>Role</th><th>Speaker</th><th>Rivet</th><th>At</th><th>Dur</th><th>Fades</th><th>Switch overlap</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""
    path.write_text(body, encoding="utf-8")


def render_job(job: dict[str, Any], job_path: Path) -> dict[str, Any]:
    output_dir = Path(str(job.get("output_dir") or job_path.parent)).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    status_path = output_dir / "status.json"
    title = str(job.get("title") or job.get("job_id") or "Hermes Sound Collage")
    plan = job.get("collage_plan") if isinstance(job.get("collage_plan"), dict) else {}
    clips = plan.get("clips") if isinstance(plan.get("clips"), list) else job.get("clips")
    if not isinstance(clips, list) or not clips:
        raise RuntimeError("collage_plan.clips must be a non-empty list")

    status_path.write_text(json.dumps({"status": "running", "started_at": time.time()}, indent=2), encoding="utf-8")

    timeline: list[dict[str, Any]] = []
    cursor = 0.0
    for index, raw in enumerate(clips):
        if not isinstance(raw, dict):
            raise RuntimeError(f"clip {index} must be an object")
        clip, cursor = _normalize_clip({**job, **plan}, raw, index, cursor)
        timeline.append(clip)
    _apply_attention_switch_fades(timeline, {**job, **plan})

    stem = str(job.get("output_name") or "sound_collage").removesuffix(".mp3").removesuffix(".wav")
    wav = output_dir / f"{stem}.wav"
    mp3 = output_dir / f"{stem}.mp3"
    spectrogram = output_dir / f"{stem}-spectrogram.png"
    timeline_json = output_dir / "timeline.json"
    plan_json = output_dir / "collage_plan.json"
    ffprobe_json = output_dir / "ffprobe.json"
    review_html = output_dir / "review.html"

    cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    for clip in timeline:
        cmd.extend(["-i", clip["source"]])
    cmd.extend(_make_filter(timeline, wav))
    _run(cmd)
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "224k", str(mp3)])
    _run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp3), "-lavfi", "showspectrumpic=s=1280x720:legend=disabled:color=fiery", str(spectrogram)])
    probe = _run(
        [
            _ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,sample_rate,channels",
            "-of",
            "json",
            str(mp3),
        ],
        capture=True,
    )
    ffprobe_json.write_text(probe, encoding="utf-8")
    timeline_json.write_text(json.dumps({"title": title, "clips": timeline}, indent=2), encoding="utf-8")
    plan_json.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    artifacts = {
        "wav": str(wav),
        "mp3": str(mp3),
        "spectrogram": str(spectrogram),
        "timeline": str(timeline_json),
        "plan": str(plan_json),
        "ffprobe": str(ffprobe_json),
        "review_html": str(review_html),
    }
    _write_review_html(review_html, title, timeline, artifacts)
    timeline_duration = max(c["timeline_end"] for c in timeline)
    total_clip_seconds = sum(c["duration"] for c in timeline)
    status = {
        "status": "complete",
        "completed_at": time.time(),
        "title": title,
        "output_path": str(mp3),
        "wav_path": str(wav),
        "timeline_path": str(timeline_json),
        "review_html_path": str(review_html),
        "spectrogram_path": str(spectrogram),
        "artifacts": artifacts,
        "clip_count": len(timeline),
        "source_count": len({c["source"] for c in timeline}),
        "timeline_duration_seconds": timeline_duration,
        "total_clip_seconds": total_clip_seconds,
        "long_project": timeline_duration >= 600 or len(timeline) >= 25,
        "overlap_seconds": max(0.0, total_clip_seconds - timeline_duration),
        "ffprobe": json.loads(probe),
    }
    status_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return status


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: sound_collage_worker.py JOB_JSON", file=sys.stderr)
        return 2
    job_path = Path(sys.argv[1]).expanduser().resolve()
    output_dir = job_path.parent
    status_path = output_dir / "status.json"
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
        status = render_job(job, job_path)
        print(json.dumps(status, indent=2))
        return 0
    except Exception as exc:
        error = {"status": "failed", "error": str(exc), "failed_at": time.time()}
        status_path.write_text(json.dumps(error, indent=2), encoding="utf-8")
        print(f"sound_collage_worker failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
