"""
Proxmox VE API client and background polling for LAN Tracker.
Polls each configured host every 30 s and caches results in memory.
"""
import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

_cache: Dict[int, Dict[str, Any]] = {}
_poll_errors: Dict[int, str] = {}
_get_hosts_fn = None


def set_hosts_getter(fn):
    global _get_hosts_fn
    _get_hosts_fn = fn


def get_cache() -> Dict[int, Dict[str, Any]]:
    return _cache


def get_errors() -> Dict[int, str]:
    return _poll_errors


async def _fetch(client: httpx.AsyncClient, base: str, path: str, tid: str, tsec: str) -> Any:
    headers = {"Authorization": f"PVEAPIToken={tid}={tsec}"}
    r = await client.get(f"{base}{path}", headers=headers)
    r.raise_for_status()
    return r.json()["data"]


async def _fetch_guest_ips(client: httpx.AsyncClient, base: str, tid: str, tsec: str, item: dict) -> None:
    node  = item["node"]
    vmid  = item["vmid"]
    try:
        if item["type"] == "lxc":
            ifaces = await _fetch(client, base, f"/nodes/{node}/lxc/{vmid}/interfaces", tid, tsec)
            ips = []
            for iface in (ifaces or []):
                inet = iface.get("inet", "")
                if inet and not inet.startswith("127."):
                    ips.append(inet.split("/")[0])
        else:
            data = await _fetch(client, base, f"/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces", tid, tsec)
            # Agent endpoint wraps array in {"result": [...]}
            ifaces = data.get("result", []) if isinstance(data, dict) else (data or [])
            ips = []
            for iface in ifaces:
                for addr in (iface.get("ip-addresses") or []):
                    if addr.get("ip-address-type") == "ipv4" and not addr["ip-address"].startswith("127."):
                        ips.append(addr["ip-address"])
        item["ips"] = ips
        logger.debug(f"IPs for {item['type']} {vmid}: {ips}")
    except Exception as e:
        logger.debug(f"IP fetch failed for {item.get('type')} {vmid}: {e}")
        item["ips"] = []


async def _backups_from_task_logs(
    client: httpx.AsyncClient, base: str, tid: str, tsec: str, node: str
) -> List[dict]:
    """Build the backup list by parsing vzdump task logs.

    The Proxmox storage content API silently omits backup files for CIFS/NFS
    storages when queried with a non-root API token (even with Datastore.Audit).
    Task logs are always readable and contain every file created or pruned,
    so we can reconstruct the current set without any extra setup.
    """
    from urllib.parse import quote as _quote

    try:
        tasks = await _fetch(client, base,
            f"/nodes/{node}/tasks?typefilter=vzdump&limit=500", tid, tsec) or []
    except Exception:
        return []

    # Include WARNING tasks — backup file was created even if task finished with warnings
    log_tasks = [t for t in tasks if t.get("status") in ("OK", "WARNING") and t.get("upid")]
    if not log_tasks:
        return []

    # Build per-VM latest task status from ALL tasks (OK + failed)
    _latest_batch: dict = {}
    _latest_ind:   dict = {}  # vmid_int -> task
    for t in tasks:
        vid = t.get("id", "")
        st  = t.get("starttime", 0)
        if not vid:
            if not _latest_batch or st > _latest_batch.get("starttime", 0):
                _latest_batch = t
        else:
            try:
                vi = int(vid)
            except ValueError:
                continue
            if vi not in _latest_ind or st > _latest_ind[vi].get("starttime", 0):
                _latest_ind[vi] = t

    def _vm_status(vmid: int) -> str:
        ind = _latest_ind.get(vmid)
        bat = _latest_batch
        if ind and bat:
            use = ind if ind.get("starttime", 0) >= bat.get("starttime", 0) else bat
        else:
            use = ind or bat
        if not use:
            return "OK"
        return "OK" if use.get("status") == "OK" else "FAILED"

    async def _fetch_log(upid: str) -> list:
        try:
            return await _fetch(client, base,
                f"/nodes/{node}/tasks/{_quote(upid, safe='')}/log?limit=3000",
                tid, tsec) or []
        except Exception:
            return []

    all_logs = await asyncio.gather(*[_fetch_log(t["upid"]) for t in log_tasks])

    # Match vzdump filenames in prune/remove log lines across PVE versions:
    # PVE 6/7: "removing old backup '/path/vzdump-lxc-...'"
    # PVE 8:   "prune vzdump-lxc-..."  /  "removing backup 'storage:backup/vzdump-...'"
    # Exclude lines with keep/skip/protect — those indicate the backup is being KEPT
    # (e.g. "keep vzdump-..." or "skipping protected backup: vzdump-...")
    _VZDUMP_FILE_RE = re.compile(
        r"vzdump-(?:lxc|qemu|ct|vm)-\d+-\d{4}_\d{2}_\d{2}-\d{2}_\d{2}_\d{2}\.[^\s'\"\\]+",
        re.I,
    )
    _PRUNE_LINE_RE  = re.compile(r"(?:remov|prun|discard)", re.I)
    _KEEP_LINE_RE   = re.compile(r"(?:keep|skip|protect)", re.I)

    # Pass 1 — collect every filename that was pruned across all logs
    pruned: set = set()
    for log in all_logs:
        for entry in log:
            text = entry.get("t", "")
            if _PRUNE_LINE_RE.search(text) and not _KEEP_LINE_RE.search(text):
                for fm in _VZDUMP_FILE_RE.finditer(text):
                    pruned.add(fm.group(0))

    # Pass 2 — collect created backups that were not subsequently pruned
    backups: List[dict] = []
    seen: set = set()

    for log in all_logs:
        lines = [e.get("t", "") for e in log]
        cur_vmid = cur_subtype = cur_ctime = cur_filename = cur_size = cur_storage = None

        for line in lines:
            m = re.search(r"Starting Backup of VM (\d+) \((\w+)\)", line)
            if m:
                cur_vmid, cur_subtype = int(m.group(1)), m.group(2)
                cur_filename = cur_size = cur_ctime = cur_storage = None

            m = re.search(r"creating vzdump archive '([^']+)'", line)
            if m:
                path = m.group(1)
                cur_filename = path.rsplit("/", 1)[-1]
                pm = re.search(r"/mnt/pve/([^/]+)/dump/", path)
                cur_storage = pm.group(1) if pm else None

            m = re.search(r"Backup started at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if m:
                try:
                    cur_ctime = int(datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp())
                except Exception:
                    pass

            m = re.search(r"archive file size: ([\d.]+)\s*([KMGT]?B)", line)
            if m:
                val, unit = float(m.group(1)), m.group(2).upper()
                mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
                cur_size = int(val * mult.get(unit, 1))

            if "Finished Backup of VM" in line and cur_filename:
                if cur_filename not in seen and cur_filename not in pruned:
                    seen.add(cur_filename)
                    fm = re.match(
                        r"vzdump-(\w+)-\d+-(\d{4}_\d{2}_\d{2})-(\d{2}_\d{2}_\d{2})\.(.+)",
                        cur_filename,
                    )
                    fmt = fm.group(4) if fm else None
                    backups.append({
                        "volid":        f"{cur_storage}:backup/{cur_filename}" if cur_storage else cur_filename,
                        "vmid":         cur_vmid,
                        "subtype":      cur_subtype,
                        "format":       fmt,
                        "size":         cur_size or 0,
                        "ctime":        cur_ctime,
                        "protected":    False,
                        "node":         node,
                        "storage_name": cur_storage or "",
                        "task_status":  _vm_status(cur_vmid),
                    })

    return backups


async def poll_host(host_cfg: dict) -> Dict[str, Any]:
    hid  = host_cfg["id"]
    base = f"https://{host_cfg['host']}:{host_cfg['port']}/api2/json"
    tid  = host_cfg["token_id"]
    tsec = host_cfg["token_secret"]
    verify = bool(host_cfg.get("verify_ssl"))

    async with httpx.AsyncClient(verify=verify, timeout=10.0) as client:
        nodes_raw = await _fetch(client, base, "/nodes", tid, tsec)

        nodes = []
        vms   = []
        containers = []
        storage    = []

        for node in nodes_raw:
            name = node["node"]
            try:
                st = await _fetch(client, base, f"/nodes/{name}/status", tid, tsec)
                node["cpu_usage"]   = round(st.get("cpu", 0) * 100, 1)
                node["mem_used"]    = st.get("memory", {}).get("used", 0)
                node["mem_total"]   = st.get("memory", {}).get("total", 1)
                node["uptime"]      = st.get("uptime", 0)
                node["load_avg"]    = st.get("loadavg", [0, 0, 0])
                node["kernel"]      = st.get("kversion", "")
                cpuinfo = st.get("cpuinfo", {})
                node["cpu_model"]   = cpuinfo.get("model", "")
                node["cpu_cores"]   = cpuinfo.get("cores", 0)
                node["cpu_threads"] = cpuinfo.get("cpus", 0)
                node["cpu_mhz"]     = cpuinfo.get("mhz", "")
                pve_ver = st.get("pveversion", "")
                node["pve_version"] = pve_ver.split("/")[1] if "/" in pve_ver else pve_ver
                node["swap_used"]   = st.get("swap",   {}).get("used",  0)
                node["swap_total"]  = st.get("swap",   {}).get("total", 0)
                node["rootfs_used"] = st.get("rootfs", {}).get("used",  0)
                node["rootfs_total"]= st.get("rootfs", {}).get("total", 0)
            except Exception as e:
                node.update({"cpu_usage": 0, "mem_used": 0, "mem_total": 1, "error": str(e)})

            for tf in ("hour", "day", "week", "month"):
                try:
                    rrd = await _fetch(client, base, f"/nodes/{name}/rrddata?timeframe={tf}&cf=AVERAGE", tid, tsec)
                    node[f"rrd_{tf}"] = rrd or []
                except Exception:
                    node[f"rrd_{tf}"] = []
            nodes.append(node)

            for endpoint, target in (("/qemu", vms), ("/lxc", containers)):
                try:
                    items = await _fetch(client, base, f"/nodes/{name}{endpoint}", tid, tsec)
                    for item in items:
                        item["node"] = name
                        item["type"] = "qemu" if endpoint == "/qemu" else "lxc"
                        target.append(item)
                except Exception:
                    pass

            try:
                for s in await _fetch(client, base, f"/nodes/{name}/storage", tid, tsec):
                    s["node"] = name
                    storage.append(s)
            except Exception:
                pass

        tasks = []
        try:
            tasks = (await _fetch(client, base, "/cluster/tasks", tid, tsec))[:20]
        except Exception:
            pass

        # Backup files — per storage that advertises backup content and is online.
        # A shared storage (CIFS/NFS) appears once per node in the storage list, so
        # we deduplicate by volid after collecting to avoid counting the same file
        # multiple times on multi-node clusters.
        backups = []
        offline_backup_storages = []
        seen_storages: set = set()  # avoid querying the same storage twice
        for s in storage:
            if 'backup' not in (s.get('content') or ''):
                continue
            stor_name = s['storage']
            if not s.get('active'):
                if stor_name not in seen_storages:
                    offline_backup_storages.append(stor_name)
                    seen_storages.add(stor_name)
                continue
            if stor_name in seen_storages:
                continue
            seen_storages.add(stor_name)
            try:
                items = await _fetch(client, base, f"/nodes/{s['node']}/storage/{stor_name}/content?content=backup", tid, tsec)
                for item in (items or []):
                    item['node'] = s['node']
                    item['storage_name'] = stor_name
                    backups.append(item)
            except Exception as e:
                logger.debug(f"Backup content fetch failed for {stor_name}: {e}")

        # Storage content API returns nothing for active backup storages → fall back
        # to reconstructing the list from vzdump task logs. This handles the known
        # Proxmox issue where CIFS/NFS backup files are invisible to non-root tokens
        # via the content API, while task logs remain always readable.
        if not backups and not offline_backup_storages:
            has_active_backup_storage = any(
                "backup" in (s.get("content") or "") and s.get("active")
                for s in storage
            )
            if has_active_backup_storage:
                seen_fallback: set = set()  # deduplicate across nodes
                for node_obj in nodes:
                    node_backups = await _backups_from_task_logs(
                        client, base, tid, tsec, node_obj["node"]
                    )
                    for b in node_backups:
                        vid = b.get("volid", "")
                        if vid not in seen_fallback:
                            seen_fallback.add(vid)
                            backups.append(b)
                logger.debug(f"Task-log fallback: {len(backups)} backups after dedup")

        # Backup jobs — cluster-level schedule definitions
        backup_jobs = []
        try:
            backup_jobs = await _fetch(client, base, "/cluster/backup", tid, tsec) or []
        except Exception:
            pass

        # VMs/CTs with no backup coverage — PVE 7+ endpoint
        not_backed_up = []
        try:
            not_backed_up = await _fetch(client, base, "/cluster/backup-info/not-backed-up", tid, tsec) or []
        except Exception:
            pass

        await asyncio.gather(
            *[_fetch_guest_ips(client, base, tid, tsec, g) for g in vms + containers],
            return_exceptions=True
        )

        return {
            "host_id":      hid,
            "label":        host_cfg["label"],
            "host":         host_cfg["host"],
            "polled_at":    datetime.utcnow().isoformat(),
            "nodes":        nodes,
            "vms":          vms,
            "containers":   containers,
            "storage":      storage,
            "tasks":        tasks,
            "backups":                backups,
            "backup_jobs":            backup_jobs,
            "not_backed_up":          not_backed_up,
            "offline_backup_storages": offline_backup_storages,
        }


async def poll_all_hosts():
    if _get_hosts_fn is None:
        return
    try:
        hosts = await _get_hosts_fn()
    except Exception as e:
        logger.error(f"Failed to load Proxmox hosts: {e}")
        return

    for host in hosts:
        if not host.get("enabled"):
            continue
        try:
            result = await poll_host(host)
            _cache[host["id"]] = result
            _poll_errors.pop(host["id"], None)
        except Exception as e:
            _poll_errors[host["id"]] = str(e)
            logger.error(f"Proxmox poll failed for '{host.get('label')}': {e}")


async def vm_action(host_cfg: dict, node: str, vmtype: str, vmid: int, action: str) -> dict:
    base   = f"https://{host_cfg['host']}:{host_cfg['port']}/api2/json"
    tid    = host_cfg["token_id"]
    tsec   = host_cfg["token_secret"]
    verify = bool(host_cfg.get("verify_ssl"))
    endpoint = f"/nodes/{node}/{vmtype}/{vmid}/status/{action}"
    async with httpx.AsyncClient(verify=verify, timeout=10.0) as client:
        headers = {"Authorization": f"PVEAPIToken={tid}={tsec}"}
        r = await client.post(f"{base}{endpoint}", headers=headers)
        r.raise_for_status()
        return r.json()


async def start_polling_loop(interval: int = 30):
    while True:
        await poll_all_hosts()
        await asyncio.sleep(interval)
