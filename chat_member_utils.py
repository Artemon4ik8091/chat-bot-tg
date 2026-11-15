import sqlite3
from typing import Union


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
