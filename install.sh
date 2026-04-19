#!/usr/bin/env bash
# LAN Tracker Network Sonar — Install Script
# https://github.com/Mati-l33t/lan-tracker-network-sonar

set -e
exec 2>&1   # merge stderr into stdout so errors are always visible

export DEBIAN_FRONTEND=noninteractive

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'
BLU='\033[0;34m'; CYN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

# ── Constants ──────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/Mati-l33t/lan-tracker-network-sonar"
INSTALL_DIR="/opt/lan-tracker"
CONF_DIR="/etc/lan-tracker"
CONF_FILE="${CONF_DIR}/lan-tracker.conf"
SERVICE_NAME="lan-tracker"
DB_NAME="lan_tracker"
DB_USER="lantracker"
APP_PORT="8080"

# ── Helpers ────────────────────────────────────────────────────────────────────
msg_info()  { echo -e "${BLU}  ➤${NC}  $1"; }
msg_ok()    { echo -e "${GRN}  ✔${NC}  $1"; }
msg_warn()  { echo -e "${YLW}  ⚠${NC}  $1"; }
msg_error() { echo -e "${RED}  ✘  ERROR:${NC} $1"; exit 1; }

header() {
  echo -e "${CYN}${BOLD}"
  echo "  ██╗      █████╗ ███╗   ██╗    ████████╗██████╗  █████╗  ██████╗██╗  ██╗███████╗██████╗ "
  echo "  ██║     ██╔══██╗████╗  ██║    ╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗"
  echo "  ██║     ███████║██╔██╗ ██║       ██║   ██████╔╝███████║██║     █████╔╝ █████╗  ██████╔╝"
  echo "  ██║     ██╔══██║██║╚██╗██║       ██║   ██╔══██╗██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗"
  echo "  ███████╗██║  ██║██║ ╚████║       ██║   ██║  ██║██║  ██║╚██████╗██║  ██╗███████╗██║  ██║"
  echo "  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝       ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝"
  echo -e "${NC}"
  echo -e "  ${BOLD}Network Sonar${NC}  ·  ${BLU}${REPO_URL}${NC}"
  echo ""
}

check_root() {
  if [[ $EUID -ne 0 ]]; then
    msg_error "Run this script as root (sudo or root shell)"
  fi
}

check_os() {
  if [[ ! -f /etc/os-release ]]; then
    msg_error "Cannot detect OS"
  fi
  # shellcheck source=/dev/null
  source /etc/os-release
  case "$ID" in
    debian|ubuntu) msg_ok "Detected: $PRETTY_NAME" ;;
    *) msg_error "Unsupported OS '$PRETTY_NAME' — Debian or Ubuntu required" ;;
  esac
}

gen_password() {
  tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 28 || true
}

install_deps() {
  msg_info "Updating package list..."
  apt-get update -qq
  msg_info "Installing dependencies (mariadb, arp-scan, python3, git)..."
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl mariadb-server arp-scan \
    python3 python3-pip python3-venv \
    net-tools iproute2
  msg_ok "Dependencies installed"
}

setup_db() {
  local db_pass="$1"
  msg_info "Starting MariaDB..."
  systemctl enable --now mariadb &>/dev/null
  msg_info "Creating database and user..."
  mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS \`${DB_NAME}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${DB_USER}'@'localhost' IDENTIFIED BY '${db_pass}';
GRANT ALL PRIVILEGES ON \`${DB_NAME}\`.* TO '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL
  msg_ok "Database ready"
}

install_app() {
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    msg_warn "Existing install found — pulling latest code"
    git -C "$INSTALL_DIR" pull --quiet
  else
    msg_info "Cloning repository..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
  fi

  msg_info "Creating Python virtual environment..."
  python3 -m venv "$INSTALL_DIR/venv"
  "$INSTALL_DIR/venv/bin/pip" install -q --upgrade pip
  "$INSTALL_DIR/venv/bin/pip" install -q \
    "fastapi" "uvicorn[standard]" "mysql-connector-python" "pydantic"
  msg_ok "Application installed at $INSTALL_DIR"
}

write_conf() {
  local db_pass="$1"
  mkdir -p "$CONF_DIR"
  cat > "$CONF_FILE" <<EOF
LT_DB_HOST=localhost
LT_DB_NAME=${DB_NAME}
LT_DB_USER=${DB_USER}
LT_DB_PASS=${db_pass}
LT_PORT=${APP_PORT}
EOF
  chmod 600 "$CONF_FILE"
  msg_ok "Config written to $CONF_FILE"
}

write_service() {
  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=LAN Tracker Network Sonar
Documentation=${REPO_URL}
After=network.target mariadb.service
Requires=mariadb.service

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}/app
EnvironmentFile=${CONF_FILE}
ExecStart=${INSTALL_DIR}/venv/bin/uvicorn app:app --host 0.0.0.0 --port \${LT_PORT}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --quiet "$SERVICE_NAME"
  systemctl restart "$SERVICE_NAME"
  msg_ok "Service enabled and started"
}

get_ip() {
  hostname -I 2>/dev/null | awk '{print $1}'
}

# ── Main ───────────────────────────────────────────────────────────────────────
header
check_root
check_os

DB_PASS=$(gen_password)

install_deps
setup_db  "$DB_PASS"
install_app
write_conf "$DB_PASS"
write_service

IP=$(get_ip)
VERSION=$(<"${INSTALL_DIR}/VERSION")

echo ""
echo -e "  ${GRN}${BOLD}Installation complete! (v${VERSION})${NC}"
echo ""
echo -e "  ${BOLD}Web UI:${NC}  http://${IP}:${APP_PORT}"
echo -e "  ${BOLD}Config:${NC}  ${CONF_FILE}"
echo -e "  ${BOLD}Logs:${NC}    journalctl -u ${SERVICE_NAME} -f"
echo ""
echo -e "  Update:     bash <(curl -fsSL ${REPO_URL}/raw/main/update.sh)"
echo -e "  Uninstall:  bash <(curl -fsSL ${REPO_URL}/raw/main/uninstall.sh)"
echo ""
