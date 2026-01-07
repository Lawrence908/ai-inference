#!/usr/bin/env python3
"""
Unified AI Inference Proxy Service
Provides a unified interface for both local (Ollama) and cloud (OpenRouter) models
with auto-detection and manual backend selection.
"""

import os
import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, List, Literal
from datetime import datetime
import json

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Depends, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import uvicorn

# Configure structured logging
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
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Configuration
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8192"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "auto")

# Metrics
REQUEST_COUNT = Counter('inference_requests_total', 'Total inference requests', ['backend', 'model', 'status'])
REQUEST_DURATION = Histogram('inference_request_duration_seconds', 'Request duration', ['backend', 'model'])
TOKEN_USAGE = Counter('inference_tokens_total', 'Total tokens used', ['backend', 'model', 'type'])
BACKEND_SELECTION = Counter('backend_selection_total', 'Backend selection count', ['backend', 'method'])
FALLBACK_COUNT = Counter('backend_fallback_total', 'Backend fallback count', ['from_backend', 'to_backend'])
OLLAMA_MODELS_CACHE = Gauge('ollama_models_available', 'Number of available Ollama models')

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# FastAPI app
app = FastAPI(
    title="Unified AI Inference Proxy",
    description="Unified proxy service for local (Ollama) and cloud (OpenRouter) AI models",
    version="1.0.0"
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer(auto_error=False)

# Pydantic models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    frequency_penalty: Optional[float] = None
    presence_penalty: Optional[float] = None
    stream: Optional[bool] = False

class ModelInfo(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    context_length: Optional[int] = None
    pricing: Optional[Dict[str, Any]] = None
    backend: Optional[str] = None  # "local" or "cloud"

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    uptime_seconds: float
    backends: Dict[str, str]

# Global state
start_time = datetime.now()
http_client: Optional[httpx.AsyncClient] = None
ollama_models_cache: Dict[str, Any] = {}
ollama_cache_timestamp: Optional[datetime] = None
OLLAMA_CACHE_TTL = 60  # Cache Ollama models for 60 seconds

async def get_http_client():
    """Get or create HTTP client"""
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),  # Longer timeout for local models
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
        )
    return http_client

async def get_ollama_models() -> List[str]:
    """Get list of available Ollama models"""
    global ollama_models_cache, ollama_cache_timestamp
    
    # Check cache
    if ollama_cache_timestamp:
        cache_age = (datetime.now() - ollama_cache_timestamp).total_seconds()
        if cache_age < OLLAMA_CACHE_TTL and ollama_models_cache:
            return list(ollama_models_cache.keys())
    
    try:
        client = await get_http_client()
        response = await client.get(f"{OLLAMA_URL}/api/tags", timeout=10.0)
        
        if response.status_code == 200:
            data = response.json()
            models = {}
            for model in data.get("models", []):
                model_name = model.get("name", "")
                # Ollama model names might include tags like "llama3:latest"
                # Extract base name
                base_name = model_name.split(":")[0]
                models[base_name] = model
                models[model_name] = model  # Also cache full name
            
            ollama_models_cache = models
            ollama_cache_timestamp = datetime.now()
            OLLAMA_MODELS_CACHE.set(len(models))
            
            logger.info("Ollama models cached", count=len(models))
            return list(models.keys())
        else:
            logger.warning("Failed to fetch Ollama models", status=response.status_code)
            return []
    except Exception as e:
        logger.error("Error fetching Ollama models", error=str(e))
        return []

async def detect_model_backend(model_name: str) -> str:
    """Detect which backend should handle the model"""
    ollama_models = await get_ollama_models()
    
    # Check if model exists in Ollama (exact match or base name match)
    if model_name in ollama_models:
        return "local"
    
    # Check base name (e.g., "llama3" matches "llama3:latest")
    base_name = model_name.split(":")[0]
    if base_name in ollama_models:
        return "local"
    
    # Default to cloud
    return "cloud"

def transform_ollama_request(chat_request: ChatRequest) -> Dict[str, Any]:
    """Transform OpenRouter format to Ollama format"""
    # Extract base model name (remove tags)
    model_name = chat_request.model.split(":")[0]
    
    request_data = {
        "model": model_name,
        "messages": [msg.dict() for msg in chat_request.messages],
        "stream": chat_request.stream,
    }
    
    # Map parameters
    if chat_request.temperature is not None:
        request_data["options"] = request_data.get("options", {})
        request_data["options"]["temperature"] = chat_request.temperature
    
    if chat_request.max_tokens is not None:
        request_data["options"] = request_data.get("options", {})
        request_data["options"]["num_predict"] = chat_request.max_tokens
    
    if chat_request.top_p is not None:
        request_data["options"] = request_data.get("options", {})
        request_data["options"]["top_p"] = chat_request.top_p
    
    return request_data

def transform_ollama_response(ollama_response: Dict[str, Any], model_name: str) -> Dict[str, Any]:
    """Transform Ollama format to OpenRouter format"""
    # Generate a compatible ID
    response_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
    
    # Extract message content
    message_content = ""
    if "message" in ollama_response:
        message_content = ollama_response["message"].get("content", "")
    
    # Extract usage
    prompt_tokens = ollama_response.get("prompt_eval_count", 0)
    completion_tokens = ollama_response.get("eval_count", 0)
    
    return {
        "id": response_id,
        "model": model_name,
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": message_content
            },
            "finish_reason": ollama_response.get("done", False) and "stop" or None
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
    }

async def handle_ollama_request(chat_request: ChatRequest) -> Dict[str, Any]:
    """Handle request to Ollama backend"""
    client = await get_http_client()
    
    # Transform request
    ollama_request = transform_ollama_request(chat_request)
    
    # Make request to Ollama
    response = await client.post(
        f"{OLLAMA_URL}/api/chat",
        json=ollama_request,
        timeout=httpx.Timeout(120.0)
    )
    
    if response.status_code != 200:
        logger.error("Ollama API error", 
                    status_code=response.status_code, 
                    response=response.text)
        raise HTTPException(status_code=response.status_code, detail=response.text)
    
    response_data = response.json()
    
    # Transform response
    return transform_ollama_response(response_data, chat_request.model)

async def handle_ollama_stream(chat_request: ChatRequest):
    """Handle streaming request to Ollama backend"""
    client = await get_http_client()
    
    # Transform request
    ollama_request = transform_ollama_request(chat_request)
    
    # Make streaming request to Ollama
    async with client.stream(
        "POST",
        f"{OLLAMA_URL}/api/chat",
        json=ollama_request,
        timeout=httpx.Timeout(120.0)
    ) as response:
        if response.status_code != 200:
            error_text = await response.aread()
            raise HTTPException(status_code=response.status_code, detail=error_text.decode())
        
        response_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
        full_content = ""
        
        async for line in response.aiter_lines():
            if not line:
                continue
            
            try:
                data = json.loads(line)
                
                # Extract content delta
                content_delta = ""
                if "message" in data and "content" in data["message"]:
                    new_content = data["message"]["content"]
                    content_delta = new_content[len(full_content):]
                    full_content = new_content
                
                # Check if done
                done = data.get("done", False)
                
                # Format as OpenAI streaming response
                if content_delta or done:
                    chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": int(datetime.now().timestamp()),
                        "model": chat_request.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": content_delta} if content_delta else {},
                            "finish_reason": "stop" if done else None
                        }]
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
                
                if done:
                    # Send final usage chunk
                    usage_chunk = {
                        "id": response_id,
                        "object": "chat.completion.chunk",
                        "created": int(datetime.now().timestamp()),
                        "model": chat_request.model,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop"
                        }],
                        "usage": {
                            "prompt_tokens": data.get("prompt_eval_count", 0),
                            "completion_tokens": data.get("eval_count", 0),
                            "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
                        }
                    }
                    yield f"data: {json.dumps(usage_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                    break
                    
            except json.JSONDecodeError:
                continue

async def handle_openrouter_request(chat_request: ChatRequest) -> Dict[str, Any]:
    """Handle request to OpenRouter backend"""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API key not configured")
    
    client = await get_http_client()
    
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://chrislawrence.ca",
        "X-Title": "Hephaestus AI"
    }
    
    # Prepare request data
    request_data = chat_request.dict(exclude_none=True)
    
    # Make request to OpenRouter
    response = await client.post(
        f"{OPENROUTER_BASE_URL}/chat/completions",
        headers=headers,
        json=request_data
    )
    
    if response.status_code != 200:
        logger.error("OpenRouter API error", 
                    status_code=response.status_code, 
                    response=response.text)
        raise HTTPException(status_code=response.status_code, detail=response.text)
    
    return response.json()

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API key (optional for now)"""
    if not credentials:
        return None
    return credentials.credentials

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting Unified AI Inference Proxy service", port=PROXY_PORT)
    
    # Check Ollama connectivity
    try:
        models = await get_ollama_models()
        logger.info("Ollama connected", models_count=len(models))
    except Exception as e:
        logger.warning("Ollama not available", error=str(e))
    
    # Check OpenRouter configuration
    if OPENROUTER_API_KEY:
        logger.info("OpenRouter configured")
    else:
        logger.warning("OpenRouter API key not configured - cloud models unavailable")
    
    # Initialize HTTP client
    await get_http_client()
    logger.info("Unified AI Inference Proxy service started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global http_client
    if http_client:
        await http_client.aclose()
    logger.info("Unified AI Inference Proxy service stopped")

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    uptime = (datetime.now() - start_time).total_seconds()
    
    # Check backend availability
    backends = {}
    try:
        await get_ollama_models()
        backends["ollama"] = "available"
    except:
        backends["ollama"] = "unavailable"
    
    if OPENROUTER_API_KEY:
        backends["openrouter"] = "configured"
    else:
        backends["openrouter"] = "not_configured"
    
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0",
        uptime_seconds=uptime,
        backends=backends
    )

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/models", response_model=List[ModelInfo])
@limiter.limit(RATE_LIMIT)
async def list_models(
    request: Request,
    backend: Optional[Literal["local", "cloud", "all"]] = Query("all", description="Filter models by backend"),
    api_key: Optional[str] = Depends(verify_api_key)
):
    """List available models from both backends
    
    When accessed via Open WebUI's OPENAI_API_BASE_URL, this returns cloud models.
    Local models are accessed directly via OLLAMA_BASE_URL in Open WebUI.
    """
    models = []
    
    # Only include local models if explicitly requested or "all"
    if backend in ("all", "local"):
        try:
            ollama_models = await get_ollama_models()
            for model_name in ollama_models:
                model_info = ollama_models[model_name]
                # Use base name to avoid duplicates (e.g., "llama3" and "llama3:latest")
                base_name = model_name.split(":")[0]
                # Only add if we haven't seen this base name yet
                if not any(m.id == base_name or m.id == model_name for m in models):
                    models.append(ModelInfo(
                        id=base_name,  # Use base name for consistency
                        name=model_info.get("name", base_name),
                        description=f"Local model via Ollama",
                        context_length=None,
                        pricing=None,
                        backend="local"
                    ))
        except Exception as e:
            logger.error("Failed to fetch Ollama models", error=str(e))
    
    # Get cloud models from OpenRouter
    if backend in ("all", "cloud") and OPENROUTER_API_KEY:
        try:
            client = await get_http_client()
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chrislawrence.ca",
                "X-Title": "Hephaestus AI"
            }
            
            response = await client.get(f"{OPENROUTER_BASE_URL}/models", headers=headers)
            if response.status_code == 200:
                models_data = response.json()
                for model in models_data.get("data", []):
                    models.append(ModelInfo(
                        id=model["id"],
                        name=model.get("name", model["id"]),
                        description=model.get("description"),
                        context_length=model.get("context_length"),
                        pricing=model.get("pricing"),
                        backend="cloud"
                    ))
        except Exception as e:
            logger.error("Failed to fetch OpenRouter models", error=str(e))
    
    logger.info("Models listed successfully", 
               count=len(models), 
               local=sum(1 for m in models if m.backend == "local"), 
               cloud=sum(1 for m in models if m.backend == "cloud"),
               filter=backend)
    return models

@app.post("/chat/completions")
@limiter.limit(RATE_LIMIT)
async def chat_completions(
    request: Request,
    chat_request: ChatRequest,
    backend: Optional[Literal["local", "cloud", "auto"]] = Query(DEFAULT_BACKEND, description="Backend selection: local, cloud, or auto"),
    api_key: Optional[str] = Depends(verify_api_key)
):
    """Unified chat completions endpoint"""
    request_start = datetime.now()
    
    # Determine which backend to use
    selected_backend = backend or DEFAULT_BACKEND
    
    if selected_backend == "auto":
        selected_backend = await detect_model_backend(chat_request.model)
        BACKEND_SELECTION.labels(backend=selected_backend, method="auto").inc()
    else:
        BACKEND_SELECTION.labels(backend=selected_backend, method="manual").inc()
    
    # Handle streaming
    if chat_request.stream:
        if selected_backend == "local":
            return StreamingResponse(
                handle_ollama_stream(chat_request),
                media_type="text/event-stream"
            )
        else:
            # OpenRouter streaming
            if not OPENROUTER_API_KEY:
                raise HTTPException(status_code=500, detail="OpenRouter API key not configured")
            
            client = await get_http_client()
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chrislawrence.ca",
                "X-Title": "Hephaestus AI"
            }
            
            request_data = chat_request.dict(exclude_none=True)
            
            async with client.stream(
                "POST",
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=request_data
            ) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    raise HTTPException(status_code=response.status_code, detail=error_text.decode())
                
                async def generate():
                    async for chunk in response.aiter_lines():
                        yield chunk + "\n"
                
                return StreamingResponse(generate(), media_type="text/event-stream")
    
    # Non-streaming requests
    try:
        if selected_backend == "local":
            response_data = await handle_ollama_request(chat_request)
        else:
            # Try cloud
            if not OPENROUTER_API_KEY:
                # If local model not found and cloud not configured, try fallback
                if selected_backend == "cloud":
                    raise HTTPException(status_code=500, detail="OpenRouter API key not configured")
                # Auto-detect failed, try cloud anyway
                FALLBACK_COUNT.labels(from_backend="local", to_backend="cloud").inc()
                raise HTTPException(status_code=404, detail=f"Model {chat_request.model} not found locally and cloud not configured")
            
            try:
                response_data = await handle_openrouter_request(chat_request)
            except HTTPException as e:
                # If cloud fails and we were on auto, try local as fallback
                if selected_backend == "auto":
                    FALLBACK_COUNT.labels(from_backend="cloud", to_backend="local").inc()
                    logger.info("Cloud request failed, trying local fallback", model=chat_request.model)
                    response_data = await handle_ollama_request(chat_request)
                    selected_backend = "local"
                else:
                    raise
        
        # Record metrics
        duration = (datetime.now() - request_start).total_seconds()
        REQUEST_DURATION.labels(backend=selected_backend, model=chat_request.model).observe(duration)
        REQUEST_COUNT.labels(backend=selected_backend, model=chat_request.model, status="success").inc()
        
        # Record token usage if available
        if "usage" in response_data:
            usage = response_data["usage"]
            if "prompt_tokens" in usage:
                TOKEN_USAGE.labels(backend=selected_backend, model=chat_request.model, type="prompt").inc(usage["prompt_tokens"])
            if "completion_tokens" in usage:
                TOKEN_USAGE.labels(backend=selected_backend, model=chat_request.model, type="completion").inc(usage["completion_tokens"])
        
        logger.info("Chat completion successful", 
                   backend=selected_backend,
                   model=chat_request.model, 
                   duration=duration,
                   tokens=response_data.get("usage", {}))
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(backend=selected_backend, model=chat_request.model, status="error").inc()
        logger.error("Unexpected error in chat completion", error=str(e), backend=selected_backend)
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Unified AI Inference Proxy",
        "version": "1.0.0",
        "status": "running",
        "backends": {
            "local": "Ollama",
            "cloud": "OpenRouter"
        },
        "endpoints": {
            "health": "/health",
            "models": "/models",
            "chat": "/chat/completions?backend=auto|local|cloud",
            "metrics": "/metrics"
        }
    }

if __name__ == "__main__":
    # IMPORTANT: Pass the app object directly to avoid re-importing this module.
    # Using the string form ("app:app") causes this file to be imported twice
    # (once as __main__ and once as module "app"), which duplicates Prometheus metrics.
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PROXY_PORT,
        log_level="info",
        access_log=True
    )



