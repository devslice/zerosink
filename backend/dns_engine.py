import asyncio
import socket
import time
import ipaddress
import logging
import re
import json
from datetime import datetime
import dnslib
from backend.config import DNS_HOST, DNS_PORT, UPSTREAM_DNS
from backend.database import get_db_connection

logger = logging.getLogger("zerosink.dns")

# App categories domain mappings
APP_CATEGORIES = {
    "social": {
        "tiktok": ["tiktok.com", "tiktokv.com", "ibyteimg.com", "byteoversea.com", "muscdn.com"],
        "instagram": ["instagram.com", "cdninstagram.com"],
        "snapchat": ["snapchat.com", "sc-cdn.net"],
        "facebook": ["facebook.com", "fbcdn.net", "facebook.net"],
        "reddit": ["reddit.com", "redditmedia.com", "redditstatic.com"],
        "twitter": ["twitter.com", "x.com", "twimg.com"],
    },
    "gaming": {
        "roblox": ["roblox.com", "rbxcdn.com"],
        "fortnite": ["fortnite.com", "epicgames.com"],
        "steam": ["steampowered.com", "steamcommunity.com", "steamstatic.com"],
        "minecraft": ["minecraft.net", "mojang.com"],
        "discord": ["discord.com", "discord.gg", "discordapp.com", "discordapp.net"],
        "playstation": ["playstation.com", "playstation.net", "sony.com"],
        "xbox": ["xbox.com", "xboxlive.com"],
    },
    "entertainment": {
        "youtube": ["youtube.com", "ytimg.com", "ggpht.com", "googlevideo.com", "youtu.be"],
        "netflix": ["netflix.com", "nflxvideo.net", "nflxext.com", "nflxso.net"],
        "twitch": ["twitch.tv", "ttvnw.net"],
        "disney": ["disneyplus.com", "disney.com", "disney-plus.net"],
        "prime": ["primevideo.com", "amazonvideo.com"],
    },
    "adult": {
        "all": ["pornhub.com", "xvideos.com", "xnxx.com", "xhamster.com", "redtube.com", "youporn.com"]
    }
}

# Caches
CLIENTS_CACHE = []
CUSTOM_RULES_CACHE = {}  # group_id -> {"allow": set(), "deny": set(), "allow_regex": list(), "deny_regex": list()}
DNS_CACHE = {}          # (qtype, qname, group_id) -> (reply_bytes, expire_time, is_blocked)
UPSTREAM_DNS_CACHE = []
LOCAL_DNS_CACHE = {}    # domain -> { 'A': [ip1], 'AAAA': [ip2] }

# Premium & Parental Caches
PREMIUM_ACTIVE = False
DOWNTIME_SCHED_CACHE = {}  # group_id -> list of schedules
GROUP_APP_BLOCKS_CACHE = {} # group_id -> {category: set of app_names}

# Global State
BLOCKING_DISABLED_UNTIL = 0.0
PRIVACY_MODE = 0

# Log queue for non-blocking database writes
log_queue = asyncio.Queue()


def reload_clients_cache():
    """Load and cache clients from database for O(1) matching."""
    global CLIENTS_CACHE
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.ip_or_cidr, c.group_id, g.name as group_name, c.name as client_name 
            FROM clients c 
            JOIN groups g ON c.group_id = g.id
        """)
        rows = cursor.fetchall()
        conn.close()
        
        new_cache = []
        for r in rows:
            ip_str = r["ip_or_cidr"].strip()
            try:
                if '/' in ip_str:
                    network = ipaddress.ip_network(ip_str, strict=False)
                    new_cache.append({
                        "network": network,
                        "is_cidr": True,
                        "group_id": r["group_id"],
                        "group_name": r["group_name"],
                        "client_name": r["client_name"]
                    })
                else:
                    addr = ipaddress.ip_address(ip_str)
                    new_cache.append({
                        "address": addr,
                        "is_cidr": False,
                        "group_id": r["group_id"],
                        "group_name": r["group_name"],
                        "client_name": r["client_name"]
                    })
            except Exception as e:
                logger.error(f"Error parsing client IP/CIDR '{ip_str}': {e}")
        CLIENTS_CACHE = new_cache
        logger.info(f"Loaded {len(CLIENTS_CACHE)} clients into IP cache.")
    except Exception as e:
        logger.error(f"Failed to reload clients cache: {e}")

def reload_custom_rules_cache():
    """Load and cache custom allow/deny rules from database, compiling RegEx patterns."""
    global CUSTOM_RULES_CACHE
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT group_id, domain, type, is_regex FROM custom_rules WHERE enabled = 1")
        rows = cursor.fetchall()
        conn.close()
        
        new_cache = {}
        for r in rows:
            g_id = r["group_id"]
            d = r["domain"].strip().lower()
            rtype = r["type"]  # 'allow' or 'deny'
            is_reg = bool(r["is_regex"])
            
            if g_id not in new_cache:
                new_cache[g_id] = {"allow": set(), "deny": set(), "allow_regex": [], "deny_regex": []}
                
            if is_reg:
                try:
                    # Support simple wildcards (e.g. *.doubleclick.net) by converting to standard regex
                    if '*' in d:
                        escaped = re.escape(d).replace(r'\*', '.*')
                        regex_str = f"^{escaped}$"
                    else:
                        regex_str = d
                    compiled = re.compile(regex_str)
                    new_cache[g_id][f"{rtype}_regex"].append(compiled)
                except Exception as ex:
                    logger.error(f"Error compiling regex rule '{d}' for group {g_id}: {ex}")
            else:
                new_cache[g_id][rtype].add(d)
                
        CUSTOM_RULES_CACHE = new_cache
        logger.info(f"Loaded custom rules cache for {len(CUSTOM_RULES_CACHE)} groups.")
    except Exception as e:
        logger.error(f"Failed to reload custom rules cache: {e}")

def reload_local_dns_cache():
    """Load and cache custom local DNS records from database."""
    global LOCAL_DNS_CACHE
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT domain, ip_address, record_type FROM local_dns_records WHERE enabled = 1")
        rows = cursor.fetchall()
        conn.close()
        
        new_cache = {}
        for r in rows:
            domain = r["domain"].strip().lower()
            ip = r["ip_address"].strip()
            rtype = r["record_type"].strip().upper()
            if domain not in new_cache:
                new_cache[domain] = {"A": [], "AAAA": []}
            if rtype in ("A", "AAAA"):
                new_cache[domain][rtype].append(ip)
        LOCAL_DNS_CACHE = new_cache
        logger.info(f"Loaded {len(LOCAL_DNS_CACHE)} local DNS records.")
    except Exception as e:
        logger.error(f"Failed to reload local DNS cache: {e}")

def reload_privacy_mode():
    """Load and cache privacy mode setting from database."""
    global PRIVACY_MODE
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'privacy_mode'")
        row = cursor.fetchone()
        conn.close()
        if row and row["value"]:
            PRIVACY_MODE = int(row["value"])
        else:
            PRIVACY_MODE = 0
        logger.info(f"Loaded privacy mode: {PRIVACY_MODE}")
    except Exception as e:
        logger.error(f"Failed to reload privacy mode: {e}")
        PRIVACY_MODE = 0

def reload_upstream_dns_cache():
    """Load and cache upstream DNS servers from database settings or fallback."""
    global UPSTREAM_DNS_CACHE
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'upstream_dns'")
        row = cursor.fetchone()
        conn.close()
        if row and row["value"]:
            servers = [s.strip() for s in row["value"].replace(',', ' ').split() if s.strip()]
            if servers:
                UPSTREAM_DNS_CACHE = servers
                logger.info(f"Loaded upstream DNS servers from settings: {UPSTREAM_DNS_CACHE}")
                return
    except Exception as e:
        logger.error(f"Failed to load upstream DNS from database: {e}")
        
    # Fallback to environment variable / default config
    servers = [s.strip() for s in UPSTREAM_DNS.replace(',', ' ').split() if s.strip()]
    UPSTREAM_DNS_CACHE = servers if servers else ["1.1.1.1"]
    logger.info(f"Loaded fallback upstream DNS servers: {UPSTREAM_DNS_CACHE}")

def reload_premium_cache():
    """Check and cache premium activation status from database."""
    global PREMIUM_ACTIVE
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'premium_license_status'")
        row = cursor.fetchone()
        
        is_active = False
        if row and row["value"] == "active":
            is_active = True
            
        cursor.execute("SELECT value FROM settings WHERE key = 'premium_license_expires_at'")
        exp_row = cursor.fetchone()
        conn.close()
        
        if is_active and exp_row and exp_row["value"]:
            try:
                val = exp_row["value"].strip()
                if val.endswith("Z"):
                    val = val[:-1] + "+00:00"
                expires_at = datetime.fromisoformat(val)
                if datetime.now(expires_at.tzinfo) > expires_at:
                    is_active = False
                    logger.warning("Cached premium license expired locally.")
            except Exception as e:
                logger.error(f"Error parsing premium expiration: {e}")
                
        PREMIUM_ACTIVE = is_active
        logger.info(f"Loaded premium status cache: {PREMIUM_ACTIVE}")
    except Exception as e:
        logger.error(f"Failed to reload premium status cache: {e}")
        PREMIUM_ACTIVE = False

def reload_parental_rules_cache():
    """Load downtime schedules and app blocks into memory cache."""
    global DOWNTIME_SCHED_CACHE, GROUP_APP_BLOCKS_CACHE
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, group_id, name, start_time, end_time, days_of_week, blocked_categories, enabled FROM downtime_schedules WHERE enabled = 1")
        sched_rows = cursor.fetchall()
        new_sched = {}
        for r in sched_rows:
            g_id = r["group_id"]
            if g_id not in new_sched:
                new_sched[g_id] = []
            
            days = {d.strip() for d in r["days_of_week"].split(",") if d.strip()}
            
            cats = None
            if r["blocked_categories"]:
                try:
                    cats = json.loads(r["blocked_categories"])
                except Exception:
                    cats = []
                    
            new_sched[g_id].append({
                "name": r["name"],
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "days_of_week": days,
                "blocked_categories": cats
            })
        DOWNTIME_SCHED_CACHE = new_sched
        
        cursor.execute("SELECT group_id, category, app_name, enabled FROM group_app_blocks WHERE enabled = 1")
        block_rows = cursor.fetchall()
        new_blocks = {}
        for r in block_rows:
            g_id = r["group_id"]
            cat = r["category"]
            app = r["app_name"]
            
            if g_id not in new_blocks:
                new_blocks[g_id] = {}
            if cat not in new_blocks[g_id]:
                new_blocks[g_id][cat] = set()
                
            new_blocks[g_id][cat].add(app)
            
        GROUP_APP_BLOCKS_CACHE = new_blocks
        logger.info(f"Loaded {len(DOWNTIME_SCHED_CACHE)} groups' schedules and {len(GROUP_APP_BLOCKS_CACHE)} groups' app blocks.")
        conn.close()
    except Exception as e:
        logger.error(f"Failed to reload parental rules cache: {e}")

def is_domain_in_category(category: str, app_name: str, domains: list) -> bool:
    """Check if any of the checked domains match the specified category/app."""
    if category not in APP_CATEGORIES:
        return False
        
    cat_apps = APP_CATEGORIES[category]
    
    if app_name != "all":
        if app_name in cat_apps:
            target_domains = cat_apps[app_name]
            for d in domains:
                for t in target_domains:
                    if d == t or d.endswith("." + t):
                        return True
        return False
        
    for app, target_domains in cat_apps.items():
        for d in domains:
            for t in target_domains:
                if d == t or d.endswith("." + t):
                    return True
                    
    return False

def check_parental_controls(group_id: int, domains: list) -> tuple[bool, str]:
    """
    Check if the requested domains are blocked by active downtime schedules or category blocks.
    Returns (is_blocked, status_message)
    """
    global PREMIUM_ACTIVE
    if not PREMIUM_ACTIVE:
        return False, None

    now_dt = datetime.now()
    current_time_str = now_dt.strftime("%H:%M")
    current_day = now_dt.strftime("%a")
    
    schedules = DOWNTIME_SCHED_CACHE.get(group_id, [])
    for sched in schedules:
        if current_day in sched["days_of_week"]:
            start = sched["start_time"]
            end = sched["end_time"]
            
            in_downtime = False
            if start <= end:
                in_downtime = (start <= current_time_str <= end)
            else:
                in_downtime = (current_time_str >= start or current_time_str <= end)
                
            if in_downtime:
                if not sched["blocked_categories"]:
                    return True, "Blocked (Downtime: Total)"
                
                for cat in sched["blocked_categories"]:
                    if is_domain_in_category(cat, "all", domains):
                        return True, f"Blocked (Downtime: {cat.capitalize()})"
                        
    group_blocks = GROUP_APP_BLOCKS_CACHE.get(group_id, {})
    for cat, apps in group_blocks.items():
        for app in apps:
            if is_domain_in_category(cat, app, domains):
                return True, f"Blocked ({cat.capitalize()}: {app.capitalize() if app != 'all' else 'All'})"
                
    return False, None

def get_client_info(client_ip: str) -> tuple:
    """Find group and client details for an incoming client IP."""
    try:
        addr = ipaddress.ip_address(client_ip)
    except Exception:
        return 1, "Default", "Unknown Client"
        
    # 1. Match exact IP
    for c in CLIENTS_CACHE:
        if not c["is_cidr"] and c["address"] == addr:
            return c["group_id"], c["group_name"], c["client_name"]
            
    # 2. Match CIDR blocks
    for c in CLIENTS_CACHE:
        if c["is_cidr"] and addr in c["network"]:
            return c["group_id"], c["group_name"], c["client_name"]
            
    return 1, "Default", client_ip  # Fallback to Default group

def get_domains_to_check(qname: str) -> list:
    """Break a domain down to its parent domains (e.g. sub.example.com -> [sub.example.com, example.com])."""
    parts = qname.split('.')
    domains = []
    # Check parent domains, stopping before TLD (e.g. check "example.com" but not "com")
    for i in range(len(parts) - 1):
        domains.append(".".join(parts[i:]))
    return domains

def is_domain_in_blocklist(group_id: int, domains: list) -> bool:
    """Check if any of the domains are in the compiled blocklist for the group."""
    if not domains:
        return False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in domains)
        query = f"SELECT 1 FROM compiled_blocks WHERE group_id = ? AND domain IN ({placeholders}) LIMIT 1"
        cursor.execute(query, [group_id] + domains)
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        logger.error(f"Blocklist check error: {e}")
        return False

def get_min_ttl(record: dnslib.DNSRecord) -> int:
    """Extract the minimum TTL from the answers/authority sections of a DNS response."""
    ttls = [rr.ttl for rr in record.rr if rr.ttl > 0]
    ttls += [rr.ttl for rr in record.auth if rr.ttl > 0]
    ttls += [rr.ttl for rr in record.ar if rr.ttl > 0]
    return min(ttls) if ttls else 60

def forward_dns_udp_sync(data: bytes, upstream: str, timeout: float = 2.0) -> bytes:
    """Synchronous socket lookup for forwarding UDP DNS queries."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(data, (upstream, 53))
        resp, _ = sock.recvfrom(4096)
        return resp
    except Exception:
        return None
    finally:
        sock.close()

async def forward_dns_udp(data: bytes, upstreams: list = None) -> bytes:
    """Forward query to multiple upstream UDP DNS servers in parallel, returning the first non-None response."""
    if upstreams is None:
        upstreams = UPSTREAM_DNS_CACHE
    if not upstreams:
        return None
    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(None, forward_dns_udp_sync, data, upstream)
        for upstream in upstreams
    ]
    for future in asyncio.as_completed(tasks):
        try:
            res = await future
            if res is not None:
                return res
        except Exception:
            pass
    return None

async def forward_dns_tcp(data: bytes, upstreams: list = None, timeout: float = 2.0) -> bytes:
    """Forward TCP DNS query to multiple upstream DNS servers in parallel, returning the first non-None response."""
    if upstreams is None:
        upstreams = UPSTREAM_DNS_CACHE
    if not upstreams:
        return None

    async def forward_single_tcp(upstream: str) -> bytes:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(upstream, 53),
                timeout=timeout
            )
            req_len = len(data).to_bytes(2, byteorder='big')
            writer.write(req_len + data)
            await writer.drain()
            
            len_bytes = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
            length = int.from_bytes(len_bytes, byteorder='big')
            resp_data = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
            
            writer.close()
            await writer.wait_closed()
            return resp_data
        except Exception as e:
            logger.debug(f"TCP DNS forwarding failed to {upstream}: {e}")
            return None

    tasks = [asyncio.create_task(forward_single_tcp(upstream)) for upstream in upstreams]
    first_res = None
    try:
        for future in asyncio.as_completed(tasks):
            try:
                res = await future
                if res is not None:
                    first_res = res
                    break
            except Exception:
                pass
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
    return first_res

def create_sinkhole_response(record: dnslib.DNSRecord, qname: str, qtype_str: str) -> bytes:
    """Create a sinkhole DNS response (0.0.0.0 for A, :: for AAAA)."""
    reply = record.reply()
    
    if qtype_str == "A":
        reply.add_answer(dnslib.RR(
            rname=record.q.qname,
            rtype=dnslib.QTYPE.A,
            rclass=1,
            ttl=300,
            rdata=dnslib.A("0.0.0.0")
        ))
    elif qtype_str == "AAAA":
        reply.add_answer(dnslib.RR(
            rname=record.q.qname,
            rtype=dnslib.QTYPE.AAAA,
            rclass=1,
            ttl=300,
            rdata=dnslib.AAAA("::")
        ))
    else:
        # Return NXDOMAIN or NOERROR with empty answer
        reply.header.rcode = dnslib.RCODE.NXDOMAIN
        
    return reply.pack()

def is_blocking_disabled() -> bool:
    global BLOCKING_DISABLED_UNTIL
    return time.time() < BLOCKING_DISABLED_UNTIL

def create_local_dns_response(record: dnslib.DNSRecord, ips: list, qtype_str: str) -> bytes:
    reply = record.reply()
    for ip in ips:
        if qtype_str == "A":
            reply.add_answer(dnslib.RR(
                rname=record.q.qname,
                rtype=dnslib.QTYPE.A,
                rclass=1,
                ttl=300,
                rdata=dnslib.A(ip)
            ))
        elif qtype_str == "AAAA":
            reply.add_answer(dnslib.RR(
                rname=record.q.qname,
                rtype=dnslib.QTYPE.AAAA,
                rclass=1,
                ttl=300,
                rdata=dnslib.AAAA(ip)
            ))
    return reply.pack()

async def resolve_dns(data: bytes, client_ip: str, protocol: str) -> bytes:
    """
    Main DNS query resolver.
    Checks rules, manages caching, and forwards if clean.
    """
    start_time = time.time()
    try:
        record = dnslib.DNSRecord.parse(data)
    except Exception as e:
        logger.warning(f"Could not parse DNS query from {client_ip}: {e}")
        return None

    if not record.questions:
        return None

    q = record.questions[0]
    qname = str(q.qname).strip('.').lower()
    qtype_str = str(dnslib.QTYPE.get(q.qtype))
    
    # 1. Resolve client group
    group_id, group_name, client_name = get_client_info(client_ip)
    
    # 2. Check cache first
    cache_key = (q.qtype, qname, group_id)
    now = time.time()
    if cache_key in DNS_CACHE:
        cached_data, expire_time, is_blocked = DNS_CACHE[cache_key]
        if now < expire_time:
            # Reconstruct response to update Transaction ID
            cached_record = dnslib.DNSRecord.parse(cached_data)
            cached_record.header.id = record.header.id
            reply_bytes = cached_record.pack()
            
            # Log cached transaction
            status = "Blocked (Cached)" if is_blocked else "Allowed (Cached)"
            reply_time = (time.time() - start_time) * 1000.0
            log_query(client_ip, client_name, qname, qtype_str, status, group_name, reply_time)
            return reply_bytes
        else:
            del DNS_CACHE[cache_key]

    # Intercept Local DNS Records (A/AAAA)
    if qname in LOCAL_DNS_CACHE:
        records_for_domain = LOCAL_DNS_CACHE[qname]
        if qtype_str in records_for_domain and records_for_domain[qtype_str]:
            reply_bytes = create_local_dns_response(record, records_for_domain[qtype_str], qtype_str)
            status = "Allowed (Local DNS)"
            DNS_CACHE[cache_key] = (reply_bytes, now + 300, False)
            reply_time = (time.time() - start_time) * 1000.0
            log_query(client_ip, client_name, qname, qtype_str, status, group_name, reply_time)
            return reply_bytes

    # 3. Form domain match hierarchy
    domains_to_check = get_domains_to_check(qname)
    
    # 4. Check custom rules
    custom_rules = CUSTOM_RULES_CACHE.get(group_id, {"allow": set(), "deny": set(), "allow_regex": [], "deny_regex": []})
    
    # Custom Whitelist Rule Check (exact & regex)
    whitelisted = False
    for d in domains_to_check:
        if d in custom_rules.get("allow", set()):
            whitelisted = True
            break
            
    if not whitelisted:
        for pattern in custom_rules.get("allow_regex", []):
            if pattern.search(qname):
                whitelisted = True
                break
                
    status = None
    reply_bytes = None
    
    if is_blocking_disabled():
        status = "Allowed (Bypassed)"
    elif whitelisted:
        status = "Allowed (Whitelist)"
    else:
        # Check parental controls (downtime and category blocks)
        is_parental_blocked, parental_status = check_parental_controls(group_id, domains_to_check)
        if is_parental_blocked:
            status = parental_status
        else:
            # Check custom blacklist (exact & regex)
            blacklisted = False
            for d in domains_to_check:
                if d in custom_rules.get("deny", set()):
                    blacklisted = True
                    break
                    
            if not blacklisted:
                for pattern in custom_rules.get("deny_regex", []):
                    if pattern.search(qname):
                        blacklisted = True
                        break
                        
            if blacklisted:
                status = "Blocked"
            else:
                # Check compiled adlists
                if is_domain_in_blocklist(group_id, domains_to_check):
                    status = "Blocked"
                
    # 5. Handle block (sinkhole)
    if status and status.startswith("Blocked"):
        reply_bytes = create_sinkhole_response(record, qname, qtype_str)
        # Cache block response for 300 seconds
        DNS_CACHE[cache_key] = (reply_bytes, now + 300, True)
    else:
        # 6. Forward to upstream
        if not status:
            status = "Allowed (Forwarded)"
            
        if protocol == "UDP":
            reply_bytes = await forward_dns_udp(data)
        else:
            reply_bytes = await forward_dns_tcp(data)
            
        if reply_bytes:
            # Parse answer and extract TTL for caching
            try:
                reply_record = dnslib.DNSRecord.parse(reply_bytes)
                ttl = get_min_ttl(reply_record)
                DNS_CACHE[cache_key] = (reply_bytes, now + ttl, False)
            except Exception:
                pass
        else:
            # Server failure to forward
            reply = record.reply()
            reply.header.rcode = dnslib.RCODE.SERVFAIL
            reply_bytes = reply.pack()
            status = "Failed (Upstream Timeout)"

    # Log query
    reply_time = (time.time() - start_time) * 1000.0
    log_query(client_ip, client_name, qname, qtype_str, status, group_name, reply_time)
    
    return reply_bytes

def log_query(client_ip: str, client_name: str, domain: str, query_type: str, status: str, group_name: str, reply_time_ms: float):
    """Enqueue log entry to be processed by background database writer, respecting privacy mode."""
    global PRIVACY_MODE
    if PRIVACY_MODE == 3:  # No Logging
        return
        
    logged_domain = domain
    logged_ip = client_ip
    logged_name = client_name
    
    if PRIVACY_MODE == 1:  # Stealth (Mask Domain)
        logged_domain = "[Hidden]"
    elif PRIVACY_MODE == 2:  # Anonymized (Mask Client IP & Name)
        logged_ip = "0.0.0.0"
        logged_name = "Anonymous Client"
        
    log_entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "client_ip": logged_ip,
        "client_name": logged_name,
        "domain": logged_domain,
        "query_type": query_type,
        "status": status,
        "group_name": group_name,
        "reply_time_ms": reply_time_ms
    }
    log_queue.put_nowait(log_entry)

def prune_query_logs():
    """Delete query logs older than the retention setting."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'log_retention_days'")
        row = cursor.fetchone()
        retention_days = int(row["value"]) if row else 7
        
        cursor.execute("DELETE FROM query_logs WHERE datetime(timestamp) < datetime('now', ?)", (f"-{retention_days} days",))
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count > 0:
            logger.info(f"Pruned {deleted_count} old query logs (retention: {retention_days} days).")
            cursor.execute("PRAGMA incremental_vacuum;")
            conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error pruning query logs: {e}")

def flush_logs_sync(entries):
    """Synchronously insert query logs in a single transaction."""
    if not entries:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN TRANSACTION")
        cursor.executemany("""
            INSERT INTO query_logs (timestamp, client_ip, client_name, domain, query_type, status, group_name, reply_time_ms)
            VALUES (:timestamp, :client_ip, :client_name, :domain, :query_type, :status, :group_name, :reply_time_ms)
        """, entries)
        conn.commit()
        logger.debug(f"Flushed {len(entries)} query logs to database in a single transaction.")
    except Exception as ex:
        logger.error(f"Failed to flush query logs: {ex}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()

async def log_writer_worker():
    """Worker task that writes queued query logs into SQLite in timed chunks (every 30s or when count hits 50)."""
    logger.info("Starting optimized query log writer task.")
    accumulated = []
    last_flush_time = time.time()
    
    while True:
        try:
            # If we've hit 50 entries, flush immediately
            if len(accumulated) >= 50:
                await asyncio.get_running_loop().run_in_executor(None, flush_logs_sync, list(accumulated))
                accumulated.clear()
                last_flush_time = time.time()
                
            # Calculate remaining time until next scheduled 30s flush
            elapsed = time.time() - last_flush_time
            timeout = max(0.1, 30.0 - elapsed)
            
            try:
                # Wait for next item in queue
                entry = await asyncio.wait_for(log_queue.get(), timeout=timeout)
                accumulated.append(entry)
                log_queue.task_done()
            except asyncio.TimeoutError:
                # 30 seconds have passed since last flush, flush whatever we have accumulated
                if accumulated:
                    await asyncio.get_running_loop().run_in_executor(None, flush_logs_sync, list(accumulated))
                    accumulated.clear()
                last_flush_time = time.time()
                
        except asyncio.CancelledError:
            # Drain any remaining entries from the queue into accumulated before flushing
            while not log_queue.empty():
                try:
                    entry = log_queue.get_nowait()
                    accumulated.append(entry)
                    log_queue.task_done()
                except (asyncio.QueueEmpty, ValueError):
                    break
            # Flush remaining logs on cancellation (e.g. shutdown)
            if accumulated:
                try:
                    flush_logs_sync(accumulated)
                except Exception as e:
                    logger.error(f"Error flushing logs on shutdown: {e}")
            break
        except Exception as e:
            logger.error(f"Query log worker error: {e}")
            await asyncio.sleep(1)

async def dns_cache_cleaner():
    """Background task to remove expired records from the DNS cache and prune database logs."""
    logger.info("Starting DNS cache cleaner and log pruner task.")
    last_prune_time = 0.0
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            expired_keys = [k for k, v in DNS_CACHE.items() if now >= v[1]]
            for k in expired_keys:
                DNS_CACHE.pop(k, None)
            if expired_keys:
                logger.debug(f"Pruned {len(expired_keys)} expired DNS cache records.")
                
            # Run DB logs pruning every 12 hours
            if now - last_prune_time >= 43200:
                await asyncio.get_running_loop().run_in_executor(None, prune_query_logs)
                last_prune_time = now
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"DNS cache cleaner error: {e}")

class DNSUDPProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for the DNS server."""
    def connection_made(self, transport):
        self.transport = transport
        
    def datagram_received(self, data, addr):
        asyncio.create_task(self.handle_query(data, addr))
        
    async def handle_query(self, data, addr):
        reply = await resolve_dns(data, addr[0], "UDP")
        if reply and self.transport:
            try:
                self.transport.sendto(reply, addr)
            except Exception as e:
                logger.error(f"Failed sending UDP response to {addr}: {e}")

async def handle_dns_tcp(reader, writer):
    """TCP request handler for the DNS server."""
    addr = writer.get_extra_info('peername')
    client_ip = addr[0] if addr else "unknown"
    try:
        while True:
            len_bytes = await reader.readexactly(2)
            if not len_bytes:
                break
            length = int.from_bytes(len_bytes, byteorder='big')
            data = await reader.readexactly(length)
            
            reply = await resolve_dns(data, client_ip, "TCP")
            if reply:
                resp_len = len(reply).to_bytes(2, byteorder='big')
                writer.write(resp_len + reply)
                await writer.drain()
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        logger.error(f"TCP DNS server error for {client_ip}: {e}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

async def start_dns_servers():
    """Start the UDP and TCP DNS servers on the configured port."""
    loop = asyncio.get_running_loop()
    
    # Reload caches initially
    reload_clients_cache()
    reload_custom_rules_cache()
    reload_upstream_dns_cache()
    reload_local_dns_cache()
    reload_privacy_mode()
    reload_premium_cache()
    reload_parental_rules_cache()
    
    # Start background helpers
    asyncio.create_task(log_writer_worker())
    asyncio.create_task(dns_cache_cleaner())
    
    # Start UDP Server
    logger.info(f"Starting UDP DNS server on {DNS_HOST}:{DNS_PORT}")
    try:
        udp_transport, udp_protocol = await loop.create_datagram_endpoint(
            lambda: DNSUDPProtocol(),
            local_addr=(DNS_HOST, DNS_PORT)
        )
    except Exception as e:
        logger.critical(f"Failed to start UDP DNS server on port {DNS_PORT}: {e}")
        raise e
        
    # Start TCP Server
    logger.info(f"Starting TCP DNS server on {DNS_HOST}:{DNS_PORT}")
    try:
        tcp_server = await asyncio.start_server(
            handle_dns_tcp,
            DNS_HOST,
            DNS_PORT
        )
    except Exception as e:
        logger.critical(f"Failed to start TCP DNS server on port {DNS_PORT}: {e}")
        udp_transport.close()
        raise e
        
    return udp_transport, tcp_server
