#!/usr/bin/env bash
# LAN Tracker Network Sonar — Uninstall Script
# https://github.com/Mati-l33t/lan-tracker-network-sonar

set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
BLU='\033[0;34m'
msg_info()  { echo -e "${BLU}  ➤${NC}  $1"; }
msg_ok()    { echo -e "${GRN}  ✔${NC}  $1"; }
msg_error() { echo -e "${RED}  ✘  ERROR:${NC} $1"; exit 1; }

INSTALL_DIR="/opt/lan-tracker"
CONF_DIR="/etc/lan-tracker"
SERVICE_NAME="lan-tracker"
DB_NAME="lan_tracker"
DB_USER="lantracker"

[[ $EUID -ne 0 ]] && msg_error "Run as root"

echo ""
echo -e "  ${YLW}${BOLD}LAN Tracker Network Sonar — Uninstaller${NC}"
echo ""
echo -e "  ${YLW}This will completely remove LAN Tracker, its database, and all data.${NC}"
echo ""
read -rp "  Are you sure? [y/N] " confirm
[[ "$confirm" != [yY] ]] && { echo "  Cancelled."; exit 0; }
echo ""

msg_info "Stopping and disabling service..."
systemctl stop    "$SERVICE_NAME" 2>/dev/null || true
systemctl disable "$SERVICE_NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
msg_ok "Service removed"

msg_info "Removing application files ($INSTALL_DIR)..."
rm -rf "$INSTALL_DIR"
msg_ok "Files removed"

msg_info "Removing configuration ($CONF_DIR)..."
rm -rf "$CONF_DIR"
msg_ok "Config removed"

msg_info "Dropping database..."
mysql -u root 2>/dev/null <<SQL || true
DROP DATABASE IF EXISTS \`${DB_NAME}\`;
DROP USER IF EXISTS '${DB_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL
msg_ok "Database removed"

echo ""
echo -e "  ${GRN}${BOLD}LAN Tracker has been completely removed.${NC}"
echo ""
