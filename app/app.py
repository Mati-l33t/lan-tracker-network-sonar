#!/usr/bin/env python3
import os, asyncio, ipaddress, logging, bcrypt, uuid, json, collections, secrets
logger = logging.getLogger(__name__)

_LOG_BUFFER = collections.deque(maxlen=200)

_OWN_LOGGERS = {"app", "auth", "proxmox_client", "proxmox_routes", "__main__"}

class _BufHandler(logging.Handler):
    def emit(self, record):
        if record.name.split(".")[0] not in _OWN_LOGGERS:
            return
        try:
            msg = record.getMessage()
            if record.exc_info and record.exc_info[0] is not None:
                exc_name = record.exc_info[0].__name__
                exc_val  = str(record.exc_info[1])
                msg += f" [{exc_name}: {exc_val}]" if exc_val else f" [{exc_name}]"
            _LOG_BUFFER.append({
                "ts":    record.created,
                "level": record.levelname,
                "name":  record.name.split(".")[-1],
                "msg":   msg,
            })
        except Exception:
            pass

_buf_handler = _BufHandler(logging.INFO)
logging.getLogger().addHandler(_buf_handler)
logging.getLogger().setLevel(logging.INFO)

from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
import mysql.connector, subprocess, re, socket, struct
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pydantic import BaseModel
from typing import List, Optional

import auth
import proxmox_routes
import proxmox_client as pvc

BASE_DIR     = Path(__file__).parent
VERSION_FILE = BASE_DIR.parent / "VERSION"

app = FastAPI()

# ── Auth middleware ────────────────────────────────────────────────────────────
_UNPROTECTED = {"/login", "/logout", "/static/login.html", "/static/logo.png", "/static/favicon.ico", "/api/subtitle", "/api/has-password"}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static/") or path in _UNPROTECTED:
        return await call_next(request)
    if not auth.is_authenticated(request):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)
    return await call_next(request)

app.include_router(auth.router)
app.include_router(proxmox_routes.router)

# ── DB ─────────────────────────────────────────────────────────────────────────

def _db_cfg():
    return {
        "host":     os.environ.get("LT_DB_HOST", "localhost"),
        "database": os.environ.get("LT_DB_NAME", "lan_tracker"),
        "user":     os.environ.get("LT_DB_USER", "lantracker"),
        "password": os.environ.get("LT_DB_PASS", ""),
    }

def _detect_defaults():
    try:
        res = subprocess.run(["ip", "route", "show"], capture_output=True, text=True)
        for line in res.stdout.splitlines():
            m = re.match(r'^(\d+\.\d+\.\d+\.\d+/\d+)\s+dev\s+\S+\s+proto\s+kernel', line)
            if m:
                net_str = m.group(1)
                if not net_str.startswith("127."):
                    return {"subnet": net_str}
    except Exception:
        logger.debug("Network interface detection failed")
    return {"subnet": ""}

_detected_subnet = _detect_defaults().get("subnet", "")
DEFAULT = {
    "subnet":       _detected_subnet,
    "static_start": "",
    "static_end":   "",
    "dhcp_start":   "",
    "dhcp_end":     "",
}

class Cfg(BaseModel):
    subnet:str; staticStart:str; staticEnd:str; dhcpStart:str; dhcpEnd:str
class DevName(BaseModel):
    ip:str; customName:str; url:str=""; icon:str=""
class IpOnly(BaseModel):
    ip:str
class PwChange(BaseModel):
    currentPassword:str; newPassword:str
class DashboardApp(BaseModel):
    name:str; url:str; icon_type:str="initials"; icon_value:str=""
    category:str=""; description:str=""; tags:List[int]=[]; is_link:int=0
class WidgetConfigPatch(BaseModel):
    clock: Optional[bool] = None
    network: Optional[bool] = None
    proxmox: Optional[bool] = None
class DashboardTag(BaseModel):
    name:str; color:str="#6366f1"
class StatusItem(BaseModel):
    id:int; url:str
class StatusBody(BaseModel):
    items:List[StatusItem]
class DashboardReorder(BaseModel):
    order:List[int]
class CategoryOrder(BaseModel):
    order:List[str]
class AuthSettings(BaseModel):
    login_disabled:bool

def db():
    try:
        return mysql.connector.connect(**_db_cfg())
    except Exception:
        logger.error("Database connection failed")
        return None

def init():
    c = db()
    if not c: return
    cur = c.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS config(id INT PRIMARY KEY,subnet VARCHAR(50),static_start VARCHAR(50),static_end VARCHAR(50),dhcp_start VARCHAR(50),dhcp_end VARCHAR(50))")
    cur.execute("CREATE TABLE IF NOT EXISTS devices(id INT AUTO_INCREMENT PRIMARY KEY,ip VARCHAR(50)UNIQUE,mac VARCHAR(50),hostname VARCHAR(255),vendor VARCHAR(255),custom_name VARCHAR(255),url VARCHAR(500),status ENUM('active','inactive','free')DEFAULT'free',type ENUM('static','dhcp')DEFAULT'dhcp',last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)")
    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS ping FLOAT NULL")
    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS open_ports VARCHAR(255) NULL")
    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS first_seen TIMESTAMP NULL")
    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS icon VARCHAR(50) DEFAULT 'unknown'")
    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_new TINYINT(1) DEFAULT 0")
    cur.execute("CREATE TABLE IF NOT EXISTS device_history(ip VARCHAR(50),scan_date DATE,PRIMARY KEY(ip,scan_date))")
    cur.execute("CREATE TABLE IF NOT EXISTS admin_config(`key` VARCHAR(50) PRIMARY KEY, value TEXT NOT NULL)")
    cur.execute("SELECT value FROM admin_config WHERE `key`='admin_hash'")
    row = cur.fetchone()
    if row and row[0]:
        auth.ADMIN_HASH = row[0]
    cur.execute("SELECT value FROM admin_config WHERE `key`='login_disabled'")
    row = cur.fetchone()
    if row and row[0] == '1':
        auth.LOGIN_DISABLED = True
    cur.execute("""CREATE TABLE IF NOT EXISTS proxmox_hosts (
        id INT AUTO_INCREMENT PRIMARY KEY,
        label VARCHAR(100) NOT NULL,
        host VARCHAR(255) NOT NULL,
        port INT NOT NULL DEFAULT 8006,
        token_id VARCHAR(255) NOT NULL,
        token_secret VARCHAR(255) NOT NULL,
        verify_ssl BOOLEAN NOT NULL DEFAULT FALSE,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        polled_at DATETIME DEFAULT NULL,
        last_error TEXT DEFAULT NULL
    )""")
    cur.execute("ALTER TABLE proxmox_hosts ADD COLUMN IF NOT EXISTS polled_at DATETIME DEFAULT NULL")
    cur.execute("ALTER TABLE proxmox_hosts ADD COLUMN IF NOT EXISTS last_error TEXT DEFAULT NULL")
    cur.execute("""CREATE TABLE IF NOT EXISTS dashboard_apps (
        id          INT AUTO_INCREMENT PRIMARY KEY,
        name        VARCHAR(100) NOT NULL,
        url         VARCHAR(500) NOT NULL,
        icon_type   VARCHAR(20) DEFAULT 'initials',
        icon_value  VARCHAR(500) DEFAULT NULL,
        category    VARCHAR(100) DEFAULT NULL,
        description VARCHAR(500) DEFAULT NULL,
        tags        TEXT DEFAULT NULL,
        sort_order  INT DEFAULT 0,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("ALTER TABLE dashboard_apps ADD COLUMN IF NOT EXISTS category VARCHAR(100) DEFAULT NULL")
    cur.execute("ALTER TABLE dashboard_apps ADD COLUMN IF NOT EXISTS description VARCHAR(500) DEFAULT NULL")
    cur.execute("ALTER TABLE dashboard_apps ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT NULL")
    cur.execute("ALTER TABLE dashboard_apps ADD COLUMN IF NOT EXISTS is_link TINYINT(1) DEFAULT 0")
    cur.execute("""CREATE TABLE IF NOT EXISTS dashboard_tags (
        id         INT AUTO_INCREMENT PRIMARY KEY,
        name       VARCHAR(50) NOT NULL,
        color      VARCHAR(20) NOT NULL DEFAULT '#6366f1',
        sort_order INT DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    cur.execute("SELECT COUNT(*)FROM config")
    if cur.fetchone()[0] == 0:
        cur.execute("INSERT INTO config VALUES(1,%s,%s,%s,%s,%s)",
            (DEFAULT["subnet"],DEFAULT["static_start"],DEFAULT["static_end"],DEFAULT["dhcp_start"],DEFAULT["dhcp_end"]))
    c.commit(); cur.close(); c.close()

def get_cfg():
    c = db()
    if not c: return DEFAULT
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM config WHERE id=1")
    r = cur.fetchone(); cur.close(); c.close()
    if r:
        return {"subnet":r["subnet"],"staticStart":r["static_start"],"staticEnd":r["static_end"],"dhcpStart":r["dhcp_start"],"dhcpEnd":r["dhcp_end"]}
    return DEFAULT

def save_cfg(subnet, ss, se, ds, de):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute(
        "INSERT INTO config(id,subnet,static_start,static_end,dhcp_start,dhcp_end)VALUES(1,%s,%s,%s,%s,%s)"
        "ON DUPLICATE KEY UPDATE subnet=%s,static_start=%s,static_end=%s,dhcp_start=%s,dhcp_end=%s",
        (subnet,ss,se,ds,de,subnet,ss,se,ds,de))
    c.commit(); cur.close(); c.close()

def ip2int(ip): return struct.unpack("!I", socket.inet_aton(ip))[0]
def ips_range(s, e):
    if not s or not e: return []
    try:
        return [socket.inet_ntoa(struct.pack("!I", i)) for i in range(ip2int(s), ip2int(e)+1)]
    except Exception:
        logger.debug("ips_range(%s, %s) failed", s, e)
        return []

def scan(subnet):
    try:
        res  = subprocess.run(["ip","route"], capture_output=True, text=True)
        iface = "eth0"
        for l in res.stdout.split("\n"):
            if subnet.split("/")[0] in l and "dev" in l:
                p = l.split()
                if "dev" in p: iface = p[p.index("dev")+1]; break
        res  = subprocess.run(["arp-scan", f"--interface={iface}", "--localnet"],
                              capture_output=True, text=True, timeout=60)
        devs = []
        for l in res.stdout.split("\n"):
            m = re.match(r"^(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:]{17})\s+(.+)$", l)
            if m: devs.append({"ip":m.group(1),"mac":m.group(2).lower(),"vendor":m.group(3).strip()})
        return devs
    except Exception:
        logger.exception("arp-scan failed")
        return []

def hostname(ip):
    try: return socket.gethostbyaddr(ip)[0]
    except Exception: return ""

def ping_host(ip):
    try:
        res = subprocess.run(["ping","-c","1","-W","2",ip], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if 'time=' in line:
                    return round(float(line.split('time=')[1].split()[0]), 1)
        return None
    except Exception: return None

def scan_ports(ip):
    common_ports = [21,22,23,25,53,80,110,443,3389,8080]
    def check(port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            open_ = s.connect_ex((ip, port)) == 0
            s.close()
            return port if open_ else None
        except Exception: return None
    with ThreadPoolExecutor(max_workers=10) as ex:
        return [p for p in ex.map(check, common_ports) if p is not None]

def ip_type(ip, ss, se, ds, de):
    if not ss or not se or not ds or not de: return "dhcp"
    try:
        n = ip2int(ip)
        if ip2int(ss) <= n <= ip2int(se): return "static"
        if ip2int(ds) <= n <= ip2int(de): return "dhcp"
    except Exception:
        logger.debug("ip_type error for %s", ip)
    return "dhcp"

def enrich(d, cfg):
    d["type"]     = ip_type(d["ip"], cfg["staticStart"], cfg["staticEnd"], cfg["dhcpStart"], cfg["dhcpEnd"])
    d["hostname"] = hostname(d["ip"])
    d["ping"]     = ping_host(d["ip"])
    d["ports"]    = ",".join(str(p) for p in scan_ports(d["ip"]))
    return d

def update_devs(devs, cfg):
    c = db()
    if not c: return
    cur = c.cursor()
    cur.execute("SELECT ip FROM devices")
    existing = {r[0] for r in cur.fetchall()}
    with ThreadPoolExecutor(max_workers=20) as ex:
        enriched = list(ex.map(lambda d: enrich(d, cfg), devs))
    today = date.today().isoformat()
    cur.execute("UPDATE devices SET status='inactive'")
    for d in enriched:
        is_new = 1 if d["ip"] not in existing else 0
        cur.execute(
            "INSERT INTO devices(ip,mac,hostname,vendor,status,type,ping,open_ports,first_seen,is_new)"
            "VALUES(%s,%s,%s,%s,'active',%s,%s,%s,NOW(),%s)"
            "ON DUPLICATE KEY UPDATE mac=VALUES(mac),hostname=VALUES(hostname),"
            "vendor=VALUES(vendor),status='active',type=VALUES(type),"
            "last_seen=CURRENT_TIMESTAMP,ping=VALUES(ping),open_ports=VALUES(open_ports),"
            "first_seen=COALESCE(first_seen,NOW()),is_new=VALUES(is_new)",
            (d["ip"],d["mac"],d["hostname"],d["vendor"],d["type"],d["ping"],d["ports"],is_new))
        cur.execute("INSERT IGNORE INTO device_history(ip,scan_date)VALUES(%s,%s)", (d["ip"], today))
    c.commit(); cur.close(); c.close()

def status():
    cfg = get_cfg()
    c   = db()
    if not c:
        return {"total":0,"active":0,"free":0,"devices":[],"freeStaticIps":[],"freeDhcpIps":[]}
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM devices ORDER BY INET_ATON(ip)")
    devs = cur.fetchall()
    cur.execute("SELECT COUNT(*) as cnt FROM devices WHERE status='active'")
    active = cur.fetchone()["cnt"]
    cur.execute("SELECT MAX(last_seen) as ls FROM devices")
    ls = cur.fetchone()["ls"]
    today = date.today()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6,-1,-1)]
    cur.execute("SELECT ip, scan_date FROM device_history WHERE scan_date>=%s", (dates[0],))
    hist_map = {}
    for row in cur.fetchall():
        hist_map.setdefault(row["ip"], set()).add(str(row["scan_date"]))
    cur.close(); c.close()
    static_ips  = ips_range(cfg["staticStart"], cfg["staticEnd"])
    dhcp_ips    = ips_range(cfg["dhcpStart"],   cfg["dhcpEnd"])
    used        = {d["ip"] for d in devs if d["status"] == "active"}
    static_set  = set(static_ips)
    free_static = [ip for ip in static_ips if ip not in used]
    free_dhcp   = [ip for ip in dhcp_ips   if ip not in used and ip not in static_set]
    for d in devs:
        raw = d.get("open_ports") or ""
        d["openPorts"] = [int(p) for p in raw.split(",") if p.strip().isdigit()]
        d["ping"]      = float(d["ping"]) if d.get("ping") is not None else None
        if d.get("last_seen"):  d["last_seen"]  = d["last_seen"].isoformat()
        if d.get("first_seen"): d["first_seen"] = d["first_seen"].isoformat()
        seen = hist_map.get(d["ip"], set())
        d["sparkline"]  = [1 if dt in seen else 0 for dt in dates]
        d["uptimePct"]  = round(sum(d["sparkline"]) / 7 * 100)
        d["isNew"]      = bool(d.get("is_new", 0))
        d["icon"]       = d.get("icon") or "unknown"
    return {
        "total":       len(devs),
        "active":      active,
        "free":        len(free_static) + len(free_dhcp),
        "lastScan":    ls.isoformat() if ls else None,
        "devices":     devs,
        "freeStaticIps": free_static,
        "freeDhcpIps":   free_dhcp,
        "config":      cfg,
    }

# ── Proxmox helpers ────────────────────────────────────────────────────────────

proxmox_routes.set_db(db)

async def _get_proxmox_hosts():
    c = db()
    if not c: return []
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM proxmox_hosts WHERE enabled=1")
    rows = cur.fetchall()
    cur.close(); c.close()
    return rows

pvc.set_hosts_getter(_get_proxmox_hosts)

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/api/version")
async def get_version():
    try:
        return {"version": VERSION_FILE.read_text().strip()}
    except Exception:
        return {"version": "unknown"}

@app.get("/api/check-update")
async def check_update():
    import httpx as _httpx
    try:
        local = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "unknown"
        async with _httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(
                "https://api.github.com/repos/Mati-l33t/lan-tracker-network-sonar/releases/latest",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "lan-tracker"}
            )
            r.raise_for_status()
            data = r.json()
            latest = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")
        return {"current": local, "latest": latest, "update_available": bool(latest and latest != local), "release_url": release_url}
    except Exception as e:
        local = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "unknown"
        return {"current": local, "latest": None, "update_available": False, "error": str(e)}

@app.post("/api/update")
async def do_update():
    update_script = BASE_DIR.parent / "update.sh"
    if not update_script.exists():
        raise HTTPException(404, "update.sh not found")
    subprocess.Popen(
        ["bash", str(update_script)],
        close_fds=True,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "updating", "message": "Update started — service will restart in a moment"}

@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard")

@app.get("/network/devices")
@app.get("/network/static")
@app.get("/network/dhcp")
async def network_page():
    return HTMLResponse(
        content=(BASE_DIR / "static" / "network.html").read_text(),
        headers={"Cache-Control": "no-cache"})

@app.get("/proxmox")
async def proxmox_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/proxmox/overview")

@app.get("/proxmox/overview")
@app.get("/proxmox/vmscontainers")
@app.get("/proxmox/storage")
@app.get("/proxmox/backups")
async def proxmox_page():
    return HTMLResponse(
        content=(BASE_DIR / "static" / "proxmox.html").read_text(),
        headers={"Cache-Control": "no-cache"})

@app.get("/settings")
async def settings_page():
    return HTMLResponse(
        content=(BASE_DIR / "static" / "settings.html").read_text(),
        headers={"Cache-Control": "no-cache"})

@app.get("/dashboard")
async def dashboard_page():
    return HTMLResponse(
        content=(BASE_DIR / "static" / "dashboard.html").read_text(),
        headers={"Cache-Control": "no-cache"})

@app.get("/static/{p:path}")
async def static_file(p: str):
    return FileResponse(BASE_DIR / "static" / p, headers={"Cache-Control": "no-cache"})

@app.get("/api/detect-network")
async def detect_network():
    return _detect_defaults()

@app.get("/api/config")
async def get_config(): return get_cfg()

@app.post("/api/config")
async def set_config(c: Cfg):
    save_cfg(c.subnet, c.staticStart, c.staticEnd, c.dhcpStart, c.dhcpEnd)
    return {"status": "ok"}

@app.get("/api/status")
async def get_status(): return status()

@app.post("/api/scan")
async def do_scan():
    cfg  = get_cfg()
    logger.info("Manual network scan started")
    devs = scan(cfg["subnet"])
    update_devs(devs, cfg)
    logger.info("Scan complete — %d device(s) found", len(devs))
    return {"status": "ok", "found": len(devs)}

@app.post("/api/device/name")
async def set_device_name(d: DevName):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute(
        "INSERT INTO devices(ip,custom_name,url,icon,status,type)VALUES(%s,%s,%s,%s,'active','static')"
        "ON DUPLICATE KEY UPDATE custom_name=VALUES(custom_name),url=VALUES(url),icon=VALUES(icon)",
        (d.ip, d.customName, d.url, d.icon or "unknown"))
    c.commit(); cur.close(); c.close()
    return {"status": "ok"}

@app.post("/api/ping")
async def do_ping(d: IpOnly):
    ms = ping_host(d.ip)
    return {"ip": d.ip, "ms": ms, "alive": ms is not None}

@app.get("/api/subtitle")
async def get_subtitle():
    c = db()
    if not c: return {"subtitle": "", "logo_url": None}
    cur = c.cursor()
    cur.execute("SELECT `key`, value FROM admin_config WHERE `key` IN ('subtitle','custom_logo')")
    rows = {r[0]: r[1] for r in cur.fetchall()}
    cur.close(); c.close()
    return {"subtitle": rows.get("subtitle", ""), "logo_url": rows.get("custom_logo") or None}

@app.post("/api/logo")
async def upload_logo(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 2 MB)")
    ext = Path(file.filename).suffix.lower() if file.filename else ".png"
    if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        ext = ".png"
    upload_dir = BASE_DIR / "static" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    fname = "custom_logo" + ext
    # remove any old custom_logo.* files first
    for old in upload_dir.glob("custom_logo.*"):
        old.unlink(missing_ok=True)
    (upload_dir / fname).write_bytes(content)
    url = "/static/uploads/" + fname
    c = db()
    if c:
        cur = c.cursor()
        cur.execute("INSERT INTO admin_config(`key`, value) VALUES('custom_logo', %s) ON DUPLICATE KEY UPDATE value=%s", (url, url))
        c.commit(); cur.close(); c.close()
    return {"url": url}

@app.delete("/api/logo")
async def delete_logo():
    upload_dir = BASE_DIR / "static" / "uploads"
    for old in upload_dir.glob("custom_logo.*"):
        old.unlink(missing_ok=True)
    c = db()
    if c:
        cur = c.cursor()
        cur.execute("DELETE FROM admin_config WHERE `key`='custom_logo'")
        c.commit(); cur.close(); c.close()
    return {"status": "ok"}

class SubtitleBody(BaseModel):
    subtitle: str = ""

@app.post("/api/subtitle")
async def set_subtitle(body: SubtitleBody):
    val = body.subtitle.strip()[:60]
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute(
        "INSERT INTO admin_config(`key`, value) VALUES('subtitle', %s) ON DUPLICATE KEY UPDATE value=%s",
        (val, val))
    c.commit(); cur.close(); c.close()
    return {"status": "ok"}

@app.get("/api/has-password")
async def has_password():
    return {"has_password": bool(auth.ADMIN_HASH)}

@app.get("/api/auth-settings")
async def get_auth_settings():
    c = db()
    if not c: return {"login_disabled": auth.LOGIN_DISABLED}
    cur = c.cursor()
    cur.execute("SELECT value FROM admin_config WHERE `key`='login_disabled'")
    row = cur.fetchone()
    cur.close(); c.close()
    return {"login_disabled": row[0] == "1" if row else False}

@app.post("/api/auth-settings")
async def set_auth_settings(body: AuthSettings):
    val = "1" if body.login_disabled else "0"
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute(
        "INSERT INTO admin_config(`key`, value) VALUES('login_disabled', %s) ON DUPLICATE KEY UPDATE value=%s",
        (val, val))
    c.commit(); cur.close(); c.close()
    auth.LOGIN_DISABLED = body.login_disabled
    return {"status": "ok"}

@app.post("/api/change-password")
async def change_password(body: PwChange):
    if auth.ADMIN_HASH and not auth.verify_password(body.currentPassword):
        raise HTTPException(400, "Current password is incorrect")
    if len(body.newPassword) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    new_hash = bcrypt.hashpw(body.newPassword.encode(), bcrypt.gensalt()).decode()
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute(
        "INSERT INTO admin_config(`key`, value) VALUES('admin_hash', %s) "
        "ON DUPLICATE KEY UPDATE value=%s",
        (new_hash, new_hash))
    c.commit(); cur.close(); c.close()
    auth.ADMIN_HASH = new_hash
    return {"status": "ok"}

@app.get("/api/dashboard/apps")
async def get_dashboard_apps():
    c = db()
    if not c: return []
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM dashboard_apps ORDER BY sort_order ASC, id ASC")
    rows = cur.fetchall()
    cur.execute("SELECT * FROM dashboard_tags")
    tag_map = {t["id"]: t for t in cur.fetchall()}
    cur.close(); c.close()
    for r in rows:
        if r.get("created_at"): r["created_at"] = r["created_at"].isoformat()
        tag_ids = json.loads(r.get("tags") or "[]")
        r["tags"] = [{"id": tid, "name": tag_map[tid]["name"], "color": tag_map[tid]["color"]}
                     for tid in tag_ids if tid in tag_map]
        r["category"] = r.get("category") or ""
        r["description"] = r.get("description") or ""
    return rows

@app.post("/api/dashboard/apps")
async def add_dashboard_app(body: DashboardApp):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM dashboard_apps")
    next_order = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO dashboard_apps(name,url,icon_type,icon_value,category,description,tags,sort_order,is_link) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (body.name, body.url, body.icon_type, body.icon_value or None,
         body.category or None, body.description or None,
         json.dumps(body.tags) if body.tags else None, next_order, body.is_link))
    new_id = cur.lastrowid
    c.commit(); cur.close(); c.close()
    return {"id": new_id}

@app.get("/api/dashboard/category-order")
async def get_category_order():
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("SELECT value FROM admin_config WHERE `key`='cat_order'")
    row = cur.fetchone()
    cur.close(); c.close()
    if row:
        import json as _json
        try: return {"order": _json.loads(row[0])}
        except Exception: pass
    return {"order": []}

@app.post("/api/dashboard/category-order")
async def set_category_order(body: CategoryOrder):
    import json as _json
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute(
        "INSERT INTO admin_config(`key`, value) VALUES('cat_order', %s) ON DUPLICATE KEY UPDATE value=%s",
        (_json.dumps(body.order), _json.dumps(body.order))
    )
    c.commit(); cur.close(); c.close()
    return {"ok": True}

@app.patch("/api/dashboard/reorder")
async def reorder_dashboard_apps(body: DashboardReorder):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    for i, app_id in enumerate(body.order):
        cur.execute("UPDATE dashboard_apps SET sort_order=%s WHERE id=%s", (i, app_id))
    c.commit(); cur.close(); c.close()
    return {"ok": True}

@app.put("/api/dashboard/apps/{app_id}")
async def update_dashboard_app(app_id: int, body: DashboardApp):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute(
        "UPDATE dashboard_apps SET name=%s,url=%s,icon_type=%s,icon_value=%s,category=%s,description=%s,tags=%s,is_link=%s WHERE id=%s",
        (body.name, body.url, body.icon_type, body.icon_value or None,
         body.category or None, body.description or None,
         json.dumps(body.tags) if body.tags else None, body.is_link, app_id))
    c.commit(); cur.close(); c.close()
    return {"ok": True}

@app.delete("/api/dashboard/apps/{app_id}")
async def delete_dashboard_app(app_id: int):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("SELECT icon_type,icon_value FROM dashboard_apps WHERE id=%s", (app_id,))
    row = cur.fetchone()
    cur.execute("DELETE FROM dashboard_apps WHERE id=%s", (app_id,))
    c.commit(); cur.close(); c.close()
    if row and row[0] == "custom" and row[1]:
        icons_dir = (BASE_DIR / "static" / "uploads" / "icons").resolve()
        icon_path = (BASE_DIR / row[1].lstrip("/")).resolve()
        try:
            icon_path.relative_to(icons_dir)
        except ValueError:
            logger.warning("Rejected out-of-bounds icon path: %s", row[1])
        else:
            try:
                icon_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Failed to delete dashboard icon: %s", row[1])
    return {"ok": True}

@app.post("/api/dashboard/upload-icon")
async def upload_dashboard_icon(file: UploadFile = File(...)):
    ALLOWED = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in ALLOWED:
        raise HTTPException(400, "Invalid file type")
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, "File too large — max 2 MB")
    upload_dir = BASE_DIR / "static" / "uploads" / "icons"
    upload_dir.mkdir(parents=True, exist_ok=True)
    fname = str(uuid.uuid4()) + ext
    (upload_dir / fname).write_bytes(content)
    return {"url": "/static/uploads/icons/" + fname}

@app.get("/api/dashboard/tags")
async def get_dashboard_tags():
    c = db()
    if not c: return []
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM dashboard_tags ORDER BY sort_order ASC, id ASC")
    rows = cur.fetchall()
    cur.close(); c.close()
    for r in rows:
        if r.get("created_at"): r["created_at"] = r["created_at"].isoformat()
    return rows

@app.post("/api/dashboard/tags")
async def add_dashboard_tag(body: DashboardTag):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM dashboard_tags")
    next_order = cur.fetchone()[0]
    cur.execute("INSERT INTO dashboard_tags(name,color,sort_order) VALUES(%s,%s,%s)",
                (body.name, body.color, next_order))
    new_id = cur.lastrowid
    c.commit(); cur.close(); c.close()
    return {"id": new_id, "name": body.name, "color": body.color}

@app.put("/api/dashboard/tags/{tag_id}")
async def update_dashboard_tag(tag_id: int, body: DashboardTag):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("UPDATE dashboard_tags SET name=%s,color=%s WHERE id=%s", (body.name, body.color, tag_id))
    c.commit(); cur.close(); c.close()
    return {"ok": True}

@app.delete("/api/dashboard/tags/{tag_id}")
async def delete_dashboard_tag(tag_id: int):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("DELETE FROM dashboard_tags WHERE id=%s", (tag_id,))
    cur.execute("SELECT id, tags FROM dashboard_apps WHERE tags IS NOT NULL AND tags != '[]'")
    rows = cur.fetchall()
    for row_id, tags_json in rows:
        try:
            tags = json.loads(tags_json or "[]")
            if tag_id in tags:
                tags = [t for t in tags if t != tag_id]
                cur.execute("UPDATE dashboard_apps SET tags=%s WHERE id=%s",
                            (json.dumps(tags) if tags else None, row_id))
        except Exception:
            logger.warning("Failed to update tags for app %s after tag delete", row_id)
    c.commit(); cur.close(); c.close()
    return {"ok": True}

@app.post("/api/dashboard/check-status")
async def check_dashboard_status(body: StatusBody):
    import httpx
    async def _check(item):
        try:
            async with httpx.AsyncClient(verify=False, timeout=3.0, follow_redirects=True) as c:
                await c.head(item.url)
            return {"id": item.id, "online": True}
        except Exception:
            return {"id": item.id, "online": False}
    results = await asyncio.gather(*[_check(i) for i in body.items])
    return list(results)

@app.get("/api/logs")
async def get_logs(since: float = 0):
    return [e for e in _LOG_BUFFER if e["ts"] > since]

@app.post("/api/device/ack")
async def ack_device(d: IpOnly):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("UPDATE devices SET is_new=0 WHERE ip=%s", (d.ip,))
    c.commit(); cur.close(); c.close()
    return {"status": "ok"}

@app.get("/api/widgets/config")
async def get_widget_config():
    c = db()
    if not c: return {"clock": True, "network": True, "proxmox": True}
    cur = c.cursor(dictionary=True)
    cur.execute("SELECT `key`, value FROM admin_config WHERE `key` IN ('widget_clock','widget_network','widget_proxmox')")
    rows = {r["key"]: r["value"] for r in cur.fetchall()}
    cur.close(); c.close()
    return {
        "clock":   rows.get("widget_clock",   "1") == "1",
        "network": rows.get("widget_network",  "1") == "1",
        "proxmox": rows.get("widget_proxmox",  "1") == "1",
    }

@app.patch("/api/widgets/config")
async def patch_widget_config(body: WidgetConfigPatch):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    mapping = {"clock": "widget_clock", "network": "widget_network", "proxmox": "widget_proxmox"}
    updates = body.model_dump(exclude_none=True)
    for field, key in mapping.items():
        if field in updates:
            val = "1" if updates[field] else "0"
            cur.execute(
                "INSERT INTO admin_config(`key`, value) VALUES(%s, %s) ON DUPLICATE KEY UPDATE value=%s",
                (key, val, val))
    c.commit(); cur.close(); c.close()
    return await get_widget_config()

@app.get("/api/widgets/network")
async def get_widget_network():
    c = db()
    if not c: return {"total": 0, "online": 0, "offline": 0, "new_devices": 0, "last_scan": None}
    cur = c.cursor(dictionary=True)
    cur.execute("""
        SELECT COUNT(*) AS total,
               SUM(status='active') AS online,
               SUM(is_new=1) AS new_devices,
               MAX(last_seen) AS last_scan
        FROM devices
    """)
    row = cur.fetchone()
    cur.close(); c.close()
    total = int(row["total"] or 0)
    online = int(row["online"] or 0)
    return {
        "total":       total,
        "online":      online,
        "offline":     total - online,
        "new_devices": int(row["new_devices"] or 0),
        "last_scan":   row["last_scan"].isoformat() if row["last_scan"] else None,
    }

@app.get("/api/widgets/proxmox")
async def get_widget_proxmox():
    return {"hosts": proxmox_routes.get_widget_summary()}

async def _daily_scan_loop():
    """Run a network scan once per day to populate 7-day activity history."""
    await asyncio.sleep(60)  # wait 1 min after startup before first auto-scan
    while True:
        try:
            cfg  = get_cfg()
            logger.info("Daily auto-scan started")
            devs = scan(cfg["subnet"])
            update_devs(devs, cfg)
            logger.info("Daily auto-scan complete — %d device(s) found", len(devs))
        except Exception as e:
            logger.error(f"Auto-scan failed: {e}")
        await asyncio.sleep(86400)  # 24 hours

@app.on_event("startup")
async def on_startup():
    if _buf_handler not in logging.getLogger().handlers:
        logging.getLogger().addHandler(_buf_handler)
        logging.getLogger().setLevel(logging.INFO)
    init()
    try:
        version = VERSION_FILE.read_text().strip()
    except Exception:
        version = "unknown"
    logger.info("HomeLab Sonar v%s started", version)
    asyncio.create_task(pvc.start_polling_loop(interval=30))
    asyncio.create_task(_daily_scan_loop())

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("LT_PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
