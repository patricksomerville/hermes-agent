---
name: sound-collage-editor
description: Builds overlapping sound collages.
version: 1.0.0
author: Patrick Somerville and Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [audio, podcast, montage, sound-design, collage]
    category: media
    related_skills: [cloud-video-editor]
---

# Sound Collage Editor Skill

Use this skill to build overlapping speech montage, audio collage, podcast essay edits, sound design beds, long-form audio projects, and soundscapes. It is for deterministic local renders and review artifacts; it is not a replacement for a human final mix.

The target grammar is closer to Patrick's Voice Memo / Actors-style editorial collage than a simple "talk over a beat" lane: transcript logic, whole thoughts, overlap, callbacks, and small sonic joints matter.

## When to Use

- The user asks for a podcast montage, overlapping voice collage, soundscape, or sound design draft.
- The user wants a transcript-driven audio essay assembled from many speakers or clips.
- The user gives Bernie any sound file and wants it probed, trimmed, faded, rendered, or used as a whole-file source.
- The user wants a longer episode, soundscape, assembly, or multi-clip project with durable timeline artifacts.
- The edit needs reviewable artifacts: MP3, WAV, spectrogram, timeline JSON, and HTML review page.
- The video workflow needs a finished sound bed before `cloud_video_edit` or `gemini_omni_handoff`.

## Prerequisites

- `ffmpeg` and `ffprobe` on the machine running Hermes.
- Source media paths that Hermes can read.
- Optional: `media_connector_status` for checking local voice, transcription, Aqua, and publishing connectors.
- Optional: `text_to_speech` for generated narration or scratch voice.

## How to Run

Use `sound_collage_edit` with a structured `collage_plan`.

```json
{
  "action": "submit",
  "title": "Actors Part 1 style draft",
  "default_overlap": 0.45,
  "collage_plan": {
    "clips": [
      {
        "source": "/absolute/path/interview-a.wav",
        "start": 12.4,
        "duration": 4.8,
        "label": "first thought",
        "speaker": "A",
        "text": "I thought acting was pretending...",
        "rivet": "pretending",
        "gain": 1.0
      },
      {
        "source": "/absolute/path/interview-b.wav",
        "start": 43.0,
        "duration": 5.2,
        "label": "answering thought",
        "speaker": "B",
        "text": "It is more like listening.",
        "overlap": 0.65
      }
    ]
  }
}
```

Then call `sound_collage_edit` with `action: "status"` or `action: "fetch"`.

For a single whole-file edit, Bernie can probe or submit the source directly:

```json
{
  "action": "probe",
  "source": "/absolute/path/voice-memo.m4a"
}
```

```json
{
  "action": "submit",
  "title": "Whole file proof",
  "source": "/absolute/path/voice-memo.m4a",
  "project_type": "whole_file"
}
```

## Quick Reference

| Tool | Use |
| --- | --- |
| `sound_collage_edit` | Probe, render, and review sound-file, collage, and long-project jobs. |
| `media_connector_status` | Check local voice, transcription, Aqua, and publishing readiness. |
| `text_to_speech` | Generate scratch narration or voice material when appropriate. |
| `cloud_video_edit` | Combine finished sound beds with video review renders. |

## Procedure

1. Build the paper edit first. Use transcript language to decide structure, not only timestamps.
2. Preserve whole thoughts unless the user explicitly asks for hard fragmentation.
3. Do not cut off sentences halfway through. Let ideas complete and overlap.
4. Use overlap as grammar. A later speaker can enter at the exact moment the listener's attention is switching.
5. Use `rivet` words for joints when two clips share or answer a word, phrase, rhythm, or idea.
6. Keep handles and fades. The default renderer uses quarter-sine fades stretched across the attention-switch overlap, not tiny cleanup fades.
7. Render with `sound_collage_edit`.
8. Review the HTML page, timeline JSON, and spectrogram before declaring the edit usable.
9. For video work, pass the finished MP3/WAV into `cloud_video_edit` or package it with `gemini_omni_handoff`.
10. For long projects, treat `timeline.json`, `collage_plan.json`, and `status.json` as the durable project record; source files stay referenced non-destructively.

## Pitfalls

- Do not flatten a concept into texture. The default target is a cohesive composite essay.
- Do not force clips to avoid overlap. Overlap and slight offsets are part of the form.
- Do not cut a sentence in half just to make a transition work; move the overlap until the idea can complete.
- Do not make the overlap happen after attention has already moved. The overlap is the attention handoff.
- Do not cut every sentence into tiny fragments unless the user asks for that exact effect.
- Do not drop transcript text from the plan; future revisions need it.
- Do not claim the render is mastered. It is a draft/proof unless a mastering pass was explicitly done.

## Verification

- `sound_collage_edit` returns a job id and writes `status.json`.
- Completed jobs include MP3, WAV, `timeline.json`, `collage_plan.json`, `review.html`, `ffprobe.json`, and a spectrogram PNG.
- `timeline.json` preserves clip labels, speakers, transcript text, rivet words, fades, gains, and overlap positions.
- `status.json` reports clip count, source count, total clip seconds, rendered timeline duration, overlap seconds, and whether the job crosses the long-project threshold.
- The output duration is shorter than the sum of clip durations when intentional overlap is used.
