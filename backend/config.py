import os
import secrets

# Base directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("ZEROSINK_DB_PATH", os.path.join(BASE_DIR, "zerosink.db"))

# DNS Settings
DNS_HOST = os.environ.get("ZEROSINK_DNS_HOST", "0.0.0.0")
DNS_PORT = int(os.environ.get("ZEROSINK_DNS_PORT", "53"))
UPSTREAM_DNS = os.environ.get("ZEROSINK_UPSTREAM_DNS", "1.1.1.1")

# Web Settings
WEB_HOST = os.environ.get("ZEROSINK_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("ZEROSINK_WEB_PORT", "80"))

# Auth & Security
# Generate a random key for JWT signing if not specified in environment
JWT_SECRET = os.environ.get("ZEROSINK_JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = int(os.environ.get("ZEROSINK_JWT_EXPIRATION_MINUTES", "1440"))  # 24 hours

# Default credentials (will be seeded if users table is empty)
DEFAULT_ADMIN_USER = os.environ.get("ZEROSINK_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ZEROSINK_ADMIN_PASSWORD", "zerosink")

# Application Version
VERSION = "1.0.11"

