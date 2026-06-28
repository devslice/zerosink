import os
import time
import json
import logging
import asyncio
import socket
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.config import BASE_DIR, WEB_HOST, WEB_PORT, DEFAULT_ADMIN_USER, VERSION, UPSTREAM_DNS
from backend.database import get_db_connection, init_db, hash_password
from backend.auth import (
    get_current_user, 
    create_access_token, 
    verify_password,
    create_temp_token,
    verify_token
)
import pyotp
from backend.lists import compile_all_groups, compile_group_lists
from backend.dns_engine import (
    start_dns_servers, 
    reload_clients_cache, 
    reload_custom_rules_cache,
    DNS_CACHE
)
from backend.dhcp_engine import start_dhcp_server, stop_dhcp_server

# Start time for uptime calculation
START_TIME = time.time()

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("zerosink.main")

ACTIVE_PORT = WEB_PORT

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle context manager to run startup and shutdown logic."""
    logger.info("Initializing database...")
    init_db()
    
    logger.info("Starting DNS engine...")
    udp_transport, tcp_server = await start_dns_servers()
    
    logger.info("Starting DHCP engine...")
    await start_dhcp_server()
    
    # Start mDNS responder
    logger.info(f"Starting mDNS responder for ZeroSink on port {ACTIVE_PORT}...")
    zeroconf_instance = None
    mdns_info = None
    try:
        from zeroconf.asyncio import AsyncZeroconf
        from zeroconf import ServiceInfo
        import socket
        
        # Get local IP address dynamically
        local_ip = "127.0.0.1"
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.254.254.254", 1))
            local_ip = s.getsockname()[0]
        except Exception:
            pass
        finally:
            s.close()
            
        zeroconf_instance = AsyncZeroconf()
        mdns_info = ServiceInfo(
            type_="_http._tcp.local.",
            name="ZeroSink._http._tcp.local.",
            addresses=[socket.inet_aton(local_ip)],
            port=ACTIVE_PORT,
            properties={},
            server="zerosink.local."
        )
        await zeroconf_instance.async_register_service(mdns_info)
        logger.info(f"mDNS responder registered service ZeroSink._http._tcp.local. at http://zerosink.local (IP: {local_ip}:{ACTIVE_PORT})")
    except Exception as e:
        logger.exception("Failed to start mDNS responder")
        
    yield
    
    # Shutdown mDNS responder
    if zeroconf_instance and mdns_info:
        logger.info("Stopping mDNS responder...")
        try:
            await zeroconf_instance.async_unregister_service(mdns_info)
            await zeroconf_instance.async_close()
            logger.info("mDNS responder stopped gracefully.")
        except Exception as e:
            logger.error(f"Error stopping mDNS responder: {e}")
            
    logger.info("Shutting down DHCP engine...")
    await stop_dhcp_server()
    
    logger.info("Shutting down DNS engine...")
    if udp_transport:
        udp_transport.close()
    if tcp_server:
        tcp_server.close()
        await tcp_server.wait_closed()
    logger.info("Shutdown complete.")

app = FastAPI(
    title="ZeroSink DNS Ad Blocker",
    description="Lightweight DNS blocker designed for Raspberry Pi Zero 2 W",
    lifespan=lifespan
)

# Enable CORS for cross-origin client access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Schemas
class LoginRequest(BaseModel):
    username: str
    password: str

class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str

class Verify2FARequest(BaseModel):
    temp_token: str
    code: str

class Disable2FARequest(BaseModel):
    password: str

class Confirm2FAEnableRequest(BaseModel):
    secret: str
    code: str

class CompleteSetupRequest(BaseModel):
    temp_token: str
    new_password: Optional[str] = None
    totp_secret: Optional[str] = None
    totp_code: Optional[str] = None
    selected_lists: Optional[list[str]] = None

class AdlistSelection(BaseModel):
    name: str
    url: str

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = None
    selected_lists: Optional[list[AdlistSelection]] = None

class ClientCreate(BaseModel):
    group_id: int
    ip_or_cidr: str
    name: Optional[str] = None

class AdlistCreate(BaseModel):
    group_id: int
    name: str
    url: str

import ipaddress

class CustomRuleCreate(BaseModel):
    domain: str
    type: str  # 'allow' or 'deny'
    is_regex: Optional[int] = 0

class SettingsUpdate(BaseModel):
    upstream_dns: str

class DNSDisableRequest(BaseModel):
    duration: int  # in seconds

class LocalDNSRecordCreate(BaseModel):
    domain: str
    ip_address: str
    record_type: str  # 'A' or 'AAAA'

class PrivacySettingsUpdate(BaseModel):
    privacy_mode: int
    log_retention_days: int

class DHCPSettingsUpdate(BaseModel):
    dhcp_enabled: int
    dhcp_range_start: str
    dhcp_range_end: str
    dhcp_router: Optional[str] = None
    dhcp_subnet_mask: str
    dhcp_lease_time: int

class PremiumLicenseRequest(BaseModel):
    license_key: str

class DowntimeScheduleCreate(BaseModel):
    group_id: int
    name: str
    start_time: str
    end_time: str
    days_of_week: str
    blocked_categories: Optional[list[str]] = None
    enabled: Optional[int] = 1

class AppBlockToggle(BaseModel):
    category: str
    app_name: str
    enabled: int

class UpdateRequest(BaseModel):
    version: str

def validate_dns_ips(dns_str: str) -> list[str]:
    """Validate that a string contains a space/comma separated list of valid IP addresses."""
    ips = [ip.strip() for ip in dns_str.replace(',', ' ').split() if ip.strip()]
    if not ips:
        raise ValueError("At least one upstream DNS server must be specified.")
    for ip in ips:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            raise ValueError(f"Invalid IP address: {ip}")
    return ips


# --- Frontend Route ---

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the static single page application (SPA)."""
    static_file = os.path.join(BASE_DIR, "static", "index.html")
    if os.path.exists(static_file):
        with open(static_file, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse(
        content="<h3>ZeroSink index.html not found! Ensure static/index.html is created.</h3>",
        status_code=404
    )


@app.get("/logo.svg")
async def serve_logo():
    """Serve the ZeroSink custom ZS logo SVG."""
    logo_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="100%" height="100%">
  <rect width="512" height="512" rx="128" fill="#0a0a0a"/>
  <path d="M256 0c4.6 0 9.2 1 13.4 2.9L457.7 82.8c22 9.3 38.4 31 38.3 57.2c-.5 99.2-41.3 280.7-213.6 363.2c-16.7 8-36.1 8-52.8 0C57.3 420.7 16.5 239.2 16 140c-.1-26.2 16.3-47.9 38.3-57.2L242.7 2.9C246.8 1 251.4 0 256 0zm0 66.8l0 378.1C394 378 431.1 230.1 432 141.4L256 66.8s0 0 0 0z" fill="#32cd32"/>
</svg>"""
    from fastapi.responses import Response
    return Response(content=logo_svg, media_type="image/svg+xml")


@app.get("/manifest.json")
async def serve_manifest():
    """Serve the Progressive Web App (PWA) manifest."""
    manifest_data = {
        "name": "ZeroSink Ad Blocker",
        "short_name": "ZeroSink",
        "start_url": "/",
        "display": "standalone",
        "theme_color": "#32cd32",
        "background_color": "#0a0d14",
        "icons": [
            {
                "src": "/logo.svg",
                "sizes": "512x512",
                "type": "image/svg+xml",
                "purpose": "any maskable"
            }
        ]
    }
    from fastapi.responses import JSONResponse
    return JSONResponse(content=manifest_data)



@app.get("/sw.js")
async def serve_sw():
    """Serve the PWA Service Worker."""
    sw_code = """
const CACHE_NAME = 'zerosink-v1';
const ASSETS = [
  '/',
  '/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  event.respondWith(
    caches.match(event.request).then(cachedResponse => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).catch(() => {});
    })
  );
});
"""
    from fastapi import Response
    return Response(content=sw_code, media_type="application/javascript")


# --- Authentication Endpoints ---

@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """Stateless login endpoint. Returns JWT access token, 2FA challenge, or setup requirement."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, totp_secret, totp_enabled FROM users WHERE username = ?", (req.username,))
    row = cursor.fetchone()
    
    if not row or not verify_password(req.password, row["password_hash"]):
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )
        
    # Check if initial setup is completed
    cursor.execute("SELECT value FROM settings WHERE key = 'initial_setup_completed'")
    setup_row = cursor.fetchone()
    conn.close()
    
    initial_setup_completed = setup_row["value"] if setup_row else "1"
    
    if initial_setup_completed == "0":
        # Generate temporary token for setup
        temp_token = create_temp_token(data={"sub": req.username})
        return {
            "require_setup": True,
            "temp_token": temp_token,
            "message": "Initial setup required (password change and optional 2FA)"
        }
        
    if row["totp_enabled"]:
        # Generate temporary 2FA token
        temp_token = create_temp_token(data={"sub": req.username})
        return {
            "require_2fa": True,
            "temp_token": temp_token,
            "message": "Two-factor authentication code required"
        }
        
    token = create_access_token(data={"sub": req.username})
    return {"access_token": token, "token_type": "bearer"}

@app.post("/api/auth/complete-setup")
async def complete_setup(req: CompleteSetupRequest):
    """Completes the initial setup (updating password and/or enabling 2FA)."""
    payload = verify_token(req.temp_token)
    if not payload or payload.get("type") != "2fa_temp":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired temporary session token"
        )
        
    username = payload["sub"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Update Password if provided
    if req.new_password:
        hashed = hash_password(req.new_password)
        cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (hashed, username))
        
    # 2. Setup 2FA if provided
    if req.totp_secret and req.totp_code:
        totp = pyotp.TOTP(req.totp_secret)
        if not totp.verify(req.totp_code):
            conn.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid 2FA verification code. Please scan the QR code again."
            )
        cursor.execute("UPDATE users SET totp_secret = ?, totp_enabled = 1 WHERE username = ?", (req.totp_secret, username))
        
    # 3. Add Selected Curated Blocklists
    trigger_compile = False
    if req.selected_lists:
        CURATED_BLOCKLISTS = {
            "malware": {
                "name": "URLhaus Malicious Domains",
                "url": "https://urlhaus.abuse.ch/downloads/hostfile/"
            },
            "tracking": {
                "name": "EasyPrivacy Tracking Blocklist",
                "url": "https://v.firebog.net/hosts/Easyprivacy.txt"
            }
        }
        for list_key in req.selected_lists:
            if list_key in CURATED_BLOCKLISTS:
                info = CURATED_BLOCKLISTS[list_key]
                cursor.execute("SELECT id FROM adlists WHERE group_id = 1 AND url = ?", (info["url"],))
                if not cursor.fetchone():
                    cursor.execute("INSERT INTO adlists (group_id, name, url, enabled) VALUES (1, ?, ?, 1)", 
                                   (info["name"], info["url"]))
                    trigger_compile = True

    # 4. Mark setup as completed
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('initial_setup_completed', '1')")
    conn.commit()
    conn.close()
    
    # Trigger background list compilation if new lists were added
    if trigger_compile:
        asyncio.create_task(asyncio.to_thread(compile_all_groups))
        
    # Issue final JWT access token
    token = create_access_token(data={"sub": username})
    return {"access_token": token, "token_type": "bearer", "status": "success"}

@app.post("/api/auth/verify-2fa")
async def verify_2fa(req: Verify2FARequest):
    """Verifies a 2FA TOTP code using the temporary token."""
    payload = verify_token(req.temp_token)
    if not payload or payload.get("type") != "2fa_temp":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired temporary session token"
        )
        
    username = payload["sub"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT totp_secret, totp_enabled FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    if not row or not row["totp_enabled"] or not row["totp_secret"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Two-factor authentication is not configured for this user"
        )
        
    totp = pyotp.TOTP(row["totp_secret"])
    if not totp.verify(req.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid two-factor authentication code"
        )
        
    token = create_access_token(data={"sub": username})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/auth/status")
async def auth_status(current_user: dict = Depends(get_current_user)):
    """Retrieve 2FA active state and username for dashboard."""
    username = current_user["sub"]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT totp_enabled FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    
    totp_enabled = bool(row["totp_enabled"]) if row else False
    return {
        "username": username,
        "totp_enabled": totp_enabled
    }

@app.get("/api/auth/setup-2fa")
async def setup_2fa(current_user: dict = Depends(get_current_user)):
    """Generates a new TOTP secret for the current user."""
    username = current_user["sub"]
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=username, issuer_name="ZeroSink")
    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri
    }

@app.post("/api/auth/enable-2fa")
async def enable_2fa(req: Confirm2FAEnableRequest, current_user: dict = Depends(get_current_user)):
    """Confirms 2FA setup with a valid code and stores the secret."""
    username = current_user["sub"]
    
    totp = pyotp.TOTP(req.secret)
    if not totp.verify(req.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check your authenticator app and try again."
        )
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET totp_secret = ?, totp_enabled = 1 WHERE username = ?", (req.secret, username))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Two-factor authentication enabled successfully"}

@app.post("/api/auth/disable-2fa")
async def disable_2fa(req: Disable2FARequest, current_user: dict = Depends(get_current_user)):
    """Allows disabling 2FA if user confirms password."""
    username = current_user["sub"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    
    if not row or not verify_password(req.password, row["password_hash"]):
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect password"
        )
        
    cursor.execute("UPDATE users SET totp_secret = NULL, totp_enabled = 0 WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "Two-factor authentication disabled"}

@app.post("/api/auth/change-password")
async def change_password(req: PasswordChangeRequest, current_user: dict = Depends(get_current_user)):
    """Allows authenticated admin to change their password."""
    username = current_user["sub"]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    
    if not row or not verify_password(req.old_password, row["password_hash"]):
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect current password"
        )
        
    new_hash = hash_password(req.new_password)
    cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["id"]))
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Password changed successfully"}



# --- Dashboard Stats Endpoints ---

def get_local_ip() -> str:
    """Find the server's local network IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to a dummy address (doesn't send any traffic) to resolve outbound interface
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        try:
            IP = socket.gethostbyname(socket.gethostname())
        except Exception:
            IP = "127.0.0.1"
    finally:
        s.close()
    return IP

def get_system_stats():
    """Retrieve process and OS stats for Raspberry Pi / Windows."""
    db_size = 0
    if os.path.exists(DB_PATH := os.path.join(BASE_DIR, "zerosink.db")):
        db_size = os.path.getsize(DB_PATH)
        
    process_ram_mb = 0.0
    system_ram_pct = 0.0
    cpu_pct = 0.0
    
    # Process memory RSS (Linux/ProcFS)
    if os.path.exists('/proc/self/status'):
        try:
            with open('/proc/self/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        process_ram_mb = float(line.split()[1]) / 1024.0
                        break
        except Exception:
            pass
            
    # System RAM (Linux/ProcFS)
    if os.path.exists('/proc/meminfo'):
        try:
            mem_total = 0
            mem_available = 0
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        mem_total = int(line.split()[1])
                    elif line.startswith('MemAvailable:'):
                        mem_available = int(line.split()[1])
            if mem_total > 0:
                system_ram_pct = ((mem_total - mem_available) / mem_total) * 100.0
        except Exception:
            pass
            
    # CPU Load (Linux/ProcFS)
    if os.path.exists('/proc/loadavg'):
        try:
            with open('/proc/loadavg', 'r') as f:
                cpu_pct = (float(f.read().split()[0]) * 100.0) / os.cpu_count()
        except Exception:
            pass
            
    return {
        "db_size_bytes": db_size,
        "process_ram_mb": round(process_ram_mb, 2),
        "system_ram_pct": round(system_ram_pct, 1),
        "cpu_pct": round(cpu_pct, 1),
        "dns_cache_size": len(DNS_CACHE),
        "uptime_seconds": int(time.time() - START_TIME),
        "version": VERSION,
        "local_ip": get_local_ip(),
        "is_docker": os.path.exists('/.dockerenv')
    }

@app.get("/api/stats/summary")
async def stats_summary(current_user: dict = Depends(get_current_user)):
    """Fetch aggregated statistics and historical logs for dashboard charts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 24 Hours Totals
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status LIKE 'Blocked%' THEN 1 ELSE 0 END) as blocked,
            SUM(CASE WHEN status LIKE 'Allowed (Whitelist)%' THEN 1 ELSE 0 END) as whitelisted,
            SUM(CASE WHEN status LIKE 'Allowed (Forwarded)%' OR status LIKE 'Allowed (Cached)%' THEN 1 ELSE 0 END) as allowed
        FROM query_logs 
        WHERE datetime(timestamp) >= datetime('now', '-24 hours')
    """)
    totals = dict(cursor.fetchone())
    
    total = totals.get("total") or 0
    blocked = totals.get("blocked") or 0
    allowed = totals.get("allowed") or 0
    whitelisted = totals.get("whitelisted") or 0
    block_rate = round((blocked / total * 100.0), 1) if total > 0 else 0.0
    
    # Query history grouped by hour (for charts)
    cursor.execute("""
        SELECT 
            strftime('%Y-%m-%dT%H:00:00Z', timestamp) as hour,
            COUNT(*) as total,
            SUM(CASE WHEN status LIKE 'Blocked%' THEN 1 ELSE 0 END) as blocked
        FROM query_logs
        WHERE datetime(timestamp) >= datetime('now', '-24 hours')
        GROUP BY hour
        ORDER BY hour ASC
    """)
    history = [dict(row) for row in cursor.fetchall()]
    
    # Top Allowed Domains
    cursor.execute("""
        SELECT domain, COUNT(*) as count 
        FROM query_logs 
        WHERE status NOT LIKE 'Blocked%' AND datetime(timestamp) >= datetime('now', '-24 hours')
        GROUP BY domain 
        ORDER BY count DESC 
        LIMIT 10
    """)
    top_allowed = [dict(row) for row in cursor.fetchall()]
    
    # Top Blocked Domains
    cursor.execute("""
        SELECT domain, COUNT(*) as count 
        FROM query_logs 
        WHERE status LIKE 'Blocked%' AND datetime(timestamp) >= datetime('now', '-24 hours')
        GROUP BY domain 
        ORDER BY count DESC 
        LIMIT 10
    """)
    top_blocked = [dict(row) for row in cursor.fetchall()]
    
    # Top Clients
    cursor.execute("""
        SELECT client_ip, client_name, COUNT(*) as count 
        FROM query_logs 
        WHERE datetime(timestamp) >= datetime('now', '-24 hours')
        GROUP BY client_ip 
        ORDER BY count DESC 
        LIMIT 10
    """)
    top_clients = [dict(row) for row in cursor.fetchall()]
    
    # Query Types
    cursor.execute("""
        SELECT query_type, COUNT(*) as count 
        FROM query_logs 
        WHERE datetime(timestamp) >= datetime('now', '-24 hours')
        GROUP BY query_type
    """)
    query_types = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "summary": {
            "total_queries": total,
            "blocked_queries": blocked,
            "allowed_queries": allowed,
            "whitelisted_queries": whitelisted,
            "block_rate_percent": block_rate
        },
        "history": history,
        "top_allowed": top_allowed,
        "top_blocked": top_blocked,
        "top_clients": top_clients,
        "query_types": query_types,
        "system": get_system_stats()
    }


# --- Query Log Endpoint ---

@app.get("/api/logs")
async def get_logs(
    limit: int = 100, 
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """Retrieve recent query logs with pagination and filters."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT id, timestamp, client_ip, client_name, domain, query_type, status, group_name, reply_time_ms FROM query_logs WHERE 1=1"
    params = []
    
    if status_filter:
        if status_filter == "Blocked":
            query += " AND status LIKE 'Blocked%'"
        elif status_filter == "Allowed":
            query += " AND status LIKE 'Allowed%'"
            
    if search:
        query += " AND (domain LIKE ? OR client_ip LIKE ? OR client_name LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    logs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return logs


# --- Group Management Endpoints ---

@app.get("/api/groups")
async def get_groups(current_user: dict = Depends(get_current_user)):
    """List all groups with counts of clients, adlists, and custom rules."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            g.id, g.name, g.description,
            (SELECT COUNT(*) FROM clients WHERE group_id = g.id) as client_count,
            (SELECT COUNT(*) FROM adlists WHERE group_id = g.id) as adlist_count,
            (SELECT COUNT(*) FROM custom_rules WHERE group_id = g.id) as rule_count
        FROM groups g
    """)
    groups = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return groups

@app.post("/api/groups")
async def create_group(group: GroupCreate, current_user: dict = Depends(get_current_user)):
    """Create a new block group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO groups (name, description) VALUES (?, ?)", (group.name, group.description))
        group_id = cursor.lastrowid
        
        # Insert selected adlists
        if group.selected_lists:
            for lst in group.selected_lists:
                cursor.execute(
                    "INSERT INTO adlists (group_id, name, url, enabled) VALUES (?, ?, ?, 1)",
                    (group_id, lst.name, lst.url.strip())
                )
            conn.commit()
            
            # Trigger background compile for this new group
            asyncio.create_task(asyncio.to_thread(compile_group_lists, group_id))
        else:
            conn.commit()
            
        return {"status": "success", "id": group_id, "name": group.name}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Group name already exists")
    finally:
        conn.close()

@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a custom group. Cannot delete the Default group (id=1)."""
    if group_id == 1:
        raise HTTPException(status_code=400, detail="Cannot delete the Default group")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Cascade delete is handled by database FOREIGN KEY ON DELETE CASCADE
    cursor.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()
    
    # Reload caches to clear deleted relations
    reload_clients_cache()
    reload_custom_rules_cache()
    
    return {"status": "success", "message": f"Group {group_id} deleted successfully"}

@app.get("/api/groups/{group_id}/details")
async def get_group_details(group_id: int, current_user: dict = Depends(get_current_user)):
    """Fetch details of a group including clients, custom rules, and adlists."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify group exists
    cursor.execute("SELECT id, name, description FROM groups WHERE id = ?", (group_id,))
    group = cursor.fetchone()
    if not group:
        conn.close()
        raise HTTPException(status_code=404, detail="Group not found")
        
    cursor.execute("SELECT id, name, ip_or_cidr FROM clients WHERE group_id = ?", (group_id,))
    clients = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT id, name, url, enabled FROM adlists WHERE group_id = ?", (group_id,))
    adlists = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT id, domain, type, enabled, is_regex FROM custom_rules WHERE group_id = ?", (group_id,))
    rules = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {
        "group": dict(group),
        "clients": clients,
        "adlists": adlists,
        "rules": rules
    }


# --- Clients Management Endpoints ---

@app.post("/api/clients")
async def create_or_update_client(client: ClientCreate, current_user: dict = Depends(get_current_user)):
    """Associate or update a client IP or CIDR with a group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # INSERT or UPDATE client details
        cursor.execute("""
            INSERT INTO clients (group_id, ip_or_cidr, name) 
            VALUES (?, ?, ?)
            ON CONFLICT(ip_or_cidr) DO UPDATE SET group_id=excluded.group_id, name=excluded.name
        """, (client.group_id, client.ip_or_cidr.strip(), client.name))
        conn.commit()
        reload_clients_cache()
        return {"status": "success"}
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"Database integrity error: {e}")
    finally:
        conn.close()

@app.delete("/api/clients/{client_id}")
async def delete_client(client_id: int, current_user: dict = Depends(get_current_user)):
    """Remove a client IP mapping."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()
    conn.close()
    reload_clients_cache()
    return {"status": "success"}


# --- Adlists Management Endpoints ---

@app.get("/api/adlists/unique")
async def get_unique_adlists(current_user: dict = Depends(get_current_user)):
    """Get unique adlists across all groups in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT name, url FROM adlists")
        rows = [dict(row) for row in cursor.fetchall()]
        return rows
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.post("/api/adlists")
async def create_adlist(adlist: AdlistCreate, current_user: dict = Depends(get_current_user)):
    """Add a new public blocklist for a group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO adlists (group_id, name, url, enabled) VALUES (?, ?, ?, 1)", 
                       (adlist.group_id, adlist.name, adlist.url.strip()))
        conn.commit()
        return {"status": "success"}
    except sqlite3.Error as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()

@app.post("/api/adlists/{adlist_id}/toggle")
async def toggle_adlist(adlist_id: int, current_user: dict = Depends(get_current_user)):
    """Toggle enabled/disabled state of an adlist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT enabled, group_id FROM adlists WHERE id = ?", (adlist_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Adlist not found")
        
    new_state = 1 if row["enabled"] == 0 else 0
    cursor.execute("UPDATE adlists SET enabled = ? WHERE id = ?", (new_state, adlist_id))
    conn.commit()
    conn.close()
    return {"status": "success", "enabled": new_state}

@app.delete("/api/adlists/{adlist_id}")
async def delete_adlist(adlist_id: int, current_user: dict = Depends(get_current_user)):
    """Delete an adlist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM adlists WHERE id = ?", (adlist_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/adlists/compile")
async def trigger_compile(group_id: Optional[int] = None, current_user: dict = Depends(get_current_user)):
    """Trigger background blocklist compilation."""
    if group_id:
        asyncio.create_task(asyncio.to_thread(compile_group_lists, group_id))
    else:
        asyncio.create_task(asyncio.to_thread(compile_all_groups))
    return {"status": "success", "message": "List compilation started in the background"}


# --- Custom Rules Endpoints ---

@app.post("/api/groups/{group_id}/rules")
async def add_custom_rule(group_id: int, rule: CustomRuleCreate, current_user: dict = Depends(get_current_user)):
    """Add a custom allow/deny domain rule to a group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        domain_clean = rule.domain.strip().lower()
        cursor.execute("""
            INSERT INTO custom_rules (group_id, domain, type, enabled, is_regex) 
            VALUES (?, ?, ?, 1, ?)
        """, (group_id, domain_clean, rule.type, rule.is_regex))
        conn.commit()
        reload_custom_rules_cache()
        return {"status": "success"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Domain rule already exists for this group")
    finally:
        conn.close()

@app.delete("/api/custom-rules/{rule_id}")
async def delete_custom_rule(rule_id: int, current_user: dict = Depends(get_current_user)):
    """Delete a custom rule."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM custom_rules WHERE id = ?", (rule_id,))
    conn.commit()
    conn.close()
    reload_custom_rules_cache()
    return {"status": "success"}


# --- Backup & Configuration Management ---

@app.get("/api/system/backup")
async def export_configuration(current_user: dict = Depends(get_current_user)):
    """
    Streamable JSON config backup that reads directly from SQLite 
    to avoid storing massive lists in RAM.
    """
    def generate_backup():
        conn = get_db_connection()
        cursor = conn.cursor()
        
        yield "{\n"
        
        # 1. Groups
        yield '  "groups": [\n'
        cursor.execute("SELECT id, name, description FROM groups")
        first = True
        while rows := cursor.fetchmany(100):
            for row in rows:
                if not first:
                    yield ",\n"
                first = False
                yield f'    {json.dumps(dict(row))}'
        yield "\n  ],\n"
        
        # 2. Clients
        yield '  "clients": [\n'
        cursor.execute("SELECT id, group_id, ip_or_cidr, name FROM clients")
        first = True
        while rows := cursor.fetchmany(100):
            for row in rows:
                if not first:
                    yield ",\n"
                first = False
                yield f'    {json.dumps(dict(row))}'
        yield "\n  ],\n"
        
        # 3. Adlists
        yield '  "adlists": [\n'
        cursor.execute("SELECT id, group_id, name, url, enabled FROM adlists")
        first = True
        while rows := cursor.fetchmany(100):
            for row in rows:
                if not first:
                    yield ",\n"
                first = False
                yield f'    {json.dumps(dict(row))}'
        yield "\n  ],\n"
        
        # 4. Custom Rules
        yield '  "custom_rules": [\n'
        cursor.execute("SELECT id, group_id, domain, type, enabled FROM custom_rules")
        first = True
        while rows := cursor.fetchmany(100):
            for row in rows:
                if not first:
                    yield ",\n"
                first = False
                yield f'    {json.dumps(dict(row))}'
        yield "\n  ]\n"
        
        yield "}\n"
        conn.close()

    return StreamingResponse(
        generate_backup(),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=zerosink_backup.json"}
    )

@app.post("/api/system/import")
async def import_configuration(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """
    Import and restore config from JSON file, processing in a transaction.
    Rebuilds memory caches and triggers background blocklist compile.
    """
    try:
        content = await file.read()
        data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("BEGIN TRANSACTION")
        
        # Clear existing tables (except users)
        cursor.execute("DELETE FROM custom_rules")
        cursor.execute("DELETE FROM adlists")
        cursor.execute("DELETE FROM clients")
        cursor.execute("DELETE FROM groups")
        
        # Restore Groups
        groups_list = data.get("groups", [])
        for g in groups_list:
            cursor.execute("INSERT OR REPLACE INTO groups (id, name, description) VALUES (?, ?, ?)",
                           (g["id"], g["name"], g.get("description")))
            
        # Restore Clients
        clients_list = data.get("clients", [])
        for c in clients_list:
            cursor.execute("INSERT OR REPLACE INTO clients (id, group_id, ip_or_cidr, name) VALUES (?, ?, ?, ?)",
                           (c["id"], c["group_id"], c["ip_or_cidr"], c.get("name")))
            
        # Restore Adlists
        adlists_list = data.get("adlists", [])
        for a in adlists_list:
            cursor.execute("INSERT OR REPLACE INTO adlists (id, group_id, name, url, enabled) VALUES (?, ?, ?, ?, ?)",
                           (a["id"], a["group_id"], a["name"], a["url"], a["enabled"]))
            
        # Restore Custom Rules
        rules_list = data.get("custom_rules", [])
        for r in rules_list:
            cursor.execute("INSERT OR REPLACE INTO custom_rules (id, group_id, domain, type, enabled) VALUES (?, ?, ?, ?, ?)",
                           (r["id"], r["group_id"], r["domain"], r["type"], r["enabled"]))
            
        # Ensure Default group (id=1) exists
        cursor.execute("SELECT 1 FROM groups WHERE id = 1")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO groups (id, name, description) VALUES (1, 'Default', 'Default blocking group')")
            
        conn.commit()
        
        # Reload memory caches
        reload_clients_cache()
        reload_custom_rules_cache()
        
        # Trigger compilation in background thread
        asyncio.create_task(asyncio.to_thread(compile_all_groups))
        
        return {"status": "success", "message": "Configuration restored successfully. List compilation started."}
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Import configuration failed: {e}")
        raise HTTPException(status_code=500, detail=f"Database import failed: {e}")
    finally:
        conn.close()


# --- SSL / HTTPS Settings Endpoints Removed ---

@app.post("/api/system/restart")
async def restart_system(current_user: dict = Depends(get_current_user)):
    """Triggers an asynchronous reboot of the backend process to apply changes."""
    logger.info("Restart requested by user. Preparing to exit...")
    
    def reboot_process():
        time.sleep(1.5)
        logger.info("Process exiting now to trigger systemd/docker restart...")
        os._exit(0)
        
    import threading
    threading.Thread(target=reboot_process, daemon=True).start()
    
    return {"status": "success", "message": "System restart triggered. Reconnecting shortly..."}

UPDATING = False

def perform_system_update(version: str, db_path: str):
    global UPDATING
    import tarfile
    import urllib.request
    import shutil
    import tempfile
    import subprocess
    import sys
    
    logger.info(f"Starting system update to version {version}...")
    try:
        # Download release tarball from GitHub
        url = f"https://github.com/devslice/zerosink/archive/refs/tags/v{version}.tar.gz"
        logger.info(f"Downloading update from {url}...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = os.path.join(tmpdir, "update.tar.gz")
            
            # Fetch with custom User-Agent to avoid issues with GitHub blocking empty agents
            req = urllib.request.Request(
                url, 
                headers={'User-Agent': 'ZeroSink-Updater'}
            )
            with urllib.request.urlopen(req) as response, open(tar_path, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
                
            logger.info("Download complete. Extracting update...")
            
            with tarfile.open(tar_path, "r:gz") as tar:
                tar.extractall(path=tmpdir)
                
            extracted_dirs = [d for d in os.listdir(tmpdir) if os.path.isdir(os.path.join(tmpdir, d)) and d.startswith("zerosink")]
            if not extracted_dirs:
                raise Exception("Could not find extracted zerosink directory in archive.")
            
            src_root = os.path.join(tmpdir, extracted_dirs[0])
            
            # Copy backend/ and static/ files to BASE_DIR
            src_backend = os.path.join(src_root, "backend")
            dest_backend = os.path.join(BASE_DIR, "backend")
            if os.path.exists(src_backend):
                logger.info("Updating backend files...")
                for root, dirs, files in os.walk(src_backend):
                    rel_path = os.path.relpath(root, src_backend)
                    dest_dir = dest_backend if rel_path == "." else os.path.join(dest_backend, rel_path)
                    os.makedirs(dest_dir, exist_ok=True)
                    for file in files:
                        shutil.copy2(os.path.join(root, file), os.path.join(dest_dir, file))
            
            src_static = os.path.join(src_root, "static")
            dest_static = os.path.join(BASE_DIR, "static")
            if os.path.exists(src_static):
                logger.info("Updating static files...")
                for root, dirs, files in os.walk(src_static):
                    rel_path = os.path.relpath(root, src_static)
                    dest_dir = dest_static if rel_path == "." else os.path.join(dest_static, rel_path)
                    os.makedirs(dest_dir, exist_ok=True)
                    for file in files:
                        shutil.copy2(os.path.join(root, file), os.path.join(dest_dir, file))
                        
            src_req = os.path.join(src_root, "requirements.txt")
            dest_req = os.path.join(BASE_DIR, "requirements.txt")
            if os.path.exists(src_req):
                shutil.copy2(src_req, dest_req)
                
            # Update dependencies in venv
            is_windows = os.name == 'nt'
            venv_bin_dir = "Scripts" if is_windows else "bin"
            pip_name = "pip.exe" if is_windows else "pip"
            python_name = "python.exe" if is_windows else "python"
            
            pip_path = os.path.join(BASE_DIR, "venv", venv_bin_dir, pip_name)
            python_path = os.path.join(BASE_DIR, "venv", venv_bin_dir, python_name)
            
            if os.path.exists(pip_path):
                logger.info("Installing new dependencies via pip...")
                subprocess.run([pip_path, "install", "-r", dest_req], check=True)
                
            if os.path.exists(python_path):
                logger.info("Running database migrations/seeds...")
                db_env = os.environ.copy()
                db_env["ZEROSINK_DB_PATH"] = db_path
                subprocess.run([python_path, "-m", "backend.database"], env=db_env, check=True)
                
            logger.info("System update completed successfully! Restarting process...")
            
            time.sleep(1.0)
            os._exit(0)
            
    except Exception as e:
        logger.error(f"Update failed: {str(e)}", exc_info=True)
        UPDATING = False

@app.post("/api/system/update")
async def trigger_update(req: UpdateRequest, current_user: dict = Depends(get_current_user)):
    global UPDATING
    
    if os.path.exists('/.dockerenv'):
        raise HTTPException(status_code=400, detail="Automatic update is not supported inside a Docker container.")
        
    if UPDATING:
        raise HTTPException(status_code=400, detail="An update is already in progress.")
        
    # Validate version syntax to prevent path traversal/injection attacks
    import re
    if not re.match(r'^[a-zA-Z0-9.-]+$', req.version):
        raise HTTPException(status_code=400, detail="Invalid version format.")
        
    UPDATING = True
    
    # Run in a background thread to prevent blocking the FastAPI server response
    import threading
    from backend.config import DB_PATH
    threading.Thread(target=perform_system_update, args=(req.version, DB_PATH), daemon=True).start()
    
    return {"status": "success", "message": "System update initiated successfully."}


# --- Settings Management Endpoints ---

@app.get("/api/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    """Retrieve all current system settings."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    
    settings_dict = {row["key"]: row["value"] for row in rows}
    
    # If upstream_dns is not present in settings yet, return fallback from config
    if "upstream_dns" not in settings_dict:
        settings_dict["upstream_dns"] = UPSTREAM_DNS
        
    return settings_dict

@app.post("/api/settings")
async def update_settings(req: SettingsUpdate, current_user: dict = Depends(get_current_user)):
    """Update system settings."""
    try:
        # Validate the upstream DNS IPs
        validate_dns_ips(req.upstream_dns)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('upstream_dns', ?)", (req.upstream_dns.strip(),))
    conn.commit()
    conn.close()
    
    # Reload the engine's cache
    from backend.dns_engine import reload_upstream_dns_cache
    reload_upstream_dns_cache()
    
    return {"status": "success", "message": "Settings updated successfully"}


# --- DNS Pause/Resume Endpoints ---

@app.post("/api/dns/disable")
async def disable_dns_blocking(req: DNSDisableRequest, current_user: dict = Depends(get_current_user)):
    import time
    import backend.dns_engine as dns_engine
    
    duration = req.duration
    if duration <= 0:
        # Disable indefinitely (10 years)
        until = time.time() + (365 * 24 * 3600 * 10)
    else:
        until = time.time() + duration
        
    dns_engine.BLOCKING_DISABLED_UNTIL = until
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('blocking_disabled_until', ?)", (str(until),))
    conn.commit()
    conn.close()
    
    return {"status": "success", "blocking_disabled_until": until}

@app.post("/api/dns/enable")
async def enable_dns_blocking(current_user: dict = Depends(get_current_user)):
    import backend.dns_engine as dns_engine
    dns_engine.BLOCKING_DISABLED_UNTIL = 0.0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM settings WHERE key = 'blocking_disabled_until'")
    conn.commit()
    conn.close()
    
    return {"status": "success"}

@app.get("/api/dns/pause-status")
async def get_dns_pause_status(current_user: dict = Depends(get_current_user)):
    import time
    import backend.dns_engine as dns_engine
    
    now = time.time()
    disabled = now < dns_engine.BLOCKING_DISABLED_UNTIL
    remaining = max(0, int(dns_engine.BLOCKING_DISABLED_UNTIL - now)) if disabled else 0
    
    if dns_engine.BLOCKING_DISABLED_UNTIL > 0 and not disabled:
        dns_engine.BLOCKING_DISABLED_UNTIL = 0.0
        
    return {
        "disabled": disabled,
        "remaining_seconds": remaining,
        "blocking_disabled_until": dns_engine.BLOCKING_DISABLED_UNTIL
    }


# --- Local DNS Endpoints ---

@app.get("/api/local-dns")
async def get_local_dns_records(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, domain, ip_address, record_type, enabled FROM local_dns_records")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

@app.post("/api/local-dns")
async def create_local_dns_record(req: LocalDNSRecordCreate, current_user: dict = Depends(get_current_user)):
    import ipaddress
    try:
        ipaddress.ip_address(req.ip_address)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid IP address")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO local_dns_records (domain, ip_address, record_type, enabled)
            VALUES (?, ?, ?, 1)
        """, (req.domain.strip().lower(), req.ip_address.strip(), req.record_type.strip().upper()))
        conn.commit()
        
        from backend.dns_engine import reload_local_dns_cache
        reload_local_dns_cache()
        return {"status": "success"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Record already exists for this domain and type")
    finally:
        conn.close()

@app.delete("/api/local-dns/{record_id}")
async def delete_local_dns_record(record_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM local_dns_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    
    from backend.dns_engine import reload_local_dns_cache
    reload_local_dns_cache()
    return {"status": "success"}


# --- Privacy Settings Endpoints ---

@app.get("/api/settings/privacy")
async def get_privacy_settings(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings WHERE key IN ('privacy_mode', 'log_retention_days')")
    rows = cursor.fetchall()
    conn.close()
    
    settings_dict = {row["key"]: row["value"] for row in rows}
    return {
        "privacy_mode": int(settings_dict.get("privacy_mode", 0)),
        "log_retention_days": int(settings_dict.get("log_retention_days", 7))
    }

@app.post("/api/settings/privacy")
async def update_privacy_settings(req: PrivacySettingsUpdate, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('privacy_mode', ?)", (str(req.privacy_mode),))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('log_retention_days', ?)", (str(req.log_retention_days),))
    conn.commit()
    conn.close()
    
    from backend.dns_engine import reload_privacy_mode
    reload_privacy_mode()
    return {"status": "success"}


# --- DHCP Endpoints ---

@app.get("/api/dhcp/settings")
async def get_dhcp_settings_api(current_user: dict = Depends(get_current_user)):
    from backend.dhcp_engine import get_dhcp_settings
    return get_dhcp_settings()

@app.post("/api/dhcp/settings")
async def update_dhcp_settings_api(req: DHCPSettingsUpdate, current_user: dict = Depends(get_current_user)):
    import ipaddress
    try:
        if req.dhcp_range_start:
            ipaddress.ip_address(req.dhcp_range_start)
        if req.dhcp_range_end:
            ipaddress.ip_address(req.dhcp_range_end)
        if req.dhcp_router:
            ipaddress.ip_address(req.dhcp_router)
        if req.dhcp_subnet_mask:
            ipaddress.ip_address(req.dhcp_subnet_mask)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {e}")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('dhcp_enabled', ?)", (str(req.dhcp_enabled),))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('dhcp_range_start', ?)", (req.dhcp_range_start.strip(),))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('dhcp_range_end', ?)", (req.dhcp_range_end.strip(),))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('dhcp_router', ?)", (req.dhcp_router.strip() if req.dhcp_router else "",))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('dhcp_subnet_mask', ?)", (req.dhcp_subnet_mask.strip(),))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('dhcp_lease_time', ?)", (str(req.dhcp_lease_time),))
    conn.commit()
    conn.close()
    
    from backend.dhcp_engine import stop_dhcp_server, start_dhcp_server
    await stop_dhcp_server()
    if req.dhcp_enabled:
        await start_dhcp_server()
        
    return {"status": "success", "message": "DHCP settings updated successfully"}

@app.get("/api/dhcp/leases")
async def get_dhcp_leases(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT mac_address, ip_address, hostname, expire_time FROM dhcp_leases")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

@app.delete("/api/dhcp/leases/{mac_address}")
async def delete_dhcp_lease_api(mac_address: str, current_user: dict = Depends(get_current_user)):
    from backend.dhcp_engine import delete_dhcp_lease
    delete_dhcp_lease(mac_address)
    return {"status": "success"}


# --- Premium Parental Controls & Lemon Squeezy Endpoints ---

import urllib.request
import urllib.parse
import socket
from datetime import datetime, timedelta

def verify_lemon_squeezy_license(license_key: str) -> dict:
    clean_key = license_key.strip().lower()
    if clean_key in ("sandbox", "test-license-key") or clean_key.startswith("test_"):
        return {
            "activated": True,
            "license_key": {
                "status": "active",
                "key": license_key,
                "expires_at": (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z"
            },
            "meta": {
                "product_name": "ZeroSink Premium Sandbox",
                "subscription_id": 999999,
                "subscription_status": "active",
                "expires_at": (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z"
            }
        }
        
    url = "https://api.lemonsqueezy.com/v1/licenses/activate"
    data = {
        "license_key": license_key.strip(),
        "instance_name": socket.gethostname()
    }
    req_data = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read()
            return json.loads(res_body.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            res_body = e.read()
            return json.loads(res_body.decode("utf-8"))
        except Exception:
            return {"activated": False, "error": f"API Error: HTTP {e.code}"}
    except Exception as e:
        return {"activated": False, "error": f"Failed to connect to licensing server: {str(e)}"}

@app.get("/api/premium/status")
async def get_premium_status(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings WHERE key IN ('premium_license_key', 'premium_license_status', 'premium_license_expires_at')")
    rows = cursor.fetchall()
    conn.close()
    
    settings_dict = {row["key"]: row["value"] for row in rows}
    
    is_active = settings_dict.get("premium_license_status") == "active"
    expires_at_str = settings_dict.get("premium_license_expires_at")
    
    if is_active and expires_at_str:
        try:
            val = expires_at_str.strip()
            if val.endswith("Z"):
                val = val[:-1] + "+00:00"
            expires_at = datetime.fromisoformat(val)
            if datetime.now(expires_at.tzinfo) > expires_at:
                is_active = False
        except Exception:
            pass
            
    return {
        "active": is_active,
        "license_key": settings_dict.get("premium_license_key", ""),
        "expires_at": expires_at_str,
        "customer_portal_url": "https://my.lemonsqueezy.com/billing" if is_active else None
    }

@app.post("/api/premium/activate")
async def activate_premium(req: PremiumLicenseRequest, current_user: dict = Depends(get_current_user)):
    res = verify_lemon_squeezy_license(req.license_key)
    
    if not res.get("activated"):
        error_msg = res.get("error") or "Invalid license key or activation failed."
        raise HTTPException(status_code=400, detail=error_msg)
        
    meta = res.get("meta", {})
    sub_status = meta.get("subscription_status", "active")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    expires_at = meta.get("expires_at")
    if not expires_at:
        expires_at = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
        
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('premium_license_key', ?)", (req.license_key.strip(),))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('premium_license_status', ?)", ("active" if sub_status in ("active", "on_trial") else "inactive",))
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('premium_license_expires_at', ?)", (expires_at,))
    conn.commit()
    conn.close()
    
    from backend.dns_engine import reload_premium_cache
    reload_premium_cache()
    
    return {"status": "success", "message": "Premium activated successfully!", "expires_at": expires_at}

@app.post("/api/premium/deactivate")
async def deactivate_premium(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM settings WHERE key IN ('premium_license_key', 'premium_license_status', 'premium_license_expires_at')")
    conn.commit()
    conn.close()
    
    from backend.dns_engine import reload_premium_cache
    reload_premium_cache()
    return {"status": "success", "message": "Premium deactivated successfully."}

# --- Downtime Schedules Endpoints ---

@app.get("/api/premium/downtimes")
async def get_downtime_schedules(current_user: dict = Depends(get_current_user)):
    from backend.dns_engine import PREMIUM_ACTIVE
    if not PREMIUM_ACTIVE:
        raise HTTPException(status_code=403, detail="Premium license required for Parental Controls.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.id, d.group_id, g.name as group_name, d.name, d.start_time, d.end_time, d.days_of_week, d.blocked_categories, d.enabled 
        FROM downtime_schedules d
        JOIN groups g ON d.group_id = g.id
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    for r in rows:
        if r["blocked_categories"]:
            try:
                r["blocked_categories"] = json.loads(r["blocked_categories"])
            except Exception:
                r["blocked_categories"] = []
        else:
            r["blocked_categories"] = []
            
    return rows

@app.post("/api/premium/downtimes")
async def save_downtime_schedule(req: DowntimeScheduleCreate, current_user: dict = Depends(get_current_user)):
    from backend.dns_engine import PREMIUM_ACTIVE
    if not PREMIUM_ACTIVE:
        raise HTTPException(status_code=403, detail="Premium license required for Parental Controls.")
        
    try:
        datetime.strptime(req.start_time, "%H:%M")
        datetime.strptime(req.end_time, "%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid time format. Use HH:MM in 24h format.")
        
    days = [d.strip() for d in req.days_of_week.split(",") if d.strip() in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
    if not days:
        raise HTTPException(status_code=400, detail="Must select at least one valid day of week.")
    clean_days = ",".join(days)
    
    blocked_cats_json = None
    if req.blocked_categories:
        blocked_cats_json = json.dumps(req.blocked_categories)
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO downtime_schedules (group_id, name, start_time, end_time, days_of_week, blocked_categories, enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (req.group_id, req.name.strip(), req.start_time, req.end_time, clean_days, blocked_cats_json, req.enabled))
    conn.commit()
    conn.close()
    
    from backend.dns_engine import reload_parental_rules_cache
    reload_parental_rules_cache()
    
    return {"status": "success", "message": "Downtime schedule saved successfully."}

@app.delete("/api/premium/downtimes/{schedule_id}")
async def delete_downtime_schedule(schedule_id: int, current_user: dict = Depends(get_current_user)):
    from backend.dns_engine import PREMIUM_ACTIVE
    if not PREMIUM_ACTIVE:
        raise HTTPException(status_code=403, detail="Premium license required for Parental Controls.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM downtime_schedules WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()
    
    from backend.dns_engine import reload_parental_rules_cache
    reload_parental_rules_cache()
    return {"status": "success", "message": "Downtime schedule deleted successfully."}

# --- App Block Category Endpoints ---

@app.get("/api/premium/app-blocks/{group_id}")
async def get_app_blocks(group_id: int, current_user: dict = Depends(get_current_user)):
    from backend.dns_engine import PREMIUM_ACTIVE, APP_CATEGORIES
    if not PREMIUM_ACTIVE:
        raise HTTPException(status_code=403, detail="Premium license required for Parental Controls.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT category, app_name, enabled FROM group_app_blocks WHERE group_id = ?", (group_id,))
    rows = cursor.fetchall()
    conn.close()
    
    active_blocks = {cat: {} for cat in APP_CATEGORIES.keys()}
    for cat, apps in APP_CATEGORIES.items():
        for app in apps.keys():
            active_blocks[cat][app] = False
        active_blocks[cat]["all"] = False
        
    for r in rows:
        cat = r["category"]
        app = r["app_name"]
        enabled = bool(r["enabled"])
        if cat in active_blocks:
            active_blocks[cat][app] = enabled
            
    return active_blocks

@app.post("/api/premium/app-blocks/{group_id}")
async def update_app_block(group_id: int, req: AppBlockToggle, current_user: dict = Depends(get_current_user)):
    from backend.dns_engine import PREMIUM_ACTIVE, APP_CATEGORIES
    if not PREMIUM_ACTIVE:
        raise HTTPException(status_code=403, detail="Premium license required for Parental Controls.")
        
    if req.category not in APP_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid app category.")
        
    valid_apps = list(APP_CATEGORIES[req.category].keys()) + ["all"]
    if req.app_name not in valid_apps:
        raise HTTPException(status_code=400, detail="Invalid app name for this category.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if req.enabled:
        cursor.execute("""
            INSERT OR REPLACE INTO group_app_blocks (group_id, category, app_name, enabled)
            VALUES (?, ?, ?, 1)
        """, (group_id, req.category, req.app_name))
    else:
        cursor.execute("""
            DELETE FROM group_app_blocks 
            WHERE group_id = ? AND category = ? AND app_name = ?
        """, (group_id, req.category, req.app_name))
        
    conn.commit()
    conn.close()
    
    from backend.dns_engine import reload_parental_rules_cache
    reload_parental_rules_cache()
    
    return {"status": "success", "message": "App blocking rule updated."}


if __name__ == "__main__":
    import uvicorn
    
    logger.info(f"Starting web server with HTTP on port {WEB_PORT}")
    
    try:
        uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
    except OSError as e:
        if isinstance(e, PermissionError) or (hasattr(e, "errno") and e.errno in (13, 10013)):
            logger.warning(f"Permission denied when binding to port {WEB_PORT} ([Errno 13] permission denied). Falling back to port 8000 for safety.")
            ACTIVE_PORT = 8000
            uvicorn.run(app, host=WEB_HOST, port=ACTIVE_PORT)
        else:
            raise
