# 🤖 AI Inference Services

Self-hosted AI inference services for the Hephaestus homelab, providing local LLM inference, image generation, and cloud model access.

## 🎯 **Services Overview**

| Service | Port | Purpose | Status |
|---------|------|---------|--------|
| **Ollama** | 11434 | Local LLM inference engine | 🟡 Pending |
| **Open WebUI** | 8189 | Web interface for AI chat | 🟡 Pending |
| **ComfyUI** | 8188 | Advanced image generation workflows | 🟡 Pending |
| **OpenRouter Proxy** | 8190 | Cloud model access via OpenRouter | 🟡 Pending |
| **Model Manager** | 8191 | Model download and management | 🟡 Pending |
| **Unified Inference Proxy** | 8192 | Unified local and cloud model access | 🟡 Pending |

## 🚀 **Quick Start**

### **1. Environment Setup**
```bash
# Copy environment template
cp env.template .env

# Edit configuration
nano .env
```

### **2. Start Services**
```bash
# Cloud-only (no local GPU): start WebUI + OpenRouter proxy
docker compose -f docker-compose-homelab.yml up -d openwebui openrouter-proxy

# With local GPU (enable local Ollama/ComfyUI)
docker compose -f docker-compose-homelab.yml --profile gpu up -d
```

### **3. Access Services**
- **Open WebUI**: http://192.168.50.128:8161 (via proxy)
- **ComfyUI**: http://192.168.50.128:8162 (via proxy)
- **Model Manager**: http://192.168.50.128:8164 (via proxy)
- **OpenRouter Proxy**: http://192.168.50.128:8163 (via proxy)

## 🔧 **Configuration**

### **Environment Variables**
Key configuration options in `.env`:

```bash
# Core Configuration
DOMAIN=chrislawrence.ca
SUBDOMAIN_PREFIX=ai

# Open WebUI
WEBUI_SECRET_KEY=your-secret-key-here
WEBUI_AUTH=True
WEBUI_NAME=Hephaestus AI

# OpenRouter Integration
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_API_URL=https://openrouter.ai/api/v1

# Unified Inference Proxy
DEFAULT_BACKEND=auto  # Options: auto, local, cloud

# GPU Configuration
CUDA_VISIBLE_DEVICES=0
NVIDIA_VISIBLE_DEVICES=all
```

### **Model Management**
```bash
# Download models via Ollama
docker exec ai-ollama ollama pull llama3
docker exec ai-ollama ollama pull mistral

# List available models
docker exec ai-ollama ollama list

# List all models (local + cloud) via unified proxy
curl http://localhost:8192/models

# Remove models
docker exec ai-ollama ollama rm model-name
```

### **Using the Unified Inference Proxy**
```bash
# Chat with auto-detection (default)
curl -X POST http://localhost:8192/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Force local model
curl -X POST "http://localhost:8192/chat/completions?backend=local" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'

# Force cloud model
curl -X POST "http://localhost:8192/chat/completions?backend=cloud" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## 📊 **Service Details**

### **Ollama (Local LLM)**
- **Purpose**: Local LLM inference with GPU acceleration
- **Models**: Llama 3, Mistral, CodeLlama, Phi-3
- **API**: RESTful API at port 11434
- **Storage**: Models stored in `ollama_data` volume

### **Open WebUI**
- **Purpose**: Web interface for AI chat and model management
- **Features**: Multi-model support, conversation history, user management
- **Backend**: Connects to Ollama and OpenRouter
- **Authentication**: Built-in user authentication

### **ComfyUI**
- **Purpose**: Advanced image generation with node-based workflows
- **Models**: Stable Diffusion, ControlNet, LoRA support
- **Features**: Batch processing, custom workflows, API access
- **Storage**: Models and outputs in dedicated volumes

### **OpenRouter Proxy**
- **Purpose**: Access to cloud-based AI models
- **Models**: GPT-4, Claude, Gemini, and more
- **Features**: Rate limiting, cost tracking, unified API
- **Authentication**: API key-based authentication

### **Unified AI Inference Proxy**
- **Purpose**: Unified interface for both local (Ollama) and cloud (OpenRouter) models
- **Features**: 
  - Auto-detection of model location (local vs cloud)
  - Manual backend selection via API parameter (`?backend=local|cloud|auto`)
  - Unified OpenRouter-compatible API interface
  - Automatic fallback between backends
  - Combined model listing from both backends
- **Usage**: 
  - Auto-detect: `POST /chat/completions?backend=auto` (default)
  - Force local: `POST /chat/completions?backend=local`
  - Force cloud: `POST /chat/completions?backend=cloud`
- **Models**: All Ollama models (local) + all OpenRouter models (cloud)
- **API**: OpenRouter-compatible format for seamless integration

### **Model Manager**
- **Purpose**: Centralized model download and management
- **Features**: Model registry, storage monitoring, download queue
- **Web UI**: Built-in dashboard for model management
- **Integration**: Works with Ollama and ComfyUI

## 🌐 **Network Integration**

### **Homelab Network**
- **Network**: `homelab-web` (external network)
- **Subnet**: 172.20.0.0/16
- **DNS**: Services accessible by container name

### **Port Mappings**
- **Direct Access**: 11434, 8188, 8189, 8190, 8191, 8192
- **Proxy Ports**: 8161, 8162, 8163, 8164 (for Organizr embedding)
- **Public URLs**: Via Cloudflare Tunnel

### **Caddy Integration**
- **Subpath Routing**: `/ai/*`, `/comfyui/*`, `/openrouter/*`, `/inference/*`, `/models/*`
- **Proxy Ports**: 8161-8165 for iframe embedding
- **Headers**: X-Frame-Options removed for embedding

## 🔒 **Security**

### **Access Control**
- **Authentication**: Open WebUI has built-in user management
- **API Keys**: OpenRouter requires API key configuration
- **Network**: Services on internal Docker network
- **Public Access**: Via Cloudflare Tunnel with authentication

### **Data Privacy**
- **Local Processing**: All inference runs locally (except OpenRouter)
- **No Logging**: Optional conversation logging
- **Model Storage**: Encrypted volumes for model storage
- **Network Isolation**: AI services on dedicated network segment

## 📈 **Monitoring**

### **Health Checks**
- **Ollama**: `/api/tags` endpoint
- **Open WebUI**: `/health` endpoint
- **ComfyUI**: `/system_stats` endpoint
- **OpenRouter Proxy**: `/health` endpoint
- **Unified Inference Proxy**: `/health` endpoint
- **Model Manager**: `/health` endpoint

### **Metrics**
- **Prometheus**: Built-in metrics for all services
- **Grafana**: AI services dashboard (planned)
- **Uptime Kuma**: Service monitoring integration

### **Logs**
```bash
# View service logs
~/manage-services.sh logs --service ai-inference

# View specific service logs
docker compose -f docker-compose-homelab.yml logs ollama
docker compose -f docker-compose-homelab.yml logs openwebui
```

## 🛠️ **Management Commands**

### **Service Management**
```bash
# Start AI services
~/manage-services.sh up --service ai-inference

# Stop AI services
~/manage-services.sh down --service ai-inference

# Restart AI services
~/manage-services.sh restart --service ai-inference

# Check status
~/manage-services.sh ps --service ai-inference
```

### **Model Management**
```bash
# Download popular models
docker exec ai-ollama ollama pull llama3:8b
docker exec ai-ollama ollama pull mistral:7b
docker exec ai-ollama ollama pull codellama:7b

# List models
docker exec ai-ollama ollama list

# Remove models
docker exec ai-ollama ollama rm model-name
```

### **Backup and Restore**
```bash
# Backup model data
~/backup-services.sh --service ai-inference

# Restore from backup
docker run --rm -v ai-inference_ollama_data:/data -v $(pwd):/backup alpine tar -xzf /backup/ollama_data-*.tgz -C /
```

## 🔧 **Troubleshooting**

### **Common Issues**

#### **GPU Not Detected**
```bash
# Check NVIDIA runtime
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi

# Check container GPU access
docker exec ai-ollama nvidia-smi
```

#### **Model Download Issues**
```bash
# Check Ollama logs
docker compose -f docker-compose-homelab.yml logs ollama

# Restart Ollama
docker compose -f docker-compose-homelab.yml restart ollama
```

#### **Memory Issues**
```bash
# Check memory usage
docker stats ai-ollama ai-comfyui

# Reduce model size
docker exec ai-ollama ollama pull llama3:7b  # Smaller model
```

#### **Network Issues**
```bash
# Check network connectivity
docker exec ai-openwebui ping ollama
docker exec ai-openwebui curl http://ollama:11434/api/tags
```

### **Performance Optimization**

#### **GPU Memory Management**
```bash
# Set GPU memory limits
export CUDA_VISIBLE_DEVICES=0
export NVIDIA_VISIBLE_DEVICES=all
```

#### **Model Caching**
```bash
# Pre-load models
docker exec ai-ollama ollama run llama3 "Hello, world!"
```

## 📚 **Documentation**

### **Service Documentation**
- [Ollama Documentation](https://ollama.ai/docs)
- [Open WebUI Documentation](https://docs.openwebui.com/)
- [ComfyUI Documentation](https://github.com/comfyanonymous/ComfyUI)
- [OpenRouter API Documentation](https://openrouter.ai/docs)

### **Model Resources**
- [Hugging Face Models](https://huggingface.co/models)
- [Ollama Model Library](https://ollama.ai/library)
- [ComfyUI Models](https://civitai.com/)

## 🚀 **Future Enhancements**

### **Planned Features**
- **Multi-GPU Support**: Scale across multiple GPUs
- **Model Fine-tuning**: Custom model training capabilities
- **API Marketplace**: Share custom workflows and models
- **Mobile Interface**: Native mobile app for AI services
- **Voice Integration**: Speech-to-text and text-to-speech

### **Integration Plans**
- **Grafana Dashboards**: AI service monitoring
- **Prometheus Metrics**: Detailed performance metrics
- **Organizr Integration**: AI services in dashboard
- **Backup Automation**: Automated model backups

---

## 📞 **Support**

### **Getting Help**
- Check service logs: `~/manage-services.sh logs --service ai-inference`
- Verify configuration: Review `.env` file
- Test connectivity: Use health check endpoints
- Check documentation: Service-specific docs above

### **Community Resources**
- [Ollama Community](https://github.com/ollama/ollama/discussions)
- [ComfyUI Discord](https://discord.gg/comfyui)
- [Open WebUI Discord](https://discord.gg/openwebui)
- [AI Homelab Community](https://reddit.com/r/selfhosted)

---

**Last Updated**: December 19, 2024  
**Status**: 🟡 Pending Deployment  
**Version**: 1.0.0  
**Maintainer**: Chris Lawrence
