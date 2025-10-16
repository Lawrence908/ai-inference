FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv git curl ca-certificates build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# Clone ComfyUI
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI

# Create venv and install dependencies
RUN python3 -m venv /opt/venv \
    && . /opt/venv/bin/activate \
    && pip install --upgrade pip \
    && pip install --no-cache-dir -r /opt/ComfyUI/requirements.txt \
    && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu121

ENV PATH="/opt/venv/bin:${PATH}"

# Expose ComfyUI data dirs via volumes
VOLUME ["/opt/ComfyUI/models", "/opt/ComfyUI/output", "/opt/ComfyUI/user", "/opt/ComfyUI/custom_nodes"]

EXPOSE 8188

WORKDIR /opt/ComfyUI

ENTRYPOINT ["bash", "-lc"]
CMD ["python3", "main.py", "--listen", "0.0.0.0", "--port", "8188"]



