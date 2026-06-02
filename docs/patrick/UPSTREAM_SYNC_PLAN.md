# Hermes upstream sync plan (Patrick / Bernie fork)

**Branch:** `codex/quiet-gateway-mcp-fallbacks-20260503`  
**HEAD:** `5f3ff8e27` (2026-06-02)  
**Remotes:** `github` → `patricksomerville/hermes-agent`, `origin` → spark, `upstream` → `NousResearch/hermes-agent`  
**Gap (2026-06-02):** 3 commits ahead of merge-base, ~1,584 commits behind `upstream/main`

## Patrick-only capabilities (must preserve through merge)

These do **not** exist on current `upstream/main` (verified via `toolsets.py` grep):

| Area | Commits / files | Why it matters on Somertime |
|------|-----------------|-----------------------------|
| **MCP HTTP fallbacks** | `62e409407`, `tools/mcp_tool.py`, `hermes_cli/mcp_config.py` | `bop-gun` primary `127.0.0.1:3001` + mesh URLs in `~/.hermes/config.yaml` |
| **Quiet gateway** | `62e409407`, `gateway/run.py`, `gateway/display_config.py`, `hermes_cli/config.py` | Less noisy progress on Telegram/Feishu |
| **Windows WSL MCP bridge** | `7b207282e`, `hermes_cli/windows_mcp_bridge.py` | aqua/cyan Windows nodes |
| **Media editing toolsets** | `5f3ff8e27`, `tools/*_tool.py`, `toolsets.py`, `skills/media/*` | Bernie sound collage, cloud video, Gemini Omni handoffs |
| **Email gateway tweaks** | `gateway/platforms/email.py` | If email channel is used |

**Total diff vs upstream:** 56 files, ~5,755 insertions (mostly media workers + tests + WSL bridge).

## Upstream wins (safe to absorb — high value)

Prioritize cherry-picks or a rebase that takes these without dropping Patrick patches:

1. **Security / MCP** — credential filtering, SSRF/Tirith, OAuth hardening (many PRs since fork point).
2. **Gateway** — per-platform streaming defaults, structured stream events, Telegram draft formatting (#37250, #37303).
3. **Dashboard / desktop** — channels admin, MCP catalog toggles (#36736, #37211) if you use desktop app.
4. **Resilience** — docker venv fix, file-safety sandbox mirror, cron unicode sanitization.
5. **Model picker** — curated OpenAI list, OpenRouter display fixes (#37404).

## Recommended merge strategy

### Phase A — Lock Patrick baseline (done in ops pass)

- [x] `uv pip install -e ".[all,dev]"` → CLI reports **v0.14.0**
- [x] Gateway restart; Telegram polling connected when DNS healthy
- [x] Focused tests: MCP fallbacks + media toolsets (150/150)
- [x] `hermes mcp test bop-gun` green

### Phase B — Rebase experiment (1–2 hours, on a throwaway branch)

```bash
cd ~/hermes-agent
git checkout -b patrick/rebase-upstream-20260602
git rebase upstream/main
# Expect conflicts in: toolsets.py, mcp_tool.py, gateway/run.py, hermes_cli/config.py
# Resolve: keep Patrick media tools + fallback_urls + quiet gateway flags
```

If conflict count is extreme (>50 files), switch to **merge** instead:

```bash
git checkout codex/quiet-gateway-mcp-fallbacks-20260503
git merge upstream/main -m "merge upstream/main into patrick fork"
```

### Phase C — Regression gate

```bash
hermes gateway stop
cd ~/hermes-agent && scripts/run_tests.sh   # full suite; no live gateway PID
hermes gateway run --replace
hermes mcp test bop-gun
# Manual: Telegram mention @Bernie + one sound_collage_edit dry-run
```

### Phase D — Mesh rollout

Per `~/.somertime/bill-memory.md`:

- `pip install mcp` in each mesh Hermes venv
- Same `mcp_servers.bop-gun.fallback_urls` block on neon/spark copies
- Push branch to `origin` (spark) and `github` after green gate

## Conflict hotspots (pre-declared)

| File | Patrick side | Upstream likely changed |
|------|--------------|-------------------------|
| `toolsets.py` | `_HERMES_CORE_TOOLS` includes media tools | Tool gating, new tools, provider splits |
| `tools/mcp_tool.py` | `fallback_urls`, reconnect logging | OAuth, security, transport |
| `gateway/run.py` | Quiet progress / topic behavior | Streaming protocol, platform registry |
| `hermes_cli/config.py` | Display + gateway quiet options | Desktop/settings consolidation |
| `gateway/platforms/telegram.py` | Small patch set | Streaming, draft formatting |

## What not to do

- **Do not** fast-forward to upstream without re-applying the 56-file diff — you will lose Bop Gun fallbacks and Bernie media tools.
- **Do not** trust full `run_tests.sh` with gateway running — conftest live-system guard blocks `killpg` (~119 failures on black).
- **Do not** treat `bop-gun` as a `media_connector_status` service — MCP server ≠ media connector preflight API.

## Decision log

| Date | Decision |
|------|----------|
| 2026-06-02 | Stay on Patrick fork for production Bernie until Phase B rebase completes |
| 2026-06-02 | Telegram gets full `hermes-telegram` core (includes media tools) — see `platform_toolsets` in `~/.hermes/config.yaml` |
