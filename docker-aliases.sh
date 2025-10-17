alias d='docker'
alias dc='docker compose'
alias dps='docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
alias dpsa='docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
alias dimg='docker images'
alias dnet='docker network ls'
alias dv='docker volume ls'

# Compose helpers (default to current directory)
alias dcup='docker compose up -d'
alias dcdown='docker compose down'
alias dcreup='docker compose up -d --build'
alias dclogs='docker compose logs -f --tail=200'
alias dctop='docker compose top'

# GPU profile helpers
alias dcgpu='docker compose --profile gpu'
alias dcupgpu='docker compose --profile gpu up -d'
alias dcreupgpu='docker compose --profile gpu up -d --build'

# Container helpers
drm() { docker rm -f "$@"; }
dexec() { docker exec -it "$1" "${@:2}"; }
dsh() { docker exec -it "$1" /bin/bash; }
dl() { docker logs -f --tail=${2:-200} "$1"; }

# Clean up dangling resources
dcprune() { docker system prune -af --volumes; }

# Show container GPU visibility
dgpu() { docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi; }

# Compose file switcher
dcf() { COMPOSE_FILE="$1" docker compose "${@:2}"; }

# Load this file: source ./docker-aliases.sh


