import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.cloud_video_edit_tool import cloud_video_edit
from toolsets import resolve_toolset


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = PROJECT_ROOT / "skills" / "media" / "cloud-video-editor" / "scripts" / "cloud_video_edit_worker.py"


def _load_worker():
    spec = importlib.util.spec_from_file_location("cloud_video_edit_worker", WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def _make_sample_video(path: Path) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=30:duration=1.2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe required")
def test_worker_renders_vertical_title_card_thumbnail_and_render_plan(tmp_path):
    worker = _load_worker()
    source = tmp_path / "source.mp4"
    _make_sample_video(source)

    output_dir = tmp_path / "job"
    job = {
        "job_id": "vertical-review",
        "source": str(source),
        "output_dir": str(output_dir),
        "edit_plan": {
            "output": {"preset": "vertical", "fps": 30},
            "clips": [
                {"type": "title_card", "text": "Review Pass", "duration": 0.4},
                {"source": str(source), "start": 0, "duration": 0.6, "label": "candidate A"},
            ],
        },
    }
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")

    status = worker.render_job(job, job_path)

    final = Path(status["output_path"])
    thumbnail = Path(status["thumbnail_path"])
    render_plan = json.loads((output_dir / "render_plan.json").read_text(encoding="utf-8"))
    assert final.exists()
    assert thumbnail.exists()
    assert render_plan["output_profile"]["width"] == 1080
    assert render_plan["output_profile"]["height"] == 1920
    assert render_plan["thumbnail"] == str(thumbnail)
    assert render_plan["remotion"]["composition"] == "HermesVideoReview"
    assert Path(render_plan["artifacts"]["review_packet"]).exists()
    assert Path(render_plan["artifacts"]["remotion_props"]).exists()
    assert Path(render_plan["artifacts"]["edl"]).exists()
    assert Path(render_plan["artifacts"]["review_html"]).exists()
    assert Path(render_plan["artifacts"]["remotion_project"]).exists()
    assert Path(render_plan["artifacts"]["remotion_project"], "src", "ReviewComposition.tsx").exists()
    assert Path(render_plan["artifacts"]["remotion_project"], "public", "remotion_props.json").exists()
    assert render_plan["artifacts"]["review_stills"]
    assert Path(render_plan["timeline"][0]["review_still"]).exists()
    edl = Path(render_plan["artifacts"]["edl"]).read_text(encoding="utf-8")
    assert "TITLE: HERMES_EDIT" in edl
    assert "FCM: NON-DROP FRAME" in edl

    probe = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(final),
        ]
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["width"] == 1080
    assert stream["height"] == 1920


def test_cloud_video_edit_status_returns_render_plan_and_fetches_outputs(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "jobs"
    fetch_dir = tmp_path / "fetch"
    job_dir = jobs_dir / "job-1"
    job_dir.mkdir(parents=True)
    final = job_dir / "final.mp4"
    thumbnail = job_dir / "final.jpg"
    final.write_bytes(b"fake mp4")
    thumbnail.write_bytes(b"fake jpg")
    render_plan = {
        "job_id": "job-1",
        "output_profile": {"width": 1080, "height": 1920, "fps": 30},
        "remotion": {"composition": "HermesVideoReview"},
        "artifacts": {
            "review_packet": str(job_dir / "review_packet.json"),
            "remotion_props": str(job_dir / "remotion_props.json"),
            "edl": str(job_dir / "timeline.edl"),
            "review_html": str(job_dir / "review.html"),
            "remotion_project": str(job_dir / "remotion-review"),
            "review_stills": {"0": str(job_dir / "review" / "clip_0000.jpg")},
        },
    }
    (job_dir / "review").mkdir()
    (job_dir / "remotion-review").mkdir()
    (job_dir / "review_packet.json").write_text("{}", encoding="utf-8")
    (job_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
    (job_dir / "timeline.edl").write_text("TITLE: HERMES_EDIT", encoding="utf-8")
    (job_dir / "review.html").write_text("<h1>Hermes Video Review</h1>", encoding="utf-8")
    (job_dir / "review" / "clip_0000.jpg").write_bytes(b"fake jpg")
    (job_dir / "remotion-review" / "package.json").write_text("{}", encoding="utf-8")
    (job_dir / "status.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "output_path": str(final),
                "thumbnail_path": str(thumbnail),
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "render_plan.json").write_text(json.dumps(render_plan), encoding="utf-8")
    monkeypatch.setenv("HERMES_VIDEO_EDIT_JOBS_DIR", str(jobs_dir))
    monkeypatch.setenv("HERMES_VIDEO_EDIT_FETCH_DIR", str(fetch_dir))

    result = json.loads(cloud_video_edit(action="status", job_id="job-1", fetch_output=True))

    assert result["success"] is True
    assert result["status"] == "complete"
    assert result["render_plan"] == render_plan
    assert Path(result["fetched_output"]).exists()
    assert Path(result["fetched_thumbnail"]).exists()
    assert Path(result["fetched_render_plan"]).exists()
    assert Path(result["fetched_artifacts"]["review_packet"]).exists()
    assert Path(result["fetched_artifacts"]["remotion_props"]).exists()
    assert Path(result["fetched_artifacts"]["edl"]).exists()
    assert Path(result["fetched_artifacts"]["review_html"]).exists()
    assert Path(result["fetched_artifacts"]["remotion_project"]).is_dir()
    assert Path(result["fetched_artifacts"]["review_stills"]["0"]).exists()


def test_video_editing_toolset_resolves_cloud_video_edit():
    assert "cloud_video_edit" in resolve_toolset("video_editing")
