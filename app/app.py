#!/usr/bin/env python3
import os, ipaddress
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
import mysql.connector, subprocess, re, socket, struct
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pydantic import BaseModel

BASE_DIR    = Path(__file__).parent
VERSION_FILE = BASE_DIR.parent / "VERSION"

app = FastAPI()

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
                    net  = ipaddress.ip_network(net_str, strict=False)
                    base = str(net.network_address).rsplit(".", 1)[0]
                    return {
                        "subnet":       net_str,
                        "static_start": f"{base}.2",
                        "static_end":   f"{base}.99",
                        "dhcp_start":   f"{base}.100",
                        "dhcp_end":     f"{base}.200",
                    }
    except Exception:
        pass
    return {
        "subnet":       "192.168.1.0/24",
        "static_start": "192.168.1.2",
        "static_end":   "192.168.1.99",
        "dhcp_start":   "192.168.1.100",
        "dhcp_end":     "192.168.1.200",
    }

DEFAULT = _detect_defaults()

class Cfg(BaseModel):
    subnet:str; staticStart:str; staticEnd:str; dhcpStart:str; dhcpEnd:str
class DevName(BaseModel):
    ip:str; customName:str; url:str=""; icon:str=""
class IpOnly(BaseModel):
    ip:str

def db():
    try: return mysql.connector.connect(**_db_cfg())
    except: return None

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
    try: return [socket.inet_ntoa(struct.pack("!I", i)) for i in range(ip2int(s), ip2int(e)+1)]
    except: return []

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
    except Exception as e:
        print(e); return []

def hostname(ip):
    try: return socket.gethostbyaddr(ip)[0]
    except: return ""

def ping_host(ip):
    try:
        res = subprocess.run(["ping","-c","1","-W","2",ip], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if 'time=' in line:
                    return round(float(line.split('time=')[1].split()[0]), 1)
        return None
    except: return None

def scan_ports(ip):
    common_ports = [21,22,23,25,53,80,110,443,3389,8080]
    def check(port):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            open_ = s.connect_ex((ip, port)) == 0
            s.close()
            return port if open_ else None
        except: return None
    with ThreadPoolExecutor(max_workers=10) as ex:
        return [p for p in ex.map(check, common_ports) if p is not None]

def ip_type(ip, ss, se, ds, de):
    if not ss or not se or not ds or not de: return "dhcp"
    try:
        n = ip2int(ip)
        if ip2int(ss) <= n <= ip2int(se): return "static"
        if ip2int(ds) <= n <= ip2int(de): return "dhcp"
    except: pass
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
    cur.execute("SELECT ip,DATE_FORMAT(scan_date,'%%Y-%%m-%%d') as d FROM device_history WHERE scan_date>=%s", (dates[0],))
    hist_map = {}
    for row in cur.fetchall():
        hist_map.setdefault(row["ip"], set()).add(row["d"])
    cur.close(); c.close()
    static_ips = ips_range(cfg["staticStart"], cfg["staticEnd"])
    dhcp_ips   = ips_range(cfg["dhcpStart"],   cfg["dhcpEnd"])
    used       = {d["ip"] for d in devs if d["status"] == "active"}
    free_static = [ip for ip in static_ips if ip not in used]
    free_dhcp   = [ip for ip in dhcp_ips   if ip not in used]
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
        "total":       len(static_ips) + len(dhcp_ips),
        "active":      active,
        "free":        len(free_static) + len(free_dhcp),
        "lastScan":    ls.isoformat() if ls else None,
        "devices":     devs,
        "freeStaticIps": free_static,
        "freeDhcpIps":   free_dhcp,
        "config":      cfg,
    }

# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/api/version")
async def get_version():
    try:
        return {"version": VERSION_FILE.read_text().strip()}
    except:
        return {"version": "unknown"}

@app.get("/")
async def root():
    return HTMLResponse(
        content=(BASE_DIR / "static" / "index.html").read_text(),
        headers={"Cache-Control": "no-cache"})

@app.get("/static/{p}")
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
    devs = scan(cfg["subnet"])
    update_devs(devs, cfg)
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

@app.post("/api/device/ack")
async def ack_device(d: IpOnly):
    c = db()
    if not c: raise HTTPException(500, "DB fail")
    cur = c.cursor()
    cur.execute("UPDATE devices SET is_new=0 WHERE ip=%s", (d.ip,))
    c.commit(); cur.close(); c.close()
    return {"status": "ok"}

@app.on_event("startup")
def on_startup(): init()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("LT_PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
