# AI Inference Services - Homelab Production Access

## Quick Start

```bash
# Start all services with GPU support
docker compose -f docker-compose-homelab.yml --profile gpu up -d

# Or rebuild and start
docker compose -f docker-compose-homelab.yml --profile gpu up -d --build
```

## Service Access Links

### **Homelab Production URLs**

| Service | Direct Port (LAN) | Proxy Port (LAN) | Public URL | Status |
|---------|------------------|------------------|------------|--------|
| **Open WebUI** | [http://192.168.50.70:8189](http://192.168.50.70:8189) | [http://192.168.50.70:8161](http://192.168.50.70:8161) | [https://chrislawrence.ca/ai](https://chrislawrence.ca/ai) | Working |
| **ComfyUI** | [http://192.168.50.70:8188](http://192.168.50.70:8188) | [http://192.168.50.70:8162](http://192.168.50.70:8162) | [https://chrislawrence.ca/comfyui](https://chrislawrence.ca/comfyui) | Pending |
| **Model Manager** | [http://192.168.50.70:8191](http://192.168.50.70:8191) | [http://192.168.50.70:8164](http://192.168.50.70:8164) | [https://chrislawrence.ca/models](https://chrislawrence.ca/models) | Pending |
| **OpenRouter Proxy** | [http://192.168.50.70:8190](http://192.168.50.70:8190) | [http://192.168.50.70:8163](http://192.168.50.70:8163) | [https://chrislawrence.ca/openrouter](https://chrislawrence.ca/openrouter) | Working |
| **Ollama API** | [http://192.168.50.70:11434](http://192.168.50.70:11434) | N/A | [https://chrislawrence.ca/ai/api](https://chrislawrence.ca/ai/api) | Pending |

### **Service Details**

#### **Open WebUI** - AI Chat Interface
- **Direct Access**: http://192.168.50.70:8189
- **Proxy Access**: http://192.168.50.70:8161 (for Organizr embedding)
- **Public Access**: https://chrislawrence.ca/ai
- **Purpose**: Web interface for chatting with AI models
- **Features**: Chat with local Ollama models or cloud models via OpenRouter
- **Network**: homelab-web (external)
- **Status**: Working

#### **ComfyUI** - Image Generation Workflows
- **Direct Access**: http://192.168.50.70:8188
- **Proxy Access**: http://192.168.50.70:8162 (for Organizr embedding)
- **Public Access**: https://chrislawrence.ca/comfyui
- **Purpose**: Advanced image generation with node-based workflows
- **Features**: Stable Diffusion, ControlNet, custom workflows
- **Network**: homelab-web (external)
- **Status**: Pending deployment

#### **Model Manager** - AI Model Management
- **Direct Access**: http://192.168.50.70:8191
- **Proxy Access**: http://192.168.50.70:8164 (for Organizr embedding)
- **Public Access**: https://chrislawrence.ca/models
- **Purpose**: Download and manage AI models for Ollama and ComfyUI
- **Features**: Browse, download, and organize models
- **Network**: homelab-web (external)
- **Status**: Pending deployment

#### **OpenRouter Proxy** - Cloud AI Access
- **Direct Access**: http://192.168.50.70:8190
- **Proxy Access**: http://192.168.50.70:8163 (for Organizr embedding)
- **Public Access**: https://chrislawrence.ca/openrouter
- **Purpose**: Proxy for accessing cloud AI models
- **Features**: Rate limiting, API key management
- **Network**: homelab-web (external)
- **Status**: Working

#### **Ollama API** - Local LLM Engine
- **Direct Access**: http://192.168.50.70:11434
- **Public Access**: https://chrislawrence.ca/ai/api
- **Purpose**: Local LLM inference engine
- **Features**: Run models locally on GPU
- **Network**: homelab-web (external)
- **Status**: Pending deployment

## Management Commands

### **Homelab Management Script**
```bash
# Start AI services
~/manage-services.sh up --service ai-inference

# Stop AI services
~/manage-services.sh down --service ai-inference

# Check status
~/manage-services.sh ps --service ai-inference

# View logs
~/manage-services.sh logs --service ai-inference
```

### **Direct Docker Compose Commands**
```bash
# Start with GPU support
docker compose -f docker-compose-homelab.yml --profile gpu up -d

# Stop all services
docker compose -f docker-compose-homelab.yml down

# Rebuild and start
docker compose -f docker-compose-homelab.yml --profile gpu up -d --build

# View logs
docker compose -f docker-compose-homelab.yml logs -f

# Check status
docker compose -f docker-compose-homelab.yml ps
```

## Environment Setup

### **Required Environment Variables**
Create a `.env` file with:
```bash
# OpenRouter API Key (for cloud models)
OPENROUTER_API_KEY=your_api_key_here

# WebUI configuration
WEBUI_SECRET_KEY=your_secret_key
WEBUI_NAME=Hephaestus AI
WEBUI_AUTH=True
ENABLE_SIGNUP=False
DEFAULT_USER_ROLE=user

# OpenRouter configuration
OPENROUTER_API_URL=https://openrouter.ai/api/v1
ALLOWED_ORIGINS=*
RATE_LIMIT=100
```

### **Network Requirements**
- **homelab-web**: External network (created by setup-networks.sh)
- **Subnet**: 172.20.0.0/16
- **Gateway**: 172.20.0.1

### **GPU Requirements**
- NVIDIA GPU with CUDA support
- NVIDIA Container Toolkit installed
- Docker configured for GPU access
- WSL2 GPU support (if running on WSL2)

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

## Network Configuration

### **Homelab Network Setup**
```bash
# Create homelab network (if not exists)
~/setup-networks.sh --network-name homelab-web --subnet 172.20.0.0/16
```

### **Proxy Configuration**
- **Caddy**: Handles proxy ports (8161-8164)
- **Cloudflare Tunnel**: Handles public access
- **Organizr**: Dashboard integration

## Troubleshooting

### **Network Issues**
```bash
# Check homelab network
docker network inspect homelab-web

# Check service connectivity
docker exec ai-openwebui curl -f http://ollama:11434/api/tags
```

### **GPU Issues**
```bash
# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

# Check GPU in containers
docker exec ai-ollama nvidia-smi
```

### **Service Issues**
```bash
# Check service status
docker compose -f docker-compose-homelab.yml ps

# View specific service logs
docker compose -f docker-compose-homelab.yml logs -f ollama
docker compose -f docker-compose-homelab.yml logs -f comfyui

# Restart specific service
docker compose -f docker-compose-homelab.yml restart ollama
```

### **Proxy Issues**
```bash
# Check Caddy proxy configuration
curl -I http://192.168.50.70:8161

# Check Cloudflare tunnel status
cloudflared tunnel list
```

## Quick Reference

| Action | Command |
|--------|---------|
| **Start everything** | `~/manage-services.sh up --service ai-inference` |
| **Stop everything** | `~/manage-services.sh down --service ai-inference` |
| **View logs** | `~/manage-services.sh logs --service ai-inference` |
| **Check status** | `~/manage-services.sh ps --service ai-inference` |
| **Test GPU** | `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` |
| **Rebuild** | `docker compose -f docker-compose-homelab.yml --profile gpu up -d --build` |

## Integration Points

### **Organizr Dashboard**
- **URL**: https://dashboard.chrislawrence.ca
- **AI Services Tab**: Configured with proxy URLs
- **Embedding**: Use proxy ports for iframe compatibility

### **Caddy Proxy**
- **Configuration**: /etc/caddy/Caddyfile
- **Proxy Ports**: 8161-8164
- **SSL**: Automatic HTTPS with Let's Encrypt

### **Cloudflare Tunnel**
- **Tunnel**: chrislawrence.ca
- **Public URLs**: https://chrislawrence.ca/ai, /comfyui, /models, /openrouter
- **Security**: Cloudflare protection and caching

---

**Note**: This is the homelab production version. For local development, use `docker-compose.yml` with localhost URLs.
