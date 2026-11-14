from datetime import datetime, timedelta
import sqlite3
from typing import Optional, Union


RETENTION_DAYS = 7


def mark_chat_member_left(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    left_at: str
) -> bool:
    cursor.execute(
        '''INSERT INTO chat_members (chat_id, user_id, first_seen_at, left_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT (chat_id, user_id) DO UPDATE SET left_at = excluded.left_at
           WHERE chat_members.left_at IS NULL''',
        (str(chat_id), str(user_id), left_at, left_at)
    )
    return cursor.rowcount > 0


def mark_chat_member_returned(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    returned_at: str
):
    cursor.execute(
        '''INSERT INTO chat_members (chat_id, user_id, first_seen_at, left_at)
           VALUES (?, ?, ?, NULL)
           ON CONFLICT (chat_id, user_id) DO UPDATE SET left_at = NULL''',
        (str(chat_id), str(user_id), returned_at)
    )


def purge_expired_chat_members(
    cursor: sqlite3.Cursor,
    now: Optional[datetime] = None
) -> int:
    if now is None:
        now = datetime.now()
    cutoff = (now - timedelta(days=RETENTION_DAYS)).strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute(
        '''DELETE FROM user_data
           WHERE EXISTS (
               SELECT 1 FROM chat_members
               WHERE chat_members.chat_id = user_data.chat_id
                 AND chat_members.user_id = user_data.user_id
                 AND chat_members.left_at IS NOT NULL
                 AND chat_members.left_at <= ?
           )''',
        (cutoff,)
    )
    deleted_stats_rows = cursor.rowcount
    cursor.execute(
        'DELETE FROM chat_members WHERE left_at IS NOT NULL AND left_at <= ?',
        (cutoff,)
    )
    return deleted_stats_rows
