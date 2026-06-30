# ZeroSink

ZeroSink is a secure, lightweight home DNS ad blocker designed specifically to run on a Raspberry Pi Zero 2 W under a strict **512MB RAM** ceiling. It features a Python (FastAPI) backend combined with an ultra-efficient asynchronous DNS engine and a single-page static web dashboard styled in dark neutral grays and vibrant Lime Green.

---

## Key Features

1. **Lightweight DNS Engine**: Custom UDP and TCP DNS server listening on port 53 that sinkholes ad domains to `0.0.0.0` (IPv4) / `::` (IPv6) and forwards clean traffic to `1.1.1.1`.
2. **Relational Group Customization**: Group clients by IP address or CIDR ranges. Assign custom allowed domains (whitelists), custom denied domains (blacklists), and active public adlists per group.
3. **Memory-Optimized Compiler**: Reads adlists streamingly line-by-line using chunked HTTP connections (negating RAM spikes) and compiles them into indexed SQLite tables.
4. **Fast Cache Layer**: Uses a TTL-respecting in-memory DNS cache to serve repeat queries instantly without contacting upstream or querying the database.
5. **Secure SPA Dashboard**: Fully stateless login gate with a Lime Green themed pane. All backend REST API endpoints are protected with JWT tokens.
6. **Streamable Backups**: Configuration import and export module that streams directly to/from SQLite.
7. **Two-Factor Authentication (2FA)**: Strengthen access control with built-in Time-based One-Time Password (TOTP) 2FA using any standard authenticator app (Google Authenticator, Authy, etc.).

---

## Directory Structure

```
ZeroSink/
├── backend/
│   ├── __init__.py
│   ├── config.py         # Network ports, JWT keys, and paths
│   ├── database.py       # SQLite database initialization, schemas, and seeds
│   ├── auth.py           # JWT generation, token verification, and bcrypt hashing
│   ├── lists.py          # Streaming blocklist downloader and compiler
│   ├── dns_engine.py     # Asynchronous UDP & TCP DNS servers and cache
│   └── main.py           # FastAPI routes, REST endpoints, and serve hook
├── static/
│   └── index.html        # SPA dashboard (Tailwind CSS + Alpine.js + Chart.js)
├── requirements.txt      # Python dependencies
└── README.md             # This guide
```

---

## Setup & Installation

ZeroSink requires binding to port `53` (UDP/TCP) for DNS resolution and port `80` (TCP) for the Web Dashboard. There are two simple installation options:

### Option 1: One-Line Curl Installer (Recommended for Raspberry Pi OS / Debian)

This is the easiest way to deploy ZeroSink on a host machine. Paste this command into your terminal to automatically install dependencies, set up a dedicated system user, configure the application, and start the systemd service:

```bash
curl -sSL https://raw.githubusercontent.com/devslice/zerosink/main/install.sh | sudo bash
```

*(Under the hood, the installer sets up the application directory at `/opt/zerosink/`, configures a Python virtual environment, grants `CAP_NET_BIND_SERVICE` capability to the Python executable, and runs the service in the background under systemd).*

---

### Option 2: Docker & Docker Compose

For containerized installation (independent of host OS Python versions):

1. Ensure you have Docker and Docker Compose installed.
2. Build and start the container in the background:
   ```bash
   docker compose up -d --build
   ```
3. Verify status:
   ```bash
   docker compose ps
   ```

---

## Access & Defaults

Once ZeroSink is running, you can access and test it using the following:

* **Web UI Dashboard**: The production dashboard is accessed universally across the home Wi-Fi network by going to `http://zerosink.local` on standard port 80.
* **Default Admin Credentials**:
  * **Username**: `admin`
  * **Password**: `zerosink`
  * *(You will be prompted to change this password on your first login)*
* **Test DNS Resolving**:
  Verify the server resolves clean domains and sinkholes ad domains:
  ```bash
  # Query a clean domain:
  nslookup google.com zerosink.local

  # Query an ad domain (should resolve to 0.0.0.0):
  nslookup doubleclick.net zerosink.local
  ```

---

## Configuration Variables

You can configure ZeroSink using the following environment variables (define them in your systemd service file or under the `environment` section of `docker-compose.yml`):

| Variable | Description | Default |
|---|---|---|
| `ZEROSINK_DNS_PORT` | Port for the DNS engine (UDP/TCP) | `53` |
| `ZEROSINK_DNS_HOST` | Bind address for DNS server | `0.0.0.0` |
| `ZEROSINK_WEB_PORT` | Port for the FastAPI Web Server & UI | `80` |
| `ZEROSINK_WEB_HOST` | Bind address for Web Server & UI | `0.0.0.0` |
| `ZEROSINK_DB_PATH` | Path to the SQLite database | `zerosink.db` |
| `ZEROSINK_UPSTREAM_DNS` | Upstream DNS resolvers (comma or space separated) | `1.1.1.1` |
| `ZEROSINK_JWT_SECRET` | Secret key for JWT signing | *Randomly generated* |
| `ZEROSINK_ADMIN_USER` | Initial default admin username | `admin` |
| `ZEROSINK_ADMIN_PASSWORD` | Initial default admin password | `zerosink` |

---

## Troubleshooting Port 53 Conflicts

Many Linux distributions run `systemd-resolved` by default, which binds to port 53 and will block ZeroSink. To disable the local stub resolver:

1. Edit `/etc/systemd/resolved.conf`:
   ```bash
   sudo nano /etc/systemd/resolved.conf
   ```
2. Uncomment or add:
   ```ini
   DNSStubListener=no
   ```
3. Restart resolved to free up port 53:
   ```bash
   sudo systemctl restart systemd-resolved
   ```

---

## Memory & Performance Optimizations (512MB RAM)

* **WAL Mode (Write-Ahead Logging)**: SQLite is configured with WAL mode enabled (`PRAGMA journal_mode=WAL`), allowing concurrent DNS logs insertions while queries read from the index.
* **Streaming List Compilation**: Blocks are parsed from network HTTP response line generators and written to SQLite in 2000-row transactions using temporary table swaps. The domain lists are never held in RAM.
* **IP CIDR Cache**: Network ranges are pre-parsed on startup and configuration update. Lookups check address range inclusion in a fast memory cache loop.
* **Log Queueing**: DNS transactions are queued in a thread-safe `asyncio.Queue` and written to disk in background batches. This isolates query resolution latency from SQLite disk writes.
* **TTL Cache Layer**: Resolved DNS replies are saved in-memory matching their DNS TTL. This completely bypasses the network and database for hot domains.
* **Immediate Cache Flush on Rule Changes**: The in-memory DNS cache is fully invalidated the moment any custom block rule, downtime schedule, or app-block toggle is modified via the dashboard, ensuring zero-delay policy enforcement.

---

## Active Connection Hardening (Conntrack Flush)

DNS blocking stops **new** connections from resolving blocked domains, but applications that already have open TCP/UDP sessions (e.g. streaming, gaming, persistent WebSockets) can continue to transmit data over those existing connections even after a block rule is applied.

To fully cut active connections when a device group is toggled from **Allowed → Blocked**, it is recommended to run a `conntrack` flush on the Linux firewall to drop active NAT and connection-tracking states:

```bash
# Flush all active tracked connections for a specific client IP
sudo conntrack -D -s <client_ip>

# Or flush all tracked connections globally (more aggressive)
sudo conntrack -F

# Optionally combine with a reset of iptables ESTABLISHED rules:
sudo iptables -I FORWARD -s <client_ip> -m state --state ESTABLISHED,RELATED -j DROP
sleep 2
sudo iptables -D FORWARD -s <client_ip> -m state --state ESTABLISHED,RELATED -j DROP
```

This can be triggered from a custom webhook, systemd service, or hooked into the ZeroSink API response for app-block toggle events via a local shell script on the Pi.

---

## Emergency 2FA Reset

If an administrator gets locked out of the dashboard or loses their 2FA device, 2FA can be disabled for a specific username via the database CLI utility:

* **For Installer (`/opt/zerosink`) Deployments**:
  ```bash
  (cd /opt/zerosink && sudo -u zerosink /opt/zerosink/venv/bin/python -m backend.database --disable-2fa admin)
  ```
* **For Docker Deployments**:
  ```bash
  docker compose exec zerosink python -m backend.database --disable-2fa admin
  ```

---

## Uninstallation

If you need to remove ZeroSink from your system, choose the appropriate method below:

### Option 1: Installer Deployment (/opt/zerosink)

You can run the automatic uninstaller script:
```bash
curl -sSL https://raw.githubusercontent.com/devslice/zerosink/main/uninstall.sh | sudo bash
```

Alternatively, you can remove the files and services manually:
```bash
# Stop and disable the systemd service
sudo systemctl stop zerosink
sudo systemctl disable zerosink

# Remove service definition and reload systemd
sudo rm /etc/systemd/system/zerosink.service
sudo systemctl daemon-reload
sudo systemctl reset-failed

# Remove installation directory and system user
sudo rm -rf /opt/zerosink
sudo userdel zerosink
```

If you disabled the local `systemd-resolved` listener (`DNSStubListener=no`) during installation, you can restore default DNS resolution by reverting that setting in `/etc/systemd/resolved.conf` and running:
```bash
sudo systemctl restart systemd-resolved
```

### Option 2: Docker Deployment

To tear down the containers, network, and associated volumes, run the following command in the repository directory:
```bash
docker compose down -v
```

---

## Local Network Access (mDNS) & PWA Installation

ZeroSink broadcasts itself dynamically on your local network using Multicast DNS (mDNS) on standard port 80 and is fully installable as a Progressive Web App (PWA).

### Local Address Resolution (mDNS)
The production dashboard is accessed universally across the home Wi-Fi network by going to:
- URL: [http://zerosink.local](http://zerosink.local) (on standard port 80)

### Standalone Mobile App (iOS & Android)
Mobile users (iOS and Android) can open this URL in their browser and use the browser options to launch ZeroSink as a clean, fullscreen standalone application:
1. **iOS (Safari)**: Open `http://zerosink.local` in Safari, tap the **Share** button (the square with an arrow pointing up), and select **Add to Home Screen**.
2. **Android (Chrome)**: Open `http://zerosink.local` in Chrome, tap the **three-dot menu** button in the top right corner, and select **Install app** or **Add to Home screen**.

Once installed, launching ZeroSink from the home screen opens it in a clean, borderless standalone frame without standard browser toolbars or navigation overlays.

### Desktop Standalone Application
1. **Desktop (Chrome/Edge)**: Open `http://zerosink.local` and click the **Install icon** on the right side of the address bar to run ZeroSink in its own dedicated, fullscreen-capable window.



