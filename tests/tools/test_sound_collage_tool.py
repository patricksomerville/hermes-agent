import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.sound_collage_tool import sound_collage_edit
from toolsets import resolve_toolset


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = PROJECT_ROOT / "skills" / "media" / "sound-collage-editor" / "scripts" / "sound_collage_worker.py"


def _load_worker():
    spec = importlib.util.spec_from_file_location("sound_collage_worker", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _make_tone(path: Path, frequency: int, duration: float = 1.0) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={duration}",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(path),
        ]
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe required")
def test_sound_collage_worker_renders_overlapping_timeline(tmp_path):
    worker = _load_worker()
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    _make_tone(first, 440)
    _make_tone(second, 660)

    output_dir = tmp_path / "job"
    job = {
        "job_id": "collage-proof",
        "title": "Collage Proof",
        "output_dir": str(output_dir),
        "default_overlap": 0.4,
        "collage_plan": {
            "clips": [
                {
                    "source": str(first),
                    "duration": 1.0,
                    "label": "first thought",
                    "speaker": "A",
                    "text": "acting is pretending",
                    "rivet": "pretending",
                },
                {
                    "source": str(second),
                    "duration": 1.0,
                    "label": "answering thought",
                    "speaker": "B",
                    "text": "it is more like listening",
                    "overlap": 0.4,
                },
            ],
        },
    }
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")

    status = worker.render_job(job, job_path)

    assert status["status"] == "complete"
    assert status["clip_count"] == 2
    assert status["source_count"] == 2
    assert status["timeline_duration_seconds"] == pytest.approx(1.6, abs=0.04)
    assert status["total_clip_seconds"] == pytest.approx(2.0, abs=0.02)
    assert status["long_project"] is False
    assert status["overlap_seconds"] > 0.35
    for key in ("output_path", "wav_path", "timeline_path", "review_html_path", "spectrogram_path"):
        assert Path(status[key]).exists()

    timeline = json.loads((output_dir / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["clips"][0]["speaker"] == "A"
    assert timeline["clips"][0]["text"] == "acting is pretending"
    assert timeline["clips"][0]["rivet"] == "pretending"
    assert timeline["clips"][1]["timeline_start"] == pytest.approx(0.6, abs=0.02)
    assert timeline["clips"][0]["fade_out"] == pytest.approx(0.36, abs=0.02)
    assert timeline["clips"][1]["fade_in"] == pytest.approx(0.36, abs=0.02)
    assert timeline["clips"][0]["fade_curve"] == "qsin"
    assert timeline["clips"][1]["attention_switch_from"] == "first thought"
    assert timeline["clips"][1]["attention_switch_overlap"] == pytest.approx(0.4, abs=0.02)

    probe = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            status["output_path"],
        ]
    )
    assert float(probe.stdout.strip()) < 1.8


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe required")
def test_sound_collage_probe_and_whole_file_source_edit(tmp_path, monkeypatch):
    source = tmp_path / "whole-file.m4a"
    _make_tone(source, 330, duration=1.4)

    probe = json.loads(sound_collage_edit(action="probe", source=str(source)))

    assert probe["success"] is True
    assert probe["decodable"] is True
    assert probe["audio_stream_count"] == 1
    assert probe["duration_seconds"] == pytest.approx(1.4, abs=0.05)

    jobs_dir = tmp_path / "jobs"
    monkeypatch.setenv("HERMES_SOUND_COLLAGE_JOBS_DIR", str(jobs_dir))

    class FakeProc:
        pid = 12345

    monkeypatch.setattr("tools.sound_collage_tool.subprocess.Popen", lambda *args, **kwargs: FakeProc())
    result = json.loads(
        sound_collage_edit(
            action="submit",
            job_id="whole-file-job",
            source=str(source),
            title="Whole File",
        )
    )

    assert result["success"] is True
    job = json.loads((jobs_dir / "whole-file-job" / "job.json").read_text(encoding="utf-8"))
    assert job["collage_plan"]["project_type"] == "whole_file"
    assert job["collage_plan"]["clips"][0]["source"] == str(source)
    assert job["collage_plan"]["clips"][0]["duration"] is None


def test_sound_collage_status_fetches_artifacts(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    fetch_dir = tmp_path / "fetch"
    job_dir = jobs_dir / "job-1"
    job_dir.mkdir(parents=True)
    mp3 = job_dir / "sound_collage.mp3"
    timeline = job_dir / "timeline.json"
    review = job_dir / "review.html"
    mp3.write_bytes(b"fake mp3")
    timeline.write_text('{"clips": []}', encoding="utf-8")
    review.write_text("<h1>Review</h1>", encoding="utf-8")
    (job_dir / "status.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "output_path": str(mp3),
                "timeline_path": str(timeline),
                "review_html_path": str(review),
                "artifacts": {
                    "mp3": str(mp3),
                    "timeline": str(timeline),
                    "review_html": str(review),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_SOUND_COLLAGE_JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("HERMES_SOUND_COLLAGE_FETCH_DIR", str(fetch_dir))

    result = json.loads(sound_collage_edit(action="fetch", job_id="job-1"))

    assert result["success"] is True
    assert result["status"] == "complete"
    assert Path(result["fetched_output"]).exists()
    assert Path(result["fetched_artifacts"]["timeline"]).exists()
    assert Path(result["fetched_artifacts"]["review_html"]).exists()


def test_sound_design_toolset_resolves_sound_collage_edit():
    assert "sound_collage_edit" in resolve_toolset("sound_design")
