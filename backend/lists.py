import urllib.request
import urllib.error
import re
import logging
import sqlite3
from typing import Generator, Tuple
from backend.database import get_db_connection

logger = logging.getLogger("zerosink.lists")

# Regex to validate domain names roughly
DOMAIN_REGEX = re.compile(
    r'^([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])'
    r'(\.([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]))*$'
)

def parse_list_line(line: str) -> Tuple[str, bool]:
    """
    Parse a line from a blocklist.
    Returns (domain, is_whitelist) or (None, False).
    """
    line = line.strip()
    if not line or line.startswith('!') or line.startswith('#') or line.startswith('['):
        return None, False

    # Remove trailing comments starting with '#' or ';'
    if '#' in line:
        line = line.split('#')[0].strip()
    if ';' in line:
        line = line.split(';')[0].strip()

    if not line:
        return None, False

    # 1. AdGuard Whitelist Rule: @@||domain^
    if line.startswith('@@||'):
        # Extract domain before any separator (^, /, $, etc.)
        domain_part = line[4:]
        match = re.split(r'[\^/\$]', domain_part)
        domain = match[0].strip().lower()
        if DOMAIN_REGEX.match(domain):
            return domain, True
        return None, False

    # 2. AdGuard Block Rule: ||domain^
    if line.startswith('||'):
        domain_part = line[2:]
        match = re.split(r'[\^/\$]', domain_part)
        domain = match[0].strip().lower()
        if DOMAIN_REGEX.match(domain):
            return domain, False
        return None, False

    # 3. Hosts format: 127.0.0.1 domain or 0.0.0.0 domain
    # Split by whitespace
    tokens = line.split()
    if len(tokens) >= 2:
        # Check if first token is IP address (hosts style)
        first = tokens[0]
        if first in ('0.0.0.0', '127.0.0.1', '::1', '::'):
            domain = tokens[1].strip().lower()
            if DOMAIN_REGEX.match(domain):
                return domain, False
        return None, False

    # 4. Simple domain list
    domain = line.lower()
    if DOMAIN_REGEX.match(domain):
        return domain, False

    return None, False

def stream_list_domains(url: str) -> Generator[Tuple[str, bool], None, None]:
    """Stream domains line-by-line from a URL to keep memory usage at a minimum."""
    logger.info(f"Streaming list from {url}")
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'ZeroSink/1.0 (Raspberry Pi Zero 2 W; AdBlocker)'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            for line_bytes in response:
                line = line_bytes.decode('utf-8', errors='ignore')
                domain, is_whitelist = parse_list_line(line)
                if domain:
                    yield domain, is_whitelist
    except Exception as e:
        logger.error(f"Error streaming list {url}: {e}")
        raise e

def compile_group_lists(group_id: int):
    """
    Download and compile all enabled lists for a specific group.
    Uses atomic table swapping to prevent read-locks on query resolution.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Get all enabled lists for this group
        cursor.execute("SELECT id, name, url FROM adlists WHERE group_id = ? AND enabled = 1", (group_id,))
        lists = cursor.fetchall()
        
        if not lists:
            logger.info(f"No enabled adlists found for group {group_id}. Clearing compiled blocks.")
            cursor.execute("DELETE FROM compiled_blocks WHERE group_id = ?", (group_id,))
            conn.commit()
            return
            
        logger.info(f"Compiling blocks for group {group_id}. Found {len(lists)} active lists.")
        
        # Create temp table for compiling blocks
        temp_table_name = f"compiled_blocks_temp_{group_id}"
        cursor.execute(f"DROP TABLE IF EXISTS {temp_table_name}")
        cursor.execute(f"""
            CREATE TABLE {temp_table_name} (
                domain TEXT PRIMARY KEY
            )
        """)
        
        # Insert blocks streamingly
        batch = []
        batch_size = 2000
        total_count = 0
        
        for lst in lists:
            list_id, name, url = lst["id"], lst["name"], lst["url"]
            try:
                for domain, is_whitelist in stream_list_domains(url):
                    # For now, we only compile blocks (blocklists).
                    # AdGuard whitelists in public lists are ignored to prioritize local whitelists.
                    if not is_whitelist:
                        batch.append((domain,))
                        if len(batch) >= batch_size:
                            cursor.executemany(f"INSERT OR IGNORE INTO {temp_table_name} (domain) VALUES (?)", batch)
                            total_count += len(batch)
                            batch = []
            except Exception as e:
                logger.error(f"Failed to load adlist '{name}' from {url}: {e}")
                # We continue compiling other lists even if one fails
                continue
                
        # Insert remaining
        if batch:
            cursor.executemany(f"INSERT OR IGNORE INTO {temp_table_name} (domain) VALUES (?)", batch)
            total_count += len(batch)
            
        logger.info(f"Group {group_id}: Compiled {total_count} unique domains into {temp_table_name}.")
        
        # Commit the active batch insertion transaction first
        conn.commit()
        
        # Clear old records for group in compiled_blocks (implicitly starts a new transaction)
        cursor.execute("DELETE FROM compiled_blocks WHERE group_id = ?", (group_id,))
        
        # Copy from temp table
        cursor.execute(f"INSERT INTO compiled_blocks (group_id, domain) SELECT ?, domain FROM {temp_table_name}", (group_id,))
        
        # Drop temp table
        cursor.execute(f"DROP TABLE {temp_table_name}")
        
        # Commit transaction
        conn.commit()
        logger.info(f"Group {group_id}: Atomic swap complete.")
        
    except Exception as e:
        logger.error(f"Failed compiling group {group_id} lists: {e}")
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        # Clean up temp table if left behind
        try:
            conn.execute(f"DROP TABLE IF EXISTS compiled_blocks_temp_{group_id}")
        except sqlite3.Error:
            pass
    finally:
        conn.close()

def compile_all_groups():
    """Compile adlists for all groups in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM groups")
    groups = cursor.fetchall()
    conn.close()
    
    for g in groups:
        compile_group_lists(g["id"])
