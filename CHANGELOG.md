# Changelog

All notable changes to LAN Tracker Network Sonar are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.2.0] — 2026-05-03

### Added
- **Proxmox Monitoring** — Proxmox VE integration: real-time CPU, RAM, swap, root disk, network I/O, and storage overview per node
- **Proxmox VM / Container control** — start, stop, reboot, and shutdown VMs and LXC containers directly from the UI
- **Proxmox backup viewer** — list vzdump backups per VM/CT with fallback to task log parsing for CIFS/NFS storage
- **Proxmox setup one-liner** — `setup-token.sh` creates the monitoring user, minimal role, and API token in one command; command shown in Settings with a copy button
- **IO wait overlay on CPU chart** — IO wait rendered as an amber overlay series on the CPU sparkline; shown in hover tooltip
- **Y-axis labels on Proxmox charts** — dynamic percentage scale (capped at 100 %, minimum 8 % range) for CPU/RAM/swap/disk; compact byte labels for network (B/s, K/s, M/s)
- **Chart timeline** — time-range label (e.g. "1 hour") / "now" beneath each sparkline
- **Min / Max in metric headers** — min and max values displayed as "Min X · Max Y" below each metric value
- **Login / session auth** — bcrypt-hashed admin password, signed session cookies, configurable via `LT_AUTH_ENABLED` / `LT_ADMIN_HASH` in `lan-tracker.conf`

### Changed
- **Settings → System** — update panel redesigned: shows installed version, "Update Available" badge with latest version and changelog link, separate Check Now / Update Now buttons
- **Settings → Proxmox** — "Label" renamed to "Node Name"; port field shows placeholder instead of hard-coded default
- **Update script** — switched from `git pull` to `git fetch && git reset --hard origin/main` to guarantee a clean update with no merge conflicts; user data (database, config) is never modified
- **Proxmox charts** — sharper lines (`vector-effect="non-scaling-stroke"`); dynamic Y-scale prevents flat-line appearance at low utilisation; mid-range gridline added
- **Mobile** — Proxmox tab bar is horizontally scrollable on small screens with hidden scrollbar

### Fixed
- Changelog link in the update panel now falls back to the releases page URL when no specific release URL is returned

---

## [1.0.0] — 2026-04-19

### Added
- Initial public release
- ARP-based network scanning with vendor lookup
- IP address management — static and DHCP ranges, free IP tracking
- Device detail view — MAC, hostname, vendor, ping latency, open ports
- Custom device names, URLs, and icons
- 7-day uptime sparklines per device
- Network map — visual topology overlay
- Dark / Light theme toggle with localStorage persistence
- One-line install script for Debian and Ubuntu
- Proxmox LXC installer with Default and Advanced modes
- Update and Uninstall scripts
- Fully dynamic configuration — no hardcoded paths or credentials
- Version endpoint (`/api/version`) — version displayed in footer
- Systemd service with auto-restart on failure

[Unreleased]: https://github.com/Mati-l33t/lan-tracker-network-sonar/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.2.0
[1.0.0]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.0.0
