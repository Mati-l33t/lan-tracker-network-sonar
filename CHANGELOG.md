# Changelog

All notable changes to HomeLab Sonar are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [1.4.0] — 2026-05-07

### Added
- **Add Link** — new panel in Dashboard settings for bookmarking any URL; favicon is fetched automatically from the site (with upload fallback for sites that don't serve one); links appear on the dashboard alongside applications with the same tile layout and live status checking
- **Disable Password Login** — toggle in Settings → System → Password Management; allows open access to the dashboard even while a password is set, without losing the password; shows a warning when active
- **Scroll to top button** — floating chevron button appears on the Settings page after scrolling down, matching the same button on the Network and Proxmox pages
- **Screenshots** — dark and light theme screenshots added to the repository and README

### Fixed
- **Category header line too wide** — the gray separator line next to category names on the dashboard now caps its width to the right edge of the tile grid; on pages with few tiles the line no longer extends all the way to the screen edge

---

## [1.3.3] — 2026-05-06

### Fixed
- **Initial password setup blocked** — on a fresh install with no password set, the Change Password form required a current password that didn't exist; current password field is now hidden on first setup, and the backend skips verification when no password has been configured yet

### Added
- **README: First Login & Password Setup section** — documents setting the initial password via the web UI or the command-line script

---

## [1.3.2] — 2026-05-06

### Added
- **Favicon** — all pages now include a `<link rel="icon">` using the app logo; browser tabs and bookmarks show the logo
- **Custom logo** — Settings → Appearance: upload any image to replace the default logo across all pages and the favicon; a Reset button restores the default; logo is stored in `static/uploads/` and persisted in the database
- **Automatic update notifications** — amber dot badge on the Settings gear icon (visible on every page) when a newer version is available; checks GitHub Releases API once every 6 hours using a `localStorage` cache; the Settings update panel auto-populates from cache without requiring a manual button press

### Fixed
- **7-day activity always 0%** — `mysql.connector` does not collapse `%%` before sending SQL to MySQL, so `DATE_FORMAT(scan_date,'%%Y-%%m-%%d')` returned the literal string `%Y-%m-%d` for every row; replaced with a plain `SELECT scan_date` column fetch and Python `str()` conversion
- **Quick Token Setup copy button broken on HTTP** — `navigator.clipboard` is unavailable in non-secure contexts (HTTP); copy button silently failed; now falls back to `document.execCommand('copy')` via a temporary textarea
- **Empty state unreadable in dark mode** — dashboard "No apps yet" icon and subtitle used `var(--text-dim)` (`#38383f`) which is near-invisible on dark backgrounds; updated to `var(--text-muted)`

### Changed
- **Dashboard status badge repositioned** — ONLINE / OFFLINE badge moved to the upper-right corner of each tile (absolute positioned) and made slightly smaller; tile name and description no longer truncated by the badge
- **Branding** — remaining "LAN Tracker" labels updated to "HomeLab Sonar": page `<title>` tags, header logo text, footer on all pages, Settings update panel, login page

---

## [1.3.1] — 2026-05-05

### Fixed
- **App subtitle not saving** — added missing `GET /api/subtitle` and `POST /api/subtitle` backend endpoints; subtitle set in Settings now persists and loads on all pages
- **Hardcoded "Network Sonar" subtitle** — network, Proxmox, and login pages now load the subtitle dynamically instead of showing a fixed string
- **Login page subtitle** — `/api/subtitle` is now a public endpoint so the login page can display the subtitle before authentication

---

## [1.3.0] — 2026-05-05

### Added
- **Application dashboard** — self-hosted app launcher at `/dashboard`; responsive tile grid with icon, name, description, category grouping, and click-to-open behaviour
- **selfhst/icons integration** — auto-detects app icons from the [selfhst/icons](https://github.com/selfhst/icons) CDN when you type an app name; tries SVG then PNG; covers 50+ common self-hosted apps with alias normalisation
- **Custom icon upload** — upload PNG, JPG, SVG, or WebP (max 2 MB) per app; stored at `/opt/lan-tracker/static/uploads/icons/`
- **Tags** — create coloured tags and assign them to dashboard apps; tags shown as badges on tiles
- **Live status badges** — concurrent HTTP HEAD checks on all dashboard apps; ONLINE / OFFLINE badges with pulse animation
- **Drag-and-drop ordering** — reorder dashboard apps in Settings by dragging rows; order persists via `sort_order` and is reflected on the dashboard
- **Category grouping** — dashboard apps grouped by category on both the dashboard and in Settings; category headers align with tile columns
- **Inline row editing** — edit an existing app in-place in Settings with icon re-detection and custom upload

### Changed
- **Settings default tab** — Settings now opens to System tab by default instead of Dashboard
- **Settings → Dashboard layout** — Add Application panel moved above Tags panel
- **Dashboard tile grid** — tiles centered on page; category labels track the left edge of the tile columns on all screen widths
- **Renamed** — display name updated from *LAN Tracker* to *HomeLab Sonar* across all pages, titles, and docs; system paths and service name (`lan-tracker`) unchanged for backwards compatibility

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
- **LXC installer** — no longer automatically creates a Proxmox API token; users run `setup-token.sh` themselves via the Settings panel

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

[Unreleased]: https://github.com/Mati-l33t/lan-tracker-network-sonar/compare/v1.3.3...HEAD
[1.3.3]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.3.3
[1.3.2]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.3.2
[1.3.1]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.3.1
[1.3.0]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.3.0
[1.2.0]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.2.0
[1.0.0]: https://github.com/Mati-l33t/lan-tracker-network-sonar/releases/tag/v1.0.0
