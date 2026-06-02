import json
from pathlib import Path

from tools.gemini_omni_handoff_tool import gemini_omni_handoff
from toolsets import resolve_toolset


def test_gemini_omni_handoff_creates_flow_packet(tmp_path, monkeypatch):
    root = tmp_path / "handoffs"
    asset = tmp_path / "source.mp4"
    asset.write_bytes(b"fake video")
    monkeypatch.setenv("HERMES_GEMINI_OMNI_HANDOFF_DIR", str(root))
    monkeypatch.delenv("GEMINI_OMNI_API_URL", raising=False)
    monkeypatch.delenv("GEMINI_OMNI_API_KEY", raising=False)

    result = json.loads(
        gemini_omni_handoff(
            action="prepare",
            title="Omni Test",
            brief="Create a coherent style-shift sequence.",
            prompt="Use the source motion and keep continuity across edits.",
            assets=[
                {
                    "path": str(asset),
                    "kind": "video",
                    "role": "motion-reference",
                    "label": "source walk",
                }
            ],
            output_spec={"duration": "10s", "aspect_ratio": "16:9"},
        )
    )

    assert result["success"] is True
    assert result["direct_api_configured"] is False
    assert result["missing_assets"] == []
    for path in result["artifacts"].values():
        assert Path(path).exists()

    payload = json.loads(Path(result["artifacts"]["handoff_json"]).read_text(encoding="utf-8"))
    assert payload["title"] == "Omni Test"
    assert payload["assets"][0]["exists"] is True
    assert payload["output_spec"]["aspect_ratio"] == "16:9"
    flow_prompt = Path(result["artifacts"]["flow_prompt"]).read_text(encoding="utf-8")
    assert "source walk" in flow_prompt
    assert str(asset) in flow_prompt


def test_gemini_omni_handoff_status_reads_packet(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_GEMINI_OMNI_HANDOFF_DIR", str(tmp_path))
    created = json.loads(gemini_omni_handoff(action="prepare", brief="A", prompt="B"))

    status = json.loads(gemini_omni_handoff(action="status", handoff_id=created["handoff_id"]))

    assert status["success"] is True
    assert status["handoff_id"] == created["handoff_id"]
    assert status["handoff"]["brief"] == "A"


def test_video_editing_toolset_resolves_gemini_omni_handoff():
    assert "gemini_omni_handoff" in resolve_toolset("video_editing")
