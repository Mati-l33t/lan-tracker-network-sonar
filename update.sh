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

if [[ $EUID -ne 0 ]]; then msg_error "Run as root"; fi
if [[ ! -d "$INSTALL_DIR" ]]; then msg_error "LAN Tracker not found at $INSTALL_DIR — run install.sh first"; fi

echo ""
echo -e "  ${BOLD}LAN Tracker Network Sonar — Updater${NC}"
echo ""

OLD_VERSION=$(<"${INSTALL_DIR}/VERSION")
msg_info "Current version: v${OLD_VERSION}"

msg_info "Fetching latest code..."
git -C "$INSTALL_DIR" fetch --quiet
git -C "$INSTALL_DIR" reset --hard origin/main --quiet
msg_ok "Code updated"

msg_info "Updating Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install -q --upgrade \
  "fastapi" "uvicorn[standard]" "mysql-connector-python" "pydantic" \
  "bcrypt" "itsdangerous" "httpx" "apscheduler" "python-multipart"
msg_ok "Dependencies updated"

# Ensure auth config keys exist (upgrade from older install)
if ! grep -q "LT_SECRET_KEY" /etc/lan-tracker/lan-tracker.conf 2>/dev/null; then
  SECRET_KEY=$(openssl rand -hex 32)
  echo "LT_SECRET_KEY=${SECRET_KEY}" >> /etc/lan-tracker/lan-tracker.conf
  msg_ok "Generated LT_SECRET_KEY"
fi
grep -q "LT_AUTH_ENABLED" /etc/lan-tracker/lan-tracker.conf 2>/dev/null || \
  echo "LT_AUTH_ENABLED=true" >> /etc/lan-tracker/lan-tracker.conf
grep -q "LT_ADMIN_HASH" /etc/lan-tracker/lan-tracker.conf 2>/dev/null || \
  echo "LT_ADMIN_HASH=" >> /etc/lan-tracker/lan-tracker.conf

msg_info "Restarting service..."
systemctl restart "$SERVICE_NAME"
msg_ok "Service restarted"

NEW_VERSION=$(<"${INSTALL_DIR}/VERSION")
echo ""
echo -e "  ${GRN}${BOLD}Updated: v${OLD_VERSION} → v${NEW_VERSION}${NC}"
echo ""
