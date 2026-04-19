#!/usr/bin/env bash
# LAN Tracker Network Sonar — Proxmox LXC Installer
# https://github.com/Mati-l33t/lan-tracker-network-sonar
#
# Run on your Proxmox VE host:
#   bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/proxmox/install.sh)

set -euo pipefail

# ── Colours ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'
BLU='\033[0;34m'; CYN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

REPO_URL="https://github.com/Mati-l33t/lan-tracker-network-sonar"
RAW_URL="https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main"

# ── Helpers ────────────────────────────────────────────────────────────────────
msg_info()  { printf "  ${BLU}➤${NC}  %-50s" "$1"; }
msg_ok()    { echo -e "${GRN}Done${NC}"; }
msg_done()  { echo -e "  ${GRN}✔${NC}  $1"; }
msg_warn()  { echo -e "  ${YLW}⚠${NC}  $1"; }
msg_error() { echo -e "\n  ${RED}✘  ERROR:${NC} $1\n"; exit 1; }

header() {
  clear
  echo -e "${CYN}${BOLD}"
  echo "  ██╗      █████╗ ███╗   ██╗    ████████╗██████╗  █████╗  ██████╗██╗  ██╗███████╗██████╗ "
  echo "  ██║     ██╔══██╗████╗  ██║    ╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗"
  echo "  ██║     ███████║██╔██╗ ██║       ██║   ██████╔╝███████║██║     █████╔╝ █████╗  ██████╔╝"
  echo "  ██║     ██╔══██║██║╚██╗██║       ██║   ██╔══██╗██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗"
  echo "  ███████╗██║  ██║██║ ╚████║       ██║   ██║  ██║██║  ██║╚██████╗██║  ██╗███████╗██║  ██║"
  echo "  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝       ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝"
  echo -e "${NC}"
  echo -e "  ${BOLD}Network Sonar${NC}  ·  Proxmox LXC Installer  ·  ${BLU}${REPO_URL}${NC}"
  echo -e "  ${YLW}This will create a Debian LXC container and install LAN Tracker inside it.${NC}"
  echo ""
}

check_proxmox() {
  command -v pveversion &>/dev/null || msg_error "This script must run on a Proxmox VE host"
  command -v pct         &>/dev/null || msg_error "pct not found — is this Proxmox VE?"
  msg_done "Proxmox VE: $(pveversion | head -1)"
}

check_root() {
  [[ $EUID -ne 0 ]] && msg_error "Run as root on the Proxmox host"
}

# ── Template handling ──────────────────────────────────────────────────────────
get_template() {
  local TEMPLATE_STORAGE="local"

  # Check for already-downloaded debian-13 template
  local existing
  existing=$(pveam list "$TEMPLATE_STORAGE" 2>/dev/null \
    | awk '{print $1}' | grep "debian-13" | sort -V | tail -1 || true)

  if [[ -n "$existing" ]]; then
    msg_done "Template found: $existing"
    TEMPLATE_PATH="$existing"
    return
  fi

  # Try downloading from pveam
  msg_info "Updating template list..."
  pveam update &>/dev/null; msg_ok

  local avail
  avail=$(pveam available --section system 2>/dev/null \
    | awk '{print $2}' | grep "^debian-13" | sort -V | tail -1 || true)

  if [[ -z "$avail" ]]; then
    # Fallback: try debian-12 if 13 not yet in list
    msg_warn "Debian 13 template not found in pveam — trying Debian 12 as fallback"
    avail=$(pveam available --section system 2>/dev/null \
      | awk '{print $2}' | grep "^debian-12" | sort -V | tail -1 || true)
    [[ -z "$avail" ]] && msg_error "No Debian template available — check Proxmox template repositories"
    msg_warn "Using: $avail"
  fi

  msg_info "Downloading $avail..."
  pveam download "$TEMPLATE_STORAGE" "$avail" &>/dev/null; msg_ok
  TEMPLATE_PATH="${TEMPLATE_STORAGE}:vztmpl/${avail}"
}

# ── Install modes ──────────────────────────────────────────────────────────────
default_mode() {
  CTID=$(pvesh get /cluster/nextid 2>/dev/null || echo "200")
  CT_HOSTNAME="lan-tracker"
  CT_CORES=1
  CT_RAM=512
  CT_DISK=4
  CT_BRIDGE="vmbr0"
  CT_STORAGE=$(pvesm status -content rootdir 2>/dev/null \
    | awk 'NR>1 && $1!="Name" {print $1; exit}' || echo "local-lvm")
  CT_IP="dhcp"
  CT_GW=""

  echo -e "  ${BOLD}Default settings:${NC}"
  echo -e "  CT ID:    ${CT_CTID:-$CTID}"
  echo -e "  Hostname: $CT_HOSTNAME"
  echo -e "  CPU:      $CT_CORES core(s)"
  echo -e "  RAM:      ${CT_RAM} MB"
  echo -e "  Disk:     ${CT_DISK} GB  on  $CT_STORAGE"
  echo -e "  Network:  DHCP on $CT_BRIDGE"
  echo ""
  read -rp "  Proceed? [Y/n] " ok
  [[ "$ok" == [nN] ]] && exit 0
}

advanced_mode() {
  which whiptail &>/dev/null || { DEBIAN_FRONTEND=noninteractive apt-get install -y -qq whiptail; }

  local next_id
  next_id=$(pvesh get /cluster/nextid 2>/dev/null || echo "200")
  local def_storage
  def_storage=$(pvesm status -content rootdir 2>/dev/null \
    | awk 'NR>1 && $1!="Name" {print $1; exit}' || echo "local-lvm")

  CTID=$(whiptail --inputbox "Container ID" 8 50 "$next_id" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  CT_HOSTNAME=$(whiptail --inputbox "Hostname" 8 50 "lan-tracker" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  CT_CORES=$(whiptail --inputbox "CPU Cores" 8 50 "1" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  CT_RAM=$(whiptail --inputbox "RAM (MB)" 8 50 "512" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  CT_DISK=$(whiptail --inputbox "Disk Size (GB)" 8 50 "4" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  CT_STORAGE=$(whiptail --inputbox "Storage Pool" 8 50 "$def_storage" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  CT_BRIDGE=$(whiptail --inputbox "Network Bridge" 8 50 "vmbr0" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  local ip_mode
  ip_mode=$(whiptail --menu "Network" 12 55 2 \
    "dhcp"   "DHCP (automatic IP)" \
    "static" "Static IP" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  CT_IP="dhcp"
  CT_GW=""
  if [[ "$ip_mode" == "static" ]]; then
    CT_IP=$(whiptail --inputbox "IP Address with prefix (e.g. 192.168.1.50/24)" 8 60 "" \
      --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0
    CT_GW=$(whiptail --inputbox "Gateway (e.g. 192.168.1.1)" 8 55 "" \
      --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0
  fi
}

# ── LXC creation ──────────────────────────────────────────────────────────────
create_lxc() {
  msg_info "Creating LXC container CT${CTID}..."

  local net="name=eth0,bridge=${CT_BRIDGE}"
  if [[ "$CT_IP" == "dhcp" ]]; then
    net+=",ip=dhcp,ip6=auto"
  else
    net+=",ip=${CT_IP}"
    [[ -n "$CT_GW" ]] && net+=",gw=${CT_GW}"
  fi

  pct create "$CTID" "$TEMPLATE_PATH" \
    --hostname   "$CT_HOSTNAME" \
    --cores      "$CT_CORES" \
    --memory     "$CT_RAM" \
    --rootfs     "${CT_STORAGE}:${CT_DISK}" \
    --net0       "$net" \
    --features   nesting=1 \
    --unprivileged 1 \
    --onboot     1 \
    --start      0 \
    --ostype     debian &>/dev/null
  msg_ok

  msg_info "Starting container..."
  pct start "$CTID"
  sleep 5
  msg_ok
}

install_in_lxc() {
  msg_info "Waiting for network inside CT${CTID}..."
  local tries=0
  until pct exec "$CTID" -- ping -c1 -W2 1.1.1.1 &>/dev/null || (( tries++ >= 15 )); do
    sleep 2
  done
  (( tries >= 15 )) && msg_error "Container has no internet access — check bridge/gateway"
  msg_ok

  msg_info "Installing LAN Tracker inside CT${CTID}..."
  pct exec "$CTID" -- bash -c "
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq curl
    bash <(curl -fsSL ${RAW_URL}/install.sh)
  "
  msg_ok
}

print_result() {
  local ct_ip
  ct_ip=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')

  echo ""
  echo -e "  ${GRN}${BOLD}╔══════════════════════════════════════════╗${NC}"
  echo -e "  ${GRN}${BOLD}║   LAN Tracker installed successfully!   ║${NC}"
  echo -e "  ${GRN}${BOLD}╚══════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  ${BOLD}Container:${NC} CT${CTID}  (${CT_HOSTNAME})"
  echo -e "  ${BOLD}Resources:${NC} ${CT_CORES} CPU · ${CT_RAM} MB RAM · ${CT_DISK} GB disk"
  echo -e "  ${BOLD}Storage:${NC}   ${CT_STORAGE}"
  echo -e "  ${BOLD}Web UI:${NC}    ${CYN}http://${ct_ip}:8080${NC}"
  echo ""
  echo -e "  Manage the container: ${BOLD}pct enter ${CTID}${NC}"
  echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────────
header
check_root
check_proxmox

MODE=$(whiptail --menu "Installation Type" 14 58 2 \
  "default"  "  Default   — Recommended settings, no prompts" \
  "advanced" "  Advanced  — Custom CPU, RAM, disk, IP" \
  --title "LAN Tracker Network Sonar" 3>&1 1>&2 2>&3) || exit 0

echo ""

case "$MODE" in
  default)  default_mode ;;
  advanced) advanced_mode ;;
esac

get_template
create_lxc
install_in_lxc
print_result
