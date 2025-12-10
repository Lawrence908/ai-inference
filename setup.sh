#!/usr/bin/env bash
set -Eeuo pipefail

# Usage:
# Full setup (recommended for first time)
./setup.sh --full-setup
# Or individual steps
./setup.sh --setup-env          # Create .env file from template
./setup.sh --check-gpu          # Check GPU availability
./setup.sh --download-models    # Download initial models
./setup.sh --start-services     # Start AI services
./setup.sh --full-setup         # Complete setup (all steps)
./setup.sh --help               # Show this help


# AI Inference Services Setup Script
# Configures and starts the AI inference services for Hephaestus homelab

ROOT_DIR="/home/chris"
APPS_DIR="$ROOT_DIR/apps"
AI_DIR="$APPS_DIR/ai-inference"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    local level="$1"; shift
    local color=""
    case "$level" in
        "ERROR") color="$RED" ;;
        "SUCCESS") color="$GREEN" ;;
        "WARNING") color="$YELLOW" ;;
        "INFO") color="$BLUE" ;;
    esac
    echo -e "${color}[$level]${NC} $*"
}

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]
Options:
  --setup-env          Create .env file from template
  --check-gpu          Check GPU availability
  --download-models    Download initial models
  --start-services     Start AI services
  --full-setup         Complete setup (all steps)
  --help               Show this help
EOF
}

check_gpu() {
    log "INFO" "Checking GPU availability..."
    
    if ! command -v nvidia-smi &> /dev/null; then
        log "WARNING" "nvidia-smi not found. GPU support may not be available."
        return 1
    fi
    
    if ! nvidia-smi &> /dev/null; then
        log "WARNING" "nvidia-smi failed. GPU may not be accessible."
        return 1
    fi
    
    log "SUCCESS" "GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits
    return 0
}

check_docker() {
    log "INFO" "Checking Docker and NVIDIA Container Toolkit..."
    
    if ! command -v docker &> /dev/null; then
        log "ERROR" "Docker not found. Please install Docker first."
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        log "ERROR" "Docker daemon not running. Please start Docker."
        exit 1
    fi
    
    # Check for NVIDIA Container Toolkit
    if ! docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi &> /dev/null; then
        log "WARNING" "NVIDIA Container Toolkit not properly configured."
        log "INFO" "Please install NVIDIA Container Toolkit for GPU support."
    else
        log "SUCCESS" "Docker with GPU support is working."
    fi
}

setup_env() {
    log "INFO" "Setting up environment configuration..."
    
    if [[ ! -f "$AI_DIR/.env" ]]; then
        if [[ -f "$AI_DIR/env.template" ]]; then
            cp "$AI_DIR/env.template" "$AI_DIR/.env"
            log "SUCCESS" "Created .env file from template"
            log "WARNING" "Please edit .env file with your configuration:"
            log "INFO" "  nano $AI_DIR/.env"
        else
            log "ERROR" "env.template not found. Cannot create .env file."
            exit 1
        fi
    else
        log "INFO" ".env file already exists. Skipping creation."
    fi
}

check_network() {
    log "INFO" "Checking homelab network..."
    
    if ! docker network inspect homelab-web &> /dev/null; then
        log "WARNING" "homelab-web network not found. Creating it..."
        "$ROOT_DIR/setup-networks.sh" --network-name homelab-web --subnet 172.20.0.0/16
    else
        log "SUCCESS" "homelab-web network exists"
    fi
}

download_models() {
    log "INFO" "Downloading initial AI models..."
    
    # Start Ollama first
    log "INFO" "Starting Ollama service..."
    docker compose -f "$AI_DIR/docker-compose-homelab.yml" up -d ollama
    
    # Wait for Ollama to be ready
    log "INFO" "Waiting for Ollama to be ready..."
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if docker exec ai-ollama curl -f http://localhost:11434/api/tags &> /dev/null; then
            log "SUCCESS" "Ollama is ready"
            break
        fi
        
        log "INFO" "Waiting for Ollama... (attempt $attempt/$max_attempts)"
        sleep 10
        ((attempt++))
    done
    
    if [[ $attempt -gt $max_attempts ]]; then
        log "ERROR" "Ollama failed to start within timeout"
        return 1
    fi
    
    # Download popular models
    log "INFO" "Downloading Llama 3 8B model..."
    docker exec ai-ollama ollama pull llama3:8b || log "WARNING" "Failed to download llama3:8b"
    
    log "INFO" "Downloading Mistral 7B model..."
    docker exec ai-ollama ollama pull mistral:7b || log "WARNING" "Failed to download mistral:7b"
    
    log "INFO" "Downloading CodeLlama 7B model..."
    docker exec ai-ollama ollama pull codellama:7b || log "WARNING" "Failed to download codellama:7b"
    
    log "SUCCESS" "Model download completed"
}

start_services() {
    log "INFO" "Starting AI inference services..."
    
    # Use homelab management script
    if [[ -f "$ROOT_DIR/manage-services.sh" ]]; then
        log "INFO" "Using homelab management script..."
        "$ROOT_DIR/manage-services.sh" up --service ai-inference
    else
        log "INFO" "Using direct docker compose..."
        docker compose -f "$AI_DIR/docker-compose-homelab.yml" up -d
    fi
    
    log "SUCCESS" "AI services started"
}

check_services() {
    log "INFO" "Checking service status..."
    
    local services=("ai-ollama" "ai-openwebui" "ai-comfyui" "ai-openrouter-proxy" "ai-model-manager")
    local all_healthy=true
    
    for service in "${services[@]}"; do
        if docker ps --filter "name=$service" --filter "status=running" | grep -q "$service"; then
            log "SUCCESS" "$service is running"
        else
            log "WARNING" "$service is not running"
            all_healthy=false
        fi
    done
    
    if [[ "$all_healthy" == true ]]; then
        log "SUCCESS" "All AI services are running"
    else
        log "WARNING" "Some services may not be running. Check logs:"
        log "INFO" "  ~/manage-services.sh logs --service ai-inference"
    fi
}

show_access_info() {
    log "INFO" "AI Services Access Information:"
    echo ""
    log "INFO" "Direct Access (LAN):"
    log "INFO" "  Open WebUI:     http://192.168.50.81:8189"
    log "INFO" "  ComfyUI:        http://192.168.50.81:8188"
    log "INFO" "  Model Manager:  http://192.168.50.81:8191"
    log "INFO" "  OpenRouter:     http://192.168.50.81:8190"
    echo ""
    log "INFO" "Proxy Access (for Organizr embedding):"
    log "INFO" "  Open WebUI:     http://192.168.50.81:8161"
    log "INFO" "  ComfyUI:        http://192.168.50.81:8162"
    log "INFO" "  Model Manager:  http://192.168.50.81:8164"
    log "INFO" "  OpenRouter:     http://192.168.50.81:8163"
    echo ""
    log "INFO" "Public Access (via Cloudflare Tunnel):"
    log "INFO" "  Open WebUI:     https://chrislawrence.ca/ai"
    log "INFO" "  ComfyUI:        https://chrislawrence.ca/comfyui"
    log "INFO" "  Model Manager:  https://chrislawrence.ca/models"
    log "INFO" "  OpenRouter:     https://chrislawrence.ca/openrouter"
    echo ""
    log "INFO" "Management Commands:"
    log "INFO" "  Start:          ~/manage-services.sh up --service ai-inference"
    log "INFO" "  Stop:           ~/manage-services.sh down --service ai-inference"
    log "INFO" "  Status:         ~/manage-services.sh ps --service ai-inference"
    log "INFO" "  Logs:           ~/manage-services.sh logs --service ai-inference"
}

main() {
    local setup_env=false
    local check_gpu_flag=false
    local download_models_flag=false
    local start_services_flag=false
    local full_setup=false
    
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --setup-env) setup_env=true; shift;;
            --check-gpu) check_gpu_flag=true; shift;;
            --download-models) download_models_flag=true; shift;;
            --start-services) start_services_flag=true; shift;;
            --full-setup) full_setup=true; shift;;
            --help) usage; exit 0;;
            *) log "ERROR" "Unknown option: $1"; usage; exit 1;;
        esac
    done
    
    if [[ "$full_setup" == true ]]; then
        setup_env=true
        check_gpu_flag=true
        download_models_flag=true
        start_services_flag=true
    fi
    
    log "INFO" "AI Inference Services Setup"
    log "INFO" "============================"
    
    # Change to AI directory
    cd "$AI_DIR"
    
    # Check prerequisites
    check_docker
    check_network
    
    if [[ "$check_gpu_flag" == true ]]; then
        check_gpu
    fi
    
    if [[ "$setup_env" == true ]]; then
        setup_env
    fi
    
    if [[ "$download_models_flag" == true ]]; then
        download_models
    fi
    
    if [[ "$start_services_flag" == true ]]; then
        start_services
        sleep 10  # Give services time to start
        check_services
    fi
    
    show_access_info
    
    log "SUCCESS" "AI Inference Services setup completed!"
}

main "$@"
