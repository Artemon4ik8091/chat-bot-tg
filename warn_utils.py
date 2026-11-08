from datetime import datetime, timedelta
import re

DEFAULT_MAX_WARNS = 3
DEFAULT_WARN_DURATION = 86400  # 24 hours (1 day) in seconds


def init_warn_tables(cursor):
    """Initializes tables for chat-specific warn settings and timed warns."""
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


def format_duration(seconds):
    """Converts seconds into human-readable Russian string."""
    if seconds is None or seconds <= 0:
        return "бессрочно"
    seconds = int(seconds)
    days = seconds // 86400
    rem = seconds % 86400
    hours = rem // 3600
    rem = rem % 3600
    minutes = rem // 60
    secs = rem % 60

    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} ч.")
    if minutes > 0:
        parts.append(f"{minutes} мин.")
    if secs > 0 and not parts:
        parts.append(f"{secs} сек.")
    return " ".join(parts) if parts else "0 сек."


def parse_duration_string(text):
    """
    Parses a string representing time duration (e.g. '24h', '2d', '30m', 'навсегда', '0').
    Returns duration in seconds. 0 means permanent/no expiration. Returns None if invalid.
    """
    if not text:
        return None
    cleaned = text.strip().lower()
    if cleaned in ['0', 'навсегда', 'бессрочно', 'отключить', 'нет', 'бесконечно']:
        return 0

    m = re.match(r'^(\d+)\s*([smhdсмчд]|сек|мин|час|дн|день|дня|дней|часа|часов|минут|минуты)?$', cleaned)
    if m:
        val = int(m.group(1))
        unit = m.group(2) or 's'
        if unit in ['d', 'д', 'дн', 'день', 'дня', 'дней']:
            return val * 86400
        elif unit in ['h', 'ч', 'час', 'часа', 'часов']:
            return val * 3600
        elif unit in ['m', 'м', 'мин', 'минут', 'минуты']:
            return val * 60
        elif unit in ['s', 'с', 'сек']:
            return val
    return None


def get_chat_warn_settings(cursor, chat_id):
    """Returns max_warns and warn_duration for a specific chat."""
    cursor.execute('SELECT max_warns, warn_duration FROM chat_warn_settings WHERE chat_id = ?', (str(chat_id),))
    row = cursor.fetchone()
    if row:
        return {'max_warns': row[0], 'warn_duration': row[1]}
    return {'max_warns': DEFAULT_MAX_WARNS, 'warn_duration': DEFAULT_WARN_DURATION}


def set_chat_max_warns(cursor, chat_id, max_warns):
    """Sets max warns limit before ban for a specific chat."""
    cursor.execute('''
        INSERT INTO chat_warn_settings (chat_id, max_warns, warn_duration)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET max_warns = excluded.max_warns
    ''', (str(chat_id), int(max_warns), DEFAULT_WARN_DURATION))


def set_chat_warn_duration(cursor, chat_id, duration_seconds):
    """Sets default warn expiration duration in seconds for a specific chat."""
    cursor.execute('''
        INSERT INTO chat_warn_settings (chat_id, max_warns, warn_duration)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET warn_duration = excluded.warn_duration
    ''', (str(chat_id), DEFAULT_MAX_WARNS, int(duration_seconds)))


def cleanup_expired_warns(cursor, chat_id=None, now_dt=None):
    """
    Deletes all expired warns from the database.
    Can be run globally or scoped to a specific chat_id.
    """
    if now_dt is None:
        now_dt = datetime.now()
    now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')

    if chat_id is not None:
        cursor.execute('''
            DELETE FROM chat_warns 
            WHERE chat_id = ? AND expires_at IS NOT NULL AND expires_at != '' AND expires_at <= ?
        ''', (str(chat_id), now_str))
    else:
        cursor.execute('''
            DELETE FROM chat_warns 
            WHERE expires_at IS NOT NULL AND expires_at != '' AND expires_at <= ?
        ''', (now_str,))
    return cursor.rowcount


def get_user_warn_count(cursor, chat_id, user_id, now_dt=None):
    """Returns the count of active (non-expired) warns for a user in a chat."""
    cleanup_expired_warns(cursor, chat_id=chat_id, now_dt=now_dt)
    cursor.execute('''
        SELECT COUNT(*) FROM chat_warns 
        WHERE chat_id = ? AND user_id = ?
    ''', (str(chat_id), str(user_id)))
    row = cursor.fetchone()
    return row[0] if row else 0


def get_user_warns(cursor, chat_id, user_id, now_dt=None):
    """Returns list of active warns for a user in a chat."""
    cleanup_expired_warns(cursor, chat_id=chat_id, now_dt=now_dt)
    cursor.execute('''
        SELECT id, created_at, expires_at, admin_id, reason 
        FROM chat_warns 
        WHERE chat_id = ? AND user_id = ?
        ORDER BY created_at ASC
    ''', (str(chat_id), str(user_id)))
    results = []
    for row in cursor.fetchall():
        results.append({
            'id': row[0],
            'created_at': row[1],
            'expires_at': row[2],
            'admin_id': row[3],
            'reason': row[4],
        })
    return results


def add_warn(cursor, chat_id, user_id, admin_id=None, duration_seconds=None, reason=None, now_dt=None):
    """
    Adds a warn for a user in a chat.
    If duration_seconds is not specified, uses the chat's configured duration.
    Returns (current_warn_count, max_warns, effective_duration_seconds, expires_at_str).
    """
    if now_dt is None:
        now_dt = datetime.now()

    cleanup_expired_warns(cursor, chat_id=chat_id, now_dt=now_dt)
    settings = get_chat_warn_settings(cursor, chat_id)

    if duration_seconds is None:
        duration_seconds = settings['warn_duration']

    created_at_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
    if duration_seconds and duration_seconds > 0:
        expires_at_dt = now_dt + timedelta(seconds=duration_seconds)
        expires_at_str = expires_at_dt.strftime('%Y-%m-%d %H:%M:%S')
    else:
        expires_at_str = None

    cursor.execute('''
        INSERT INTO chat_warns (chat_id, user_id, admin_id, reason, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (str(chat_id), str(user_id), admin_id, reason, created_at_str, expires_at_str))

    cursor.execute('''
        SELECT COUNT(*) FROM chat_warns 
        WHERE chat_id = ? AND user_id = ?
    ''', (str(chat_id), str(user_id)))
    count = cursor.fetchone()[0]

    return count, settings['max_warns'], duration_seconds, expires_at_str


def remove_warn(cursor, chat_id, user_id, now_dt=None):
    """
    Removes the most recent active warn for a user in a chat.
    Returns (success_bool, remaining_count, max_warns).
    """
    cleanup_expired_warns(cursor, chat_id=chat_id, now_dt=now_dt)
    settings = get_chat_warn_settings(cursor, chat_id)

    cursor.execute('''
        SELECT id FROM chat_warns 
        WHERE chat_id = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
    ''', (str(chat_id), str(user_id)))
    row = cursor.fetchone()
    if not row:
        return False, 0, settings['max_warns']

    cursor.execute('DELETE FROM chat_warns WHERE id = ?', (row[0],))

    cursor.execute('''
        SELECT COUNT(*) FROM chat_warns 
        WHERE chat_id = ? AND user_id = ?
    ''', (str(chat_id), str(user_id)))
    remaining = cursor.fetchone()[0]
    return True, remaining, settings['max_warns']
