# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A Docker Compose stack of self-hosted AI inference services (Ollama, Open WebUI, ComfyUI, plus three
custom Python microservices) for the homelab. It runs on two hosts with different networking needs:

- **Apollo** (this WSL2 workstation, RTX 5080) — local dev, uses `compose.override.yaml`
- **Hephaestus** (homelab server) — production, joins the external `homelab-web` Docker network

There is no test suite, linter config, or CI in this repo — verification is done by starting the stack
and hitting the `/health` endpoints.

## Commands

```bash
# Start everything with GPU services (Ollama, ComfyUI, model-manager)
docker compose --profile gpu up -d

# Start cloud-only (no local GPU): just WebUI + OpenRouter proxy
docker compose up -d openwebui openrouter-proxy

# Rebuild after changing a service's app.py/Dockerfile
docker compose --profile gpu up -d --build

# Logs / status
docker compose logs -f --tail=200 <service>
docker compose ps

# Optional shell aliases (source once)
source ./docker-aliases.sh   # dc, dcup, dcgpu, dl <container>, dsh <container>, etc.
```

`compose.yaml` is the base file; `compose.override.yaml` is auto-merged by `docker compose` on this
machine and remaps every port to `71xx` (vs. the base `81xx`/`11434`), adds `gpus: all`, and switches
the `web` network from `external: homelab-web` to a local `bridge` network — so on Apollo the stack is
fully self-contained and doesn't require the homelab network to exist. Don't add a `-f` flag pointing at
`docker-compose-homelab.yml`/`docker-compose.yml` — those names are referenced by `setup.sh` /
`setup-local.sh` but the actual compose files in this repo are `compose.yaml` / `compose.override.yaml`.

Each of the three custom services rebuilds independently via `build: ./<service-dir>`; there's no shared
base image or monorepo tooling (no lockfiles beyond per-service `requirements.txt`).

## Architecture

Six services on the `web` Docker network, all healthchecked via HTTP:

| Service | Dir | Framework | Port | Role |
|---|---|---|---|---|
| `ollama` | (image) | — | 11434 | Local LLM inference engine |
| `ai-inference-proxy` | `ai-inference-proxy/` | FastAPI | 8192 | **Unified proxy** — local+cloud |
| `openwebui` | (image) | — | 8189 | Chat UI, talks to Ollama directly + the unified proxy |
| `comfyui` | `comfyui/` | — | 8188 | Image generation (custom Dockerfile, workflows/custom_nodes bind-mounted) |
| `openrouter-proxy` | `openrouter-proxy/` | FastAPI | 8190 | Thin OpenRouter passthrough (rate limit, metrics, caching) |
| `model-manager` | `model-manager/` | Flask | 8191 | Model download/registry + storage monitoring for Ollama & ComfyUI |
| `person-trainer` | `person-trainer/` | FastAPI | 8193 | Person photo library + FLUX LoRA training/generation (see below) |

### The unified proxy is the core piece (`ai-inference-proxy/app.py`)

Open WebUI is wired to two model sources simultaneously:
- `OLLAMA_BASE_URL` → Ollama directly (shows as "local" models)
- `OPENAI_API_BASE_URL` → `ai-inference-proxy` (shows as "external"; combines local + cloud)

`ai-inference-proxy` presents an OpenAI/OpenRouter-compatible `/chat/completions` API and internally
routes each request to either Ollama or OpenRouter:

- **Backend selection** (`?backend=auto|local|cloud`, default `auto`): `detect_model_backend()` checks
  whether the requested model name (or its base name before `:`) is in the live Ollama model list
  (cached 60s via `get_ollama_models()`); if so it's `local`, otherwise `cloud`.
- **Format translation**: `transform_ollama_request` / `transform_ollama_response` convert between
  Ollama's `/api/chat` shape and the OpenAI chat-completion shape (including SSE streaming chunks in
  `handle_ollama_stream`).
- **Fallback**: on `auto`, if the cloud call fails it retries against Ollama, and vice versa
  (`FALLBACK_COUNT` metric tracks this).
- **Observability**: Prometheus metrics (`inference_requests_total`, `inference_tokens_total`,
  `backend_selection_total`, etc.) exposed at `/metrics`; structured JSON logging via `structlog`.

`openrouter-proxy/app.py` is a simpler sibling with the same FastAPI/structlog/slowapi/Prometheus
scaffolding but only talks to OpenRouter (no backend-detection logic) — useful when you want cloud
models without the unified-proxy indirection.

`model-manager/app.py` (Flask, not FastAPI) manages the model registry/downloads independently and
exposes `/api/ollama/models`, `/api/download/ollama/<model_name>`, `/api/storage`, etc.

### Person LoRA training (`person-trainer/`)

Upload ~15 photos of a person, train a FLUX LoRA, generate images of them. The
training itself does **not** run in Docker: FLUX LoRA training needs direct GPU
access with a specific torch build (cu128, for the 5080's sm_120/Blackwell
capability) that only exists in a **host** venv, not a container. So this feature
splits across two things that only talk to each other via shared files, never
directly:

- `person-trainer` (this container): people/photos registry (`people.json`-style,
  one `person.json` per person under `PEOPLE_DIR`), the HTML UI, and `/generate`
  (real ComfyUI HTTP calls, unaffected by any of this). `/train` does **not** invoke
  training — it just writes a job-spec JSON into
  `PEOPLE_DIR/{person_id}/train_jobs/{job_id}.json`.
- `~/ml-tools/sd-scripts/run_trainer.py` on the Apollo **host** (not in this repo,
  not in Docker) — a `kohya-ss/sd-scripts` venv, installed as the
  `lora-trainer.service` systemd user service (`loginctl enable-linger chris` is
  required so it survives logout/reboot). Polls that same `PEOPLE_DIR` mount
  (`~/ai-data/people` on Apollo) for pending jobs, runs
  `accelerate launch flux_train_network.py`, writes step/status progress back into
  the same job file. Waits for ComfyUI's queue to be empty before starting a job, so
  generation always wins over a queued training run.

Do not try to make `person-trainer` invoke training directly — it has no GPU access
and no venv. If you need to change training behavior, edit `run_trainer.py` on the
host and `systemctl --user restart lora-trainer.service`, not anything in this repo.

Two hardware findings worth knowing before touching this:
- ComfyUI's own built-in training nodes (`TrainLoraNode` etc.) do **not** work for
  FLUX on this card — OOMs in `backward()` even with every low-VRAM knob enabled, and
  the failure wedges the ComfyUI container until restarted. That's why this uses an
  external trainer instead. Full detail in `~/github/comfyui/README.md`.
- Any FLUX workflow — training or generation — needs to load the model with on-load
  fp8 casting (kohya's `--fp8_base`, or ComfyUI's `UNETLoader` with
  `weight_dtype: "fp8_e4m3fn"`). Loading `flux1-dev.safetensors` at full precision
  (`weight_dtype: "default"`) pushes this box's ~15.5GB WSL2 RAM into heavy swap
  thrashing and can hang for minutes. `person-trainer/workflows/generate_with_lora_flux.json`
  already has this fix; don't remove it.

### Other pieces

- `context-pack-tool.py` — an Open WebUI **Tool** plugin (pasted into WebUI's Tools UI, not built by
  Docker Compose here). It calls `http://context-pack:8000`, a separate personal RAG service that lives
  outside this repo — don't assume that container exists in this stack.
- `data/` — gitignored bind-mount root for models/cache/outputs, shared across Ollama, ComfyUI, and
  model-manager.
- `setup.sh` vs `setup-local.sh` — both do env-setup/GPU-check/model-download/start-services, but target
  different hosts: `setup.sh` assumes the Hephaestus layout (`/home/chris/apps/ai-inference`,
  `docker-compose-homelab.yml`, external `manage-services.sh`); `setup-local.sh` is self-contained and
  relative to its own location. Prefer `setup-local.sh` when working on Apollo.

## Working on the FastAPI services

Both `ai-inference-proxy` and `openrouter-proxy` share the same conventions — match them when editing:
structured `structlog` JSON logging, Prometheus `Counter`/`Histogram` metrics per request, `slowapi`
rate limiting via `RATE_LIMIT` env var, CORS from `ALLOWED_ORIGINS`, and a single shared `httpx.AsyncClient`
via `get_http_client()`. `uvicorn.run(app, ...)` is called with the app object directly (not the
`"app:app"` string form) — the module docstring at the bottom of each `app.py` explains this avoids
double-importing and duplicating Prometheus metric registration; keep that pattern if you touch the
`__main__` block.
