#!/usr/bin/env bash
# LAN Tracker Network Sonar — Update Script
# https://github.com/Mati-l33t/lan-tracker-network-sonar

set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; BLU='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
msg_info()  { echo -e "${BLU}  ➤${NC}  $1"; }
msg_ok()    { echo -e "${GRN}  ✔${NC}  $1"; }
msg_error() { echo -e "${RED}  ✘  ERROR:${NC} $1"; exit 1; }

INSTALL_DIR="/opt/lan-tracker"
SERVICE_NAME="lan-tracker"

[[ $EUID -ne 0 ]]         && msg_error "Run as root"
[[ ! -d "$INSTALL_DIR" ]] && msg_error "LAN Tracker not found at $INSTALL_DIR — run install.sh first"

echo ""
echo -e "  ${BOLD}LAN Tracker Network Sonar — Updater${NC}"
echo ""

OLD_VERSION=$(<"${INSTALL_DIR}/VERSION")
msg_info "Current version: v${OLD_VERSION}"

msg_info "Pulling latest code..."
git -C "$INSTALL_DIR" pull --quiet
msg_ok "Code updated"

msg_info "Updating Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade \
  "fastapi" "uvicorn[standard]" "mysql-connector-python" "pydantic"
msg_ok "Dependencies updated"

msg_info "Restarting service..."
systemctl restart "$SERVICE_NAME"
msg_ok "Service restarted"

NEW_VERSION=$(<"${INSTALL_DIR}/VERSION")
echo ""
echo -e "  ${GRN}${BOLD}Updated: v${OLD_VERSION} → v${NEW_VERSION}${NC}"
echo ""
