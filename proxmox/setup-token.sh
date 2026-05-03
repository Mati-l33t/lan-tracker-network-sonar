#!/usr/bin/env bash
# LAN Tracker Network Sonar — Proxmox API Token Setup
# Run on your Proxmox VE host shell:
#   bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/proxmox/setup-token.sh)
#
# Creates: monitoring@pam user, LanTrackerRole (read-only + VM power), API token
# Safe to re-run — removes and recreates the token each time.

set -euo pipefail

YW="\033[33m"; GN="\033[1;92m"; RD="\033[01;31m"; BL="\033[36m"
CM="\033[0;92m"; CL="\033[m"; BOLD="\033[1m"; TAB="  "

msg_info()  { echo -e "${TAB}${YW}  ⏳ ${1}...${CL}"; }
msg_ok()    { echo -e "${TAB}${CM}  ✔️   ${1}${CL}"; }
msg_error() { echo -e "${TAB}${RD}  ✖️   ${1}${CL}"; exit 1; }

[[ $EUID -ne 0 ]] && msg_error "Run as root on your Proxmox host"
command -v pveum >/dev/null 2>&1 || msg_error "pveum not found — run this on a Proxmox VE host"

echo ""
echo -e "${TAB}${BOLD}${BL}LAN Tracker — Proxmox API Token Setup${CL}"
echo ""

msg_info "Creating monitoring@pam user"
pveum user add monitoring@pam --comment "LAN Tracker monitoring" 2>/dev/null || true
msg_ok "User monitoring@pam ready"

msg_info "Creating LanTrackerRole"
pveum role add LanTrackerRole \
    --privs "Datastore.Audit,Sys.Audit,SDN.Audit,VM.Audit,VM.PowerMgmt" 2>/dev/null || \
pveum role modify LanTrackerRole \
    --privs "Datastore.Audit,Sys.Audit,SDN.Audit,VM.Audit,VM.PowerMgmt" 2>/dev/null || true
msg_ok "LanTrackerRole ready"

msg_info "Assigning role on /"
pveum acl modify / --user monitoring@pam --role LanTrackerRole 2>/dev/null || true
msg_ok "Role assigned"

msg_info "Creating API token"
pveum user token remove monitoring@pam lan-tracker 2>/dev/null || true
TOKEN_JSON=$(pveum user token add monitoring@pam lan-tracker \
    --comment "LAN Tracker" --privsep 0 --output-format json 2>/dev/null)
TOKEN_SECRET=$(echo "$TOKEN_JSON" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['value'])" 2>/dev/null || echo "")

[[ -z "$TOKEN_SECRET" ]] && msg_error "Failed to create token — check Proxmox logs"
msg_ok "Token created"

echo ""
echo -e "${TAB}${BOLD}${BL}┌─────────────────────────────────────────────────────────────┐${CL}"
echo -e "${TAB}${BOLD}${BL}│            API Token for LAN Tracker                        │${CL}"
echo -e "${TAB}${BOLD}${BL}├─────────────────────────────────────────────────────────────┤${CL}"
echo -e "${TAB}${BOLD}${BL}│${CL}  Token ID  :  ${GN}monitoring@pam!lan-tracker${CL}"
echo -e "${TAB}${BOLD}${BL}│${CL}  Secret    :  ${GN}${TOKEN_SECRET}${CL}"
echo -e "${TAB}${BOLD}${BL}│${CL}"
echo -e "${TAB}${BOLD}${BL}│${CL}  In LAN Tracker → Settings → Proxmox → Add Host:"
echo -e "${TAB}${BOLD}${BL}│${CL}    Host/IP      : this Proxmox node's IP or hostname"
echo -e "${TAB}${BOLD}${BL}│${CL}    Token ID     : monitoring@pam!lan-tracker"
echo -e "${TAB}${BOLD}${BL}│${CL}    Token Secret : (secret shown above)"
echo -e "${TAB}${BOLD}${BL}├─────────────────────────────────────────────────────────────┤${CL}"
echo -e "${TAB}${BOLD}${BL}│${CL}  ${RD}⚠  Save this secret — it cannot be retrieved later${CL}"
echo -e "${TAB}${BOLD}${BL}└─────────────────────────────────────────────────────────────┘${CL}"
echo ""
