#!/usr/bin/env python3
"""
OpenRouter Proxy Service
Provides a proxy interface to OpenRouter API with rate limiting, caching, and monitoring.
"""

import os
import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
import json

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import uvicorn
from contextlib import asynccontextmanager

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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1")
PROXY_PORT = int(os.getenv("PROXY_PORT", "8190"))
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")

# Metrics
REQUEST_COUNT = Counter('openrouter_requests_total', 'Total OpenRouter requests', ['model', 'status'])
REQUEST_DURATION = Histogram('openrouter_request_duration_seconds', 'Request duration', ['model'])
TOKEN_USAGE = Counter('openrouter_tokens_total', 'Total tokens used', ['model', 'type'])

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting OpenRouter Proxy service", port=PROXY_PORT)

    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not configured")
        raise RuntimeError("OPENROUTER_API_KEY is required")

    # Initialize shared HTTP client
    await get_http_client()
    logger.info("OpenRouter Proxy service started successfully")

    yield

    # Shutdown
    global http_client
    if http_client:
        await http_client.aclose()
    logger.info("OpenRouter Proxy service stopped")

app = FastAPI(
    title="OpenRouter Proxy",
    description="Proxy service for OpenRouter API with rate limiting, caching, and monitoring",
    version="1.0.0",
    lifespan=lifespan,
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

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    uptime_seconds: float

# Global state
start_time = datetime.now()
http_client: Optional[httpx.AsyncClient] = None

async def get_http_client():
    """Get or create HTTP client"""
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
        )
    return http_client

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API key (optional for now)"""
    if not credentials:
        return None
    # In production, implement proper API key verification
    return credentials.credentials

 

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    uptime = (datetime.now() - start_time).total_seconds()
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0",
        uptime_seconds=uptime
    )

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/models", response_model=List[ModelInfo])
@limiter.limit(RATE_LIMIT)
async def list_models(request: Request, api_key: Optional[str] = Depends(verify_api_key)):
    """List available models from OpenRouter"""
    try:
        client = await get_http_client()
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://chrislawrence.ca",
            "X-Title": "Hephaestus AI"
        }
        
        response = await client.get(f"{OPENROUTER_BASE_URL}/models", headers=headers)
        response.raise_for_status()
        
        models_data = response.json()
        models = []
        
        for model in models_data.get("data", []):
            models.append(ModelInfo(
                id=model["id"],
                name=model.get("name", model["id"]),
                description=model.get("description"),
                context_length=model.get("context_length"),
                pricing=model.get("pricing")
            ))
        
        logger.info("Models listed successfully", count=len(models))
        return models
        
    except httpx.HTTPError as e:
        logger.error("Failed to fetch models", error=str(e))
        raise HTTPException(status_code=502, detail="Failed to fetch models from OpenRouter")
    except Exception as e:
        logger.error("Unexpected error listing models", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/chat/completions")
@limiter.limit(RATE_LIMIT)
async def chat_completions(
    request: Request,
    chat_request: ChatRequest,
    api_key: Optional[str] = Depends(verify_api_key)
):
    """Proxy chat completions to OpenRouter"""
    start_time = datetime.now()
    
    try:
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
        
        # Record metrics
        duration = (datetime.now() - start_time).total_seconds()
        REQUEST_DURATION.labels(model=chat_request.model).observe(duration)
        REQUEST_COUNT.labels(model=chat_request.model, status=response.status_code).inc()
        
        if response.status_code != 200:
            logger.error("OpenRouter API error", 
                        status_code=response.status_code, 
                        response=response.text)
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        response_data = response.json()
        
        # Record token usage if available
        if "usage" in response_data:
            usage = response_data["usage"]
            if "prompt_tokens" in usage:
                TOKEN_USAGE.labels(model=chat_request.model, type="prompt").inc(usage["prompt_tokens"])
            if "completion_tokens" in usage:
                TOKEN_USAGE.labels(model=chat_request.model, type="completion").inc(usage["completion_tokens"])
        
        logger.info("Chat completion successful", 
                   model=chat_request.model, 
                   duration=duration,
                   tokens=response_data.get("usage", {}))
        
        return response_data
        
    except httpx.HTTPError as e:
        REQUEST_COUNT.labels(model=chat_request.model, status="error").inc()
        logger.error("HTTP error in chat completion", error=str(e))
        raise HTTPException(status_code=502, detail="Failed to communicate with OpenRouter")
    except Exception as e:
        REQUEST_COUNT.labels(model=chat_request.model, status="error").inc()
        logger.error("Unexpected error in chat completion", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/usage")
@limiter.limit("10/minute")
async def get_usage(request: Request, api_key: Optional[str] = Depends(verify_api_key)):
    """Get usage statistics from OpenRouter"""
    try:
        client = await get_http_client()
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = await client.get(f"{OPENROUTER_BASE_URL}/auth/key", headers=headers)
        response.raise_for_status()
        
        return response.json()
        
    except httpx.HTTPError as e:
        logger.error("Failed to fetch usage", error=str(e))
        raise HTTPException(status_code=502, detail="Failed to fetch usage from OpenRouter")
    except Exception as e:
        logger.error("Unexpected error fetching usage", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "OpenRouter Proxy",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "models": "/models",
            "chat": "/chat/completions",
            "usage": "/usage",
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
