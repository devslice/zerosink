import socket
import struct
import time
import logging
import asyncio
import ipaddress
from datetime import datetime
from backend.database import get_db_connection

logger = logging.getLogger("zerosink.dhcp")

# Background task reference
dhcp_task = None
dhcp_transport = None

class DHCPPacket:
    def __init__(self):
        self.op = 1        # 1 = Boot Request, 2 = Boot Reply
        self.htype = 1     # 1 = Ethernet
        self.hlen = 6      # MAC address length
        self.hops = 0
        self.xid = b'\x00\x00\x00\x00'
        self.secs = 0
        self.flags = 0
        self.ciaddr = '0.0.0.0'
        self.yiaddr = '0.0.0.0'
        self.siaddr = '0.0.0.0'
        self.giaddr = '0.0.0.0'
        self.chaddr = b'\x00' * 6
        self.options = {}

    @classmethod
    def parse(cls, data):
        if len(data) < 240:
            return None
        try:
            packet = cls()
            packet.op, packet.htype, packet.hlen, packet.hops = struct.unpack('!BBBB', data[:4])
            packet.xid = data[4:8]
            packet.secs, packet.flags = struct.unpack('!HH', data[8:12])
            packet.ciaddr = socket.inet_ntoa(data[12:16])
            packet.yiaddr = socket.inet_ntoa(data[16:20])
            packet.siaddr = socket.inet_ntoa(data[20:24])
            packet.giaddr = socket.inet_ntoa(data[24:28])
            packet.chaddr = data[28:28 + packet.hlen]
            
            # Check magic cookie
            cookie = data[236:240]
            if cookie != b'\x63\x82\x53\x63':
                return None
                
            # Parse options
            idx = 240
            while idx < len(data):
                opt_type = data[idx]
                if opt_type == 0:  # Padding
                    idx += 1
                    continue
                if opt_type == 255:  # End
                    break
                if idx + 1 >= len(data):
                    break
                opt_len = data[idx + 1]
                if idx + 2 + opt_len > len(data):
                    break
                opt_val = data[idx + 2 : idx + 2 + opt_len]
                packet.options[opt_type] = opt_val
                idx += 2 + opt_len
                
            return packet
        except Exception as e:
            logger.error(f"Error parsing DHCP packet: {e}")
            return None

    def pack(self):
        try:
            header = struct.pack('!BBBB', self.op, self.htype, self.hlen, self.hops)
            header += self.xid
            header += struct.pack('!HH', self.secs, self.flags)
            header += socket.inet_aton(self.ciaddr)
            header += socket.inet_aton(self.yiaddr)
            header += socket.inet_aton(self.siaddr)
            header += socket.inet_aton(self.giaddr)
            header += self.chaddr.ljust(16, b'\x00')
            header += b'\x00' * 64   # sname
            header += b'\x00' * 128  # file
            header += b'\x63\x82\x53\x63'  # magic cookie
            
            options_bytes = b''
            for opt_type, opt_val in self.options.items():
                options_bytes += struct.pack('!BB', opt_type, len(opt_val)) + opt_val
            options_bytes += b'\xff'  # End
            
            full_packet = header + options_bytes
            # Ensure minimum packet size of 300 bytes for compatibility
            if len(full_packet) < 300:
                full_packet += b'\x00' * (300 - len(full_packet))
            return full_packet
        except Exception as e:
            logger.error(f"Error packing DHCP packet: {e}")
            return b''

def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    return IP

def get_dhcp_settings():
    """Retrieve DHCP configuration settings from database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'dhcp_%'")
    rows = cursor.fetchall()
    conn.close()
    
    settings = {
        "dhcp_enabled": 0,
        "dhcp_range_start": "",
        "dhcp_range_end": "",
        "dhcp_router": "",
        "dhcp_subnet_mask": "255.255.255.0",
        "dhcp_lease_time": 86400  # 24 hours
    }
    
    for r in rows:
        val = r["value"]
        if r["key"] == "dhcp_enabled":
            settings["dhcp_enabled"] = int(val)
        elif r["key"] == "dhcp_lease_time":
            settings["dhcp_lease_time"] = int(val)
        else:
            settings[r["key"]] = val
            
    return settings

def mac_to_str(mac_bytes: bytes) -> str:
    return ":".join(f"{b:02x}" for b in mac_bytes)

def get_available_ip(mac_str: str, settings: dict) -> str:
    """Find an available IP address in the configured DHCP pool range."""
    start_ip = settings.get("dhcp_range_start")
    end_ip = settings.get("dhcp_range_end")
    if not start_ip or not end_ip:
        return None
        
    try:
        start_addr = int(ipaddress.IPv4Address(start_ip))
        end_addr = int(ipaddress.IPv4Address(end_ip))
    except Exception:
        return None
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. First check if this client already has an active lease
    cursor.execute("SELECT ip_address, expire_time FROM dhcp_leases WHERE mac_address = ?", (mac_str,))
    row = cursor.fetchone()
    if row:
        ip = row["ip_address"]
        expire = float(row["expire_time"])
        # If it matches the range and is either not expired or we want to keep it, return it
        if start_addr <= int(ipaddress.IPv4Address(ip)) <= end_addr:
            conn.close()
            return ip
            
    # 2. Get list of all leased/occupied IPs
    cursor.execute("SELECT ip_address, expire_time FROM dhcp_leases")
    leases = cursor.fetchall()
    conn.close()
    
    now = time.time()
    occupied = {}
    for l in leases:
        occupied[l["ip_address"]] = float(l["expire_time"])
        
    # 3. Find first free IP in range
    for val in range(start_addr, end_addr + 1):
        ip_str = str(ipaddress.IPv4Address(val))
        # If not leased, or lease expired
        if ip_str not in occupied or occupied[ip_str] < now:
            return ip_str
            
    return None

def save_dhcp_lease(mac_str: str, ip_str: str, hostname: str, duration_sec: int):
    """Save or update DHCP lease in SQLite."""
    expire = time.time() + duration_sec
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO dhcp_leases (mac_address, ip_address, hostname, expire_time)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mac_address) DO UPDATE SET 
                ip_address=excluded.ip_address, 
                hostname=excluded.hostname, 
                expire_time=excluded.expire_time
        """, (mac_str, ip_str, hostname, str(expire)))
        conn.commit()
        logger.info(f"Saved DHCP lease: MAC={mac_str} IP={ip_str} Hostname={hostname} Expire={datetime.fromtimestamp(expire)}")
        
        # Also auto-update client IP listing in clients group 1 (Default) to resolve client names in query logs
        if hostname:
            cursor.execute("""
                INSERT INTO clients (group_id, ip_or_cidr, name)
                VALUES (1, ?, ?)
                ON CONFLICT(ip_or_cidr) DO UPDATE SET name=excluded.name
            """, (ip_str, hostname))
            conn.commit()
            
            # Reload DNS client cache
            from backend.dns_engine import reload_clients_cache
            reload_clients_cache()
    except Exception as e:
        logger.error(f"Failed to save DHCP lease: {e}")
    finally:
        conn.close()

def delete_dhcp_lease(mac_str: str):
    """Delete a DHCP lease."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dhcp_leases WHERE mac_address = ?", (mac_str,))
    conn.commit()
    conn.close()

def parse_hostname_option(val_bytes: bytes) -> str:
    try:
        return val_bytes.decode('utf-8', errors='ignore').strip('\x00')
    except Exception:
        return ""

async def handle_dhcp_packet(data: bytes, transport):
    packet = DHCPPacket.parse(data)
    if not packet or packet.op != 1:  # Boot requests only
        return
        
    settings = get_dhcp_settings()
    if not settings.get("dhcp_enabled"):
        return
        
    msg_type = packet.options.get(53)
    if not msg_type:
        return
        
    msg_code = msg_type[0]
    mac_str = mac_to_str(packet.chaddr)
    hostname = parse_hostname_option(packet.options.get(12, b''))
    
    server_ip = get_local_ip()
    subnet_mask = settings.get("dhcp_subnet_mask", "255.255.255.0")
    router_ip = settings.get("dhcp_router") or server_ip
    dns_ip = server_ip  # Offer ZeroSink as DNS resolver
    lease_time = settings.get("dhcp_lease_time", 86400)
    
    # 1. Handle DHCPDISCOVER
    if msg_code == 1:
        offered_ip = get_available_ip(mac_str, settings)
        if not offered_ip:
            logger.warning(f"No IP addresses available in pool for discovery from {mac_str}")
            return
            
        logger.info(f"DHCP DISCOVER from {mac_str} ({hostname}) -> Offering {offered_ip}")
        
        reply = DHCPPacket()
        reply.op = 2
        reply.xid = packet.xid
        reply.yiaddr = offered_ip
        reply.siaddr = server_ip
        reply.chaddr = packet.chaddr
        
        # Options
        reply.options[53] = b'\x02'  # DHCPOFFER
        reply.options[54] = socket.inet_aton(server_ip)  # Server Identifier
        reply.options[1] = socket.inet_aton(subnet_mask)  # Subnet Mask
        reply.options[3] = socket.inet_aton(router_ip)  # Router
        reply.options[6] = socket.inet_aton(dns_ip)  # DNS
        reply.options[51] = struct.pack('!I', lease_time)  # Lease Time
        
        if hostname:
            reply.options[12] = hostname.encode('utf-8')
            
        packed = reply.pack()
        # Broadcast the offer back to port 68
        transport.sendto(packed, ('255.255.255.255', 68))
        
    # 2. Handle DHCPREQUEST
    elif msg_code == 3:
        requested_ip = packet.options.get(50)
        if requested_ip:
            requested_ip_str = socket.inet_ntoa(requested_ip)
        else:
            requested_ip_str = packet.ciaddr
            
        # Verify requested IP is available or matches MAC
        offered_ip = get_available_ip(mac_str, settings)
        
        if requested_ip_str and requested_ip_str == offered_ip:
            logger.info(f"DHCP REQUEST from {mac_str} ({hostname}) for {requested_ip_str} -> ACKing")
            
            # Save the lease to SQLite
            save_dhcp_lease(mac_str, requested_ip_str, hostname, lease_time)
            
            reply = DHCPPacket()
            reply.op = 2
            reply.xid = packet.xid
            reply.yiaddr = requested_ip_str
            reply.siaddr = server_ip
            reply.chaddr = packet.chaddr
            
            # Options
            reply.options[53] = b'\x05'  # DHCPACK
            reply.options[54] = socket.inet_aton(server_ip)
            reply.options[1] = socket.inet_aton(subnet_mask)
            reply.options[3] = socket.inet_aton(router_ip)
            reply.options[6] = socket.inet_aton(dns_ip)
            reply.options[51] = struct.pack('!I', lease_time)
            if hostname:
                reply.options[12] = hostname.encode('utf-8')
                
            packed = reply.pack()
            transport.sendto(packed, ('255.255.255.255', 68))
        else:
            logger.warning(f"DHCP REQUEST from {mac_str} for IP {requested_ip_str} rejected (expected {offered_ip}) -> NAKing")
            reply = DHCPPacket()
            reply.op = 2
            reply.xid = packet.xid
            reply.chaddr = packet.chaddr
            
            # Options
            reply.options[53] = b'\x06'  # DHCPNAK
            reply.options[54] = socket.inet_aton(server_ip)
            
            packed = reply.pack()
            transport.sendto(packed, ('255.255.255.255', 68))
            
    # 3. Handle DHCPRELEASE
    elif msg_code == 7:
        logger.info(f"DHCP RELEASE from {mac_str}")
        delete_dhcp_lease(mac_str)

class DHCPUDPProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        logger.info("DHCP UDP Protocol connection established.")
        
    def datagram_received(self, data, addr):
        asyncio.create_task(handle_dhcp_packet(data, self.transport))

async def prune_expired_leases_loop():
    """Background task to remove expired leases periodically."""
    logger.info("Starting DHCP leases expiration pruner.")
    while True:
        try:
            await asyncio.sleep(300)  # Check every 5 minutes
            now = time.time()
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM dhcp_leases WHERE CAST(expire_time AS REAL) < ?", (now,))
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            if deleted > 0:
                logger.info(f"Pruned {deleted} expired DHCP leases from database.")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"DHCP lease pruner error: {e}")

async def start_dhcp_server():
    """Create raw socket with broadcast options and start the DHCP listener."""
    global dhcp_task, dhcp_transport
    
    settings = get_dhcp_settings()
    if not settings.get("dhcp_enabled"):
        logger.info("DHCP server is disabled. Skipping startup.")
        return
        
    loop = asyncio.get_running_loop()
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    
    try:
        sock.bind(('0.0.0.0', 67))
    except Exception as e:
        logger.error(f"DHCP server failed to bind port 67: {e}. Check privileges/ports.")
        sock.close()
        return
        
    logger.info("Starting DHCP server listener on port 67...")
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: DHCPUDPProtocol(),
            sock=sock
        )
        dhcp_transport = transport
        dhcp_task = asyncio.create_task(prune_expired_leases_loop())
    except Exception as e:
        logger.critical(f"Failed starting DHCP engine datagram endpoint: {e}")
        sock.close()

async def stop_dhcp_server():
    """Stop the DHCP server listener and background tasks."""
    global dhcp_task, dhcp_transport
    if dhcp_transport:
        dhcp_transport.close()
        dhcp_transport = None
    if dhcp_task:
        dhcp_task.cancel()
        try:
            await dhcp_task
        except asyncio.CancelledError:
            pass
        dhcp_task = None
    logger.info("DHCP server stopped.")
