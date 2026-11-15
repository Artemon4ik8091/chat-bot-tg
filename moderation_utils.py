import sqlite3
import time
from typing import Dict, List, Optional, Union


def record_ban(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    admin_id: Optional[int],
    source: str,
    created_at: str,
    until_date: Optional[int] = None,
    warn_count: Optional[int] = None,
    max_warns: Optional[int] = None,
    last_warn: Optional[Dict[str, Optional[str]]] = None,
):
    last_warn = last_warn or {}
    cursor.execute(
        '''INSERT INTO chat_ban_history (
               chat_id, user_id, admin_id, source, created_at, until_date,
               warn_count, max_warns, last_warn_created_at,
               last_warn_expires_at, last_warn_reason
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (
            str(chat_id),
            str(user_id),
            admin_id,
            source,
            created_at,
            until_date,
            warn_count,
            max_warns,
            last_warn.get('created_at'),
            last_warn.get('expires_at'),
            last_warn.get('reason'),
        )
    )


def get_chat_ban_history(cursor: sqlite3.Cursor, chat_id: Union[int, str]) -> List[dict]:
    cursor.execute(
        '''SELECT user_id, admin_id, source, created_at, until_date,
                  warn_count, max_warns, last_warn_created_at,
                  last_warn_expires_at, last_warn_reason
           FROM chat_ban_history
           WHERE chat_id = ?
           ORDER BY id DESC''',
        (str(chat_id),)
    )
    columns = (
        'user_id', 'admin_id', 'source', 'created_at', 'until_date',
        'warn_count', 'max_warns', 'last_warn_created_at',
        'last_warn_expires_at', 'last_warn_reason'
    )
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_latest_chat_ban(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str]
) -> Optional[dict]:
    cursor.execute(
        '''SELECT source, created_at, until_date, revoked_at
           FROM chat_ban_history
           WHERE chat_id = ? AND user_id = ?
           ORDER BY id DESC LIMIT 1''',
        (str(chat_id), str(user_id))
    )
    row = cursor.fetchone()
    if not row or row[3] is not None:
        return None
    return {'source': row[0], 'created_at': row[1], 'until_date': row[2]}


def get_active_chat_ban(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    now_timestamp: Optional[int] = None
) -> Optional[dict]:
    ban = get_latest_chat_ban(cursor, chat_id, user_id)
    if ban is None:
        return None
    until_date = ban['until_date']
    if now_timestamp is None:
        now_timestamp = int(time.time())
    if until_date is not None and until_date <= now_timestamp:
        return None
    return ban


def revoke_latest_chat_ban(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    revoked_at: str
) -> bool:
    cursor.execute(
        '''UPDATE chat_ban_history
           SET revoked_at = ?
           WHERE id = (
               SELECT id FROM chat_ban_history
               WHERE chat_id = ? AND user_id = ?
               ORDER BY id DESC LIMIT 1
           )
             AND revoked_at IS NULL''',
        (revoked_at, str(chat_id), str(user_id))
    )
    return cursor.rowcount > 0


def has_recent_matching_ban(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    until_date: Optional[int],
    event_time: str
) -> bool:
    cursor.execute(
        '''SELECT 1 FROM chat_ban_history
           WHERE chat_id = ? AND user_id = ?
             AND until_date IS ?
             AND created_at BETWEEN datetime(?, '-5 minutes') AND datetime(?, '+5 minutes')
           LIMIT 1''',
        (str(chat_id), str(user_id), until_date, event_time, event_time)
    )
    return cursor.fetchone() is not None


def set_chat_mute(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    started_at: str,
    until_date: Optional[int]
):
    cursor.execute(
        '''INSERT INTO chat_mutes (chat_id, user_id, started_at, until_date)
           VALUES (?, ?, ?, ?)
           ON CONFLICT (chat_id, user_id) DO UPDATE SET
               started_at = excluded.started_at,
               until_date = excluded.until_date''',
        (str(chat_id), str(user_id), started_at, until_date)
    )


def clear_chat_mute(cursor: sqlite3.Cursor, chat_id: Union[int, str], user_id: Union[int, str]):
    cursor.execute(
        'DELETE FROM chat_mutes WHERE chat_id = ? AND user_id = ?',
        (str(chat_id), str(user_id))
    )


def get_chat_mute(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str]
) -> Optional[dict]:
    cursor.execute(
        '''SELECT started_at, until_date FROM chat_mutes
           WHERE chat_id = ? AND user_id = ?''',
        (str(chat_id), str(user_id))
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {'started_at': row[0], 'until_date': row[1]}
