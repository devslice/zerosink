import sqlite3
import os
import bcrypt
import logging
from backend.config import DB_PATH, DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD

logger = logging.getLogger("zerosink.database")

def get_db_connection():
    """Establish a connection to the SQLite database with optimized settings."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for concurrent reads/writes
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def hash_password(password: str) -> str:
    """Helper to hash password during database seeding."""
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

def init_db():
    """Initialize database tables if they do not exist and seed default values."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Groups Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT
    );
    """)
    
    # 2. Clients Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        ip_or_cidr TEXT UNIQUE NOT NULL,
        name TEXT,
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
    );
    """)
    
    # 3. Adlists Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS adlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
    );
    """)
    
    # 4. Custom Rules Table (Whitelist/Blacklist)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custom_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        domain TEXT NOT NULL,
        type TEXT NOT NULL, -- 'allow' (whitelist), 'deny' (blacklist)
        enabled INTEGER NOT NULL DEFAULT 1,
        is_regex INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
        UNIQUE(group_id, domain, type)
    );
    """)
    
    # 5. Compiled Blocks Table (Compiled blocker hosts)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS compiled_blocks (
        group_id INTEGER NOT NULL,
        domain TEXT NOT NULL,
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
        PRIMARY KEY (group_id, domain)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compiled_blocks_domain ON compiled_blocks(domain);")

    # 6. Query Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS query_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        client_ip TEXT NOT NULL,
        client_name TEXT,
        domain TEXT NOT NULL,
        query_type TEXT NOT NULL,
        status TEXT NOT NULL, -- 'Blocked', 'Allowed (Whitelist)', 'Allowed (Forwarded)', 'Allowed (Cached)'
        group_name TEXT NOT NULL,
        reply_time_ms REAL NOT NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_query_logs_timestamp ON query_logs(timestamp);")
    
    # 7. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        totp_secret TEXT,
        totp_enabled INTEGER NOT NULL DEFAULT 0
    );
    """)
    
    # 8. Settings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    
    # 9. Local DNS Records Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS local_dns_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        record_type TEXT NOT NULL, -- 'A' or 'AAAA'
        enabled INTEGER NOT NULL DEFAULT 1,
        UNIQUE(domain, ip_address, record_type)
    );
    """)
    
    # 10. DHCP Leases Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS dhcp_leases (
        mac_address TEXT PRIMARY KEY,
        ip_address TEXT UNIQUE NOT NULL,
        hostname TEXT,
        expire_time TEXT NOT NULL
    );
    """)
    
    # 11. Downtime Schedules Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS downtime_schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        days_of_week TEXT NOT NULL,
        blocked_categories TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
    );
    """)
    
    # 12. Group App Blocks Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS group_app_blocks (
        group_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        app_name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
        PRIMARY KEY (group_id, category, app_name)
    );
    """)

    
    # Run Migrations for existing users table
    cursor.execute("PRAGMA table_info(users);")
    columns = [row["name"] for row in cursor.fetchall()]
    if "totp_secret" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT;")
    if "totp_enabled" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0;")
        
    # Run Migrations for existing custom_rules table
    cursor.execute("PRAGMA table_info(custom_rules);")
    columns = [row["name"] for row in cursor.fetchall()]
    if "is_regex" not in columns:
        cursor.execute("ALTER TABLE custom_rules ADD COLUMN is_regex INTEGER NOT NULL DEFAULT 0;")
        
    # Commit table creation and migrations
    conn.commit()
    
    # Seeding: Default Group
    cursor.execute("SELECT id FROM groups WHERE id = 1")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO groups (id, name, description) VALUES (1, 'Default', 'Default blocking group for all devices')")
        conn.commit()
        logger.info("Seeded default group")
        
    # Seeding: Default User
    cursor.execute("SELECT id FROM users LIMIT 1")
    has_seeded_user = False
    if not cursor.fetchone():
        pwd_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (DEFAULT_ADMIN_USER, pwd_hash))
        conn.commit()
        logger.info(f"Seeded default user '{DEFAULT_ADMIN_USER}'")
        has_seeded_user = True
        
    # Seeding: Initial Setup Completed Setting
    cursor.execute("SELECT value FROM settings WHERE key = 'initial_setup_completed'")
    if not cursor.fetchone():
        # If we just seeded the first default user now, setup is NOT completed ('0').
        # Otherwise, if it's an upgrade of an existing DB with users, mark as completed ('1').
        if has_seeded_user:
            initial_value = '0'
        else:
            # Check if there are users
            cursor.execute("SELECT id FROM users LIMIT 1")
            has_users = cursor.fetchone() is not None
            initial_value = '1' if has_users else '0'
            
        cursor.execute("INSERT INTO settings (key, value) VALUES ('initial_setup_completed', ?)", (initial_value,))
        conn.commit()
        logger.info(f"Seeded initial_setup_completed = '{initial_value}'")
        
    # Seeding: Default Adlists (StevenBlack and AdGuard DNS filter)
    cursor.execute("SELECT id FROM adlists LIMIT 1")
    if not cursor.fetchone():
        default_lists = [
            ("StevenBlack Base Unified", "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"),
            ("AdGuard DNS Filter", "https://adguardteam.github.io/AdGuardSDNSFilter/Filters/filter.txt")
        ]
        for name, url in default_lists:
            cursor.execute("INSERT INTO adlists (group_id, name, url, enabled) VALUES (1, ?, ?, 1)", (name, url))
        conn.commit()
        logger.info("Seeded default public adlists")
        
    conn.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ZeroSink Database Manager")
    parser.add_argument("--init", action="store_true", help="Initialize the database")
    parser.add_argument("--disable-2fa", metavar="USERNAME", type=str, help="Emergency disable of 2FA for specified user")
    args = parser.parse_args()
    
    if args.disable_2fa:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET totp_enabled = 0, totp_secret = NULL WHERE username = ?", (args.disable_2fa,))
        conn.commit()
        if cursor.rowcount > 0:
            print(f"Successfully disabled 2FA and cleared secret for user '{args.disable_2fa}'.")
        else:
            print(f"User '{args.disable_2fa}' not found.")
        conn.close()
    else:
        init_db()
