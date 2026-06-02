---
name: cloud-video-editor
description: Edits videos with FFmpeg and Remotion handoff.
version: 1.0.0
platforms: [linux, macos]
metadata:
  hermes:
    tags: [video, editing, remotion, ffmpeg, review, post-production]
    category: media
---

# Cloud Video Editor

Use this skill when the user asks Hermes to edit video, assemble selects, prepare a review pass, make social exports, build thumbnails/title cards, or connect an edit pipeline to Remotion.

## Core Abilities

- Ingest local paths, downloaded media, message attachments, and public URLs when the user has permission to use them.
- Inspect media before editing with `ffprobe`, still frames, transcripts, or vision tools.
- Build deterministic preview renders with FFmpeg: trims, reorders, mute/audio pass-through, labels, title cards, aspect-ratio exports, and thumbnails.
- Produce structured edit artifacts: `render_plan.json`, `review_packet.json`, `review.html`, `remotion_props.json`, `remotion-review/`, per-clip review stills, candidate lists, override JSON, and EDL/FCPXML-ready data.
- Keep source footage untouched. Write derived outputs into a job/output directory.
- Treat private footage, minors, school material, and unreleased creative work as local-only unless the user explicitly approves a cloud upload.

## Remotion Lane

The WalkSteady/OneWalker integration pattern is:

- **FFmpeg** is the deterministic worker for rough assemblies, trims, labels, thumbnails, aspect exports, and preview MP4s.
- **Remotion** is the browser review and programmable composition layer: cut-review UI, live preview, candidate selection, motion graphics, captions, data overlays, and repeatable React timelines.
- **FCPXML/EDL** is the handoff layer for Final Cut, Premiere, Resolve, or another NLE.
- **Generative video bridges** are explicit bridge steps, not defaults. They require user approval for external upload, public/HTTPS frame URLs when a provider needs them, and working credits/auth before claiming they are available.

OneWalker-style review shape:

1. A scorer emits cut packets: outgoing frame, top-N incoming candidate frames, scores, transcript/pose/semantic notes, and current edit choice.
2. Remotion displays each cut as an interactive review surface.
3. The user clicks or keys an override.
4. Hermes writes override JSON and re-renders a preview MP4.
5. Once locked, Hermes exports FCPXML/EDL or a final MP4.

Worker outputs now include:

- `final.mp4`: deterministic preview render.
- `final.jpg`: thumbnail.
- `render_plan.json`: canonical status/timeline/artifact manifest.
- `review.html`: no-build local browser review page.
- `review_packet.json`: browser-review data with cuts, current choices, candidate arrays, and still paths.
- `remotion_props.json`: direct props for a Remotion composition.
- `remotion-review/`: generated Remotion project with copied public assets and `HermesVideoReview` composition.
- `timeline.edl`: simple CMX-style EDL for NLE review/handoff.
- `review/clip_####.jpg`: per-clip stills for cut review or storyboard grids.

Before promising connected media, local voice, local LLM, or Aqua worker
behavior, run `media_connector_status`. For account-specific detail, see
`references/integration-matrix.md` and keep that matrix current before
promising Google Photos, Vimeo, YouTube channel, Cloudinary, Runway, Orpheus,
Vox, or Aqua behavior.

## Edit Plan Shape

`cloud_video_edit` accepts an `edit_plan` such as:

```json
{
  "output": {"preset": "vertical", "fps": 30},
  "clips": [
    {"type": "title_card", "text": "Morning Walk", "duration": 1.5, "background": "black"},
    {"source": "/path/source.mp4", "start": 10.2, "end": 14.8, "label": "good entrance"},
    {"source": "/path/source.mp4", "start": 31, "duration": 3, "mute": true}
  ]
}
```

Supported output presets:

- `landscape`, `wide`, `youtube`: 1920x1080
- `vertical`, `portrait`, `reel`, `reels`, `short`, `shorts`, `story`, `tiktok`: 1080x1920
- `square`, `feed`: 1080x1080

## Editorial Defaults

- Prefer preview renders over abstract descriptions.
- Preserve handles and avoid hard audio/visual cliffs when the edit is meant for creative review.
- Use labels and title cards for review clarity, not as a substitute for the final creative design.
- For transcript-driven work, build the cut logic from the language and meaning, not just timecodes.
