#!/bin/bash
# ==============================================================================
# ZeroSink Uninstaller Script for Raspberry Pi OS & Debian/Ubuntu
# ==============================================================================

# Ensure script is run as root
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run this uninstaller as root (e.g., sudo ./uninstall.sh)"
  exit 1
fi

echo "========================================================"
echo "          Starting ZeroSink Uninstaller                 "
echo "========================================================"

# 1. Stop and disable systemd service
echo "[1/4] Stopping and disabling ZeroSink systemd service..."
if systemctl is-active --quiet zerosink; then
  systemctl stop zerosink
  echo "Service stopped."
fi

if systemctl is-enabled --quiet zerosink; then
  systemctl disable zerosink
  echo "Service disabled."
fi

# 2. Remove systemd service file
echo "[2/4] Removing systemd service files..."
if [ -f /etc/systemd/system/zerosink.service ]; then
  rm -f /etc/systemd/system/zerosink.service
  systemctl daemon-reload
  systemctl reset-failed
  echo "Service configuration removed."
else
  echo "No service file found at /etc/systemd/system/zerosink.service."
fi

# 3. Remove system user 'zerosink'
echo "[3/4] Removing system user 'zerosink'..."
if id "zerosink" &>/dev/null; then
  userdel zerosink
  echo "System user 'zerosink' removed."
else
  echo "System user 'zerosink' does not exist."
fi

# 4. Remove installation files
echo "[4/4] Removing installation directory /opt/zerosink..."
if [ -d "/opt/zerosink" ]; then
  rm -rf /opt/zerosink
  echo "Installation directory /opt/zerosink deleted."
else
  echo "Installation directory /opt/zerosink not found."
fi

echo "========================================================"
echo "   SUCCESS: ZeroSink has been completely removed.       "
echo "========================================================"
echo ""
echo "NOTE:"
echo "If you disabled the local DNSStubListener in systemd-resolved"
echo "(/etc/systemd/resolved.conf) during installation, you may"
echo "wish to re-enable it to restore default DNS resolving:"
echo ""
echo "  1. Edit /etc/systemd/resolved.conf and change/remove:"
echo "     DNSStubListener=no"
echo "  2. Restart the resolver:"
echo "     sudo systemctl restart systemd-resolved"
echo "========================================================"
