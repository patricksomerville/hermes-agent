---
name: gemini-omni-editor
description: Prepares Gemini Omni editing handoffs.
version: 1.0.0
author: Patrick Somerville and Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [gemini, omni, google-flow, video-editing, generative-video]
    category: media
    related_skills: [cloud-video-editor, sound-collage-editor]
---

# Gemini Omni Editor Skill

Use this skill when the user wants Gemini Omni in Bernie's creative video workflow. Gemini Omni Flash is a real Google generative editing model, but the stable developer API path must be verified before direct automated submission.

The default Hermes behavior is therefore: use Gemini 3.5 Flash as a normal model/provider for agentic planning and analysis, and use `gemini_omni_handoff` to prepare Google Flow / Gemini Omni handoff packets for generative video creation or conversational edits.

## When to Use

- The user asks for Gemini Omni, Google Flow, any-input video generation, or conversational video edits.
- The edit needs text, image, audio, or video references bundled into one coherent creative prompt.
- The editing suite needs an Omni-ready packet with provenance, assets, and output constraints.
- A local deterministic edit from `cloud_video_edit` or `sound_collage_edit` should become a generative reference.

## Prerequisites

- `media_connector_status` can check whether `gemini_omni` is configured for Flow handoff or future direct API access.
- `gemini_omni_handoff` prepares handoff packets without requiring an API.
- For normal Gemini model use, configure provider `gemini` with `GOOGLE_API_KEY` or `GEMINI_API_KEY`.
- For direct Omni API use, require explicit verification of `GEMINI_OMNI_API_URL` and `GEMINI_OMNI_API_KEY`; do not infer it from a normal Gemini API key.

## How to Run

Use `gemini_omni_handoff` with a creative brief, prompt, assets, and output spec.

```json
{
  "action": "prepare",
  "title": "Omni scene revision",
  "brief": "Revise a walking shot into a synchronized style-shift sequence.",
  "prompt": "Use the source video motion and the sound bed rhythm. Keep the walk continuous, shift styles on beat, and preserve the original emotional tone.",
  "assets": [
    {
      "path": "/absolute/path/source-walk.mp4",
      "kind": "video",
      "role": "motion-reference",
      "label": "source walk"
    },
    {
      "path": "/absolute/path/sound-bed.wav",
      "kind": "audio",
      "role": "rhythm-reference",
      "label": "sound bed"
    }
  ],
  "output_spec": {
    "duration": "10s",
    "aspect_ratio": "16:9",
    "audio_policy": "preserve rhythm; generate only supporting sound if requested"
  }
}
```

## Quick Reference

| Tool | Use |
| --- | --- |
| `gemini_omni_handoff` | Create Flow-ready prompts, asset manifests, review HTML, and future API drafts. |
| `media_connector_status` | Check `gemini_omni`, Google Flow, and direct API readiness. |
| `cloud_video_edit` | Produce deterministic local review renders and reference clips. |
| `sound_collage_edit` | Produce sound beds and montage references for Omni prompts. |

## Procedure

1. Decide whether the task is deterministic editing or generative editing.
2. Use `cloud_video_edit` and `sound_collage_edit` for deterministic trims, exports, review packets, and sound beds.
3. Use Gemini 3.5 Flash for planning, analyzing assets, prompt drafting, and structured edit reasoning.
4. Use `gemini_omni_handoff` when the task needs Gemini Omni's generative scene creation or conversational video editing.
5. Attach source assets manually in Google Flow unless direct Omni API credentials and endpoint are explicitly configured and verified.
6. Keep `omni_handoff.json` with the editing-suite project as the provenance and revision record.

## Pitfalls

- Do not claim direct Gemini Omni API access unless the endpoint is verified in the current environment.
- Do not use Gemini Omni for ordinary trims, labels, thumbnails, or deterministic social exports; use `cloud_video_edit`.
- Do not use Gemini Omni to change a person's speech or likeness without explicit user approval and provenance.
- Do not lose the source asset manifest; generative edits need reproducible reference packets.

## Verification

- `gemini_omni_handoff` creates `omni_handoff.json`, `flow_prompt.md`, `api_request_draft.json`, and `review.html`.
- `media_connector_status` reports `gemini_omni` without revealing secrets.
- The handoff packet lists every source asset and whether it exists locally.
- The packet says whether direct API configuration is present; absence of a direct API should not block Flow handoff.
