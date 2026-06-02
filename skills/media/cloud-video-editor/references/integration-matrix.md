# Cloud Video Editor Integration Matrix

Use this matrix when Bernie needs to reason about media accounts, upload
targets, expensive generation services, or remote render/transcription workers.
Verify live credentials before invoking anything that writes, uploads, publishes,
or spends credits.

## Current Verified Surface

| Surface | Current status | Use it for | Guardrail |
| --- | --- | --- | --- |
| Hermes `cloud_video_edit` | Wired into core and `video_editing`. | Deterministic FFmpeg preview renders, review stills, `review.html`, EDL, `review_packet.json`, `remotion_props.json`, generated Remotion review project. | Preserve sources; fetch outputs before claiming completion. |
| Hermes `media_connector_status` | Wired into core, `video_editing`, and `media_connectors`. | Readiness checks and write/cost preflights for media accounts, local LLMs, local voice, and Aqua worker URLs. | Reports booleans only; never print secret values. |
| Hermes Remotion handoff | Generated project under each fetched job. | Browser review, React timeline prototyping, captions/motion graphics follow-up. | Treat Remotion as the review/composition layer, not a replacement for probing source media. |
| Hermes YouTube bundled skill | Transcript extraction only. | Summaries, chapters, quiz/content transforms from public video transcripts. | This is not channel OAuth, upload, caption management, or analytics. |
| Hermes `video_generate` plugin path | FAL-backed video generation can be configured with `FAL_KEY`. | Text-to-video and image-to-video when configured. | Paid model path; require explicit user intent. |
| Hermes TTS/STT | OpenAI/Groq/ElevenLabs/Gemini plus local Piper/KittenTTS/NeuTTS and command-provider Orpheus/Vox paths. | Scratch narration, temp VO, transcription, captions, audio review. | Do not clone or publish voices without explicit permission and provenance. |
| Hermes local LLMs | `hermes model` supports LM Studio and custom OpenAI-compatible endpoints. | Local editorial planning, caption passes, transcript cleanup, and offline inference. | Set the real endpoint/model/context; do not assume Aqua or localhost is running. |
| Bop Gun Google Workspace | `listAccounts` shows account `patrick`. | Drive/Docs/Sheets/Slides asset and metadata workflows. | Google Photos is separate; Drive access does not imply Photos library access. |
| Bop Gun YouTube | Read tools for search, video, channel, playlist, trending. | Public YouTube discovery and metadata. | No verified upload/manage/comment/caption authority. |
| Bop Gun Runway | Runway tools are available; usage check is read-only. | Expensive image/video generation and task polling. | Check balance/usage first; never generate without approval. |
| Bop Gun Replicate | Run/list/get/cancel prediction tools are available. | Model experiments and creative generation. | Paid/variable-cost path; log model slug and inputs. |
| Bop Gun ElevenLabs | Voice listing, TTS, history, subscription usage tools are available. | VO scratch tracks, narration experiments, audio history checks. | Respect voice rights and cost controls. |
| Aqua media worker | Aqua has FFmpeg/FFprobe 8.0.1, faster-whisper lane, and Manny tool shed. | Remote media probing, transcoding, transcription, CLI-heavy editorial work. | Prefer read/status checks first; do not run long or costly jobs without a named output plan. |

## Gaps To Wire As First-Class Hermes Tools

| Service | Missing first-class capability | Recommended env/config | Notes |
| --- | --- | --- | --- |
| Google Photos | Picker/import flow and app-created upload/library management. | OAuth client credentials plus `GOOGLE_PHOTOS_*` token storage. | After the 2025 Photos API changes, full-library list/search is not a normal API promise. Use Picker for user-selected items and Library API only for app-created media. |
| Vimeo | Upload, transcode polling, metadata/privacy/folder management, review-link creation. | `VIMEO_ACCESS_TOKEN`; optional default folder/privacy config. | Prefer TUS/resumable upload; token scopes must match upload/private metadata needs. |
| YouTube channel | Upload, thumbnail, captions, playlists, analytics, comments. | OAuth client and stored channel token; use `youtube.upload` for upload-only workflows. | Keep publish defaults private/unlisted until explicit approval. |
| Cloudinary | Asset upload, derived transform URLs, eager transformations, metadata search, signed delivery. | `CLOUDINARY_URL` or `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`. | Useful as the media CDN and transform cache between review tools, Remotion, Vimeo, and web surfaces. |
| Orpheus / Vox local voice | Local command-provider TTS. | `ORPHEUS_TTS_COMMAND`, `VOX_TTS_COMMAND`, or `tts.providers.<name>.command`. | Command templates must read `{input_path}` and write `{output_path}`; validate a short sample before using in a render. |
| Frame.io or review equivalent | Client review links, comments, version stacks. | Provider token once chosen. | Valuable for editorial collaboration; avoid building custom review comments until this is evaluated. |
| Mux | Streamable review/playback assets, thumbnails, HLS, webhooks. | `MUX_TOKEN_ID`, `MUX_TOKEN_SECRET`. | Better for playback infrastructure than editorial decision-making. |
| AssemblyAI/Deepgram | Word-level transcript, diarization, captions, summaries. | Provider API key. | Use when local faster-whisper is not enough or speaker/word timing matters. |

## Integration Spine

1. Ingest from local files, Drive, user-selected Google Photos items, Vimeo links,
   YouTube links, or Cloudinary assets into one asset manifest.
2. Probe every asset with FFprobe before editing.
3. Run `media_connector_status` before promising a connected media, local voice,
   local LLM, or Aqua path.
4. Render previews through `cloud_video_edit`.
5. Hand off the review packet to `review.html` and the generated Remotion project.
6. Route heavy local work to Aqua when the input/output paths are explicit.
7. Route paid generation through Runway, Replicate, FAL, or ElevenLabs only after a
   balance/usage check and explicit task intent.
8. Publish only after the review artifact, metadata, destination, and privacy
   setting are named.

## Cost Controls

- Add a spend preflight before any Runway, Replicate, FAL, Cloudinary eager
  transformation, Vimeo upload, or YouTube publish action.
- Default publishing privacy to private or unlisted.
- Record source path, output path, model/service, estimated cost class, and
  approval note in the render plan or job log.
- Poll long-running remote tasks by ID instead of restarting generation.
