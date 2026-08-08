# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read this first

**This repo is a stub. It deploys nothing.** As of 2026-08-08 the entire inference stack
that used to live here was deleted, because it had been superseded by the gateway fabric
under `/mnt/storage/services/`. If a request concerns running, fixing, or extending AI
inference on this homelab, the work almost certainly belongs in one of those directories,
not here.

`/home/chris/apps/ai-inference` and `/mnt/storage/apps/ai-inference` are the **same
directory** (`/home/chris/apps` is a bind mount of `/mnt/storage/apps`). Same inode, not
two checkouts.

## Where the work actually goes

| Concern | Directory | Container / endpoint |
|---|---|---|
| Image gen front door, failover, `/generate`, OpenAI images shim | `/mnt/storage/services/comfyui-gateway/` | `comfyui-gateway`, `:8189` |
| daedalus SDXL fallback node | `/mnt/storage/services/comfyui/` | `zeus-comfyui`, alias `comfyui:8188` |
| Apollo FLUX primary node | not on this host | `192.168.50.30:8188`, native |
| LLM front door, failover | `/home/chris/services/ollama-gateway/` | `ollama-gateway` (Caddy), `:11440` |
| daedalus LLM node | zeus stack | `zeus-ollama`, `:11435` |
| Public reverse proxy | `/mnt/storage/services/daedalus-infra/proxy/` | Caddy, separate stack on purpose |
| Port and route registry | `/mnt/storage/services/daedalus-infra/config/services.yml` | source of truth |

The two gateways are deliberately separate stacks from the public proxy, so changing
model routing never recreates the reverse proxy.

## Architecture worth knowing before touching the gateways

- **comfyui-gateway is a bespoke FastAPI service, not a load balancer.** ComfyUI's API is
  a stateful multi-step exchange (`POST /prompt`, poll `/history/{id}`, `GET /view`) that
  a dumb round-robin LB would split across nodes on failover. Router logic was lifted from
  `zeus/zeus/core/comfyui.py`. Do not "simplify" it into a Caddy upstream block.
- **ollama-gateway is the opposite call**: Ollama's API is stateless enough for Caddy, so
  it uses `lb_policy first` plus active (`/api/version` every 10s) and passive
  (`fail_duration 30s`, `max_fails 1`) health checks, with `flush_interval -1` so NDJSON
  and token streams are not buffered.
- **The Ollama fabric has a sharp edge**: a request naming a model that exists only on
  Apollo will 404 if it falls through to the 3080. Failover-shared models must be pulled
  with identical tags on both nodes.
- **The 3080 is shared.** `zeus-ollama` pins roughly 8 to 9 GB of the 10 GB card, so
  ComfyUI there runs `--lowvram` to coexist. That is why the gateway's
  `COMFYUI_POLL_TIMEOUT` defaults to 180s.
- FLUX ignores `negative_prompt` (guidance-distilled, cfg=1). FLUX.1-dev is
  non-commercial and is not `tenant_exposable`; see `services/model-registry/`.

## What lives here now

- `context-pack-tool.py` is **not a service**. It is an Open WebUI tool plugin, pasted
  into the Open WebUI tools UI, that calls the separate `context-pack` RAG service at
  `http://context-pack:8000`. It has no Dockerfile and is not built or deployed by
  anything in this repo.
- `scripts/verify-gpu.sh` checks GPU visibility on the host, through Docker, and inside
  `zeus-ollama` and `zeus-comfyui`, the two workloads sharing the daedalus RTX 3080. It
  does not check the Apollo primaries, which are off-box.
- `.env` is untracked and gitignored. It still holds credentials for the deleted stack
  (`OPENROUTER_API_KEY`, `WEBUI_SECRET_KEY`). Do not wire anything new to it.

## Conventions

- Do not recreate `compose.yaml`, `setup.sh`, or an `ai-*` container set here. If a new
  inference service is genuinely needed, it goes in `/mnt/storage/services/<name>/`
  following the `comfyui-gateway` and `ollama-gateway` conventions, and gets registered in
  `services.yml`.
- Port 8189 belongs to `comfyui-gateway` now. Port 8191, formerly the model manager, is
  registered to an unrelated service. Check `services.yml` before claiming any port.
- The `homelab-web` Docker network is **external**. Compose will not create it.
- No emdashes in generated text or docs, per the homelab-wide convention in
  `/mnt/CLAUDE.md`. Use commas, semicolons, colons, or restructure.
