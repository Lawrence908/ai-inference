#!/usr/bin/env bash
set -Eeuo pipefail

# Usage:
# Full setup (recommended for first time)
# ./setup-local.sh --full-setup

# Or individual steps
# ./setup-local.sh --check-gpu          # Test GPU + Docker
# ./setup-local.sh --download-models    # Download AI models
# ./setup-local.sh --start-services     # Start all services with GPU

# AI Inference Services Setup Script
# Configures and starts the AI inference services for local WSL2 development

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_DIR="$SCRIPT_DIR"

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
    
    # Check for NVIDIA Container Toolkit with WSL2-specific test
    log "INFO" "Testing GPU access in Docker..."
    if ! docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi &> /dev/null; then
        log "WARNING" "NVIDIA Container Toolkit not properly configured for WSL2."
        log "INFO" "Please run the NVIDIA Container Toolkit setup commands:"
        log "INFO" "  sudo nvidia-ctk runtime configure --runtime=docker"
        log "INFO" "  sudo nvidia-ctk cdi generate --output=/etc/cdi"
        log "INFO" "  sudo systemctl restart docker"
        return 1
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
    log "INFO" "Checking Docker network configuration..."
    
    # For local development, we use the default Docker network
    log "SUCCESS" "Using default Docker network for local development"
}

download_models() {
    log "INFO" "Downloading initial AI models..."
    
    # Start Ollama first
    log "INFO" "Starting Ollama service..."
    docker compose -f "$AI_DIR/docker-compose.yml" --profile gpu up -d ollama
    
    # Wait for Ollama to be ready
    log "INFO" "Waiting for Ollama to be ready..."
    local max_attempts=30
    local attempt=1
    
    while [[ $attempt -le $max_attempts ]]; do
        if curl -f http://localhost:7114/api/tags &> /dev/null; then
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
    
    # Use local docker compose with GPU profile
    log "INFO" "Starting services with GPU support..."
    docker compose -f "$AI_DIR/docker-compose.yml" --profile gpu up -d
    
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
        log "INFO" "  docker compose logs -f"
    fi
}

show_access_info() {
    log "INFO" "AI Services Access Information:"
    echo ""
    log "INFO" "Local Development Access:"
    log "INFO" "  Open WebUI:     http://localhost:7189"
    log "INFO" "  ComfyUI:        http://localhost:7188"
    log "INFO" "  Model Manager:  http://localhost:7191"
    log "INFO" "  OpenRouter:     http://localhost:7190"
    log "INFO" "  Ollama API:     http://localhost:7114"
    echo ""
    log "INFO" "Management Commands:"
    log "INFO" "  Start:          docker compose --profile gpu up -d"
    log "INFO" "  Stop:           docker compose down"
    log "INFO" "  Rebuild:        docker compose --profile gpu up -d --build"
    log "INFO" "  Status:         docker compose ps"
    log "INFO" "  Logs:           docker compose logs -f"
    echo ""
    log "INFO" "Useful Aliases (source ./docker-aliases.sh):"
    log "INFO" "  dcupgpu         - Start with GPU"
    log "INFO" "  dcreupgpu      - Rebuild and start with GPU"
    log "INFO" "  dclogs         - View logs"
    log "INFO" "  dgpu           - Test GPU in Docker"
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
