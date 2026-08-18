# person-trainer API contract

Base URL: `http://192.168.50.30:8193` (LAN, portproxied out of WSL2) or `http://comfyui`-style
in-cluster hostname `http://person-trainer:8193` if calling from another container on the same
`homelab-web` Docker network. `:7193` is the Apollo-local override port, same API.

This service owns the person/photo registry and training job lifecycle. It does **not** run
training itself — see `ai-inference/CLAUDE.md`'s "Person LoRA training" section if you need that
context. Callers only ever talk to this HTTP API.

## People

### `POST /people`
Create a person.

Request:
```json
{ "name": "Elon Musk", "trigger_word": null }
```
`trigger_word` is optional — omit it and one is generated as `sks_{person_id}`.

Response `200`:
```json
{
  "id": "22ee66a4",
  "name": "Elon Musk",
  "trigger_word": "sks_22ee66a4",
  "created_at": 1786930794.91,
  "photos": [],
  "lora_status": "none",
  "lora_filename": null
}
```

### `GET /people`
Returns an array of person objects (same shape as above, `lora_status`/`last_job` kept live —
see below).

### `GET /people/{person_id}`
Single person object. `404` if unknown.

### `DELETE /people/{person_id}`
Deletes the person, their photos, and their trained `.safetensors` (if any). Response:
`{ "deleted": "<person_id>" }`.

## Photos

### `POST /people/{person_id}/photos`
Multipart upload, field name `files` (repeatable). Accepts JPEG/PNG/WebP/AVIF/HEIC — anything
Pillow (+ pillow-heif/pillow-avif-plugin) can decode. Images are auto-converted to JPEG and
downsized to a 1536px longest edge on the way in.

Response `200`:
```json
{
  "added": [{ "id": "b55bb9af", "filename": "b55bb9af.jpg" }],
  "skipped": [{ "filename": "photo3.avif", "reason": "cannot identify image file" }],
  "total": 12
}
```
Always check `skipped` — files that fail to decode are silently excluded from `added` but not
from the request, so a 15-file upload can legitimately return fewer than 15 in `added`.

### `GET /people/{person_id}/photos/{photo_id}`
Returns the JPEG bytes directly (for `<img src>`).

### `DELETE /people/{person_id}/photos/{photo_id}`
`{ "deleted": "<photo_id>" }`.

## Training

Single global job slot — one training run at a time across *all* people (it's one GPU on Apollo).

### `POST /people/{person_id}/train`
Request (all fields optional, shown defaults):
```json
{ "steps": 1500, "network_dim": 16, "learning_rate": 0.0001 }
```
Requires >= 3 photos already uploaded. `409` if a job is already running/queued for anyone.
`400` if <3 photos.

Response `200` (the created job):
```json
{
  "job_id": "6dc6e9be",
  "trigger_word": "sks_22ee66a4",
  "steps": 1500,
  "network_dim": 16,
  "learning_rate": 0.0001,
  "seed": 42,
  "status": "pending",
  "created_at": 1786930808.12
}
```

### `GET /people/{person_id}/train/status`
Poll this. Returns the latest job for that person, evolving through:

```json
{
  "job_id": "6dc6e9be",
  "status": "running",
  "current_step": 923,
  "total_steps": 1500,
  "message": "training on 12 photos",
  "loss": 0.338,
  "updated_at": 1786933038.71
}
```

`status` values: `pending` -> `running` -> `done` | `failed` | `cancelled`. A `running` job with
no `updated_at` heartbeat in 300s is auto-flagged `failed` with
`"error": "runner stopped responding..."` on the next read (covers a crashed/killed host runner).
On `done`, the job includes `"lora_filename": "22ee66a4.safetensors"` and the person's own
`lora_status`/`lora_filename` (from `GET /people/{id}`) flip to `ready` at the same time — poll
the person, not just the job, if that's more convenient. If no job has ever been created:
`{ "status": "none" }`.

### `POST /people/{person_id}/train/cancel`
`400` if nothing running/pending. Otherwise marks `status: "cancel_requested"`; the host runner
checks this between training steps and stops (not instant).

## Generation

### `POST /people/{person_id}/generate`
`409` if `lora_status != "ready"`.

Request:
```json
{
  "prompt": "walking on a beach at sunset, cinematic lighting",
  "width": 1024,
  "height": 1024,
  "lora_strength": 1.0,
  "seed": null
}
```
The person's `trigger_word` is automatically prepended to `prompt` server-side — don't add it
yourself. `seed` omitted -> random.

Response: raw `image/png` bytes (not JSON) on `200`. `502` if ComfyUI errors or is unreachable,
`504` after ~120s with no result.

## Misc

### `GET /loras`
`["22ee66a4.safetensors", ...]` — every trained LoRA file on disk, independent of the people
registry (useful for reconciliation/orphan checks).

### `GET /health`
`{ "status": "healthy", "uptime_seconds": 123.4 }`

## Notes for integrators

- All state (people, photos, job status) lives in plain JSON files on a host bind mount — there's
  no database, no auth. This is a single-user LAN service; don't expose it past the homelab.
- `lora_status` on a person is only as fresh as your last `GET` — it's computed by reading the
  latest job file each time, not pushed. Poll `train/status` (or the person) every few seconds
  while a job is `pending`/`running`; stop polling once it's terminal.
- Photo/job state persists across `person-trainer` container restarts/rebuilds (it's all on the
  host mount) — safe to redeploy this service mid-training.
