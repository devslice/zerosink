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
# If a secret is provided via environment, use it directly.
# Otherwise, persist a randomly-generated secret to disk so that JWT tokens
# remain valid across service restarts and updates.
def _load_or_create_jwt_secret() -> str:
    env_secret = os.environ.get("ZEROSINK_JWT_SECRET")
    if env_secret:
        return env_secret
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    secret_file = os.path.join(data_dir, ".jwt_secret")
    if os.path.exists(secret_file):
        with open(secret_file, "r") as f:
            stored = f.read().strip()
            if stored:
                return stored
    new_secret = secrets.token_hex(32)
    with open(secret_file, "w") as f:
        f.write(new_secret)
    return new_secret

JWT_SECRET = _load_or_create_jwt_secret()
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = int(os.environ.get("ZEROSINK_JWT_EXPIRATION_MINUTES", "1440"))  # 24 hours

# Default credentials (will be seeded if users table is empty)
DEFAULT_ADMIN_USER = os.environ.get("ZEROSINK_ADMIN_USER", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("ZEROSINK_ADMIN_PASSWORD", "zerosink")

# Application Version
VERSION = "1.0.9"

# Stripe Settings
ZEROSINK_LICENSING_URL = os.environ.get("ZEROSINK_LICENSING_URL", "https://zerosink-licensing.ant-90c.workers.dev/verify")
STRIPE_CHECKOUT_URL = os.environ.get("STRIPE_CHECKOUT_URL", "https://buy.stripe.com/test_aFa00lfaT7ZYgTm5LufMA00")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")  # Set via environment variable on the Pi
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "price_1TnMpcP4p1ovWS4ZUV3Aphkv")


