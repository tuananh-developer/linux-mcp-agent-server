#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="/opt/linux-mcp-agent-server"
CONFIG_DIR="/etc/linux-mcp-agent"
SERVICE_USER="linux-mcp-agent"
PYTHON_VERSION="3.15.2"
UV_VERSION="0.13.6"
COMPOSE_FILE="$INSTALL_DIR/deploy/compose/compose.yaml"
COMPOSE_ENV="$CONFIG_DIR/compose.env"
SERVER_ENV="$CONFIG_DIR/server.env"
REALM_TEMPLATE="$INSTALL_DIR/deploy/keycloak/realm-linux-agent.example.json"
REALM_RENDERED="/run/linux-mcp-agent-realm.json"
USER_RENDERED="/run/linux-mcp-agent-user.json"
PASSWORD_RENDERED="/run/linux-mcp-agent-password.json"
MARKER="$CONFIG_DIR/install.conf"
RESUME=false
REUSE_EXISTING_SECRETS=false
MCP_DOMAIN="mcp.home.arpa"
AUTH_DOMAIN="auth.home.arpa"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
cleanup() {
  rm -f "$REALM_RENDERED" "$USER_RENDERED" "$PASSWORD_RENDERED"
  if [[ -n "${KEYCLOAK_ID:-}" ]]; then
    docker exec --user 0 "$KEYCLOAK_ID" rm -f \
      /tmp/linux-agent-realm.json /tmp/linux-agent-user.json /tmp/linux-agent-password.json \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ "$EUID" -ne 0 ]]; then
  command -v sudo >/dev/null 2>&1 || die "Run this installer as root or install sudo first."
  sudo -v
  exec sudo -E bash "$0" "$@"
fi

ROOT="$(pwd -P)"
[[ -f "$ROOT/pyproject.toml" && -f "$ROOT/deploy/compose/compose.yaml" && -f "$ROOT/scripts/install.sh" ]] ||
  die "Run this script from the root of a clone of linux-mcp-agent-server."

if (( $# > 1 )); then die "Usage: sudo bash scripts/install.sh [--resume]"; fi
if (( $# == 1 )); then
  case "$1" in
    --resume) RESUME=true ;;
    --help|-h)
      cat <<'HELP'
Linux Observatory one-command installer

Usage:
  cd linux-mcp-agent-server
  sudo bash scripts/install.sh

Supported target: Ubuntu 24.04 LTS (amd64 or arm64).
Creates Docker infrastructure, Keycloak realm and first login, encrypted
provider vault, and a native systemd MCP service. Existing data is not replaced.
Use scripts/upgrade.sh for updates and scripts/uninstall.sh for removal.
If an installation stops part-way through, rerun with --resume. Existing secrets
and data will be reused; do not delete the installation directories by hand.
HELP
      exit 0
      ;;
    *) die "Unknown option: $1. Use --help." ;;
  esac
fi

if [[ "$RESUME" == "true" ]]; then
  [[ ! -f "$MARKER" ]] || die "Installation is already complete. Use scripts/upgrade.sh instead."
  if [[ -f "$COMPOSE_ENV" && -f "$SERVER_ENV" && -f "$CONFIG_DIR/agent-client.env" ]]; then
    # These files are created by this installer and protected by root-only permissions.
    source "$COMPOSE_ENV"
    source "$SERVER_ENV"
    source "$CONFIG_DIR/agent-client.env"
    MCP_DOMAIN="${MCP_DOMAIN:?Missing MCP_DOMAIN in compose config}"
    AUTH_DOMAIN="${AUTH_DOMAIN:?Missing AUTH_DOMAIN in compose config}"
    RESOURCE_SERVER_SECRET="${MCP_INTROSPECTION_CLIENT_SECRET:?Missing introspection secret}"
    AGENT_CLIENT_SECRET="${MCP_AGENT_CLIENT_SECRET:?Missing agent client secret}"
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?Missing database secret}"
    KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:?Missing Keycloak admin secret}"
    REUSE_EXISTING_SECRETS=true
    log "Resuming the existing installation without replacing secrets or data"
  elif [[ -e "$COMPOSE_ENV" || -e "$SERVER_ENV" || -e "$CONFIG_DIR/agent-client.env" ]]; then
    die "Partial secret files were found. Refusing to regenerate or overwrite them; inspect $CONFIG_DIR."
  else
    log "Resuming before secrets were generated; continuing first-time setup"
  fi
else
  [[ ! -f "$MARKER" ]] || die "Already installed. Use: sudo bash scripts/upgrade.sh"
  [[ ! -e "$INSTALL_DIR" ]] || die "$INSTALL_DIR exists but is not marked as this install; inspect it or use --resume."
  [[ ! -e "$CONFIG_DIR/server.env" && ! -e "$CONFIG_DIR/compose.env" ]] ||
    die "$CONFIG_DIR already contains configuration. Refusing to overwrite existing settings or secrets."
fi

[[ -r /etc/os-release ]] || die "Cannot identify Linux distribution."
# shellcheck disable=SC1091
source /etc/os-release
[[ "$ID" == "ubuntu" && "$VERSION_ID" == "24.04" ]] ||
  die "Only Ubuntu 24.04 LTS is supported (detected $PRETTY_NAME)."
ARCH="$(dpkg --print-architecture)"
[[ "$ARCH" == "amd64" || "$ARCH" == "arm64" ]] ||
  die "Unsupported architecture: $ARCH (supported: amd64, arm64)."
[[ -t 0 ]] || die "Run in an interactive terminal to set the first dashboard user's password."

if [[ "$REUSE_EXISTING_SECRETS" == "false" ]]; then
  log "Using the project's standard hostnames"
  printf 'Dashboard: https://%s\nAuthentication: https://%s\n' "$MCP_DOMAIN" "$AUTH_DOMAIN"
fi

LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
if [[ -z "$LAN_IP" ]]; then LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; fi
read -r -p "IPv4 address for LAN access [$LAN_IP]: " input
[[ -n "$input" ]] && LAN_IP="$input"
python3 - "$LAN_IP" <<'PY' || die "Enter a valid IPv4 address."
import ipaddress, sys
try:
    ipaddress.IPv4Address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
PY

read -r -p "First dashboard username [operator]: " FIRST_USER
[[ -n "$FIRST_USER" ]] || FIRST_USER="operator"
[[ "$FIRST_USER" =~ ^[A-Za-z0-9._-]{3,64}$ ]] ||
  die "Username must be 3-64 letters, digits, dots, underscores or hyphens."
read -r -p "First dashboard user's email (optional): " FIRST_EMAIL
if [[ -n "$FIRST_EMAIL" && ! "$FIRST_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  die "Email address is not valid."
fi
while true; do
  read -r -s -p "Password for $FIRST_USER (at least 12 characters): " FIRST_PASSWORD
  printf '\n'
  read -r -s -p "Confirm password: " FIRST_PASSWORD_CONFIRM
  printf '\n'
  [[ "$FIRST_PASSWORD" == "$FIRST_PASSWORD_CONFIRM" ]] || { warn "Passwords do not match."; continue; }
  PASSWORD_LENGTH="$(printf '%s' "$FIRST_PASSWORD" | wc -c)"
  (( PASSWORD_LENGTH >= 12 )) || { warn "Password must contain at least 12 characters."; continue; }
  break
done

log "Installing base dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl openssl rsync python3 iproute2

install_docker_repository() {
  install -m 0755 -d /etc/apt/keyrings
  if [[ ! -s /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
  fi
  CODENAME="$VERSION_CODENAME"
  if [[ -n "$UBUNTU_CODENAME" ]]; then CODENAME="$UBUNTU_CODENAME"; fi
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $CODENAME
Components: stable
Architectures: $ARCH
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
}

if ! docker compose version >/dev/null 2>&1; then
  for package in docker.io docker-compose docker-compose-v2 podman-docker; do
    if dpkg -s "$package" 2>/dev/null | grep -q '^Status: install ok installed$'; then
      die "Found legacy/conflicting package '$package'. Review Docker's migration instructions first; this installer will not remove existing container packages or data."
    fi
  done
  log "Installing Docker Engine and Compose from Docker's official Ubuntu repository"
  install_docker_repository
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."
docker info >/dev/null 2>&1 || die "Docker daemon is not ready."

log "Installing pinned uv"
if ! command -v uv >/dev/null 2>&1 || [[ "$(uv --version | awk '{print $2}')" != "$UV_VERSION" ]]; then
  curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" |
    env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
UV_BIN="$(command -v uv || true)"
[[ -x "$UV_BIN" ]] || UV_BIN="/usr/local/bin/uv"
[[ -x "$UV_BIN" && "$("$UV_BIN" --version | awk '{print $2}')" == "$UV_VERSION" ]] ||
  die "Could not install uv $UV_VERSION."

log "Creating service user and protected directories"
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/linux-mcp-agent --create-home --shell /usr/sbin/nologin "$SERVICE_USER"
fi
usermod -aG systemd-journal "$SERVICE_USER"
install -d -o root -g root -m 0755 "$INSTALL_DIR"
install -d -o root -g "$SERVICE_USER" -m 0750 "$CONFIG_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 /var/lib/linux-mcp-agent
install -d -o root -g root -m 0755 /var/cache/linux-mcp-agent/uv

log "Copying application files"
rsync -a \
  --exclude='/.git/' --exclude='/.venv/' --exclude='/.uv-python/' \
  --exclude='/.pytest_cache/' --exclude='/.ruff_cache/' \
  --exclude='/.env' --exclude='/deploy/compose/.env' --exclude='__pycache__/' \
  "$ROOT/" "$INSTALL_DIR/"
chown -R root:root "$INSTALL_DIR"

if [[ "$REUSE_EXISTING_SECRETS" == "false" ]]; then
  log "Generating installation secrets"
  POSTGRES_PASSWORD="$(openssl rand -hex 32)"
  KEYCLOAK_ADMIN_PASSWORD="$(openssl rand -hex 32)"
  RESOURCE_SERVER_SECRET="$(openssl rand -hex 32)"
  AGENT_CLIENT_SECRET="$(openssl rand -hex 32)"
  MCP_RESOURCE_URI="https://$MCP_DOMAIN/mcp"
  KEYCLOAK_ISSUER_URL="https://$AUTH_DOMAIN/realms/linux-agent"

  umask 077
  cat > "$COMPOSE_ENV" <<EOF
MCP_DOMAIN=$MCP_DOMAIN
AUTH_DOMAIN=$AUTH_DOMAIN
POSTGRES_DB=keycloak
POSTGRES_USER=keycloak
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=$KEYCLOAK_ADMIN_PASSWORD
EOF
  chown root:root "$COMPOSE_ENV"
  chmod 0600 "$COMPOSE_ENV"

  cat > "$SERVER_ENV" <<EOF
APP_ENV=production
AUTH_MODE=keycloak
MCP_HOST=127.0.0.1
MCP_PORT=3002
MCP_PUBLIC_URL=$MCP_RESOURCE_URI
MCP_ALLOWED_HOSTS=127.0.0.1:3002,localhost:3002,$MCP_DOMAIN,$MCP_DOMAIN:443
MCP_ALLOWED_ORIGINS=
KEYCLOAK_ISSUER_URL=$KEYCLOAK_ISSUER_URL
MCP_INTROSPECTION_URL=http://127.0.0.1:8080/realms/linux-agent/protocol/openid-connect/token/introspect
MCP_RESOURCE_URI=$MCP_RESOURCE_URI
MCP_REQUIRED_AUDIENCE=$MCP_RESOURCE_URI
MCP_INTROSPECTION_CLIENT_ID=linux-mcp-resource-server
MCP_INTROSPECTION_CLIENT_SECRET=$RESOURCE_SERVER_SECRET
MCP_REQUIRED_SCOPE=mcp.read
MCP_LOGS_SCOPE=mcp.logs.read
ALLOWED_DISK_PATHS=/,/home
LOG_SOURCES_FILE=$CONFIG_DIR/log-sources.json
JOURNALCTL_PATH=/usr/bin/journalctl
JOURNALCTL_TIMEOUT_SECONDS=1.5
MAX_LOG_OUTPUT_BYTES=65536
LOG_LEVEL=INFO
MCP_INTROSPECTION_CACHE_TTL_SECONDS=30.0
ALLOWED_SYSTEMD_UNITS=ssh.service,cron.service,systemd-timesyncd.service
SYSTEMCTL_PATH=/usr/bin/systemctl
CPU_WARNING_THRESHOLD_PERCENT=85
MEMORY_WARNING_THRESHOLD_PERCENT=90
DISK_WARNING_THRESHOLD_PERCENT=85
AGENT_ENABLED=true
AGENT_PROVIDER=openai
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:4b
OLLAMA_CONTEXT_LENGTH=4096
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-luna
OPENAI_MAX_OUTPUT_TOKENS=1024
EOF
  chown root:"$SERVICE_USER" "$SERVER_ENV"
  chmod 0640 "$SERVER_ENV"

  cat > "$CONFIG_DIR/agent-client.env" <<EOF
MCP_AGENT_CLIENT_ID=linux-mcp-agent-client
MCP_AGENT_CLIENT_SECRET=$AGENT_CLIENT_SECRET
MCP_AGENT_RESOURCE_URI=$MCP_RESOURCE_URI
EOF
  chown root:root "$CONFIG_DIR/agent-client.env"
  chmod 0600 "$CONFIG_DIR/agent-client.env"
fi

if [[ ! -f "$CONFIG_DIR/log-sources.json" ]]; then
  install -o root -g "$SERVICE_USER" -m 0640 \
    "$INSTALL_DIR/config/log-sources.example.json" "$CONFIG_DIR/log-sources.json"
fi

log "Installing Python $PYTHON_VERSION and project dependencies"
export UV_PYTHON_INSTALL_DIR="$INSTALL_DIR/.uv-python"
export UV_CACHE_DIR="/var/cache/linux-mcp-agent/uv"
"$UV_BIN" sync --project "$INSTALL_DIR" --python "$PYTHON_VERSION" --no-dev
test -x "$INSTALL_DIR/.venv/bin/python" || die "Python environment was not created."

log "Initializing encrypted provider credential vault"
bash "$INSTALL_DIR/scripts/init-provider-vault-key.sh"

log "Starting PostgreSQL and Keycloak"
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" config --quiet
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" up -d postgres keycloak
KEYCLOAK_ID="$(docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" ps -q keycloak)"
[[ -n "$KEYCLOAK_ID" ]] || die "Keycloak container was not created."
printf 'Waiting for Keycloak health check'
HEALTH=""
for _ in $(seq 1 120); do
  HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$KEYCLOAK_ID" 2>/dev/null || true)"
  if [[ "$HEALTH" == "healthy" ]]; then printf ' ready\n'; break; fi
  if [[ "$HEALTH" == "unhealthy" || "$HEALTH" == "exited" || "$HEALTH" == "dead" ]]; then
    printf '\n'
    docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" logs --tail=80 keycloak >&2
    die "Keycloak failed health checks."
  fi
  printf '.'
  sleep 2
done
[[ "$HEALTH" == "healthy" ]] || die "Timed out waiting for Keycloak."

log "Creating Keycloak realm, clients and initial dashboard user"
MCP_DOMAIN="$MCP_DOMAIN" AUTH_DOMAIN="$AUTH_DOMAIN" \
RESOURCE_SERVER_SECRET="$RESOURCE_SERVER_SECRET" AGENT_CLIENT_SECRET="$AGENT_CLIENT_SECRET" \
INITIAL_ADMIN_USERNAME="$FIRST_USER" INITIAL_ADMIN_PASSWORD="$FIRST_PASSWORD" \
INITIAL_ADMIN_EMAIL="$FIRST_EMAIL" \
python3 "$INSTALL_DIR/scripts/render-keycloak-realm.py" \
  --template "$REALM_TEMPLATE" --output "$REALM_RENDERED" \
  --user-output "$USER_RENDERED" --credential-output "$PASSWORD_RENDERED"
docker cp "$REALM_RENDERED" "$KEYCLOAK_ID:/tmp/linux-agent-realm.json"
docker cp "$USER_RENDERED" "$KEYCLOAK_ID:/tmp/linux-agent-user.json"
docker cp "$PASSWORD_RENDERED" "$KEYCLOAK_ID:/tmp/linux-agent-password.json"
docker exec --user 0 "$KEYCLOAK_ID" chown 1000:0 \
  /tmp/linux-agent-realm.json /tmp/linux-agent-user.json /tmp/linux-agent-password.json
docker exec --user 0 "$KEYCLOAK_ID" chmod 0600 \
  /tmp/linux-agent-realm.json /tmp/linux-agent-user.json /tmp/linux-agent-password.json
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" exec -T \
  -e INSTALL_FIRST_USER="$FIRST_USER" keycloak /bin/bash -s <<'IN_CONTAINER'
set -Eeuo pipefail
KCADM=/opt/keycloak/bin/kcadm.sh
trap 'rm -f /tmp/linux-agent-realm.json /tmp/linux-agent-user.json /tmp/linux-agent-password.json' EXIT
"$KCADM" config credentials --server http://127.0.0.1:8080 --realm master \
  --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null
if "$KCADM" get realms/linux-agent >/dev/null 2>&1; then
  echo "Realm linux-agent already exists; preserving its users, clients and settings."
else
  "$KCADM" create realms -f /tmp/linux-agent-realm.json
  echo "Created realm linux-agent."
fi
USER_ID="$("$KCADM" get users -r linux-agent -q "username=$INSTALL_FIRST_USER" --fields id --format csv --noquotes | tail -n 1 | tr -d '\r')"
if [[ -z "$USER_ID" ]]; then
  "$KCADM" create users -r linux-agent -f /tmp/linux-agent-user.json >/dev/null
  USER_ID="$("$KCADM" get users -r linux-agent -q "username=$INSTALL_FIRST_USER" --fields id --format csv --noquotes | tail -n 1 | tr -d '\r')"
fi
[[ -n "$USER_ID" ]] || { echo "Initial Keycloak user was not created." >&2; exit 1; }
"$KCADM" update "users/$USER_ID/reset-password" -r linux-agent -f /tmp/linux-agent-password.json -n
echo "Initial dashboard account is ready."
IN_CONTAINER
rm -f "$REALM_RENDERED" "$USER_RENDERED" "$PASSWORD_RENDERED"

log "Configuring and validating the browser OAuth client"
MCP_DOMAIN="$MCP_DOMAIN" MCP_RESOURCE_URI="$MCP_RESOURCE_URI" \
LINUX_MCP_COMPOSE_ENV_FILE="$COMPOSE_ENV" \
bash "$INSTALL_DIR/scripts/configure-browser-client.sh"

log "Installing and enabling native MCP systemd service"
install -o root -g root -m 0644 "$INSTALL_DIR/deploy/systemd/linux-mcp-agent.service" \
  /etc/systemd/system/linux-mcp-agent.service
systemctl daemon-reload
systemctl enable --now linux-mcp-agent.service

printf 'Waiting for MCP health check'
MCP_READY=false
for _ in $(seq 1 30); do
  if curl --silent --show-error --fail --max-time 2 http://127.0.0.1:3002/healthz >/dev/null 2>&1; then
    MCP_READY=true
    break
  fi
  printf '.'
  sleep 1
done
printf '\n'
if [[ "$MCP_READY" != "true" ]]; then
  systemctl status linux-mcp-agent.service --no-pager -l >&2 || true
  journalctl -u linux-mcp-agent.service -n 80 --no-pager >&2 || true
  die "MCP service did not become healthy."
fi

log "Starting Caddy HTTPS reverse proxy"
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" --profile lan up -d caddy
CA_TEMP="/run/linux-observatory-root.crt"
docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" --profile lan \
  exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > "$CA_TEMP"
grep -q "BEGIN CERTIFICATE" "$CA_TEMP" || die "Could not export Caddy's local root CA."
install -o root -g root -m 0644 "$CA_TEMP" "$CONFIG_DIR/caddy-root.crt"
install -o root -g root -m 0644 "$CA_TEMP" \
  /usr/local/share/ca-certificates/linux-observatory-root.crt
rm -f "$CA_TEMP"
update-ca-certificates >/dev/null

log "Adding dashboard hostnames to this machine's hosts file"
HOSTS_TEMP="$(mktemp)"
awk '
  $0 == "# BEGIN LINUX OBSERVATORY MANAGED HOSTS" { skip=1; next }
  $0 == "# END LINUX OBSERVATORY MANAGED HOSTS" { skip=0; next }
  !skip { print }
' /etc/hosts > "$HOSTS_TEMP"
{
  printf '%s\n' "# BEGIN LINUX OBSERVATORY MANAGED HOSTS"
  printf '%s %s %s\n' "$LAN_IP" "$MCP_DOMAIN" "$AUTH_DOMAIN"
  printf '%s\n' "# END LINUX OBSERVATORY MANAGED HOSTS"
} >> "$HOSTS_TEMP"
install -o root -g root -m 0644 "$HOSTS_TEMP" /etc/hosts
rm -f "$HOSTS_TEMP"

cat > "$MARKER" <<EOF
INSTALL_DIR=$INSTALL_DIR
MCP_DOMAIN=$MCP_DOMAIN
AUTH_DOMAIN=$AUTH_DOMAIN
LAN_IP=$LAN_IP
INSTALL_VERSION=1
EOF
chown root:root "$MARKER"
chmod 0600 "$MARKER"

log "Running final health checks"
curl --silent --show-error --fail --max-time 5 \
  --cacert "$CONFIG_DIR/caddy-root.crt" \
  --resolve "$MCP_DOMAIN:443:127.0.0.1" \
  "https://$MCP_DOMAIN/healthz" >/dev/null ||
  die "HTTPS health check failed. Inspect Caddy logs and journalctl -u linux-mcp-agent."

docker compose --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" ps
systemctl --no-pager --full status linux-mcp-agent.service | sed -n '1,12p'

printf '\n\033[1;32mLinux Observatory installation completed.\033[0m\n'
printf 'Dashboard:       https://%s/dashboard\n' "$MCP_DOMAIN"
printf 'AI Assistant:    https://%s/assistant\n' "$MCP_DOMAIN"
printf 'First user:      %s\n' "$FIRST_USER"
printf 'MCP endpoint:    https://%s/mcp\n' "$MCP_DOMAIN"
printf 'LAN IP:          %s\n' "$LAN_IP"
printf 'Agent client:    %s/agent-client.env (root-only)\n' "$CONFIG_DIR"
printf 'TLS root CA:     %s/caddy-root.crt\n' "$CONFIG_DIR"
printf 'Keycloak admin:  %s/compose.env (root-only)\n' "$CONFIG_DIR"
printf '\nOther LAN devices must resolve %s and %s to %s and trust the Caddy root CA.\n' "$MCP_DOMAIN" "$AUTH_DOMAIN" "$LAN_IP"
printf 'Upgrade:         sudo bash scripts/upgrade.sh (from a fresh repository clone)\n'
printf 'Diagnostics:     sudo bash scripts/doctor.sh\n'
printf 'Uninstall:       sudo bash scripts/uninstall.sh (preserves data by default)\n'
printf '\nSign in and save provider API keys from the Dashboard. No vault key needs to be copied manually.\n'
