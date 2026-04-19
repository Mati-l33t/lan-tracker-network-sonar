# Changelog

All notable changes to LAN Tracker Network Sonar are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

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

[Unreleased]: https://github.com/Mati-l33t/lan-tracker-network-sonar/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.0.0
