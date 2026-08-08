# ai-inference

**This repo no longer runs a stack.** The self-hosted inference services that used to
live here (Ollama, Open WebUI, ComfyUI, an OpenRouter proxy, a unified inference proxy,
and a model manager) were superseded by the gateway-based fabric under
`/mnt/storage/services/`. They were removed on 2026-08-08 rather than left to rot.

What remains here is a small amount of still-useful tooling plus this pointer to where
the real services now live.

## Where the live services are

Nothing in this directory is deployed. Use these instead.

### Image generation

| Piece | Path | Endpoint | Notes |
|---|---|---|---|
| **comfyui-gateway** | `/mnt/storage/services/comfyui-gateway/` | `http://192.168.50.128:8189` | Always-on front door, FastAPI, failover across both GPUs |
| Apollo node (primary) | native, off-box | `192.168.50.30:8188` | RTX 5080, FLUX, not always on |
| daedalus node (fallback) | `/mnt/storage/services/comfyui/` | `comfyui:8188` (`zeus-comfyui`) | RTX 3080, SDXL `--lowvram`, always-on |

Consumers point only at the gateway on `:8189` and do not care which GPU answers. The
gateway health-checks Apollo via `GET /system_stats`; if it is up the whole
`POST /prompt` to poll `/history/{id}` to `GET /view` exchange runs there, otherwise it
falls through to the 3080.

```bash
# native
curl -s http://192.168.50.128:8189/generate \
  -d '{"prompt":"a red fox in snow, cinematic","width":1024,"height":1024}'

# OpenAI images-compatible shim
curl -s http://192.168.50.128:8189/v1/images/generations \
  -d '{"prompt":"a red fox in snow","size":"1024x1024"}'

# which node is serving right now
curl -s http://192.168.50.128:8189/healthz
```

### Text generation

| Piece | Path | Endpoint | Notes |
|---|---|---|---|
| **ollama-gateway** | `/home/chris/services/ollama-gateway/` | `http://192.168.50.128:11440` | Caddy, `lb_policy first`, active + passive health checks |
| Apollo node (primary) | native, off-box | `192.168.50.30:11434` | RTX 5080 |
| daedalus node (fallback) | zeus stack | `:11435` (`zeus-ollama`) | RTX 3080, shares the card with ComfyUI |

Both gateways are pinned and have Watchtower disabled on purpose: a front door on the
always-on path should not rebuild itself on a surprise upstream change.

## What is still in this repo

| File | Purpose |
|---|---|
| `context-pack-tool.py` | Open WebUI **tool plugin** (pasted into the Open WebUI tools UI, not a service). Calls the separate `context-pack` RAG service at `http://context-pack:8000` for `search` / `generate` / skills lookup. |
| `scripts/verify-gpu.sh` | Checks that the GPU is visible to the host, to Docker, and inside the two daedalus GPU containers (`zeus-ollama`, `zeus-comfyui`). Updated to probe those instead of the removed `ai-ollama`. |
| `CLAUDE.md` | Guidance for Claude Code working in this directory. |

## What was removed, and why

| Removed | Superseded by |
|---|---|
| `compose.yaml` (whole stack) | `services/comfyui-gateway/`, `services/comfyui/`, `services/ollama-gateway/` |
| `comfyui/` (Dockerfile, workflows, custom_nodes) | `services/comfyui/` using `yanwk/comfyui-boot`, fronted by the gateway |
| `ollama/`, `openwebui/` | `zeus-ollama` behind `ollama-gateway`; no Open WebUI instance is currently deployed |
| `ai-inference-proxy/` (unified local + cloud proxy, `:8192`) | The gateways handle routing and failover per fabric |
| `openrouter-proxy/` (`:8190`) | Not currently deployed anywhere |
| `model-manager/` (`:8191`) | `services/model-registry/`. Note `:8191` is now registered to an unrelated service in `services.yml` |
| `setup.sh`, `env.template`, `DEPLOYMENT_SUMMARY.md`, `OPENWEBUI_SETUP.md` | Described a `docker-compose-homelab.yml` that never existed in this tree, plus homelab scripts that are gone |
| `data/` | Was empty |

Docker volumes `ai-inference_ollama_data` (13 GB), `ai-inference_openwebui_data` (1 GB,
included `webui.db` and a `vector_db`), and `ai-inference_comfyui_data` (12 KB) were
deleted at the same time, reclaiming roughly 14 GB on `/mnt/storage`.

Everything above is recoverable from git history on `origin` if any of it is ever wanted
back. The one exception is the deleted volume contents, which are gone.

`.env` is left in place, untracked and gitignored. It still holds an `OPENROUTER_API_KEY`
and a `WEBUI_SECRET_KEY` for the removed stack. Delete it once you have confirmed the key
is not reused elsewhere.

## Related

- Service catalog and port registry: `/mnt/storage/services/daedalus-infra/config/services.yml`
- Public reverse proxy (separate stack, deliberately): `/mnt/storage/services/daedalus-infra/proxy/`
- Homelab network reference: the `network-topology` skill, and `homelab-docs/network.md` §9 / §9a
