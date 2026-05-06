<div align="center">

<img src="app/static/logo.png" alt="HomeLab Sonar Logo" width="100">

# HomeLab Sonar

**Self-hosted LAN scanner, IP manager, and home lab dashboard — know every device on your network.**

[![Release](https://img.shields.io/github/v/release/Mati-l33t/lan-tracker-network-sonar?style=flat-square&color=4f9eff)](https://github.com/Mati-l33t/lan-tracker-network-sonar/releases)
[![License](https://img.shields.io/github/license/Mati-l33t/lan-tracker-network-sonar?style=flat-square&color=4f9eff)](LICENSE)
[![Stars](https://img.shields.io/github/stars/Mati-l33t/lan-tracker-network-sonar?style=flat-square&color=4f9eff)](https://github.com/Mati-l33t/lan-tracker-network-sonar/stargazers)

</div>

---

## Features

- **Live network scan** — discovers all active devices via ARP with vendor lookup
- **IP address management** — static & DHCP ranges, free IP tracking, custom device names
- **Device details** — MAC address, hostname, vendor, ping latency, open ports
- **7-day uptime sparklines** — visual history per device
- **Proxmox monitoring** — real-time CPU, RAM, swap, disk, and network I/O per node; VM/LXC power control; backup viewer
- **Application dashboard** — self-hosted app launcher with icons, categories, tags, drag-and-drop ordering, and live status badges
- **Dark / Light theme** — persistent across sessions
- **Network map** — visual topology of discovered devices
- **One-command install** — single line for Debian/Ubuntu; Proxmox LXC installer included
- **Auto-restart** — runs as a systemd service, survives reboots

---

## Quick Install — Debian / Ubuntu

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/install.sh)
```

> **Requirements:** Debian 11+ or Ubuntu 20.04+, root access, internet connection.

The installer will:
1. Install all dependencies (MariaDB, arp-scan, Python 3, git)
2. Clone the repo to `/opt/lan-tracker`
3. Generate a random database password
4. Create and enable a systemd service
5. Print the URL to open in your browser

---

## First Login & Password Setup

After installation the app is accessible to anyone on your network with no password. **Set a password immediately** after install.

Open the app in your browser, go to **Settings → System → Password Management** and set your password directly in the UI — no current password required on first setup.

Alternatively, set the password from the command line on the server:

```bash
python3 /opt/lan-tracker/scripts/set-password.py
```

Then restart the service:

```bash
systemctl restart lan-tracker
```

Once a password is set, the login page will be shown on every visit.

---

## Proxmox LXC Install

Run on your **Proxmox VE host** (not inside a VM or container):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/proxmox/install.sh)
```

You will be prompted to choose:

| Mode | Description |
|---|---|
| **Default** | Debian LXC · 1 CPU · 512 MB RAM · 4 GB disk · DHCP — no further questions |
| **Advanced** | Choose CT ID, hostname, CPU cores, RAM, disk, storage pool, bridge, static IP |

The script downloads the Debian template if needed, creates the container, and runs the full installer inside it.

---

## Proxmox Monitoring Setup

HomeLab Sonar connects to Proxmox VE via an API token. Run this one-liner **on your Proxmox VE host shell** to create one:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/proxmox/setup-token.sh)
```

This creates the `monitoring@pam` user, a minimal `LanTrackerRole`, and an API token — then prints the token secret for you to copy. Safe to re-run at any time.

The token secret is shown once when created. Then in HomeLab Sonar go to **Settings → Proxmox → Add Host** and enter:

| Field | Value |
|---|---|
| Token ID | `monitoring@pam!lan-tracker` |
| Token Secret | *(the secret shown above)* |

**What the token can do:**

| Privilege | Purpose |
|---|---|
| `VM.Audit` | Read VM / container details |
| `VM.PowerMgmt` | Start, stop, reboot, shutdown VMs and containers |
| `Sys.Audit` | Read node stats, task logs, backup schedules |
| `Datastore.Audit` | Read storage content |
| `SDN.Audit` | Read SDN/network info |

It cannot create or delete VMs, modify configs, manage users, or access backup file contents on CIFS/NFS shares (see note below).

> **CIFS/NFS backup storage:** Due to a Proxmox API limitation, backup files on CIFS or NFS shares are not visible to non-root tokens via the content API. HomeLab Sonar automatically falls back to reading vzdump task logs to reconstruct the backup list — no extra setup or elevated permissions needed.

---

## Update

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/update.sh)
```

---

## Uninstall

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Mati-l33t/lan-tracker-network-sonar/main/uninstall.sh)
```

This removes the application, service, config, and database entirely.

---

## Configuration

Network configuration (subnet, static range, DHCP range) is done through the **web UI** — no config file editing needed.

The app's runtime settings (DB credentials, port) live in `/etc/lan-tracker/lan-tracker.conf` and are generated automatically during installation:

```ini
LT_DB_HOST=localhost
LT_DB_NAME=lan_tracker
LT_DB_USER=lantracker
LT_DB_PASS=<auto-generated>
LT_PORT=8080
```

To change the port, edit this file and restart the service:

```bash
systemctl restart lan-tracker
```

---

## Service Management

```bash
systemctl status  lan-tracker    # Check status
systemctl restart lan-tracker    # Restart
journalctl -u lan-tracker -f     # Live logs
```

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes
4. Open a Pull Request

Please use the issue templates for bug reports and feature requests.

---

## License

[MIT](LICENSE) © [Mati-l33t](https://github.com/Mati-l33t)
