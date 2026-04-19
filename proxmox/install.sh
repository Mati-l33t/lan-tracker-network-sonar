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

ensure_whiptail() {
  command -v whiptail &>/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq whiptail
}

# Build a whiptail menu list from pvesm storage names
# Usage: storage_menu <content-type>   e.g. vztmpl | rootdir
storage_menu() {
  local content="$1"
  pvesm status -content "$content" 2>/dev/null \
    | awk 'NR>1 && $1!="Name" {print $1, $1}' \
    | tr '\n' ' '
}

# Pick a storage via whiptail menu, falling back to first available
pick_storage() {
  local content="$1"   # vztmpl or rootdir
  local title="$2"
  local prompt="$3"

  local entries
  entries=$(storage_menu "$content")

  if [[ -z "$entries" ]]; then
    msg_error "No storage found with content type '$content' — check your Proxmox storage config"
  fi

  # Count entries (each entry is "name name" = 2 words)
  local count
  count=$(echo "$entries" | wc -w)

  if [[ "$count" -eq 2 ]]; then
    # Only one storage — use it automatically
    echo "$entries" | awk '{print $1}'
    return
  fi

  # Multiple — show menu
  # shellcheck disable=SC2086
  whiptail --menu "$prompt" 16 60 8 $entries \
    --title "$title" 3>&1 1>&2 2>&3 || exit 0
}

# ── Template handling ──────────────────────────────────────────────────────────
get_template() {
  # Scan ALL storages with vztmpl content for an existing debian-13 template
  local all_storages found_path=""
  all_storages=$(pvesm status -content vztmpl 2>/dev/null \
    | awk 'NR>1 && $1!="Name" {print $1}' || true)

  for stor in $all_storages; do
    local hit
    hit=$(pveam list "$stor" 2>/dev/null \
      | awk '{print $1}' | grep "debian-13" | sort -V | tail -1 || true)
    if [[ -n "$hit" ]]; then
      found_path="$hit"
      msg_done "Template found on '$stor': $hit"
      break
    fi
  done

  if [[ -n "$found_path" ]]; then
    TEMPLATE_PATH="$found_path"
    return
  fi

  # Not found anywhere — download to the user-selected storage
  msg_info "Updating template list..."
  pveam update &>/dev/null; msg_ok

  local avail
  avail=$(pveam available --section system 2>/dev/null \
    | awk '{print $2}' | grep "^debian-13" | sort -V | tail -1 || true)

  if [[ -z "$avail" ]]; then
    msg_warn "Debian 13 template not found in pveam — trying Debian 12 as fallback"
    avail=$(pveam available --section system 2>/dev/null \
      | awk '{print $2}' | grep "^debian-12" | sort -V | tail -1 || true)
    [[ -z "$avail" ]] && msg_error "No Debian template available — check Proxmox template repositories"
    msg_warn "Using: $avail"
  fi

  msg_info "Downloading $avail to ${TEMPLATE_STORAGE}..."
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
  CT_IP="dhcp"
  CT_GW=""

  echo -e "  ${BOLD}Storage selection${NC}"
  echo ""

  TEMPLATE_STORAGE=$(pick_storage "vztmpl" \
    "LAN Tracker — Template Storage" \
    "Where should the Debian template be downloaded/stored?")

  CT_STORAGE=$(pick_storage "rootdir" \
    "LAN Tracker — Container Storage" \
    "Where should the LXC container be installed?")

  echo ""
  echo -e "  ${BOLD}Default settings:${NC}"
  echo -e "  CT ID:             $CTID"
  echo -e "  Hostname:          $CT_HOSTNAME"
  echo -e "  CPU:               $CT_CORES core(s)"
  echo -e "  RAM:               ${CT_RAM} MB"
  echo -e "  Disk:              ${CT_DISK} GB  on  $CT_STORAGE"
  echo -e "  Network:           DHCP on $CT_BRIDGE"
  echo -e "  Template storage:  $TEMPLATE_STORAGE"
  echo ""
  read -rp "  Proceed? [Y/n] " ok
  [[ "$ok" == [nN] ]] && exit 0
}

advanced_mode() {
  local next_id
  next_id=$(pvesh get /cluster/nextid 2>/dev/null || echo "200")

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

  TEMPLATE_STORAGE=$(pick_storage "vztmpl" \
    "LAN Tracker — Advanced Setup" \
    "Template storage — where to download/store the Debian template:")

  CT_STORAGE=$(pick_storage "rootdir" \
    "LAN Tracker — Advanced Setup" \
    "Container storage — where to install the LXC:")

  CT_BRIDGE=$(whiptail --inputbox "Network Bridge" 8 50 "vmbr0" \
    --title "LAN Tracker — Advanced Setup" 3>&1 1>&2 2>&3) || exit 0

  local ip_mode
  ip_mode=$(whiptail --menu "Network Configuration" 12 55 2 \
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
  echo -e "  ${BOLD}Container:${NC}         CT${CTID}  (${CT_HOSTNAME})"
  echo -e "  ${BOLD}Resources:${NC}         ${CT_CORES} CPU · ${CT_RAM} MB RAM · ${CT_DISK} GB disk"
  echo -e "  ${BOLD}Container storage:${NC} ${CT_STORAGE}"
  echo -e "  ${BOLD}Template storage:${NC}  ${TEMPLATE_STORAGE}"
  echo -e "  ${BOLD}Web UI:${NC}            ${CYN}http://${ct_ip}:8080${NC}"
  echo ""
  echo -e "  Manage the container: ${BOLD}pct enter ${CTID}${NC}"
  echo ""
}

# ── Main ───────────────────────────────────────────────────────────────────────
header
check_root
check_proxmox
ensure_whiptail

MODE=$(whiptail --menu "Installation Type" 14 58 2 \
  "default"  "  Default   — Recommended settings, minimal prompts" \
  "advanced" "  Advanced  — Custom CPU, RAM, disk, IP, bridge" \
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
