"""
FastAPI routes for Proxmox monitoring (/api/proxmox/...)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import proxmox_client as pvc

router  = APIRouter(prefix="/api/proxmox")
_get_db = None


def set_db(fn):
    global _get_db
    _get_db = fn


class HostCreate(BaseModel):
    label:        str
    host:         str
    port:         int  = 8006
    token_id:     str
    token_secret: str
    verify_ssl:   bool = False
    enabled:      bool = True


class VMAction(BaseModel):
    node:   str
    vmid:   int
    vmtype: str
    action: str


class HostUpdate(BaseModel):
    label:        Optional[str]  = None
    host:         Optional[str]  = None
    port:         Optional[int]  = None
    token_id:     Optional[str]  = None
    token_secret: Optional[str]  = None
    verify_ssl:   Optional[bool] = None
    enabled:      Optional[bool] = None


# ── Host CRUD ──────────────────────────────────────────────────────────────────

@router.get("/hosts")
async def list_hosts():
    conn = _get_db()
    if not conn:
        raise HTTPException(503, "DB unavailable")
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, label, host, port, token_id, verify_ssl, enabled, created_at, polled_at, last_error "
        "FROM proxmox_hosts ORDER BY id"
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    for r in rows:
        if r.get("created_at"):
            r["created_at"] = r["created_at"].isoformat()
        if r.get("polled_at"):
            r["polled_at"] = r["polled_at"].isoformat()
    return rows


@router.post("/hosts", status_code=201)
async def create_host(body: HostCreate):
    conn = _get_db()
    if not conn:
        raise HTTPException(503, "DB unavailable")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO proxmox_hosts (label, host, port, token_id, token_secret, verify_ssl, enabled) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (body.label, body.host, body.port, body.token_id, body.token_secret, body.verify_ssl, body.enabled)
    )
    conn.commit()
    new_id = cur.lastrowid
    cur.close(); conn.close()
    await pvc.poll_all_hosts()
    return {"id": new_id, "message": "Host added"}


@router.put("/hosts/{host_id}")
async def update_host(host_id: int, body: HostUpdate):
    conn = _get_db()
    if not conn:
        raise HTTPException(503, "DB unavailable")
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM proxmox_hosts WHERE id=%s", (host_id,))
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise HTTPException(404, "Host not found")
    try:
        updates = body.model_dump(exclude_none=True)
    except AttributeError:
        updates = {k: v for k, v in body.__dict__.items() if v is not None}
    if not updates:
        cur.close(); conn.close()
        return {"message": "Nothing to update"}
    set_clause = ", ".join(f"{k}=%s" for k in updates)
    cur.execute(f"UPDATE proxmox_hosts SET {set_clause} WHERE id=%s", (*updates.values(), host_id))
    conn.commit()
    cur.close(); conn.close()
    return {"message": "Updated"}


@router.delete("/hosts/{host_id}")
async def delete_host(host_id: int):
    conn = _get_db()
    if not conn:
        raise HTTPException(503, "DB unavailable")
    cur = conn.cursor()
    cur.execute("DELETE FROM proxmox_hosts WHERE id=%s", (host_id,))
    conn.commit()
    cur.close(); conn.close()
    pvc.get_cache().pop(host_id, None)
    pvc.get_errors().pop(host_id, None)
    return {"message": "Deleted"}


@router.post("/hosts/{host_id}/test")
async def test_host(host_id: int):
    conn = _get_db()
    if not conn:
        raise HTTPException(503, "DB unavailable")
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM proxmox_hosts WHERE id=%s", (host_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        conn.close()
        raise HTTPException(404, "Host not found")
    try:
        result = await pvc.poll_host(row)
        wr = conn.cursor()
        wr.execute("UPDATE proxmox_hosts SET polled_at=NOW(), last_error=NULL WHERE id=%s", (host_id,))
        conn.commit(); wr.close(); conn.close()
        return {
            "success":    True,
            "nodes":      len(result.get("nodes", [])),
            "vms":        len(result.get("vms", [])),
            "containers": len(result.get("containers", [])),
        }
    except Exception as e:
        wr = conn.cursor()
        wr.execute("UPDATE proxmox_hosts SET last_error=%s WHERE id=%s", (str(e), host_id))
        conn.commit(); wr.close(); conn.close()
        return {"success": False, "error": str(e)}


@router.post("/hosts/test-new")
async def test_new_host(body: HostCreate):
    """Test connection with credentials from a form (not yet saved)."""
    fake = {
        "id": 0, "label": body.label, "host": body.host, "port": body.port,
        "token_id": body.token_id, "token_secret": body.token_secret,
        "verify_ssl": body.verify_ssl, "enabled": True,
    }
    try:
        result = await pvc.poll_host(fake)
        return {
            "success":    True,
            "nodes":      len(result.get("nodes", [])),
            "vms":        len(result.get("vms", [])),
            "containers": len(result.get("containers", [])),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Live data ──────────────────────────────────────────────────────────────────

@router.get("/data")
async def get_all_data():
    cache  = pvc.get_cache()
    errors = pvc.get_errors()
    return {"hosts": list(cache.values()), "errors": {str(k): v for k, v in errors.items()}}


@router.get("/data/{host_id}")
async def get_host_data(host_id: int):
    cache = pvc.get_cache()
    if host_id not in cache:
        err = pvc.get_errors().get(host_id)
        if err:
            raise HTTPException(503, f"Poll error: {err}")
        raise HTTPException(404, "No data yet — host may not have been polled")
    return cache[host_id]


@router.post("/hosts/{host_id}/action")
async def host_vm_action(host_id: int, body: VMAction):
    if body.action not in {"start", "stop", "reboot", "shutdown"}:
        raise HTTPException(400, "Invalid action")
    if body.vmtype not in {"qemu", "lxc"}:
        raise HTTPException(400, "Invalid vmtype")
    conn = _get_db()
    if not conn:
        raise HTTPException(503, "DB unavailable")
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM proxmox_hosts WHERE id=%s", (host_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        raise HTTPException(404, "Host not found")
    try:
        result = await pvc.vm_action(row, body.node, body.vmtype, body.vmid, body.action)
        return {"status": "ok", "result": result}
    except Exception as e:
        raise HTTPException(500, f"Action failed: {e}")


@router.post("/refresh")
async def force_refresh():
    await pvc.poll_all_hosts()
    return {"message": "Refreshed"}


def get_widget_summary():
    """Return a slim per-node summary from the in-memory cache for the dashboard widget."""
    if not _get_db:
        return []
    conn = _get_db()
    if not conn:
        return []
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, label FROM proxmox_hosts WHERE enabled=1 ORDER BY id")
    hosts = cur.fetchall()
    cur.close(); conn.close()

    cache = pvc.get_cache()
    result = []
    for host in hosts:
        hid = host["id"]
        data = cache.get(hid)
        if not data:
            continue
        nodes_out = []
        all_guests = data.get("vms", []) + data.get("containers", [])
        for node in data.get("nodes", []):
            node_name = node.get("node", "")
            node_guests = [g for g in all_guests if g.get("node") == node_name]
            vms_running = sum(1 for g in node_guests if g.get("status") == "running")
            vms_stopped = sum(1 for g in node_guests if g.get("status") != "running")
            mem_used  = node.get("mem",    0)
            mem_total = node.get("maxmem", 0)
            cpu_pct   = round(node.get("cpu", 0) * 100, 1)
            nodes_out.append({
                "node":        node_name,
                "cpu_usage":   cpu_pct,
                "mem_used":    mem_used,
                "mem_total":   mem_total,
                "uptime":      node.get("uptime", 0),
                "vms_running": vms_running,
                "vms_stopped": vms_stopped,
            })
        if nodes_out:
            result.append({"name": host["label"], "nodes": nodes_out})
    return result
