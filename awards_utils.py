import sqlite3
from typing import List, Union


def _normalize_award(award: str) -> str:
    normalized_award = award.strip()
    if not normalized_award:
        raise ValueError('Award name cannot be empty')
    return normalized_award


def add_user_award(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    award: str
) -> bool:
    normalized_award = _normalize_award(award)

    cursor.execute(
        '''INSERT OR IGNORE INTO chat_user_awards (chat_id, user_id, award, award_key)
           VALUES (?, ?, ?, ?)''',
        (
            str(chat_id),
            str(user_id),
            normalized_award,
            normalized_award.casefold()
        )
    )
    return cursor.rowcount > 0


def add_global_user_award(
    cursor: sqlite3.Cursor,
    user_id: Union[int, str],
    award: str
) -> bool:
    normalized_award = _normalize_award(award)
    cursor.execute(
        '''INSERT OR IGNORE INTO global_user_awards (user_id, award, award_key)
           VALUES (?, ?, ?)''',
        (str(user_id), normalized_award, normalized_award.casefold())
    )
    return cursor.rowcount > 0


def remove_user_award(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str],
    award: str
) -> bool:
    normalized_award = _normalize_award(award)
    cursor.execute(
        '''DELETE FROM chat_user_awards
           WHERE chat_id = ? AND user_id = ? AND award_key = ?''',
        (str(chat_id), str(user_id), normalized_award.casefold())
    )
    return cursor.rowcount > 0


def remove_global_user_award(
    cursor: sqlite3.Cursor,
    user_id: Union[int, str],
    award: str
) -> bool:
    normalized_award = _normalize_award(award)
    cursor.execute(
        '''DELETE FROM global_user_awards
           WHERE user_id = ? AND award_key = ?''',
        (str(user_id), normalized_award.casefold())
    )
    return cursor.rowcount > 0


def get_user_awards(
    cursor: sqlite3.Cursor,
    chat_id: Union[int, str],
    user_id: Union[int, str]
) -> List[str]:
    cursor.execute(
        '''SELECT award FROM chat_user_awards
           WHERE chat_id = ? AND user_id = ?
           ORDER BY id''',
        (str(chat_id), str(user_id))
    )
    return [row[0] for row in cursor.fetchall()]


def get_global_user_awards(cursor: sqlite3.Cursor, user_id: Union[int, str]) -> List[str]:
    cursor.execute(
        '''SELECT award FROM global_user_awards
           WHERE user_id = ?
           ORDER BY id''',
        (str(user_id),)
    )
    return [row[0] for row in cursor.fetchall()]
