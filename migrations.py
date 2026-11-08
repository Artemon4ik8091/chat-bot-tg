from datetime import datetime
import os
import shutil
import sqlite3
import sys
from typing import Callable, List, Set


class Migration:
    def __init__(self, version: int, name: str, up: Callable[[sqlite3.Cursor], None]):
        self.version = version
        self.name = name
        self.up = up

    def __repr__(self):
        return f"<Migration v{self.version}: {self.name}>"


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


def column_exists(cursor: sqlite3.Cursor, table_name: str, column_name: str) -> bool:
    if not table_exists(cursor, table_name):
        return False
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


# ==============================================================================
# MIGRATION DEFINITIONS
# ==============================================================================

def migration_001_base_schema(cursor: sqlite3.Cursor):
    """Initial base schema: users, low_admins, legacy warns, chats, user_profiles, user_data."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            hashed_username TEXT PRIMARY KEY,
            user_id INTEGER
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS low_admins (
            chat_id TEXT,
            username TEXT,
            PRIMARY KEY (chat_id, username)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS warns (
            user_id TEXT PRIMARY KEY,
            warn_count INTEGER,
            last_warn_time TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            chat_id TEXT PRIMARY KEY,
            chat_title TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            nickname TEXT,
            description TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_data (
            chat_id TEXT,
            user_id TEXT,
            date TEXT,
            message_count INTEGER,
            last_activity TEXT,
            PRIMARY KEY (chat_id, user_id, date)
        )
    ''')


def migration_002_rp_requests(cursor: sqlite3.Cursor):
    """RP requests table with sender_first_name."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rp_requests (
            request_id TEXT PRIMARY KEY,
            chat_id TEXT,
            sender_id INTEGER,
            sender_first_name TEXT,
            target_id INTEGER,
            command TEXT,
            phrase TEXT,
            created_at TEXT
        )
    ''')
    if not column_exists(cursor, 'rp_requests', 'sender_first_name'):
        cursor.execute('ALTER TABLE rp_requests ADD COLUMN sender_first_name TEXT')


def migration_003_marriages(cursor: sqlite3.Cursor):
    """Marriages and marriage requests tables."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marriages (
            chat_id TEXT,
            spouse1_id INTEGER,
            spouse2_id INTEGER,
            created_at TEXT,
            PRIMARY KEY (chat_id, spouse1_id, spouse2_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marriage_requests (
            request_id TEXT PRIMARY KEY,
            chat_id TEXT,
            proposer_id INTEGER,
            proposer_first_name TEXT,
            target_id INTEGER,
            created_at TEXT
        )
    ''')


def migration_004_user_data_last_target(cursor: sqlite3.Cursor):
    """Add last_mentioned_target column to user_data if not exists."""
    if table_exists(cursor, 'user_data') and not column_exists(cursor, 'user_data', 'last_mentioned_target'):
        cursor.execute('ALTER TABLE user_data ADD COLUMN last_mentioned_target TEXT')


def migration_005_chat_warn_system(cursor: sqlite3.Cursor):
    """Per-chat warn settings and timed warns table."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_warn_settings (
            chat_id TEXT PRIMARY KEY,
            max_warns INTEGER DEFAULT 3,
            warn_duration INTEGER DEFAULT 86400
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            user_id TEXT,
            admin_id INTEGER,
            reason TEXT,
            created_at TEXT,
            expires_at TEXT
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_warns_chat_user 
        ON chat_warns (chat_id, user_id)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_warns_expires 
        ON chat_warns (expires_at)
    ''')


MIGRATIONS: List[Migration] = [
    Migration(1, "base_schema", migration_001_base_schema),
    Migration(2, "rp_requests", migration_002_rp_requests),
    Migration(3, "marriages", migration_003_marriages),
    Migration(4, "user_data_last_target", migration_004_user_data_last_target),
    Migration(5, "chat_warn_system", migration_005_chat_warn_system),
]


# ==============================================================================
# MIGRATION ENGINE
# ==============================================================================

def ensure_migrations_table(cursor: sqlite3.Cursor):
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    ''')


def get_applied_migrations(cursor: sqlite3.Cursor) -> Set[int]:
    ensure_migrations_table(cursor)
    cursor.execute('SELECT version FROM schema_migrations')
    return {row[0] for row in cursor.fetchall()}


def backup_database(db_path: str) -> str:
    """Creates a timestamped backup of the database file."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = f"{db_path}.bak_{timestamp}"
    shutil.copy2(db_path, backup_path)
    return backup_path


def run_migrations(db_path: str = 'bot_data.db', make_backup: bool = True) -> List[int]:
    """
    Applies all pending migrations to the specified SQLite database safely.
    If the database already exists and has pending migrations, creates a backup first.
    Returns list of newly applied migration versions.
    """
    db_exists = os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        applied_versions = get_applied_migrations(cursor)
        pending = [m for m in MIGRATIONS if m.version not in applied_versions]

        if not pending:
            return []

        # If database already existed and we have migrations to apply, create backup
        if db_exists and make_backup:
            try:
                b_path = backup_database(db_path)
                print(f"[Migrations] Created automatic pre-migration backup: {b_path}")
            except Exception as e:
                print(f"[Migrations] Warning: Failed to create database backup: {e}")

        applied = []
        for migration in pending:
            print(f"[Migrations] Applying v{migration.version:03d}_{migration.name}...")
            migration.up(cursor)
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                'INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)',
                (migration.version, migration.name, now_str)
            )
            conn.commit()
            applied.append(migration.version)
            print(f"[Migrations] Applied v{migration.version:03d}_{migration.name} successfully.")

        return applied
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def get_migration_status(db_path: str = 'bot_data.db') -> dict:
    """Returns a summary of applied and pending migrations."""
    if not os.path.exists(db_path):
        return {
            'db_exists': False,
            'applied': [],
            'pending': [{'version': m.version, 'name': m.name} for m in MIGRATIONS],
        }
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        applied_set = get_applied_migrations(cursor)
        cursor.execute('SELECT version, name, applied_at FROM schema_migrations ORDER BY version ASC')
        applied_details = [{'version': r[0], 'name': r[1], 'applied_at': r[2]} for r in cursor.fetchall()]
        pending_details = [
            {'version': m.version, 'name': m.name}
            for m in MIGRATIONS if m.version not in applied_set
        ]
        return {
            'db_exists': True,
            'applied': applied_details,
            'pending': pending_details,
        }
    finally:
        conn.close()


if __name__ == '__main__':
    command = sys.argv[1].lower() if len(sys.argv) > 1 else 'migrate'
    target_db = sys.argv[2] if len(sys.argv) > 2 else 'bot_data.db'

    if command == 'status':
        status = get_migration_status(target_db)
        print(f"=== Migration Status for {target_db} ===")
        print(f"Database exists: {status['db_exists']}")
        print("\nApplied migrations:")
        if status['applied']:
            for item in status['applied']:
                print(f"  [✓] v{item['version']:03d}_{item['name']} (applied at {item['applied_at']})")
        else:
            print("  (None)")
        print("\nPending migrations:")
        if status['pending']:
            for item in status['pending']:
                print(f"  [ ] v{item['version']:03d}_{item['name']}")
        else:
            print("  (All migrations applied. Up to date!)")

    elif command == 'backup':
        if not os.path.exists(target_db):
            print(f"Database {target_db} does not exist.")
        else:
            b_path = backup_database(target_db)
            print(f"Backup created: {b_path}")

    elif command in ['migrate', 'up', 'run']:
        print(f"Running migrations on {target_db}...")
        newly_applied = run_migrations(target_db)
        if newly_applied:
            print(f"Done! Successfully applied {len(newly_applied)} migrations.")
        else:
            print("Database is already up to date. No pending migrations.")
    else:
        print("Usage: python3 migrations.py [migrate|status|backup] [db_path]")
