#!/usr/bin/env python3
"""
Model Manager Service
Manages AI model downloads, updates, and storage for the AI inference stack.
"""

import os
import json
import time
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml
import psutil
from flask import Flask, jsonify, request, render_template_string
from flask_cors import CORS
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
import structlog

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
MANAGER_PORT = int(os.getenv("MANAGER_PORT", "8191"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://comfyui:8188")
MODEL_STORAGE_PATH = os.getenv("MODEL_STORAGE_PATH", "/app/models")

# Metrics
MODEL_DOWNLOADS = Counter('model_downloads_total', 'Total model downloads', ['model_type', 'status'])
MODEL_SIZE = Gauge('model_size_bytes', 'Model size in bytes', ['model_name'])
STORAGE_USAGE = Gauge('storage_usage_bytes', 'Storage usage in bytes')
REQUEST_DURATION = Histogram('model_manager_request_duration_seconds', 'Request duration')

# Flask app
app = Flask(__name__)
CORS(app)

# Global state
start_time = datetime.now()
model_registry = {}
download_queue = []

class ModelManager:
    def __init__(self):
        self.storage_path = Path(MODEL_STORAGE_PATH)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.load_model_registry()
    
    def load_model_registry(self):
        """Load model registry from disk"""
        registry_file = self.storage_path / "registry.json"
        if registry_file.exists():
            try:
                with open(registry_file, 'r') as f:
                    self.model_registry = json.load(f)
                logger.info("Model registry loaded", count=len(self.model_registry))
            except Exception as e:
                logger.error("Failed to load model registry", error=str(e))
                self.model_registry = {}
        else:
            self.model_registry = {}
    
    def save_model_registry(self):
        """Save model registry to disk"""
        registry_file = self.storage_path / "registry.json"
        try:
            with open(registry_file, 'w') as f:
                json.dump(self.model_registry, f, indent=2)
            logger.info("Model registry saved")
        except Exception as e:
            logger.error("Failed to save model registry", error=str(e))
    
    def get_storage_usage(self):
        """Get current storage usage"""
        try:
            usage = psutil.disk_usage(str(self.storage_path))
            return {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent
            }
        except Exception as e:
            logger.error("Failed to get storage usage", error=str(e))
            return {"total": 0, "used": 0, "free": 0, "percent": 0}
    
    def get_ollama_models(self):
        """Get models from Ollama"""
        try:
            response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
            if response.status_code == 200:
                return response.json().get("models", [])
            else:
                logger.error("Failed to get Ollama models", status=response.status_code)
                return []
        except Exception as e:
            logger.error("Failed to connect to Ollama", error=str(e))
            return []
    
    def download_ollama_model(self, model_name: str):
        """Download model via Ollama"""
        try:
            logger.info("Starting Ollama model download", model=model_name)
            response = requests.post(
                f"{OLLAMA_URL}/api/pull",
                json={"name": model_name},
                stream=True,
                timeout=300
            )
            
            if response.status_code == 200:
                # Stream the response to track progress
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line.decode())
                            if "status" in data:
                                logger.info("Download progress", 
                                          model=model_name, 
                                          status=data["status"])
                        except json.JSONDecodeError:
                            continue
                
                # Update registry
                self.model_registry[model_name] = {
                    "type": "ollama",
                    "downloaded_at": datetime.now().isoformat(),
                    "status": "downloaded"
                }
                self.save_model_registry()
                
                MODEL_DOWNLOADS.labels(model_type="ollama", status="success").inc()
                logger.info("Ollama model download completed", model=model_name)
                return True
            else:
                logger.error("Ollama model download failed", 
                           model=model_name, 
                           status=response.status_code)
                MODEL_DOWNLOADS.labels(model_type="ollama", status="error").inc()
                return False
                
        except Exception as e:
            logger.error("Ollama model download error", model=model_name, error=str(e))
            MODEL_DOWNLOADS.labels(model_type="ollama", status="error").inc()
            return False
    
    def get_comfyui_models(self):
        """Get ComfyUI model information"""
        try:
            # This would require ComfyUI API integration
            # For now, return basic info
            return {
                "checkpoints": [],
                "loras": [],
                "controlnets": [],
                "vae": []
            }
        except Exception as e:
            logger.error("Failed to get ComfyUI models", error=str(e))
            return {}
    
    def get_model_info(self, model_name: str):
        """Get detailed information about a model"""
        if model_name in self.model_registry:
            return self.model_registry[model_name]
        else:
            return {"status": "not_found"}

# Initialize model manager
model_manager = ModelManager()

@app.route("/health")
def health_check():
    """Health check endpoint"""
    uptime = (datetime.now() - start_time).total_seconds()
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "uptime_seconds": uptime
    })

@app.route("/metrics")
def metrics():
    """Prometheus metrics endpoint"""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}

@app.route("/")
def index():
    """Main dashboard"""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Model Manager</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .card { background: #f5f5f5; padding: 20px; margin: 20px 0; border-radius: 8px; }
            .status { padding: 4px 8px; border-radius: 4px; color: white; }
            .success { background: #28a745; }
            .error { background: #dc3545; }
            .warning { background: #ffc107; color: black; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #f2f2f2; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 AI Model Manager</h1>
            
            <div class="card">
                <h2>Storage Status</h2>
                <div id="storage-status">Loading...</div>
            </div>
            
            <div class="card">
                <h2>Ollama Models</h2>
                <div id="ollama-models">Loading...</div>
            </div>
            
            <div class="card">
                <h2>Model Registry</h2>
                <div id="model-registry">Loading...</div>
            </div>
            
            <div class="card">
                <h2>Quick Actions</h2>
                <button onclick="downloadModel()">Download Llama 3</button>
                <button onclick="refreshStatus()">Refresh Status</button>
            </div>
        </div>
        
        <script>
            async function loadStorageStatus() {
                try {
                    const response = await fetch('/api/storage');
                    const data = await response.json();
                    document.getElementById('storage-status').innerHTML = `
                        <p>Total: ${(data.total / 1024 / 1024 / 1024).toFixed(2)} GB</p>
                        <p>Used: ${(data.used / 1024 / 1024 / 1024).toFixed(2)} GB (${data.percent}%)</p>
                        <p>Free: ${(data.free / 1024 / 1024 / 1024).toFixed(2)} GB</p>
                    `;
                } catch (error) {
                    document.getElementById('storage-status').innerHTML = '<p>Error loading storage status</p>';
                }
            }
            
            async function loadOllamaModels() {
                try {
                    const response = await fetch('/api/ollama/models');
                    const data = await response.json();
                    let html = '<table><tr><th>Name</th><th>Size</th><th>Modified</th></tr>';
                    data.forEach(model => {
                        html += `<tr>
                            <td>${model.name}</td>
                            <td>${(model.size / 1024 / 1024 / 1024).toFixed(2)} GB</td>
                            <td>${new Date(model.modified_at).toLocaleString()}</td>
                        </tr>`;
                    });
                    html += '</table>';
                    document.getElementById('ollama-models').innerHTML = html;
                } catch (error) {
                    document.getElementById('ollama-models').innerHTML = '<p>Error loading Ollama models</p>';
                }
            }
            
            async function loadModelRegistry() {
                try {
                    const response = await fetch('/api/registry');
                    const data = await response.json();
                    let html = '<table><tr><th>Model</th><th>Type</th><th>Status</th><th>Downloaded</th></tr>';
                    Object.entries(data).forEach(([name, info]) => {
                        html += `<tr>
                            <td>${name}</td>
                            <td>${info.type}</td>
                            <td><span class="status success">${info.status}</span></td>
                            <td>${new Date(info.downloaded_at).toLocaleString()}</td>
                        </tr>`;
                    });
                    html += '</table>';
                    document.getElementById('model-registry').innerHTML = html;
                } catch (error) {
                    document.getElementById('model-registry').innerHTML = '<p>Error loading model registry</p>';
                }
            }
            
            async function downloadModel() {
                try {
                    const response = await fetch('/api/download/ollama/llama3', { method: 'POST' });
                    if (response.ok) {
                        alert('Model download started!');
                        refreshStatus();
                    } else {
                        alert('Failed to start download');
                    }
                } catch (error) {
                    alert('Error starting download');
                }
            }
            
            function refreshStatus() {
                loadStorageStatus();
                loadOllamaModels();
                loadModelRegistry();
            }
            
            // Load initial data
            refreshStatus();
            
            // Refresh every 30 seconds
            setInterval(refreshStatus, 30000);
        </script>
    </body>
    </html>
    """)

@app.route("/api/storage")
def get_storage():
    """Get storage usage information"""
    usage = model_manager.get_storage_usage()
    STORAGE_USAGE.set(usage["used"])
    return jsonify(usage)

@app.route("/api/ollama/models")
def get_ollama_models():
    """Get Ollama models"""
    models = model_manager.get_ollama_models()
    return jsonify(models)

@app.route("/api/registry")
def get_registry():
    """Get model registry"""
    return jsonify(model_manager.model_registry)

@app.route("/api/download/ollama/<model_name>", methods=["POST"])
def download_ollama_model(model_name):
    """Download Ollama model"""
    success = model_manager.download_ollama_model(model_name)
    if success:
        return jsonify({"status": "started", "model": model_name})
    else:
        return jsonify({"status": "error", "model": model_name}), 500

@app.route("/api/models/<model_name>")
def get_model_info(model_name):
    """Get specific model information"""
    info = model_manager.get_model_info(model_name)
    return jsonify(info)

@app.route("/api/status")
def get_status():
    """Get overall system status"""
    storage = model_manager.get_storage_usage()
    ollama_models = model_manager.get_ollama_models()
    
    return jsonify({
        "storage": storage,
        "ollama_models_count": len(ollama_models),
        "registry_count": len(model_manager.model_registry),
        "uptime": (datetime.now() - start_time).total_seconds()
    })

if __name__ == "__main__":
    logger.info("Starting Model Manager service", port=MANAGER_PORT)
    app.run(host="0.0.0.0", port=MANAGER_PORT, debug=False)
