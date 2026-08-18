#!/usr/bin/env python3
"""
Person Trainer Service
Manages a per-person photo library and drives FLUX LoRA training + generation
for the "make good images of a specific person" feature.

Training itself does not happen in this container: it needs direct GPU access
that only the host has (see ~/ml-tools/sd-scripts/run_trainer.py, a systemd
user service on Apollo). This service and that runner communicate purely by
reading/writing JSON files under the shared PEOPLE_DIR mount - this service
never invokes training directly.
"""
import asyncio
import io
import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

import httpx
import structlog
import uvicorn
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import pillow_avif  # noqa: F401 - registers the AVIF decoder with PIL on import
from PIL import Image
from pillow_heif import register_heif_opener
from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

register_heif_opener()  # adds HEIC/HEIF decode support (iPhone photos)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger()

SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8193"))
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://comfyui:8188")
PEOPLE_DIR = os.getenv("PEOPLE_DIR", "/app/people")
LORAS_DIR = os.getenv("LORAS_DIR", "/app/loras")
WORKFLOW_PATH = os.getenv(
    "GENERATE_WORKFLOW_PATH", "/app/workflows/generate_with_lora_flux.json"
)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
MAX_PHOTO_DIMENSION = 1536
JOB_STALE_SECONDS = 300

REQUEST_COUNT = Counter(
    "person_trainer_requests_total", "Total requests", ["endpoint", "status"]
)
TRAIN_JOBS = Counter("person_trainer_train_jobs_total", "Training jobs submitted")
GENERATE_DURATION = Histogram(
    "person_trainer_generate_duration_seconds", "Generation duration"
)

http_client: Optional[httpx.AsyncClient] = None
start_time = datetime.now()


async def get_http_client() -> httpx.AsyncClient:
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
    return http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(PEOPLE_DIR, exist_ok=True)
    logger.info(
        "Starting person-trainer service", port=SERVICE_PORT, people_dir=PEOPLE_DIR
    )
    await get_http_client()
    yield
    if http_client:
        await http_client.aclose()
    logger.info("person-trainer service stopped")


app = FastAPI(
    title="Person Trainer",
    description="Person photo library + FLUX LoRA training/generation",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PersonCreate(BaseModel):
    name: str
    trigger_word: Optional[str] = None


class TrainRequest(BaseModel):
    steps: int = 1500
    network_dim: int = 16
    learning_rate: float = 1e-4


class GenerateRequest(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    lora_strength: float = 1.0
    seed: Optional[int] = None


def person_dir(person_id: str) -> str:
    return os.path.join(PEOPLE_DIR, person_id)


def person_path(person_id: str) -> str:
    return os.path.join(person_dir(person_id), "person.json")


def load_person(person_id: str) -> dict:
    path = person_path(person_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"person {person_id} not found")
    with open(path) as f:
        return json.load(f)


def save_person(person: dict):
    path = person_path(person["id"])
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(person, f, indent=2)
    os.replace(tmp, path)


def list_people() -> List[dict]:
    people = []
    if not os.path.isdir(PEOPLE_DIR):
        return people
    for entry in sorted(os.listdir(PEOPLE_DIR)):
        path = os.path.join(PEOPLE_DIR, entry, "person.json")
        if os.path.exists(path):
            with open(path) as f:
                people.append(json.load(f))
    return people


def train_jobs_dir(person_id: str) -> str:
    return os.path.join(person_dir(person_id), "train_jobs")


def latest_job(person_id: str) -> Optional[dict]:
    jdir = train_jobs_dir(person_id)
    if not os.path.isdir(jdir):
        return None
    jobs = []
    for name in os.listdir(jdir):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(jdir, name)) as f:
                jobs.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    if not jobs:
        return None
    jobs.sort(key=lambda j: j.get("created_at", 0))
    job = jobs[-1]
    if job.get("status") == "running":
        updated = job.get("updated_at", job.get("started_at", 0))
        if time.time() - updated > JOB_STALE_SECONDS:
            job["status"] = "failed"
            job["error"] = "runner stopped responding (stale job, no update in 2min)"
    return job


def any_job_active() -> bool:
    if not os.path.isdir(PEOPLE_DIR):
        return False
    for pid in os.listdir(PEOPLE_DIR):
        job = latest_job(pid)
        if job and job.get("status") in ("pending", "running", "cancel_requested"):
            return True
    return False


def sync_lora_status(person: dict) -> dict:
    job = latest_job(person["id"])
    if not job:
        return person
    status_map = {
        "pending": "training",
        "running": "training",
        "cancel_requested": "training",
        "done": "ready",
        "failed": "failed",
        "cancelled": "failed",
    }
    person["lora_status"] = status_map.get(job.get("status"), person.get("lora_status", "none"))
    if job.get("status") == "done":
        person["lora_filename"] = job.get("lora_filename")
    person["last_job"] = job
    return person


@app.get("/health")
async def health():
    uptime = (datetime.now() - start_time).total_seconds()
    return {"status": "healthy", "uptime_seconds": uptime}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
async def index():
    return FileResponse("/app/static/index.html")


@app.post("/people")
async def create_person(body: PersonCreate):
    person_id = str(uuid.uuid4())[:8]
    trigger_word = body.trigger_word or f"sks_{person_id}"
    os.makedirs(os.path.join(person_dir(person_id), "photos"), exist_ok=True)
    os.makedirs(train_jobs_dir(person_id), exist_ok=True)
    person = {
        "id": person_id,
        "name": body.name,
        "trigger_word": trigger_word,
        "created_at": time.time(),
        "photos": [],
        "lora_status": "none",
        "lora_filename": None,
    }
    save_person(person)
    REQUEST_COUNT.labels(endpoint="create_person", status="200").inc()
    logger.info("person created", person_id=person_id, name=body.name)
    return person


@app.get("/people")
async def get_people():
    return [sync_lora_status(p) for p in list_people()]


@app.get("/people/{person_id}")
async def get_person(person_id: str):
    return sync_lora_status(load_person(person_id))


@app.delete("/people/{person_id}")
async def delete_person(person_id: str):
    person = sync_lora_status(load_person(person_id))
    shutil.rmtree(person_dir(person_id), ignore_errors=True)
    lora_filename = person.get("lora_filename")
    if lora_filename:
        lora_path = os.path.join(LORAS_DIR, lora_filename)
        if os.path.exists(lora_path):
            os.remove(lora_path)
    logger.info("person deleted", person_id=person_id)
    return {"deleted": person_id}


@app.post("/people/{person_id}/photos")
async def upload_photos(person_id: str, files: List[UploadFile] = File(...)):
    person = load_person(person_id)
    photos_dir = os.path.join(person_dir(person_id), "photos")
    os.makedirs(photos_dir, exist_ok=True)
    added = []
    skipped = []
    for upload in files:
        contents = await upload.read()
        try:
            image = Image.open(io.BytesIO(contents))
            image = image.convert("RGB")
        except Exception as exc:
            skipped.append({"filename": upload.filename, "reason": str(exc)})
            continue
        image.thumbnail((MAX_PHOTO_DIMENSION, MAX_PHOTO_DIMENSION))
        photo_id = str(uuid.uuid4())[:8]
        filename = f"{photo_id}.jpg"
        image.save(os.path.join(photos_dir, filename), "JPEG", quality=92)
        entry = {"id": photo_id, "filename": filename}
        person["photos"].append(entry)
        added.append(entry)
    save_person(person)
    if skipped:
        logger.warning("photos skipped", person_id=person_id, skipped=skipped)
    logger.info("photos uploaded", person_id=person_id, count=len(added))
    return {"added": added, "skipped": skipped, "total": len(person["photos"])}


@app.get("/people/{person_id}/photos/{photo_id}")
async def get_photo(person_id: str, photo_id: str):
    person = load_person(person_id)
    match = next((p for p in person["photos"] if p["id"] == photo_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="photo not found")
    path = os.path.join(person_dir(person_id), "photos", match["filename"])
    return FileResponse(path)


@app.delete("/people/{person_id}/photos/{photo_id}")
async def delete_photo(person_id: str, photo_id: str):
    person = load_person(person_id)
    match = next((p for p in person["photos"] if p["id"] == photo_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="photo not found")
    path = os.path.join(person_dir(person_id), "photos", match["filename"])
    if os.path.exists(path):
        os.remove(path)
    person["photos"] = [p for p in person["photos"] if p["id"] != photo_id]
    save_person(person)
    return {"deleted": photo_id}


@app.post("/people/{person_id}/train")
async def start_training(person_id: str, body: TrainRequest):
    person = load_person(person_id)
    if len(person["photos"]) < 3:
        raise HTTPException(
            status_code=400, detail="need at least 3 photos to start training"
        )
    if any_job_active():
        raise HTTPException(
            status_code=409, detail="a training job is already running or queued"
        )
    job_id = str(uuid.uuid4())[:8]
    jdir = train_jobs_dir(person_id)
    os.makedirs(jdir, exist_ok=True)
    job = {
        "job_id": job_id,
        "trigger_word": person["trigger_word"],
        "steps": body.steps,
        "network_dim": body.network_dim,
        "learning_rate": body.learning_rate,
        "seed": 42,
        "status": "pending",
        "created_at": time.time(),
    }
    with open(os.path.join(jdir, f"{job_id}.json"), "w") as f:
        json.dump(job, f, indent=2)
    TRAIN_JOBS.inc()
    logger.info("training job queued", person_id=person_id, job_id=job_id)
    return job


@app.get("/people/{person_id}/train/status")
async def train_status(person_id: str):
    load_person(person_id)
    job = latest_job(person_id)
    if not job:
        return {"status": "none"}
    return job


@app.post("/people/{person_id}/train/cancel")
async def cancel_training(person_id: str):
    load_person(person_id)
    job = latest_job(person_id)
    if not job or job.get("status") not in ("pending", "running"):
        raise HTTPException(status_code=400, detail="no active job to cancel")
    jdir = train_jobs_dir(person_id)
    path = os.path.join(jdir, f"{job['job_id']}.json")
    job["status"] = "cancel_requested"
    with open(path, "w") as f:
        json.dump(job, f, indent=2)
    return job


@app.get("/loras")
async def list_loras():
    if not os.path.isdir(LORAS_DIR):
        return []
    return [f for f in os.listdir(LORAS_DIR) if f.endswith(".safetensors")]


@app.post("/people/{person_id}/generate")
async def generate(person_id: str, body: GenerateRequest):
    person = sync_lora_status(load_person(person_id))
    if person["lora_status"] != "ready" or not person.get("lora_filename"):
        raise HTTPException(
            status_code=409, detail="person has no ready LoRA yet - train first"
        )

    with open(WORKFLOW_PATH) as f:
        workflow_text = f.read()

    seed = body.seed if body.seed is not None else int(time.time() * 1000) % (2**32)
    prompt_text = f"{person['trigger_word']}, {body.prompt}"
    filename_prefix = f"person_{person_id}"

    workflow_text = (
        workflow_text.replace("{{LORA_FILENAME}}", person["lora_filename"])
        .replace('"{{LORA_STRENGTH}}"', str(body.lora_strength))
        .replace('"{{PROMPT}}"', json.dumps(prompt_text))
        .replace('"{{WIDTH}}"', str(body.width))
        .replace('"{{HEIGHT}}"', str(body.height))
        .replace('"{{SEED}}"', str(seed))
        .replace("{{FILENAME_PREFIX}}", filename_prefix)
    )
    workflow = json.loads(workflow_text)
    workflow.pop("_comment", None)

    client = await get_http_client()
    start = time.time()
    try:
        submit = await client.post(f"{COMFYUI_URL}/prompt", json=workflow)
        submit.raise_for_status()
        prompt_id = submit.json()["prompt_id"]

        for _ in range(120):
            hist = await client.get(f"{COMFYUI_URL}/history/{prompt_id}")
            data = hist.json()
            if prompt_id in data:
                outputs = data[prompt_id].get("outputs", {})
                images = outputs.get("11", {}).get("images", [])
                if images:
                    img = images[0]
                    view = await client.get(
                        f"{COMFYUI_URL}/view",
                        params={
                            "filename": img["filename"],
                            "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output"),
                        },
                    )
                    view.raise_for_status()
                    GENERATE_DURATION.observe(time.time() - start)
                    return Response(content=view.content, media_type="image/png")
                status = data[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    raise HTTPException(
                        status_code=502, detail=f"ComfyUI generation failed: {status}"
                    )
            await asyncio.sleep(1)
        raise HTTPException(status_code=504, detail="generation timed out")
    except httpx.HTTPError as e:
        logger.error("generation request failed", error=str(e))
        raise HTTPException(status_code=502, detail=f"ComfyUI unreachable: {e}")


if __name__ == "__main__":
    # Pass the app object directly (not "app:app") to avoid double-import and
    # duplicated Prometheus metric registration.
    uvicorn.run(app, host="0.0.0.0", port=SERVICE_PORT, log_level="info")
