# person-trainer API contract

Base URL: `http://192.168.50.30:8193` (LAN, portproxied out of WSL2) or `http://comfyui`-style
in-cluster hostname `http://person-trainer:8193` if calling from another container on the same
`homelab-web` Docker network. `:7193` is the Apollo-local override port, same API.

This service owns the person/photo registry and training job lifecycle. It does **not** run
training itself — see `ai-inference/CLAUDE.md`'s "Person LoRA training" section if you need that
context. Callers only ever talk to this HTTP API.

## Auth

Controlled by the `PERSON_TRAINER_TOKEN` env var (same name/value on both sides of the
integration).

- **Unset / empty (default)**: auth is off. Every route behaves exactly as documented below with
  no header required — this is the current state.
- **Set**: every route except `GET /health` requires `Authorization: Bearer <token>`. Missing,
  malformed, or wrong token → `401` with `{"detail": "..."}` and a `WWW-Authenticate: Bearer`
  header. `GET /health` is always open (uptime probes shouldn't need the secret). CORS preflight
  (`OPTIONS`) is also exempt.
- Tokens are compared in constant time server-side; the value is never logged.
- Flip it on with zero downtime: deploy this code first, agree the secret value out of band (not
  in a commit), set it in both `person-trainer`'s env and the caller's env, restart both — no code
  change needed on the caller's side beyond already sending the header.

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
  "duplicates": [{ "filename": "img4.jpg", "similar_to": "b55bb9af", "distance": 3 }],
  "total": 12
}
```
Always check `skipped` — files that fail to decode are silently excluded from `added` but not
from the request, so a 15-file upload can legitimately return fewer than 15 in `added`.

`duplicates` is informational only — flagged files are still decoded and added (they appear in
`added` too), not rejected. It's a perceptual-hash (dHash) near-duplicate check against every
photo already on the person, including others in the same upload batch. `distance` is a Hamming
distance out of 64 bits; lower means more similar (the threshold used server-side is 8). Useful
for prompting "these look like the same shot" without blocking the upload.

### `GET /people/{person_id}/photos/{photo_id}`
Returns the JPEG bytes directly (for `<img src>`).

### `PATCH /people/{person_id}/photos/{photo_id}`
Set or clear a per-photo caption, used during training (see below).

Request: `{ "caption": "outdoors, wearing sunglasses" }` (or `{ "caption": null }` to clear).
Response `200`: the updated photo object, e.g. `{ "id": "b55bb9af", "filename": "b55bb9af.jpg",
"caption": "outdoors, wearing sunglasses", "phash": 123456789 }`.

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
`400` if <3 photos. Each photo's caption (set via the `PATCH` route above) is combined with the
trigger word for that image's training caption (`"{trigger_word}, {caption}"`); photos with no
caption just use the trigger word alone. Captions are optional but improve how well a longer
generation prompt holds likeness — see the Notes section.

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

**Versioning**: each successful job writes a new, distinctly-named `.safetensors` rather than
overwriting the previous one, and `person.lora_filename` always tracks the file from the most
recently completed job — so a retrain never silently destroys a working LoRA, and this is fully
transparent to callers as long as you always read `lora_filename` fresh rather than caching a
filename. One older version is kept on disk as a backup before being pruned; deleting a person
(`DELETE /people/{person_id}`) removes every version, not just the current one.

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
