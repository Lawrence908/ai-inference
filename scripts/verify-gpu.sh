#!/bin/bash
# Verify GPU is accessible to Docker containers

set -euo pipefail

echo "=== GPU Validation ==="

# Host GPU check
echo "Host NVIDIA-SMI:"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
else
  echo "nvidia-smi not found on host. Is the NVIDIA driver installed?"
fi

# Docker GPU check  
echo -e "\nDocker GPU Test:"
echo "(This will run: docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi)"
if command -v docker >/dev/null 2>&1; then
  docker run --rm --gpus all nvidia/cuda:12.2.0-base-ubuntu22.04 nvidia-smi
else
  echo "docker command not found. Install Docker to run this check."
fi

# Ollama container GPU check (if running)
if command -v docker >/dev/null 2>&1 && docker ps | grep -q ai-ollama; then
  echo -e "\nOllama Container GPU:"
  echo "(This will run inside ai-ollama: nvidia-smi, if present)"
  docker exec ai-ollama nvidia-smi 2>/dev/null || echo "nvidia-smi not in container (OK for Ollama; it still uses the GPU via the NVIDIA runtime)"
fi
