#!/bin/bash
# ==============================================================================
# ZeroSink Installer Script for Raspberry Pi OS & Debian/Ubuntu
# ==============================================================================

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this installer as root (e.g., sudo ./install.sh)"
  exit 1
fi

echo "========================================================"
echo "          Starting ZeroSink Installer                   "
echo "========================================================"

# 1. Update package list and install system requirements
echo "[1/7] Installing system dependencies..."
apt-get update && apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  sqlite3 \
  curl \
  git \
  && echo "Dependencies installed successfully." || { echo "Failed to install dependencies."; exit 1; }

# 2. Create system user for ZeroSink (non-root, minimal privileges)
if id "zerosink" &>/dev/null; then
  echo "[2/7] System user 'zerosink' already exists."
else
  echo "[2/7] Creating system user 'zerosink'..."
  useradd --system --no-create-home --shell /bin/false zerosink
fi

# 3. Create install directory and copy code
INSTALL_DIR="/opt/zerosink"
echo "[3/7] Copying files to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"

# Check if local files are present; if not, clone the repository to a temp directory
TEMP_CLONE_DIR=""
if [ ! -d "backend" ] || [ ! -d "static" ] || [ ! -f "requirements.txt" ]; then
  echo "Local source files not found. Cloning ZeroSink repository from GitHub..."
  TEMP_CLONE_DIR=$(mktemp -d)
  git clone --depth 1 https://github.com/devslice/zerosink.git "$TEMP_CLONE_DIR"
  SRC_DIR="$TEMP_CLONE_DIR"
else
  SRC_DIR="."
fi

# Copy backend, static files and requirements.txt from source directory
cp -r "$SRC_DIR/backend" "$INSTALL_DIR/"
cp -r "$SRC_DIR/static" "$INSTALL_DIR/"
cp "$SRC_DIR/requirements.txt" "$INSTALL_DIR/"

# Clean up temp clone directory if created
if [ -n "$TEMP_CLONE_DIR" ]; then
  rm -rf "$TEMP_CLONE_DIR"
fi

# Ensure database directory exists and permissions are secure
mkdir -p "$INSTALL_DIR/data"
touch "$INSTALL_DIR/data/zerosink.db"

# Set ownership
chown -R zerosink:zerosink "$INSTALL_DIR"
chmod -R 755 "$INSTALL_DIR"
chmod -R 775 "$INSTALL_DIR/data"

# 4. Set up virtual environment
echo "[4/7] Setting up Python virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# 5. Initialize database
echo "[5/7] Initializing SQLite database..."
export ZEROSINK_DB_PATH="$INSTALL_DIR/data/zerosink.db"
(cd "$INSTALL_DIR" && sudo -u zerosink -E "$INSTALL_DIR/venv/bin/python" -m backend.database)

# 6. Configure systemd Service
echo "[6/7] Configuring systemd service..."
CAT_SERVICE=$(cat <<EOF
[Unit]
Description=ZeroSink DNS Blocker & Dashboard
After=network.target

[Service]
Type=simple
User=zerosink
Group=zerosink
WorkingDirectory=$INSTALL_DIR
Environment=ZEROSINK_DB_PATH=$INSTALL_DIR/data/zerosink.db
Environment=ZEROSINK_WEB_HOST=0.0.0.0
Environment=ZEROSINK_WEB_PORT=80
Environment=ZEROSINK_DNS_HOST=0.0.0.0
Environment=ZEROSINK_DNS_PORT=53
ExecStart=$INSTALL_DIR/venv/bin/python -m backend.main
Restart=always

# Security sandbox settings
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
)

echo "$CAT_SERVICE" > /etc/systemd/system/zerosink.service
systemctl daemon-reload

# 7. Start and Enable ZeroSink Service
echo "[7/7] Starting ZeroSink service..."
systemctl enable zerosink
systemctl restart zerosink

# Wait briefly for startup
sleep 2

if systemctl is-active --quiet zerosink; then
  LOCAL_IP=$(hostname -I | awk '{print $1}')
  echo "========================================================"
  echo "   SUCCESS! ZeroSink is running successfully.           "
  echo "========================================================"
  echo "  Local mDNS URL: http://zerosink.local"
  echo "  Dashboard URL:  http://$LOCAL_IP"
  echo "  DNS IP address: $LOCAL_IP"
  echo "--------------------------------------------------------"
  echo "  Note: To install as a Progressive Web App (PWA) on"
  echo "  your device, open http://zerosink.local in your"
  echo "  browser and select 'Add to Home Screen'."
  echo "========================================================"
  echo "To check logs, run: sudo journalctl -u zerosink -f"
else
  echo "========================================================"
  echo "   ERROR: ZeroSink service failed to start.             "
  echo "   Check logs with: sudo journalctl -u zerosink -n 50   "
  echo "========================================================"
fi
