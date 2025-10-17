# AI Inference Services - Local Development Access

## Quick Start

```bash
# Load aliases for convenience
source ./docker-aliases.sh

# Start all services with GPU support
dcupgpu

# Or rebuild and start
dcreupgpu
```

## Service Access Links

### **Local Development URLs (7xxx ports)**

| Service | URL | Description | GPU Required |
|---------|-----|-------------|--------------|
| **Open WebUI** | [http://localhost:7189](http://localhost:7189) | AI chat interface | No |
| **ComfyUI** | [http://localhost:7188](http://localhost:7188) | Image generation workflows | Yes |
| **Model Manager** | [http://localhost:7191](http://localhost:7191) | Download and manage AI models | Yes |
| **OpenRouter Proxy** | [http://localhost:7190](http://localhost:7190) | Cloud AI model access | No |
| **Ollama API** | [http://localhost:7114](http://localhost:7114) | Local LLM inference engine | Yes |

### **Service Details**

#### **Open WebUI** - `http://localhost:7189`
- **Purpose**: Web interface for chatting with AI models
- **Features**: Chat with local Ollama models or cloud models via OpenRouter
- **Setup**: No additional setup required
- **Models**: Connects to Ollama for local models, OpenRouter for cloud models

#### **ComfyUI** - `http://localhost:7188`
- **Purpose**: Advanced image generation with node-based workflows
- **Features**: Stable Diffusion, ControlNet, custom workflows
- **Setup**: GPU required for image generation
- **Models**: Downloads models automatically to `./data/models`

#### **Model Manager** - `http://localhost:7191`
- **Purpose**: Download and manage AI models for Ollama and ComfyUI
- **Features**: Browse, download, and organize models
- **Setup**: Requires Ollama and ComfyUI to be running
- **Storage**: Models stored in `./data/models`

#### **OpenRouter Proxy** - `http://localhost:7190`
- **Purpose**: Proxy for accessing cloud AI models
- **Features**: Rate limiting, API key management
- **Setup**: Requires `OPENROUTER_API_KEY` environment variable
- **Models**: Access to 100+ cloud models via OpenRouter

#### **Ollama API** - `http://localhost:7114`
- **Purpose**: Local LLM inference engine
- **Features**: Run models locally on your GPU
- **Setup**: GPU required for optimal performance
- **Models**: Download with `ollama pull <model-name>`

## Management Commands

### **Docker Compose Commands**
```bash
# Start with GPU support
docker compose --profile gpu up -d

# Stop all services
docker compose down

# Rebuild and start
docker compose --profile gpu up -d --build

# View logs
docker compose logs -f

# Check status
docker compose ps
```

### **Convenience Aliases** (after `source ./docker-aliases.sh`)
```bash
# GPU services
dcupgpu          # Start with GPU
dcreupgpu       # Rebuild and start with GPU
dcdown          # Stop all services

# Monitoring
dclogs          # View logs
dctop           # Show running processes
dps             # Show containers

# GPU testing
dgpu            # Test GPU in Docker
```

## Environment Setup

### **Required Environment Variables**
Create a `.env` file with:
```bash
# OpenRouter API Key (for cloud models)
OPENROUTER_API_KEY=your_api_key_here

# Optional: WebUI configuration
WEBUI_SECRET_KEY=your_secret_key
WEBUI_NAME=Local AI
WEBUI_AUTH=True
ENABLE_SIGNUP=False
```

### **GPU Requirements**
- NVIDIA GPU with CUDA support
- NVIDIA Container Toolkit installed
- Docker configured for GPU access

## Directory Structure

```
ai-inference/
├── docker-compose.yml          # Local development compose
├── docker-compose-homelab.yml  # Homelab production compose
├── docker-aliases.sh          # Convenience aliases
├── setup.sh                   # Setup script
├── data/                      # Model storage
│   ├── models/               # Downloaded models
│   ├── outputs/              # Generated outputs
│   └── cache/                # WebUI cache
├── comfyui/                  # ComfyUI customizations
├── openrouter-proxy/         # OpenRouter proxy code
└── model-manager/           # Model manager code
```

## Troubleshooting

### **GPU Issues**
```bash
# Test GPU access
dgpu

# Check NVIDIA Container Toolkit
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### **Service Issues**
```bash
# Check service status
docker compose ps

# View specific service logs
docker compose logs -f ollama
docker compose logs -f comfyui

# Restart specific service
docker compose restart ollama
```

### **Port Conflicts**
- All services use 7xxx ports to avoid conflicts with homelab (8xxx/9xxx)
- If ports are still in use, check with: `netstat -tulpn | grep :71`

## Quick Reference

| Action | Command |
|--------|---------|
| **Start everything** | `dcupgpu` |
| **Stop everything** | `dcdown` |
| **View logs** | `dclogs` |
| **Test GPU** | `dgpu` |
| **Check status** | `dps` |
| **Rebuild** | `dcreupgpu` |

---

**Note**: This is the local development version. For production deployment, use `docker-compose-homelab.yml` with your homelab infrastructure.
