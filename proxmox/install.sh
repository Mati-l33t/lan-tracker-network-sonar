#!/usr/bin/env bash
# LAN Tracker Network Sonar — Proxmox LXC Installer
# https://github.com/Mati-l33t/lan-tracker-network-sonar
#
# Run on your Proxmox VE host:
#   bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/proxmox/install.sh)

set -euo pipefail

RAW_URL="https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main"
REPO_URL="https://github.com/Mati-l33t/lan-tracker-network-sonar"

YW="\033[33m"
GN="\033[1;92m"
RD="\033[01;31m"
BL="\033[36m"
CM="\033[0;92m"
CL="\033[m"
BOLD="\033[1m"
TAB="  "

APP="LAN Tracker"
NSAPP="lan-tracker"
var_cpu="1"
var_ram="512"
var_disk="4"
var_unprivileged="1"

msg_info()  { echo -e "${TAB}${YW}  ⏳ ${1}...${CL}"; }
msg_ok()    { echo -e "${TAB}${CM}  ✔️   ${1}${CL}"; }
msg_error() { echo -e "${TAB}${RD}  ✖️   ${1}${CL}"; exit 1; }

header_info() {
  clear
  cat << 'EOF'
  ██╗      █████╗ ███╗   ██╗    ████████╗██████╗  █████╗  ██████╗██╗  ██╗███████╗██████╗
  ██║     ██╔══██╗████╗  ██║    ╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██║ ██╔╝██╔════╝██╔══██╗
  ██║     ███████║██╔██╗ ██║       ██║   ██████╔╝███████║██║     █████╔╝ █████╗  ██████╔╝
  ██║     ██╔══██║██║╚██╗██║       ██║   ██╔══██╗██╔══██║██║     ██╔═██╗ ██╔══╝  ██╔══██╗
  ███████╗██║  ██║██║ ╚████║       ██║   ██║  ██║██║  ██║╚██████╗██║  ██╗███████╗██║  ██║
  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝       ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
EOF
  echo -e "${TAB}${BOLD}${BL}LAN Tracker Network Sonar — Proxmox LXC Installer${CL}"
  echo -e "${TAB}${YW}GitHub: ${REPO_URL}${CL}"
  echo ""
}

# ── Storage picker ─────────────────────────────────────────────────────────────
select_storage() {
  local type="$1"
  local content="rootdir"
  [ "$type" = "template" ] && content="vztmpl"

  local names=()
  while IFS= read -r name; do
    names+=("$name" " ")
  done < <(pvesm status -content "$content" 2>/dev/null | awk 'NR>1 {print $1}')

  local count=$(( ${#names[@]} / 2 ))
  if [ "$count" -eq 0 ]; then
    msg_error "No suitable ${type} storage found — check Proxmox storage config"
  fi
  if [ "$count" -eq 1 ]; then
    echo "${names[0]}"
    return
  fi

  whiptail --backtitle "LAN Tracker Installer" \
    --title "$([ "$type" = "template" ] && echo "TEMPLATE STORAGE" || echo "CONTAINER STORAGE")" \
    --menu "\nWhere to store the ${type}?" 16 58 8 \
    "${names[@]}" \
    3>&1 1>&2 2>&3
}

# ── Template ───────────────────────────────────────────────────────────────────
get_template() {
  local storage="$1"

  # Scan ALL storages with vztmpl for an existing debian-13 template first
  local all_storages
  all_storages=$(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1 {print $1}' || true)

  for stor in $all_storages; do
    local hit
    hit=$(pveam list "$stor" 2>/dev/null | awk '{print $1}' | grep "debian-13" | sort -V | tail -1 || true)
    if [ -n "$hit" ]; then
      msg_ok "Template found on '$stor': $hit"
      echo "$hit"
      return
    fi
  done

  # Not found — download to chosen storage
  msg_info "Updating template list"
  pveam update >/dev/null 2>&1

  local avail
  avail=$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep "^debian-13" | sort -V | tail -1 || true)

  if [ -z "$avail" ]; then
    msg_info "Debian 13 not available yet — falling back to Debian 12"
    avail=$(pveam available --section system 2>/dev/null | awk '{print $2}' | grep "^debian-12" | sort -V | tail -1 || true)
    [ -z "$avail" ] && msg_error "No Debian template available in pveam"
  fi

  msg_info "Downloading $avail to $storage"
  pveam download "$storage" "$avail" >/dev/null 2>&1
  msg_ok "Template downloaded"
  echo "${storage}:vztmpl/${avail}"
}

# ── Default settings ───────────────────────────────────────────────────────────
default_settings() {
  CTID=$(pvesh get /cluster/nextid 2>/dev/null || echo 200)
  HN="$NSAPP"
  DISK_SIZE="$var_disk"
  CORE_COUNT="$var_cpu"
  RAM_SIZE="$var_ram"
  BRG="vmbr0"
  NET="dhcp"
  GATE=""
  VLAN_TAG=""
  UNPRIVILEGED="$var_unprivileged"

  echo -e "${TAB}${BOLD}⚙️  Using Default Settings${CL}"
  echo -e "${TAB}🆔  Container ID:  ${BL}${CTID}${CL}"
  echo -e "${TAB}🏠  Hostname:      ${BL}${HN}${CL}"
  echo -e "${TAB}💾  Disk Size:     ${BL}${DISK_SIZE} GB${CL}"
  echo -e "${TAB}🧠  CPU Cores:     ${BL}${CORE_COUNT}${CL}"
  echo -e "${TAB}🛠️  RAM:           ${BL}${RAM_SIZE} MB${CL}"
  echo -e "${TAB}🌉  Bridge:        ${BL}${BRG}${CL}"
  echo -e "${TAB}📡  IP:            ${BL}DHCP${CL}"
  echo ""
}

# ── Advanced settings ──────────────────────────────────────────────────────────
advanced_settings() {
  local nextid
  nextid=$(pvesh get /cluster/nextid 2>/dev/null || echo 200)

  CTID=$(whiptail --backtitle "LAN Tracker Installer" --title "CONTAINER ID" \
    --inputbox "\nSet Container ID:" 8 58 "$nextid" 3>&1 1>&2 2>&3) || exit

  HN=$(whiptail --backtitle "LAN Tracker Installer" --title "HOSTNAME" \
    --inputbox "\nSet Hostname:" 8 58 "$NSAPP" 3>&1 1>&2 2>&3) || exit
  HN=$(echo "${HN,,}" | tr -d ' ')

  DISK_SIZE=$(whiptail --backtitle "LAN Tracker Installer" --title "DISK SIZE" \
    --inputbox "\nSet Disk Size in GB:" 8 58 "$var_disk" 3>&1 1>&2 2>&3) || exit

  CORE_COUNT=$(whiptail --backtitle "LAN Tracker Installer" --title "CPU CORES" \
    --inputbox "\nAllocate CPU Cores:" 8 58 "$var_cpu" 3>&1 1>&2 2>&3) || exit

  RAM_SIZE=$(whiptail --backtitle "LAN Tracker Installer" --title "RAM" \
    --inputbox "\nAllocate RAM in MB:" 8 58 "$var_ram" 3>&1 1>&2 2>&3) || exit

  # Bridge — list available vmbr interfaces
  local bridge_opts=()
  while IFS= read -r br; do
    bridge_opts+=("$br" " ")
  done < <(ip link show 2>/dev/null | awk -F': ' '/^[0-9]+: vmbr/{print $2}' | cut -d@ -f1)

  if [ "${#bridge_opts[@]}" -gt 2 ]; then
    BRG=$(whiptail --backtitle "LAN Tracker Installer" --title "NETWORK BRIDGE" \
      --menu "\nSelect network bridge:" 16 58 6 "${bridge_opts[@]}" 3>&1 1>&2 2>&3) || exit
  else
    BRG="vmbr0"
  fi

  local ip_choice
  ip_choice=$(whiptail --backtitle "LAN Tracker Installer" --title "IP CONFIGURATION" \
    --menu "\nSelect IP configuration:" 12 58 2 \
    "dhcp"   "Automatic (DHCP)" \
    "static" "Static IP" \
    3>&1 1>&2 2>&3) || exit

  NET="dhcp"; GATE=""
  if [ "$ip_choice" = "static" ]; then
    NET=$(whiptail --backtitle "LAN Tracker Installer" --title "STATIC IP" \
      --inputbox "\nEnter Static IP with CIDR:\n(e.g. 192.168.1.50/24)" 10 58 "" 3>&1 1>&2 2>&3) || exit
    local gw
    gw=$(whiptail --backtitle "LAN Tracker Installer" --title "GATEWAY" \
      --inputbox "\nEnter Gateway IP:\n(e.g. 192.168.1.1)" 10 58 "" 3>&1 1>&2 2>&3) || exit
    GATE=",gw=${gw}"
  fi

  local vlan_input
  vlan_input=$(whiptail --backtitle "LAN Tracker Installer" --title "VLAN TAG" \
    --inputbox "\nSet VLAN Tag (leave blank for none):" 8 58 "" 3>&1 1>&2 2>&3) || exit
  [ -n "$vlan_input" ] && VLAN_TAG=",tag=${vlan_input}" || VLAN_TAG=""

  UNPRIVILEGED="$var_unprivileged"

  echo -e "${TAB}${BOLD}🧩 Using Advanced Settings${CL}"
  echo -e "${TAB}🆔  Container ID:  ${BL}${CTID}${CL}"
  echo -e "${TAB}🏠  Hostname:      ${BL}${HN}${CL}"
  echo -e "${TAB}💾  Disk Size:     ${BL}${DISK_SIZE} GB${CL}"
  echo -e "${TAB}🧠  CPU Cores:     ${BL}${CORE_COUNT}${CL}"
  echo -e "${TAB}🛠️  RAM:           ${BL}${RAM_SIZE} MB${CL}"
  echo -e "${TAB}🌉  Bridge:        ${BL}${BRG}${CL}"
  echo -e "${TAB}📡  IP:            ${BL}${NET}${CL}"
  echo ""
}

# ── Build container ────────────────────────────────────────────────────────────
build_container() {
  msg_info "Selecting storage"
  TEMPLATE_STORAGE=$(select_storage template)
  CONTAINER_STORAGE=$(select_storage container)
  msg_ok "Storage selected"

  TEMPLATE=$(get_template "$TEMPLATE_STORAGE")
  msg_ok "Template ready"

  local tz
  tz=$(timedatectl show --value --property=Timezone 2>/dev/null || echo "UTC")
  [[ "$tz" == Etc/* ]] && tz="UTC"

  msg_info "Creating LXC container ${CTID}"
  pct create "$CTID" "$TEMPLATE" \
    --hostname    "$HN" \
    --cores       "$CORE_COUNT" \
    --memory      "$RAM_SIZE" \
    --rootfs      "${CONTAINER_STORAGE}:${DISK_SIZE}" \
    --net0        "name=eth0,bridge=${BRG},ip=${NET}${GATE}${VLAN_TAG}" \
    --features    "nesting=1" \
    --unprivileged "$UNPRIVILEGED" \
    --tags        "lan-tracker" \
    --onboot      1 \
    --timezone    "$tz" \
    >/dev/null 2>&1
  msg_ok "LXC container ${CTID} created"

  msg_info "Starting container"
  pct start "$CTID"
  sleep 5
  msg_ok "Container started"

  msg_info "Waiting for network"
  local tries=0
  while ! pct exec "$CTID" -- ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; do
    sleep 3
    tries=$((tries + 1))
    if [ "$tries" -gt 15 ]; then
      msg_error "Network not reachable inside container — check bridge/gateway"
    fi
  done
  msg_ok "Network connected"

  CT_IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')
}

# ── Run install inside container ───────────────────────────────────────────────
run_install() {
  msg_info "Downloading install script"
  curl -fsSL "${RAW_URL}/install.sh" -o /tmp/lan-tracker-install.sh
  msg_ok "Install script downloaded"

  msg_info "Pushing install script into container"
  pct push "$CTID" /tmp/lan-tracker-install.sh /tmp/lan-tracker-install.sh --perms 0755
  rm -f /tmp/lan-tracker-install.sh
  msg_ok "Install script ready"

  msg_info "Running installer inside container"
  pct exec "$CTID" -- bash /tmp/lan-tracker-install.sh
  msg_ok "Installer finished"
}

# ── Main ───────────────────────────────────────────────────────────────────────
header_info

if whiptail --backtitle "LAN Tracker Installer" --title "INSTALL MODE" \
  --yesno "\nWould you like to use Default Settings?\n\nDefaults:\n  CPU: ${var_cpu} core\n  RAM: ${var_ram} MB\n  Disk: ${var_disk} GB\n  IP: DHCP\n  Type: Unprivileged" 16 58; then
  default_settings
else
  advanced_settings
fi

echo -e "${TAB}${BOLD}🚀 Creating LAN Tracker LXC...${CL}"
build_container
run_install

echo ""
msg_ok "LAN Tracker installation complete!"
echo ""
echo -e "${TAB}${GN}🌐 Web UI: ${BL}http://${CT_IP}:8080${CL}"
echo -e "${TAB}${YW}📋 Logs:   journalctl -u lan-tracker -f  (inside container)${CL}"
echo -e "${TAB}${YW}🖥️  Enter:  pct enter ${CTID}${CL}"
echo ""
