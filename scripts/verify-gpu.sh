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

# Per-container GPU check for the daedalus GPU workloads that share the RTX 3080.
# These are the fallback nodes behind ollama-gateway (:11440) and comfyui-gateway (:8189);
# the primaries live on Apollo (192.168.50.30) and are not checked from here.
if command -v docker >/dev/null 2>&1; then
  for c in zeus-ollama zeus-comfyui; do
    if docker ps --format '{{.Names}}' | grep -qx "$c"; then
      echo -e "\n$c container GPU:"
      docker exec "$c" nvidia-smi 2>/dev/null \
        || echo "nvidia-smi not in container (OK; it can still use the GPU via the NVIDIA runtime)"
    else
      echo -e "\n$c is not running, skipping."
    fi
  done
fi
