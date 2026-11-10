import io
import json
import logging
import os
import random
import re
import sqlite3
import subprocess
import threading
import time
import traceback
import uuid

from datetime import datetime, timedelta

import telebot
from telebot.types import (
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from requests.exceptions import ReadTimeout, ConnectionError
from xxhash import xxh32

from criminal_code_utils import (
    CRIMINAL_CODE_EDITION,
    format_criminal_code_messages,
    format_criminal_code_punishments,
    get_random_criminal_code_article,
)
from rp_command_utils import (
    format_rp_response,
    load_chat_rp_commands,
    load_rp_commands,
    parse_rp_command_creation,
    parse_rp_command_delete,
    save_chat_rp_commands,
    save_rp_commands,
)
from shipping_utils import (
    format_shipping_message,
    generate_ship_name,
    get_chat_shipping_candidates,
    is_shipping_command,
    pick_random_pair,
)
from warn_utils import (
    add_warn,
    cleanup_expired_warns,
    format_duration,
    get_chat_warn_settings,
    get_user_warn_count,
    get_user_warns,
    init_warn_tables,
    parse_duration_string,
    remove_warn,
    set_chat_max_warns,
    set_chat_warn_duration,
)
from migrations import run_migrations

####### CREATE DB IF NOT EXIST ##########

if not os.path.exists('db.json'):
    db = {'token': 'None', 'admin_id_for_errors': None, 'owner_id': None, 'beta_testers': []}
    js = json.dumps(db, indent=2)
    with open('db.json', 'w') as outfile:
        outfile.write(js)
    print('ВНИМАНИЕ: Файл db.json создан. Введи токен в "None", свой ID администратора в "admin_id_for_errors", ID владельца в "owner_id" и IDs бета-тестеров в "beta_testers" (db.json)')
    exit()
else:
    print('DEBUG: Файл db.json существует.')

rp_data = load_rp_commands('rp_commands.json')
chat_rp_data = load_chat_rp_commands('rp_chat_commands.json')

from contextlib import contextmanager

@contextmanager
def db_connection():
    """Context manager for bot_data.db: yields a cursor, commits on success, always closes."""
    conn = sqlite3.connect('bot_data.db')
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    finally:
        conn.close()

# Initialize SQLite database via migrations
def init_sqlite_db():
    applied = run_migrations('bot_data.db', make_backup=True)
    if applied:
        print(f'DEBUG: SQLite database migrated ({len(applied)} migrations applied).')
    else:
        print('DEBUG: SQLite database is up to date.')

init_sqlite_db()

def warn_cleanup_worker():
    while True:
        try:
            with db_connection() as cursor:
                cleanup_expired_warns(cursor)
        except Exception as e:
            print(f"DEBUG: Error in warn cleanup: {e}")
        time.sleep(60)

threading.Thread(target=warn_cleanup_worker, daemon=True, name="WarnCleanupWorker").start()

############ WORK WITH DBs ##########

def read_db():
    with open('db.json', 'r') as openfile:
        return json.load(openfile)


def persist_rp_commands():
    global rp_data, chat_rp_data
    save_rp_commands(rp_data, 'rp_commands.json')
    save_chat_rp_commands(chat_rp_data, 'rp_chat_commands.json')
    return rp_data


def get_chat_rp_commands(chat_id):
    return chat_rp_data.get(str(chat_id), {})


def get_effective_rp_commands(chat_id):
    effective = dict(rp_data)
    effective.update(get_chat_rp_commands(chat_id))
    return effective


def write_db(db):
    js = json.dumps(db, indent=2)
    with open('db.json', 'w') as outfile:
        outfile.write(js)

def escape_html(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

known_errs = {
    'A request to the Telegram API was unsuccessful. Error code: 400. Description: Bad Request: not enough rights to restrict/unrestrict chat member': 'Увы, но у бота не хватает прав для этого.'
}

log_stream = io.StringIO()
logging.basicConfig(stream=log_stream, level=logging.ERROR)

def catch_error(message, e, err_type=None):
    if not err_type:
        global log_stream, known_errs
        e = str(e)
        print(f"DEBUG: Ошибка в обработке сообщения: {e}")
        print(f"DEBUG: Текст сообщения: {message.text}")
        print(f"DEBUG: Ответный текст: {locals().get('response_text', 'Не определён')}")
        if e in known_errs:
            bot.send_message(message.chat.id, known_errs[e])
        else:
            logging.error(traceback.format_exc())
            err = log_stream.getvalue()
            db_config = read_db()
            admin_id = db_config.get('admin_id_for_errors')
            if admin_id:
                try:
                    bot.send_message(admin_id, 'Критическая ошибка (свяжитесь с @aswer_user) :\n\n' + telebot.formatting.hcode(err), parse_mode='HTML')
                    bot.send_message(message.chat.id, 'Произошла критическая ошибка. Информация отправлена администратору.')
                except Exception as send_e:
                    print(f"Не удалось отправить ошибку администратору с ID {admin_id}: {send_e}")
                    bot.send_message(message.chat.id, 'Критическая ошибка (свяжитесь с @aswer_user) :\n\n' + telebot.formatting.hcode(err), parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, 'Критическая ошибка (свяжитесь с @aswer_user) :\n\n' + telebot.formatting.hcode(err), parse_mode='HTML')
            log_stream.truncate(0)
            log_stream.seek(0)
    elif err_type == 'no_user':
        bot.send_message(message.chat.id, 'Так.. а кому это адресованно то, глупый админ?')

def save_last_target(chat_id, user_id, target_id):
    with db_connection() as cursor:
        # Проверяем, существует ли запись, если нет — создаём
        cursor.execute('''
            INSERT OR IGNORE INTO user_data (chat_id, user_id, date, message_count, last_activity, last_mentioned_target)
            VALUES (?, ?, ?, 0, ?, ?)
        ''', (str(chat_id), str(user_id), datetime.now().strftime('%Y-%m-%d'), None, None))
        # Обновляем last_mentioned_target
        cursor.execute('''
            UPDATE user_data SET last_mentioned_target = ? 
            WHERE chat_id = ? AND user_id = ? AND date = ?
        ''', (str(target_id), str(chat_id), str(user_id), datetime.now().strftime('%Y-%m-%d')))

def get_last_target(chat_id, user_id):
    with db_connection() as cursor:
        cursor.execute('''
            SELECT last_mentioned_target FROM user_data 
            WHERE chat_id = ? AND user_id = ? AND date = ? LIMIT 1
        ''', (str(chat_id), str(user_id), datetime.now().strftime('%Y-%m-%d')))
        result = cursor.fetchone()
    return result[0] if result and result[0] else None

def save_rp_request(request_id, chat_id, sender_id, target_id, command, phrase, sender_first_name):
    with db_connection() as cursor:
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT INTO rp_requests (request_id, chat_id, sender_id, sender_first_name, target_id, command, phrase, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                       (request_id, str(chat_id), sender_id, sender_first_name, target_id, command, phrase, created_at))

def get_rp_request(request_id):
    with db_connection() as cursor:
        cursor.execute('SELECT chat_id, sender_id, sender_first_name, target_id, command, phrase FROM rp_requests WHERE request_id = ?', (request_id,))
        result = cursor.fetchone()
    return result if result else None

def save_marriage_request(request_id, chat_id, proposer_id, target_id, proposer_first_name):
    with db_connection() as cursor:
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT INTO marriage_requests (request_id, chat_id, proposer_id, proposer_first_name, target_id, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                       (request_id, str(chat_id), proposer_id, proposer_first_name, target_id, created_at))

def get_marriage_request(request_id):
    with db_connection() as cursor:
        cursor.execute('SELECT chat_id, proposer_id, proposer_first_name, target_id FROM marriage_requests WHERE request_id = ?', (request_id,))
        result = cursor.fetchone()
    return result if result else None

def delete_marriage_request(request_id):
    with db_connection() as cursor:
        cursor.execute('DELETE FROM marriage_requests WHERE request_id = ?', (request_id,))

def is_married(chat_id, user_id):
    with db_connection() as cursor:
        cursor.execute('''
            SELECT 1 FROM marriages 
            WHERE chat_id = ? AND (spouse1_id = ? OR spouse2_id = ?)
        ''', (str(chat_id), user_id, user_id))
        result = cursor.fetchone()
    return bool(result)

def get_spouse(chat_id, user_id):
    with db_connection() as cursor:
        cursor.execute('''
            SELECT spouse1_id, spouse2_id FROM marriages 
            WHERE chat_id = ? AND (spouse1_id = ? OR spouse2_id = ?)
        ''', (str(chat_id), user_id, user_id))
        result = cursor.fetchone()
    if result:
        return result[1] if result[0] == user_id else result[0]
    return None

def register_marriage(chat_id, user1_id, user2_id):
    min_id, max_id = sorted([user1_id, user2_id])
    with db_connection() as cursor:
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT OR IGNORE INTO marriages (chat_id, spouse1_id, spouse2_id, created_at) VALUES (?, ?, ?, ?)',
                       (str(chat_id), min_id, max_id, created_at))

def dissolve_marriage(chat_id, user_id):
    spouse_id = get_spouse(chat_id, user_id)
    if spouse_id:
        min_id, max_id = sorted([user_id, spouse_id])
        with db_connection() as cursor:
            cursor.execute('DELETE FROM marriages WHERE chat_id = ? AND spouse1_id = ? AND spouse2_id = ?',
                           (str(chat_id), min_id, max_id))
        return spouse_id
    return None

def get_all_marriages(chat_id):
    with db_connection() as cursor:
        cursor.execute('SELECT spouse1_id, spouse2_id, created_at FROM marriages WHERE chat_id = ?', (str(chat_id),))
        results = cursor.fetchall()
    return results

def read_users():
    with db_connection() as cursor:
        cursor.execute('SELECT hashed_username, user_id FROM users')
        users = {row[0]: row[1] for row in cursor.fetchall()}
    return users

def write_users(hashed_username, user_id):
    with db_connection() as cursor:
        cursor.execute('INSERT OR REPLACE INTO users (hashed_username, user_id) VALUES (?, ?)', (hashed_username, user_id))

def get_nickname(user_id):
    with db_connection() as cursor:
        cursor.execute('SELECT nickname FROM user_profiles WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
    return result[0] if result else None

def set_nickname(user_id, nickname):
    with db_connection() as cursor:
        # Создаём строку, если не существует (не трогаем существующие поля)
        cursor.execute('INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)', (user_id,))
        # Обновляем только ник
        cursor.execute('UPDATE user_profiles SET nickname = ? WHERE user_id = ?', (nickname, user_id))

def remove_nickname(user_id):
    with db_connection() as cursor:
        cursor.execute('UPDATE user_profiles SET nickname = NULL WHERE user_id = ?', (user_id,))

def get_description(user_id):
    with db_connection() as cursor:
        cursor.execute('SELECT description FROM user_profiles WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
    return result[0] if result else None

def set_description(user_id, description):
    with db_connection() as cursor:
        # Создаём строку, если не существует (не трогаем существующие поля)
        cursor.execute('INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)', (user_id,))
        # Обновляем только описание
        cursor.execute('UPDATE user_profiles SET description = ? WHERE user_id = ?', (description, user_id))

def remove_description(user_id):
    with db_connection() as cursor:
        cursor.execute('UPDATE user_profiles SET description = NULL WHERE user_id = ?', (user_id,))

def greet_owner_if_self(message, owner_id):
    if message.from_user.id == owner_id:
        bot.send_message(message.chat.id, "Так точно, создатель!")

def get_uptime():
    try:
        # Запускаем команду 'uptime'
        # 'capture_output=True' сохраняет stdout и stderr
        # 'text=True' декодирует вывод в строку (UTF-8 по умолчанию)
        result = subprocess.run(['uptime'], capture_output=True, text=True, check=True)
                
        # Возвращаем стандартный вывод команды
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        # Обработка ошибок, если команда завершилась с ненулевым кодом
        print(f"Ошибка выполнения команды: {e}")
        return ""
    except FileNotFoundError:
        # Обработка ошибки, если команда 'uptime' не найдена
        print("Команда 'uptime' не найдена.")
        return ""

def read_la():
    with db_connection() as cursor:
        cursor.execute('SELECT chat_id, username FROM low_admins')
        la = {}
        for chat_id, username in cursor.fetchall():
            if chat_id not in la:
                la[chat_id] = []
            la[chat_id].append(username)
    return la

def write_la(la):
    with db_connection() as cursor:
        cursor.execute('DELETE FROM low_admins')
        for chat_id, usernames in la.items():
            for username in usernames:
                cursor.execute('INSERT INTO low_admins (chat_id, username) VALUES (?, ?)', (chat_id, username))

def sha(text):
    text = str(text)
    return xxh32(text).hexdigest()

def retry_bot_call(message, func, *args, **kwargs):
    for attempt in range(3):
        try:
            return func(*args, **kwargs)
        except (ReadTimeout, ConnectionError) as e:
            if attempt < 2:
                try:
                    bot.send_message(message.chat.id, "Чёт не получилось, попробую сделать снова..")
                except:
                    pass  # If send fails, ignore
                time.sleep(1)
            else:
                try:
                    bot.send_message(message.chat.id, "Действие не удалось из за плохого подключения к интернету, можно попробовать отправить команду ещё раз.")
                except:
                    pass
                return None

def get_admins(message):
    try:
        chat = retry_bot_call(message, bot.get_chat, message.chat.id)
        if chat is None:
            return None
        if chat.type == 'private':
            return []
        else:
            admins = retry_bot_call(message, bot.get_chat_administrators, chat_id=message.chat.id)
            if admins is None:
                return None
            true_admins = []
            for i in admins:
                if i.status == 'creator' or i.can_restrict_members == True:
                    true_admins.append(i.user.id)
        return true_admins
    except Exception as e:
        catch_error(message, e)
        return None

def is_anon(message):
    if message.from_user.username == 'Channel_Bot' or message.from_user.username == 'GroupAnonymousBot':
        if message.from_user.is_premium == None:
            return True
    return False

def get_target(message):
    try:
        users = read_users()
        spl = message.text.split()
        if (len(spl) > 1 and spl[1][0] == '@') or (len(spl) > 2 and spl[2][0] == '@'):
            for i in spl:
                if i[0] == '@':
                    username = i[1:]
                    break
            hashed_username = sha(username)
            if hashed_username in users:
                return users[hashed_username]
            return None
        else:
            target = message.reply_to_message.from_user.id
            if target not in get_admins(message):
                return target
            return None
    except:
        return None

def get_name(message):
    try:
        text = message.text.split()
        if len(text) > 1 and text[1].startswith('@'):
            username = text[1][1:]
            if re.match(r'^[a-zA-Z0-9_]+$', username):
                users = read_users()
                hashed_username = sha(username.lower())
                if hashed_username in users:
                    user_id = users[hashed_username]
                    return get_user_link_sync(user_id, message.chat.id)
                return format_user_link(username, username)
            else:
                return "пользователь"
        if len(text) > 2 and text[2].startswith('@'):
            username = text[2][1:]
            if re.match(r'^[a-zA-Z0-9_]+$', username):
                users = read_users()
                hashed_username = sha(username.lower())
                if hashed_username in users:
                    user_id = users[hashed_username]
                    return get_user_link_sync(user_id, message.chat.id)
                return format_user_link(username, username)
            else:
                return "пользователь"
        target_user = message.reply_to_message.from_user
        display_name = get_nickname(target_user.id) or target_user.first_name
        return format_user_link(display_name, target_user.username, target_user.id)
    except Exception as e:
        catch_error(message, e)
        return "пользователь"

def get_time(message):
    formats = {'s': [1, 'секунд(ы)'], 'm': [60, 'минут(ы)'], 'h': [3600, 'час(а)'], 'd': [86400, 'день/дня']}
    text = message.text.split()[1:]
    time = None
    for i in text:
        if time:
            break
        for f in list(formats.keys()):
            if f in i:
                try:
                    time = [i[:-1], int(i[:-1]) * formats[i[-1]][0], formats[i[-1]][1]]
                    break
                except:
                    pass
    return time

def have_rights(message, set_la=False):
    db = read_db()
    owner_id = db['owner_id']
    if message.from_user.id == owner_id:
        return True
    la = read_la()
    if message.from_user.id in get_admins(message):
        return True
    elif is_anon(message):
        return True
    elif str(message.chat.id) in la and not set_la:
        if str(message.from_user.username) in la[str(message.chat.id)]:
            return True
    else:
        bot.reply_to(message, 'Да кто ты такой, чтобы я тебя слушался??')
        return False


def can_manage_rp_commands(message):
    db = read_db()
    owner_id = db.get('owner_id')
    if owner_id and message.from_user.id == owner_id:
        return True
    if getattr(message.chat, 'type', None) == 'private':
        return False
    admins = get_admins(message)
    return bool(admins and message.from_user.id in admins)

def can_manage_warn_settings(message):
    db = read_db()
    owner_id = db.get('owner_id')
    if owner_id and message.from_user.id == owner_id:
        return True
    if getattr(message.chat, 'type', None) == 'private':
        return False
    admins = get_admins(message)
    return bool(admins and message.from_user.id in admins)

def key_by_value(dictionary, key):
    for i in dictionary:
        if dictionary[i] == key:
            return i
    return None

def analytic(message):
    current_user_id = message.from_user.id
    current_username = message.from_user.username
    if current_username is None:
        return
    hashed_current_username = sha(current_username.lower())
    write_users(hashed_current_username, current_user_id)

def load_data(filename):
    with db_connection() as cursor:
        if filename == 'warns.json':
            cursor.execute('SELECT user_id, warn_count, last_warn_time FROM warns')
            data = {row[0]: {'warn_count': row[1], 'last_warn_time': row[2]} for row in cursor.fetchall()}
        elif filename == 'user_data.json':
            cursor.execute('SELECT chat_id, user_id, date, message_count, last_activity FROM user_data')
            data = {}
            for chat_id, user_id, date, message_count, last_activity in cursor.fetchall():
                if chat_id not in data:
                    data[chat_id] = {}
                if user_id not in data[chat_id]:
                    data[chat_id][user_id] = {'stats': {}, 'last_activity': last_activity}
                data[chat_id][user_id]['stats'][date] = message_count
    return data

def save_data(data, filename):
    with db_connection() as cursor:
        if filename == 'warns.json':
            cursor.execute('DELETE FROM warns')
            for user_id, info in data.items():
                cursor.execute('INSERT INTO warns (user_id, warn_count, last_warn_time) VALUES (?, ?, ?)',
                               (user_id, info['warn_count'], info['last_warn_time']))
        elif filename == 'user_data.json':
            cursor.execute('DELETE FROM user_data')
            for chat_id, users in data.items():
                for user_id, info in users.items():
                    last_activity = info.get('last_activity', '')
                    for date, count in info['stats'].items():
                        cursor.execute('INSERT INTO user_data (chat_id, user_id, date, message_count, last_activity) VALUES (?, ?, ?, ?, ?)',
                                       (chat_id, user_id, date, count, last_activity))

user_warns = load_data('warns.json')

user_data = load_data('user_data.json')

def get_user_daily_stats(chat_id, user_id):
    today = datetime.now().strftime('%Y-%m-%d')
    with db_connection() as cursor:
        cursor.execute('SELECT message_count FROM user_data WHERE chat_id = ? AND user_id = ? AND date = ?',
                       (str(chat_id), str(user_id), today))
        result = cursor.fetchone()
    return result[0] if result else 0

def get_user_weekly_stats(chat_id, user_id):
    week_ago = datetime.now() - timedelta(days=7)
    week_ago_str = week_ago.strftime('%Y-%m-%d')
    with db_connection() as cursor:
        cursor.execute('SELECT SUM(message_count) FROM user_data WHERE chat_id = ? AND user_id = ? AND date >= ?',
                       (str(chat_id), str(user_id), week_ago_str))
        result = cursor.fetchone()
    return result[0] if result[0] else 0

def get_user_monthly_stats(chat_id, user_id):
    month_ago = datetime.now() - timedelta(days=30)
    month_ago_str = month_ago.strftime('%Y-%m-%d')
    with db_connection() as cursor:
        cursor.execute('SELECT SUM(message_count) FROM user_data WHERE chat_id = ? AND user_id = ? AND date >= ?',
                       (str(chat_id), str(user_id), month_ago_str))
        result = cursor.fetchone()
    return result[0] if result[0] else 0

def get_user_all_time_stats(chat_id, user_id):
    with db_connection() as cursor:
        cursor.execute('SELECT SUM(message_count) FROM user_data WHERE chat_id = ? AND user_id = ?',
                       (str(chat_id), str(user_id)))
        result = cursor.fetchone()
    return result[0] if result[0] else 0

def get_daily_stats(chat_id):
    today = datetime.now().strftime('%Y-%m-%d')
    with db_connection() as cursor:
        cursor.execute('SELECT user_id, message_count FROM user_data WHERE chat_id = ? AND date = ?',
                       (str(chat_id), today))
        daily_stats = {row[0]: row[1] for row in cursor.fetchall()}
    return daily_stats

def get_weekly_stats(chat_id):
    week_ago = datetime.now() - timedelta(days=7)
    week_ago_str = week_ago.strftime('%Y-%m-%d')
    with db_connection() as cursor:
        cursor.execute('SELECT user_id, SUM(message_count) FROM user_data WHERE chat_id = ? AND date >= ? GROUP BY user_id',
                       (str(chat_id), week_ago_str))
        weekly_stats = {row[0]: row[1] for row in cursor.fetchall()}
    return weekly_stats

def get_monthly_stats(chat_id):
    month_ago = datetime.now() - timedelta(days=30)
    month_ago_str = month_ago.strftime('%Y-%m-%d')
    with db_connection() as cursor:
        cursor.execute('SELECT user_id, SUM(message_count) FROM user_data WHERE chat_id = ? AND date >= ? GROUP BY user_id',
                       (str(chat_id), month_ago_str))
        monthly_stats = {row[0]: row[1] for row in cursor.fetchall()}
    return monthly_stats

def get_all_time_stats(chat_id):
    with db_connection() as cursor:
        cursor.execute('SELECT user_id, SUM(message_count) FROM user_data WHERE chat_id = ? GROUP BY user_id',
                       (str(chat_id),))
        all_time_stats = {row[0]: row[1] for row in cursor.fetchall()}
    return all_time_stats

def warn_user(message, user_id, duration_seconds=None):
    chat_id = message.chat.id
    admin_id = message.from_user.id if message.from_user else None
    with db_connection() as cursor:
        warn_count, max_warns, effective_dur, expires_at = add_warn(
            cursor, chat_id, user_id, admin_id=admin_id, duration_seconds=duration_seconds
        )
    target_name = get_name(message)
    duration_str = format_duration(effective_dur)

    if warn_count < max_warns:
        if warn_count == 1:
            text = f"{target_name}, ая-яй, вредим значит? Так нельзя. Пока что просто предупреждаю.\n"
        else:
            text = f"{target_name}, ты опять вредишь? Напоминаю: преды не бесконечные!\n"
        text += f"⚠️ Предупреждение <b>[{warn_count}/{max_warns}]</b>"
        if effective_dur and effective_dur > 0:
            text += f" (срок действия: {duration_str})"
        text += f". При достижении {max_warns} — бан!"
        bot.reply_to(message, text, parse_mode='HTML')
    else:
        bot.reply_to(
            message,
            f"Я предупреждал... Лимит предупреждений <b>[{warn_count}/{max_warns}]</b> исчерпан. Прощай, {target_name}!",
            parse_mode='HTML'
        )
        try:
            bot.ban_chat_member(chat_id, user_id)
        except Exception as e:
            catch_error(message, e)

def remove_warn_for_user(message, user_id):
    chat_id = message.chat.id
    with db_connection() as cursor:
        success, remaining, max_warns = remove_warn(cursor, chat_id, user_id)
    return success, remaining, max_warns

db = read_db()
print('DEBUG: Инициализация бота...')
bot = telebot.TeleBot(db['token'])
telebot.apihelper.proxy = {'https': 'http://127.0.0.1:7897'}
print('DEBUG: Бот успешно инициализирован. Запуск polling...')

def get_user_link_sync(user_id, chat_id, include_profile_link=True):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        display_name = get_nickname(user_id) or member.user.first_name
        username = member.user.username if include_profile_link else None
        return format_user_link(display_name, username, user_id)
    except Exception as e:
        print(f"Error getting user link for ID {user_id} in chat {chat_id}: {e}")
        return f"Пользователь {user_id}"

def format_user_link(display_name, username, user_id=None):
    display_name = escape_html(display_name)
    if username:
        username = escape_html(username.lstrip('@'))
        return f'<a href="https://t.me/{username}">{display_name}</a>'
    if user_id is not None:
        return f'{display_name} ({user_id})'
    return display_name

def format_time_ago(datetime_str):
    if not datetime_str:
        return "Нет данных"
    try:
        last_activity_dt = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M:%S')
        now = datetime.now()
        delta = now - last_activity_dt
        if delta.total_seconds() < 60:
            return "только что"
        elif delta.total_seconds() < 3600:
            minutes = int(delta.total_seconds() / 60)
            if minutes == 1:
                return f"{minutes} минуту назад"
            elif 2 <= minutes <= 4:
                return f"{minutes} минуты назад"
            else:
                return f"{minutes} минут назад"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            if hours == 1:
                return f"{hours} час назад"
            elif 2 <= hours <= 4:
                return f"{hours} часа назад"
            else:
                return f"{hours} часов назад"
        else:
            days = delta.days
            if days == 1:
                return f"{days} день назад"
            elif 2 <= days <= 4:
                return f"{days} дня назад"
            else:
                return f"{days} дней назад"
    except Exception as e:
        print(f"Ошибка при форматировании времени: {e}")
        return "Неизвестно"

def add_chat_to_db(chat_id, chat_title):
    with db_connection() as cursor:
        cursor.execute('INSERT OR REPLACE INTO chats (chat_id, chat_title) VALUES (?, ?)', (str(chat_id), chat_title))

def get_all_chats():
    with db_connection() as cursor:
        cursor.execute('SELECT chat_id FROM chats')
        chats = [row[0] for row in cursor.fetchall()]
    return chats

def get_profile_addition(chat_id, user_id):
    spouse_id = get_spouse(chat_id, user_id)
    if spouse_id:
        spouse_name = get_user_link_sync(spouse_id, chat_id, include_profile_link=False)
        return f"\n💍 В браке с {spouse_name}"
    return ""

@bot.message_handler(content_types=['new_chat_members'])
def handle_new_chat_members(message):
    db = read_db()
    owner_id = db['owner_id']
    bot_id = bot.get_me().id
    for user in message.new_chat_members:
        if user.id == bot_id:
            chat_title = bot.get_chat(message.chat.id).title
            add_chat_to_db(message.chat.id, chat_title)
        if user.id == owner_id:
            bot.send_message(message.chat.id, "Добро пожаловать, мой создатель! Рад вас видеть в этом чате. Как видишь я тут.. модерирую)")

@bot.message_handler(func=lambda message: message.text and message.text.upper() in ['ТОП ДЕНЬ', 'ТОП ДНЯ'])
def handle_top_day(message):
    chat_id = str(message.chat.id)
    daily_stats = get_daily_stats(chat_id)
    sorted_stats = sorted(daily_stats.items(), key=lambda x: x[1], reverse=True)
    text = "Топ крутышек за сегодня:\n"
    total_messages_chat = 0
    if not sorted_stats:
        text = "Статистика за сегодня пока пуста."
    else:
        for i, (user_id, count) in enumerate(sorted_stats):
            user_link = get_user_link_sync(int(user_id), message.chat.id)
            text += f"{i+1}. {user_link}: {count} сообщений\n"
            total_messages_chat += count
    text += f"\nВсего сообщений в чате за сегодня: {total_messages_chat}"
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True, disable_notification=True)

@bot.message_handler(func=lambda message: message.text and message.text.upper() in ['ТОП НЕДЕЛЯ', 'ТОП НЕДЕЛИ'])
def handle_top_week(message):
    chat_id = str(message.chat.id)
    weekly_stats = get_weekly_stats(chat_id)
    sorted_stats = sorted(weekly_stats.items(), key=lambda x: x[1], reverse=True)
    text = "Топ крутышек за неделю:\n"
    total_messages_chat = 0
    if not sorted_stats:
        text = "Статистика за неделю пока пуста."
    else:
        for i, (user_id, count) in enumerate(sorted_stats):
            user_link = get_user_link_sync(int(user_id), message.chat.id)
            text += f"{i+1}. {user_link}: {count} сообщений\n"
            total_messages_chat += count
    text += f"\nВсего сообщений в чате за неделю: {total_messages_chat}"
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True, disable_notification=True)

@bot.message_handler(func=lambda message: message.text and message.text.upper() in ['ТОП МЕСЯЦ', 'ТОП МЕСЯЦА'])
def handle_top_month(message):
    chat_id = str(message.chat.id)
    monthly_stats = get_monthly_stats(chat_id)
    sorted_stats = sorted(monthly_stats.items(), key=lambda x: x[1], reverse=True)
    text = "Топ крутышек за месяц:\n"
    total_messages_chat = 0
    if not sorted_stats:
        text = "Статистика за месяц пока пуста."
    else:
        for i, (user_id, count) in enumerate(sorted_stats):
            user_link = get_user_link_sync(int(user_id), message.chat.id)
            text += f"{i+1}. {user_link}: {count} сообщений\n"
            total_messages_chat += count
    text += f"\nВсего сообщений в чате за месяц: {total_messages_chat}"
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True, disable_notification=True)

@bot.message_handler(func=lambda message: message.text and message.text.upper() in ['ТОП', 'ТОП ВСЯ'])
def handle_top_all_time(message):
    chat_id = str(message.chat.id)
    all_time_stats = get_all_time_stats(chat_id)
    sorted_stats = sorted(all_time_stats.items(), key=lambda x: x[1], reverse=True)
    text = "Топ крутышек за всё время:\n"
    total_messages_chat = 0
    if not sorted_stats:
        text = "Статистика за всё время пока пуста."
    else:
        for i, (user_id, count) in enumerate(sorted_stats):
            user_link = get_user_link_sync(int(user_id), message.chat.id)
            text += f"{i+1}. {user_link}: {count} сообщений\n"
            total_messages_chat += count
    text += f"\nВсего сообщений в чате за всё время: {total_messages_chat}"
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True, disable_notification=True)

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, "Привет, я Барбариска, ваш чат бот, который поможет модерировать сие прекрасненькую группу. Надеюсь вам будет весело! Чтоб вызвать справку отправь .хелп")

@bot.message_handler(commands=['list'])
def handle_list(message):
    db = read_db()
    owner_id = db['owner_id']
    if message.from_user.id != owner_id:
        bot.reply_to(message, "Эта команда доступна только владельцу бота.")
        return
    chats = get_all_chats()
    if not chats:
        bot.send_message(message.chat.id, "Бот не добавлен ни в один чат.")
        return
    text = f"Список чатов ({len(chats)}):\n"
    for chat_id in chats:
        try:
            chat = bot.get_chat(int(chat_id))
            title = chat.title or "Private Chat"
            text += f"- {title} (ID: {chat_id})\n"
        except Exception as e:
            text += f"- Chat ID: {chat_id} (Ошибка получения названия: {e})\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    analytic(message)
    if message.text:
        chat_id = str(message.chat.id)
        user_id = str(message.from_user.id)
        date = datetime.now().strftime('%Y-%m-%d')
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with db_connection() as cursor:
            cursor.execute('SELECT message_count FROM user_data WHERE chat_id = ? AND user_id = ? AND date = ?',
                           (chat_id, user_id, date))
            result = cursor.fetchone()
            if result:
                cursor.execute('UPDATE user_data SET message_count = ?, last_activity = ? WHERE chat_id = ? AND user_id = ? AND date = ?',
                               (result[0] + 1, current_time if message.text.upper() != 'КТО Я' else '', chat_id, user_id, date))
            else:
                cursor.execute('INSERT INTO user_data (chat_id, user_id, date, message_count, last_activity) VALUES (?, ?, ?, ?, ?)',
                               (chat_id, user_id, date, 1, current_time if message.text.upper() != 'КТО Я' else ''))

    if message.text and message.text.strip().casefold() == 'моя статья':
        try:
            article = get_random_criminal_code_article()
            display_name = escape_html(get_nickname(message.from_user.id) or message.from_user.first_name)
            article_title = escape_html(article['title'])
            response_header = (
                f"⚖️ {display_name}, по версии шуточного суда Барбариски, тебе выпала статья "
                f"<b>{article['number']} УК РФ — {article_title}</b>."
            )
            response_details = []
            for punishment in format_criminal_code_punishments(article):
                part_label, text = punishment.split(": ", maxsplit=1)
                response_details.append(f"<b>{escape_html(part_label)}:</b> {escape_html(text)}")
            response_details.append(
                f"Санкции приведены по редакции УК РФ от {CRIMINAL_CODE_EDITION}; "
                "это не прогноз реального приговора. "
                "Команда шуточная и не является обвинением."
            )
            response_messages = format_criminal_code_messages(response_header, response_details)
            bot.reply_to(message, response_messages[0], parse_mode='HTML')
            for response in response_messages[1:]:
                bot.send_message(message.chat.id, response, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)
        return

    db = read_db()
    owner_id = db['owner_id']

    if message.text == 'bot?':
        username = escape_html(message.from_user.first_name)
        bot.reply_to(message, f'Hello. I see you, {username}')

    if message.text.upper() == "КАКАЯ НАГРУЗКА":
        uptime_output = get_uptime()
        bot.reply_to(message, "Выполняю команду uptime:\n" + uptime_output)

    if message.text.upper().startswith('БАРБАРИС СКАЖИ '):
        text_to_say = message.text[14:]
        user = message.from_user.first_name
        user_id = message.from_user.id
        user_link = (
            f"[{user}](https://t.me/{message.from_user.username})"
            if message.from_user.username
            else f"{user} ({user_id})"
        )
        bot.send_message(message.chat.id, f"{user_link} заставил меня сказать:{text_to_say}", parse_mode='Markdown')

    if message.text.upper().startswith('БАРБАРИС, СКАЖИ '):
        text_to_say = message.text[15:]
        user = message.from_user.first_name
        user_id = message.from_user.id
        user_link = (
            f"[{user}](https://t.me/{message.from_user.username})"
            if message.from_user.username
            else f"{user} ({user_id})"
        )
        bot.send_message(message.chat.id, f"{user_link} заставил меня сказать:{text_to_say}", parse_mode='Markdown')

    if message.text.upper() == 'ПИНГ':
        bot.reply_to(message, f'ПОНГ')

    if message.text.upper() == 'ПИУ':
        bot.reply_to(message, f'ПАУ')

    if message.text.upper() == 'КИНГ':
        bot.reply_to(message, f'КОНГ')

    if message.text.upper() == 'БОТ':
        bot.reply_to(message, f'✅ На месте')

    if message.text.upper().startswith("ЧТО С БОТОМ"):
        bot.reply_to(message, f'Да тут я.. отойти даже нельзя блин.. Я ТОЖЕ ИМЕЮ ПРАВО НА ОТДЫХ!')

    if message.text.upper() == 'КТО Я':
        db = read_db()
        owner_id = db['owner_id']
        beta_testers = db.get('beta_testers', [])
        user_id = message.from_user.id
        chat_id = str(message.chat.id)
        member = retry_bot_call(message, bot.get_chat_member, message.chat.id, user_id)
        if member is None:
            return
        display_name = get_nickname(user_id) or member.user.first_name
        username = format_user_link(display_name, member.user.username, user_id)
        daily_count = get_user_daily_stats(chat_id, user_id)
        weekly_count = get_user_weekly_stats(chat_id, user_id)
        monthly_count = get_user_monthly_stats(chat_id, user_id)
        all_time_count = get_user_all_time_stats(chat_id, user_id)
        with db_connection() as cursor:
            cursor.execute('SELECT last_activity FROM user_data WHERE chat_id = ? AND user_id = ? LIMIT 1',
                        (chat_id, user_id))
            result = cursor.fetchone()
            last_active_time = format_time_ago(result[0]) if result and result[0] else "Нет данных"
        owner_text = "\n🌟 Владелец бота" if int(user_id) == owner_id else ""
        beta_text = "\n💠 Бета-тестер бота" if int(user_id) in beta_testers else ""
        # Добавляем статус "Просто пользователь", если пользователь не владелец и не бета-тестер
        status_text = "\n👤 Просто пользователь" if not owner_text and not beta_text else ""
        description_text = f"\n📝 {get_description(user_id)}" if get_description(user_id) else ""
        marriage_text = get_profile_addition(int(chat_id), user_id)
        reply_text = (
            f"Ты <b>{username}</b>{owner_text}{beta_text}{status_text}{description_text}{marriage_text}\n\n"
            f"Последний твой актив:\n{last_active_time}\n"
            f"Краткая стата (д|н|м|вся):\n{daily_count}|{weekly_count}|{monthly_count}|{all_time_count}"
        )
        bot.reply_to(
            message,
            reply_text,
            parse_mode='HTML',
            disable_web_page_preview=not bool(member.user.username)
        )

    if message.text.upper().startswith('КТО ТЫ'):
        try:
            db = read_db()
            owner_id = db['owner_id']
            beta_testers = db.get('beta_testers', [])
            target_user_id = None
            target_user_name = None
            if message.reply_to_message:
                target_user_id = message.reply_to_message.from_user.id
                member = retry_bot_call(message, bot.get_chat_member, message.chat.id, target_user_id)
                if member is None:
                    return
                display_name = get_nickname(target_user_id) or member.user.first_name
                target_user_name = format_user_link(display_name, member.user.username, target_user_id)
            else:
                spl = message.text.split()
                if len(spl) > 2 and spl[2][0] == '@':
                    username_from_command = spl[2][1:]
                    hashed_username = sha(username_from_command.lower())
                    users = read_users()
                    if hashed_username in users:
                        target_user_id = users[hashed_username]
                        member = retry_bot_call(message, bot.get_chat_member, message.chat.id, target_user_id)
                        if member is None:
                            return
                        display_name = get_nickname(target_user_id) or member.user.first_name
                        target_user_name = format_user_link(display_name, member.user.username, target_user_id)
                    else:
                        bot.reply_to(message, "Пользователь с таким юзернеймом не найден в моей базе.")
                        return
                elif len(spl) > 1 and spl[1][0] == '@':
                    username_from_command = spl[1][1:]
                    hashed_username = sha(username_from_command.lower())
                    users = read_users()
                    if hashed_username in users:
                        target_user_id = users[hashed_username]
                        member = retry_bot_call(message, bot.get_chat_member, message.chat.id, target_user_id)
                        if member is None:
                            return
                        display_name = get_nickname(target_user_id) or member.user.first_name
                        target_user_name = format_user_link(display_name, member.user.username, target_user_id)
                    else:
                        bot.reply_to(message, "Пользователь с таким юзернеймом не найден в моей базе.")
                        return
                else:
                    bot.reply_to(message, "Для команды 'кто ты' необходимо ответить на сообщение пользователя или указать его юзернейм (например, 'кто ты @username').")
                    return
            if target_user_id and target_user_name:
                chat_id = str(message.chat.id)
                daily_count = get_user_daily_stats(chat_id, target_user_id)
                weekly_count = get_user_weekly_stats(chat_id, target_user_id)
                monthly_count = get_user_monthly_stats(chat_id, target_user_id)
                all_time_count = get_user_all_time_stats(chat_id, target_user_id)
                with db_connection() as cursor:
                    cursor.execute('SELECT last_activity FROM user_data WHERE chat_id = ? AND user_id = ? LIMIT 1',
                                (chat_id, target_user_id))
                    result = cursor.fetchone()
                    last_active_time = format_time_ago(result[0]) if result and result[0] else "Нет данных"
                owner_text = "\n🌟 Владелец бота" if int(target_user_id) == owner_id else ""
                beta_text = "\n💠 Бета-тестер бота" if int(target_user_id) in beta_testers else ""
                # Добавляем статус "Просто пользователь", если пользователь не владелец и не бета-тестер
                status_text = "\n👤 Просто пользователь" if not owner_text and not beta_text else ""
                description_text = f"\n📝 {get_description(target_user_id)}" if get_description(target_user_id) else ""
                marriage_text = get_profile_addition(int(chat_id), target_user_id)
                reply_text = (
                    f"Это <b>{target_user_name}</b>{owner_text}{beta_text}{status_text}{description_text}{marriage_text}\n\n"
                    f"Последний актив:\n{last_active_time}\n"
                    f"Краткая стата (д|н|м|вся):\n{daily_count}|{weekly_count}|{monthly_count}|{all_time_count}"
                )
                bot.reply_to(
                    message,
                    reply_text,
                    parse_mode='HTML',
                    disable_web_page_preview=not bool(member.user.username)
                )
            else:
                bot.reply_to(message, "Не удалось определить целевого пользователя.")
        except Exception as e:
            catch_error(message, e)

    if message.text.upper().startswith("РАНДОМ "):
        try:
            msg = message.text.upper()
            msg = msg.replace("РАНДОМ ", "")
            min_val = ""
            max_val = ""
            for item in msg:
                if item != " ":
                    min_val += item
                else:
                    break
            max_val = msg.replace(f"{min_val} ", "")
            max_val, min_val = int(max_val), int(min_val)
            try:
                if max_val < min_val:
                    bot.reply_to(message, f"Цифарки местами поменяй, олух")
                elif max_val == min_val:
                    bot.reply_to(message, f"Да ты гений я смотрю, умом берёшь.")
                else:
                    result = random.randint(min_val, max_val)
                    bot.reply_to(message, f"Случайное число из диапазона [{min_val}..{max_val}] выпало на {result}")
            except:
                return 0
        except:
            return 0

    if message.text:
        upper_text = message.text.strip().upper()

        if upper_text.startswith(('ЛИМИТ ВАРНОВ', 'ВАРН ЛИМИТ', 'ЛИМИТ ПРЕДОВ', '+ВАРНЛИМИТ')):
            try:
                parts = message.text.strip().split()
                int_val = None
                for p in parts[1:]:
                    if p.isdigit():
                        int_val = int(p)
                        break

                if int_val is not None:
                    if not can_manage_warn_settings(message):
                        bot.reply_to(message, "Эту настройку могут менять только администраторы группы и владелец бота.")
                    elif int_val < 1 or int_val > 100:
                        bot.reply_to(message, "Количество варнов должно быть числом от 1 до 100 (например: <code>лимит варнов 3</code>).", parse_mode='HTML')
                    else:
                        with db_connection() as cursor:
                            set_chat_max_warns(cursor, message.chat.id, int_val)
                        bot.reply_to(message, f"✅ Лимит предупреждений до бана для этого чата установлен на <b>{int_val}</b>.", parse_mode='HTML')
                else:
                    with db_connection() as cursor:
                        settings = get_chat_warn_settings(cursor, message.chat.id)
                    dur_str = format_duration(settings['warn_duration'])
                    text = (
                        f"⚙️ <b>Настройки варнов в этом чате:</b>\n"
                        f"• Лимит варнов до бана: <b>{settings['max_warns']}</b>\n"
                        f"• Срок действия варна: <b>{dur_str}</b>\n\n"
                        f"<i>Изменить лимит:</i> <code>лимит варнов [число]</code>\n"
                        f"<i>Изменить время:</i> <code>время варна [время]</code> (например: <code>время варна 24h</code>, <code>время варна навсегда</code>)"
                    )
                    bot.reply_to(message, text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

        if upper_text.startswith(('ВРЕМЯ ВАРНА', 'ВРЕМЯ ВАРНОВ', 'СРОК ВАРНА', 'ВАРН ВРЕМЯ')):
            try:
                for prefix in ['ВРЕМЯ ВАРНОВ', 'ВРЕМЯ ВАРНА', 'СРОК ВАРНА', 'ВАРН ВРЕМЯ']:
                    if upper_text.startswith(prefix):
                        arg = message.text.strip()[len(prefix):].strip()
                        break
                else:
                    arg = ""

                if arg:
                    if not can_manage_warn_settings(message):
                        bot.reply_to(message, "Эту настройку могут менять только администраторы группы и владелец бота.")
                    else:
                        dur = parse_duration_string(arg)
                        if dur is None:
                            bot.reply_to(message, "Неверный формат времени. Примеры: <code>время варна 24h</code>, <code>время варна 7d</code>, <code>время варна 30m</code>, <code>время варна навсегда</code>.", parse_mode='HTML')
                        else:
                            with db_connection() as cursor:
                                set_chat_warn_duration(cursor, message.chat.id, dur)
                            dur_str = format_duration(dur)
                            bot.reply_to(message, f"✅ Время действия варна в этом чате установлено: <b>{dur_str}</b>.", parse_mode='HTML')
                else:
                    with db_connection() as cursor:
                        settings = get_chat_warn_settings(cursor, message.chat.id)
                    dur_str = format_duration(settings['warn_duration'])
                    bot.reply_to(message, f"⏳ Время действия предупреждения в этом чате: <b>{dur_str}</b>.", parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

        if upper_text in ['ВАРНЫ', 'СПИСОК ВАРНОВ', 'МОИ ВАРНЫ'] or upper_text.startswith('ВАРНЫ '):
            try:
                if message.reply_to_message:
                    target_user_id = message.reply_to_message.from_user.id
                else:
                    target_from_cmd = get_target(message)
                    target_user_id = target_from_cmd if target_from_cmd else message.from_user.id

                user_link = get_user_link_sync(target_user_id, message.chat.id)
                with db_connection() as cursor:
                    warns = get_user_warns(cursor, message.chat.id, target_user_id)
                    settings = get_chat_warn_settings(cursor, message.chat.id)

                if not warns:
                    bot.reply_to(
                        message,
                        f"У {user_link} нет активных предупреждений в этом чате 😇",
                        parse_mode='HTML',
                        disable_web_page_preview=True
                    )
                else:
                    text = f"⚠️ <b>Предупреждения пользователя {user_link}:</b>\n"
                    text += f"Активно: <b>[{len(warns)}/{settings['max_warns']}]</b>\n\n"
                    for idx, w in enumerate(warns, 1):
                        created = w['created_at']
                        expires = w['expires_at'] or "бессрочно"
                        text += f"{idx}. Выдан: {created} (истекает: {expires})\n"
                    bot.reply_to(message, text, parse_mode='HTML', disable_web_page_preview=True)
            except Exception as e:
                catch_error(message, e)

    if message.text.upper() == 'ВАРН' or (message.text.upper().startswith('ВАРН ') and not message.text.upper().startswith(('ВАРН ЛИМИТ', 'ВАРН ВРЕМЯ'))):
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                if message.reply_to_message:
                    target_id = message.reply_to_message.from_user.id
                else:
                    target_id = get_target(message)

                if not target_id:
                    bot.reply_to(message, "Команда должна быть ответом на сообщение нарушителя или содержать @username.")
                else:
                    admins = get_admins(message)
                    if target_id == owner_id or (admins and target_id in admins):
                        bot.reply_to(message, "Нельзя выдать предупреждение администратору.")
                    else:
                        custom_dur = None
                        time_info = get_time(message)
                        if time_info:
                            custom_dur = time_info[1]
                        else:
                            parts = message.text.strip().split()
                            for p in parts[1:]:
                                if not p.startswith('@'):
                                    parsed = parse_duration_string(p)
                                    if parsed is not None:
                                        custom_dur = parsed
                                        break
                        warn_user(message, target_id, duration_seconds=custom_dur)
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == 'СНЯТЬ ВАРН' or message.text.upper().startswith('СНЯТЬ ВАРН '):
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                if message.reply_to_message:
                    target_id = message.reply_to_message.from_user.id
                else:
                    target_id = get_target(message)

                if not target_id:
                    bot.reply_to(message, "Команда должна быть ответом на сообщение пользователя или содержать @username.")
                else:
                    success, remaining, max_w = remove_warn_for_user(message, target_id)
                    target_name = get_name(message)
                    if success:
                        bot.reply_to(message, f"Ладно, {target_name}, последний косяк снят. Активных варнов: <b>[{remaining}/{max_w}]</b>.", parse_mode='HTML')
                    else:
                        bot.reply_to(message, f"У {target_name} нет активных предупреждений в этом чате.", parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper().startswith('МУТ'):
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                target = get_target(message)
                time = get_time(message)
                if target is None:
                    # Проверяем, если это реплай на владельца
                    if message.reply_to_message:
                        potential_target = message.reply_to_message.from_user.id
                        if potential_target == owner_id:
                            # Притворяемся, что мутим
                            if time:
                                answer = f'Я заклеил ему рот на {time[0]} {time[2]}. Маловато как по мне, ну ладно.'
                            else:
                                answer = f'Я заклеил ему рот.'
                            bot.reply_to(message, answer, parse_mode='HTML')
                            return
                    catch_error(message, 'None', 'no_user')
                else:
                    if target == owner_id:
                        # Притворяемся, что мутим
                        if time:
                            answer = f'Я заклеил ему рот на {time[0]} {time[2]}. Маловато как по мне, ну ладно.'
                        else:
                            answer = f'Я заклеил ему рот.'
                        bot.reply_to(message, answer, parse_mode='HTML')
                    else:
                        if time:
                            retry_bot_call(message, bot.restrict_chat_member, message.chat.id, target, until_date=message.date + time[1])
                            answer = f'Я заклеил ему рот на {time[0]} {time[2]}. Маловато как по мне, ну ладно.'
                        else:
                            retry_bot_call(message, bot.restrict_chat_member, message.chat.id, target, until_date=message.date)
                            answer = f'Я заклеил ему рот.'
                        try:
                            bot.reply_to(message, answer, parse_mode='HTML')
                        except:
                            bot.reply_to(message, answer)
        except Exception as e:
            catch_error(message, e)

    if message.text.upper().startswith('РАЗМУТ'):
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                target = get_target(message)
                if target:
                    retry_bot_call(message, bot.restrict_chat_member, message.chat.id, target, can_send_messages=True,
                                             can_send_other_messages=True, can_send_polls=True,
                                             can_add_web_page_previews=True, until_date=message.date)
                    bot.reply_to(message, f'''Ладно, так и быть, пусть он говорит.
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "КИК":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                target = get_target(message)
                if target:
                    retry_bot_call(message, bot.ban_chat_member, message.chat.id, target)
                    retry_bot_call(message, bot.unban_chat_member, message.chat.id, target)
                    bot.reply_to(message, f'''Этот плохиш был изгнан с сие великой группы.
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "БАН":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                target = get_target(message)
                if target is None:
                    # Проверяем, если это реплай на владельца
                    if message.reply_to_message:
                        potential_target = message.reply_to_message.from_user.id
                        if potential_target == owner_id:
                            # Притворяемся, что баним, но на самом деле кикаем
                            retry_bot_call(message, bot.ban_chat_member, message.chat.id, potential_target)
                            retry_bot_call(message, bot.unban_chat_member, message.chat.id, potential_target)
                            bot.reply_to(message, f'''Этот плохиш был изгнан с сие великой группы и не имеет права прощения!
    ''', parse_mode='HTML')
                            return
                    catch_error(message, 'None', 'no_user')
                else:
                    if target == owner_id:
                        # Притворяемся, что баним, но на самом деле кикаем
                        retry_bot_call(message, bot.ban_chat_member, message.chat.id, target)
                        retry_bot_call(message, bot.unban_chat_member, message.chat.id, target)
                        bot.reply_to(message, f'''Этот плохиш был изгнан с сие великой группы и не имеет права прощения!
    ''', parse_mode='HTML')
                    else:
                        retry_bot_call(message, bot.ban_chat_member, message.chat.id, target)
                        bot.reply_to(message, f'''Этот плохиш был изгнан с сие великой группы и не имеет права прощения!
    ''', parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "РАЗБАН":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                target = get_target(message)
                if target:
                    retry_bot_call(message, bot.unban_chat_member, message.chat.id, target)
                    bot.reply_to(message, f'''Ладно, может право на прощение он и имеет.. Но только единожды! Наверное..
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '-ЧАТ':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                retry_bot_call(message, bot.set_chat_permissions, message.chat.id, telebot.types.ChatPermissions(
                    can_send_messages=False,
                    can_send_audios=False,
                    can_send_documents=False,
                    can_send_photos=False,
                    can_send_videos=False,
                    can_send_video_notes=False,
                    can_send_voice_notes=False,
                    can_send_polls=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False
                ))
                # Ensure owner is not muted
                try:
                    member = retry_bot_call(message, bot.get_chat_member, message.chat.id, owner_id)
                    if member:
                        try:
                            retry_bot_call(message, bot.restrict_chat_member, message.chat.id, owner_id,
                                can_send_messages=True,
                                can_send_audios=True,
                                can_send_documents=True,
                                can_send_photos=True,
                                can_send_videos=True,
                                can_send_video_notes=True,
                                can_send_voice_notes=True,
                                can_send_polls=True,
                                can_send_other_messages=True,
                                can_add_web_page_previews=True)
                        except:
                            pass
                except:
                    pass
                bot.reply_to(message, 'Крч вы достали админов господа.. и меня тоже. Закрываем чат..)')
            else:
                bot.reply_to(message, f'А, ещё.. <tg-spoiler>ПОПЛАЧ)))))</tg-spoiler>', parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '+ЧАТ':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                retry_bot_call(message, bot.set_chat_permissions, message.chat.id, telebot.types.ChatPermissions(
                    can_send_messages=True,
                    can_send_audios=True,
                    can_send_documents=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_video_notes=True,
                    can_send_voice_notes=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                ))
                bot.reply_to(message, 'Ладно, мне надоела тишина. Открываю чат..')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() in ["ПИН", "ЗАКРЕП"]:
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                retry_bot_call(message, bot.pin_chat_message, message.chat.id, message.reply_to_message.id)
                bot.reply_to(message, "Видимо это что то важное.. кхм... Закрепил!")
        except:
            return 0

    if message.text.upper() == "АНПИН":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                retry_bot_call(message, bot.unpin_chat_message, message.chat.id, message.reply_to_message.id)
                bot.reply_to(message, "Больше не важное, лол.. кхм... Открепил!")
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '+АДМИН':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                user_id = message.reply_to_message.from_user.id
                chat_id = message.chat.id
                retry_bot_call(message, bot.promote_chat_member, chat_id, user_id, can_manage_chat=True, can_change_info=True, can_delete_messages=True, can_restrict_members=True, can_invite_users=True, can_pin_messages=True, can_manage_video_chats=True, can_manage_voice_chats=True, can_post_stories=True, can_edit_stories=True, can_delete_stories=True)
                bot.reply_to(message, "Теперь у этого человечка есть власть над чатом!! Бойтесь.")
        except:
            return 0

    if message.text.upper() == '-АДМИН':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                user_id = message.reply_to_message.from_user.id
                chat_id = message.chat.id
                retry_bot_call(message, bot.promote_chat_member, chat_id, user_id, can_manage_chat=False, can_change_info=False, can_delete_messages=False, can_restrict_members=False, can_invite_users=False, can_pin_messages=False, can_manage_video_chats=False, can_manage_voice_chats=False, can_post_stories=False, can_edit_stories=False, can_delete_stories=False)
                bot.reply_to(message, "Лох, понижен в должности. Теперь его можно не бояться")
        except:
            return 0

    if message.text.upper() == "-СМС":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                greet_owner_if_self(message, owner_id)
                retry_bot_call(message, bot.delete_message, message.chat.id, message.reply_to_message.id)
                retry_bot_call(message, bot.delete_message, message.chat.id, message.id)
        except Exception as e:
            catch_error(message, e)

    if message.text.upper().startswith('+НИК '):
        nick = message.text[5:].strip()
        if nick:
            set_nickname(message.from_user.id, nick)
            bot.reply_to(message, f"Ник установлен: {nick}")
        else:
            bot.reply_to(message, "Укажите ник после +ник")

    if message.text.upper() == '-НИК':
        remove_nickname(message.from_user.id)
        bot.reply_to(message, "Ник сброшен")

    if message.text.upper().startswith('+ОПИСАНИЕ '):
        desc = message.text[10:].strip()
        if desc:
            set_description(message.from_user.id, desc)
            bot.reply_to(message, f"Описание установлено: {desc}")
        else:
            bot.reply_to(message, "Укажите описание после +описание")

    if message.text.upper() == '-ОПИСАНИЕ':
        remove_description(message.from_user.id)
        bot.reply_to(message, "Описание сброшено")

    if message.text and message.text.upper() == ".ХЕЛП":
        try:
            effective_commands = get_effective_rp_commands(message.chat.id)
            commands_list = sorted(effective_commands.keys())

            help_text = "<b>Помощь по командам:</b>\n\n"
            help_text += """<blockquote expandable><b>Основные команды бота</b>
+ник {ник} / -ник - Установить/сбросить кастомный ник (отображается в топе и РП)
+описание {описание} / -описание - Установить/сбросить описание (отображается в кто я/кто ты)
Какая нагрузка - выполняет команду uptime и отправляет её вывод
Топ день / Топ дня - Топ крутышек за день в этом чате.
Топ неделя / Топ недели - Топ крутышек за неделю в этом чате.
Топ месяц / Топ месяца - Топ крутышек за месяц в этом чате.
Топ все / Топ вся - Топ крутышек за все время в этом чате.
Кто ты @username / reply - Показывает инфу о пользователе.
Бан/Разбан - Блокировка/разблокировка пользователя
Кик - Изгнание пользователя
Мут/Размут [2m/2h] - Лишение/выдача права слова пользователю (m - минуты, h - часы)
Варн [время] / Снять варн - Выдача/Снятие предупреждения пользователю (напр. варн 2h)
Варны - Просмотр активных предупреждений пользователя
Лимит варнов [число] - Настройка лимита варнов до бана для этой группы (только админы)
Время варна [время] - Настройка времени действия варна для этой группы (только админы)
Закреп||Пин - Прикрепить сообщение
Анпин - открепить сообщение
Рандом a b - Случайный выбор числа в диапазоне a..b
Моя статья - Случайная статья УК РФ для автора команды (шутка)
.Хелп - Этот список
.Rphelp - Справка по созданию своих RP-команд
.Rpcreate - Создать свою RP-команду
.Rpdelete - Удалить свою RP-команду
Пинг/Кинг/Бот - Для проверки бота
Что с ботом? - ..)
+чат/-чат - Открытие/закрытие чата
+админ/-админ - Выдача/снятие прав администратора пользователя
Барбарис, скажи - Повторяет за вами (запятая кст не обязательна, но и с ней оно работает)
Брак (reply) - Предложить брак пользователю.
Развод - Развестись с пользователем.
Браки / Список браков - Список всех браков в чате.
Шипперим - Случайный шипперинг двух участников чата.
</blockquote>\n"""

            help_text_rp = "<blockquote expandable><b>РП-Команды</b>\n"
            for cmd in commands_list:
                command_data = effective_commands[cmd]
                desc = command_data.get('description', command_data['request'].format(sender="Кто-то", target="Кого-то"))
                help_text_rp += f"• <code>{cmd}</code>: {desc}\n"

            help_text_rp += "\n<i>Использование:</i> Напишите команду с реплаем или @имя, например, <code>обнять @User</code>."
            help_text_rp += "\n<i>Создание своей команды:</i> <code>+рпк имя | request | accept | reject | [описание] | [вариант1, вариант2, вариант3]</code>"
            help_text_rp += "\n<i>Удаление команды:</i> <code>-рпк имя</code>"
            help_text_rp += "\n<i>Шаблоны:</i> <code>{sender}</code> — инициатор, <code>{target}</code> — цель, <code>{random_part}</code> — случайный вариант."
            help_text_rp += "\n<i>Пример:</i> <code>+рпк ударить | {sender} хочет ударить | {sender} ударил {target} {random_part} | {target} увернулся | Ударить с размахом | в глаз, в челюсть, в живот</code>"
            help_text_rp += "</blockquote>"

            bot.reply_to(message, help_text, parse_mode='HTML')
            bot.send_message(message.chat.id, help_text_rp, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text and message.text.upper().startswith('?РПК'):
        help_text = """<b>Как создавать свои RP-команды</b>\n\n"""
        help_text += """Формат команды:\n<code>+рпк имя | request | accept | reject | [описание] | [вариант1, вариант2, вариант3]</code>\n\n"""
        help_text += """Пример:\n<code>+рпк ударить | {sender} хочет ударить | {sender} ударил {target} {random_part} | {target} увернулся | Ударить с размахом | в глаз, в челюсть, в живот</code>\n\n"""
        help_text += """Поддерживаемые шаблоны:\n• <code>{sender}</code> — кто инициирует команду\n• <code>{target}</code> — цель команды\n• <code>{random_part}</code> — случайный вариант, если нужен\n\n"""
        help_text += """Удалить команду можно так:\n<code>-рпк имя</code>"""
        bot.reply_to(message, help_text, parse_mode='HTML')

    if message.text and message.text.upper().startswith('+РПК'):
        try:
            if not can_manage_rp_commands(message):
                bot.reply_to(message, "Эту команду могут использовать только владелец бота или администраторы чата.")
                return
            parsed = parse_rp_command_creation(message.text)
            if not parsed:
                bot.reply_to(message, "Формат: <code>+рпк имя | request | accept | reject | [описание] | [вариант1, вариант2, вариант3]</code>", parse_mode='HTML')
                return
            command_name, request, accept, reject, description, random_parts = parsed
            chat_id = str(message.chat.id)
            chat_commands = chat_rp_data.setdefault(chat_id, {})
            existed = command_name in chat_commands
            chat_commands[command_name] = {
                'request': request,
                'accept': accept,
                'reject': reject,
            }
            if description:
                chat_commands[command_name]['description'] = description
            if random_parts:
                chat_commands[command_name]['random_parts'] = random_parts
            elif 'random_parts' in chat_commands[command_name]:
                del chat_commands[command_name]['random_parts']
            persist_rp_commands()
            action = 'обновлена' if existed else 'создана'
            bot.reply_to(message, f"РП-команда <code>{command_name}</code> {action}.", parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text and message.text.upper().startswith('-РПК'):
        try:
            if not can_manage_rp_commands(message):
                bot.reply_to(message, "Эту команду могут использовать только владелец бота или администраторы чата.")
                return
            command_name = parse_rp_command_delete(message.text)
            if not command_name:
                bot.reply_to(message, "Формат: <code>-рпк имя</code>", parse_mode='HTML')
                return
            chat_id = str(message.chat.id)
            chat_commands = chat_rp_data.get(chat_id, {})
            if command_name in chat_commands:
                del chat_commands[command_name]
                if not chat_commands:
                    chat_rp_data.pop(chat_id, None)
                persist_rp_commands()
                bot.reply_to(message, f"РП-команда <code>{command_name}</code> удалена.", parse_mode='HTML')
            else:
                bot.reply_to(message, f"РП-команда <code>{command_name}</code> не найдена.", parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == 'БРАК':
        try:
            if not message.reply_to_message:
                bot.reply_to(message, "Команда 'Брак' должна быть в ответ на сообщение пользователя.")
                return
            target_id = message.reply_to_message.from_user.id
            proposer_id = message.from_user.id
            chat_id = message.chat.id
            if proposer_id == target_id:
                bot.reply_to(message, "Чел буквально поженил себя и свою руку. Ну ладно, я не осуждаю, но это странно. Брака не будет.")
                return
            if is_married(chat_id, proposer_id):
                bot.reply_to(message, "Услышал тебя родной. Изменяем значит. Не не не бро. Сначала разведись.")
                return
            if is_married(chat_id, target_id):
                bot.reply_to(message, "Не успел. Этот человек уже в браке. Не пытайся быть третьим лишним.")
                return
            request_id = str(uuid.uuid4())
            save_marriage_request(request_id, chat_id, proposer_id, target_id, message.from_user.first_name)
            proposer_link = get_user_link_sync(proposer_id, chat_id)
            target_link = get_user_link_sync(target_id, chat_id)
            text = f"{proposer_link} хочет вступить в брак с {target_link}!"
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("Согласиться", callback_data=f"marriage_agree_{request_id}"),
                InlineKeyboardButton("Отказаться", callback_data=f"marriage_reject_{request_id}")
            )
            bot.send_message(
                chat_id,
                text,
                parse_mode='HTML',
                reply_markup=markup,
                disable_web_page_preview=True
            )
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == 'РАЗВОД':
        try:
            user_id = message.from_user.id
            chat_id = message.chat.id
            spouse_id = dissolve_marriage(chat_id, user_id)
            if spouse_id:
                spouse_link = get_user_link_sync(spouse_id, chat_id)
                bot.reply_to(
                    message,
                    f"Развод оформлен. Сожалеем для {spouse_link}.",
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
            else:
                bot.reply_to(message, "Так ты не в браке даже...")
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() in ['БРАКИ', 'СПИСОК БРАКОВ']:
        try:
            marriages = get_all_marriages(message.chat.id)
            if not marriages:
                bot.reply_to(message, "В этом чате нет зарегистрированных браков.")
            else:
                text = "Список браков в чате:\n"
                for i, (sp1, sp2, created_str) in enumerate(marriages, 1):
                    link1 = get_user_link_sync(sp1, message.chat.id)
                    link2 = get_user_link_sync(sp2, message.chat.id)
                    created_dt = datetime.strptime(created_str, '%Y-%m-%d %H:%M:%S')
                    date_str = created_dt.strftime('%Y-%m-%d')
                    now = datetime.now()
                    delta = now - created_dt
                    days = delta.days
                    if days == 0:
                        duration = "менее дня"
                    elif days == 1:
                        duration = "1 день"
                    else:
                        duration = f"{days} дней"
                    text += f"{i}. {link1} 💍 {link2} (Заключен: {date_str}, Длительность: {duration})\n"
                bot.send_message(
                    message.chat.id,
                    text,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
        except Exception as e:
            catch_error(message, e)

    if message.text and is_shipping_command(message.text):
        try:
            chat_id = message.chat.id
            current_uid = message.from_user.id if message.from_user and not message.from_user.is_bot else None
            reply_uid = (
                message.reply_to_message.from_user.id
                if message.reply_to_message and message.reply_to_message.from_user and not message.reply_to_message.from_user.is_bot
                else None
            )

            with db_connection() as cursor:
                candidates = get_chat_shipping_candidates(cursor, chat_id, current_uid, reply_uid)

            # Добавляем администраторов чата
            try:
                admins = bot.get_chat_administrators(chat_id)
                for admin in admins:
                    if admin.user and not admin.user.is_bot:
                        candidates.add(admin.user.id)
            except Exception:
                pass

            # Исключаем бота и служебные аккаунты
            try:
                bot_id = bot.get_me().id
                candidates.discard(bot_id)
            except Exception:
                pass
            candidates.discard(777000)
            candidates.discard(1087968824)

            if len(candidates) < 2:
                bot.reply_to(message, "Недостаточно участников для шипперинга! Мне нужно хотя бы два человечка в этом чате 💔")
                return

            def check_member(uid):
                try:
                    member = bot.get_chat_member(chat_id, uid)
                    if member.status not in ['left', 'kicked'] and not member.user.is_bot:
                        return member
                except Exception:
                    return None
                return None

            valid_members = pick_random_pair(candidates, check_member)

            if len(valid_members) < 2:
                bot.reply_to(message, "Не удалось найти двух активных участников для шипперинга 💔")
                return

            (uid1, member1), (uid2, member2) = valid_members[0], valid_members[1]
            link1 = get_user_link_sync(uid1, chat_id)
            link2 = get_user_link_sync(uid2, chat_id)
            name1 = get_nickname(uid1) or member1.user.first_name or f"Участник {uid1}"
            name2 = get_nickname(uid2) or member2.user.first_name or f"Участник {uid2}"
            ship_name = generate_ship_name(name1, name2)

            is_already_married = (get_spouse(chat_id, uid1) == uid2)
            if is_already_married:
                percent = 100
            else:
                percent = random.randint(0, 100)

            extra_notes = []
            if is_already_married:
                extra_notes.append("💍 <i>Кстати, эти двое уже состоят в браке! Совет да любовь!</i>")
            else:
                spouse1 = get_spouse(chat_id, uid1)
                spouse2 = get_spouse(chat_id, uid2)
                if spouse1:
                    s1_link = get_user_link_sync(spouse1, chat_id)
                    extra_notes.append(f"👀 <i>Опаньки... А {link1} вообще-то уже в браке с {s1_link}!</i>")
                if spouse2:
                    s2_link = get_user_link_sync(spouse2, chat_id)
                    extra_notes.append(f"👀 <i>Опаньки... А {link2} вообще-то уже в браке с {s2_link}!</i>")

            text = format_shipping_message(link1, link2, ship_name, percent, extra_notes=extra_notes)
            bot.send_message(chat_id, text, parse_mode='HTML', disable_web_page_preview=True)
            return
        except Exception as e:
            catch_error(message, e)

##############       RP COMMANDS        #################

    if message.text:
        normalized_text = message.text.lower().strip()
        command = None
        user_phrase = ''
        effective_commands = get_effective_rp_commands(message.chat.id)
        # Сортируем команды по длине descending (чтобы "цыц!" матчился раньше "цыц")
        for cmd in sorted(effective_commands.keys(), key=len, reverse=True):
            if normalized_text.startswith(cmd):
                command = cmd
                user_phrase = normalized_text[len(cmd):].strip()
                break

        if command:
            sender_id = message.from_user.id
            sender_display = get_nickname(sender_id) or message.from_user.first_name
            sender_display = escape_html(sender_display)

            # Определяем цель
            if message.reply_to_message:
                # Цель - реплай
                target_name = get_name(message)
            elif any(part.startswith('@') for part in message.text.split()):  # Если есть @ в тексте
                target_name = get_name(message)  # get_name обработает @
            else:
                # Self-команда: цель = sender
                target_name = format_user_link(sender_display, message.from_user.username, sender_id)

            command_data = effective_commands[command]
            template = command_data['accept']
            random_parts = command_data.get('random_parts', [])
            if '{random_part}' in template and random_parts:
                template = template.replace('{random_part}', random.choice(random_parts))
            template = template.replace('{random_part}', '')
            response_text = template.replace('{sender}', sender_display).replace('{target}', target_name)
            if user_phrase:
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)


##############       RP INLINE COMMANDS        #################

@bot.inline_handler(lambda query: True)
def handle_inline_query(query):
    try:
        text = query.query.strip().lower()
        if not text:
            return

        command = None
        user_phrase = ''
        # Аналогично: сортировка по длине для "цыц!"
        for cmd in sorted(rp_data.keys(), key=len, reverse=True):
            if text.startswith(cmd):
                command = cmd
                user_phrase = text[len(cmd):].strip()
                break

        if not command:
            return

        sender_id = query.from_user.id
        sender_nickname = get_nickname(sender_id) or query.from_user.first_name
        sender_display = escape_html(sender_nickname)
        sender_first_name = query.from_user.first_name

        request_text = rp_data[command]['request'].format(sender=sender_display)

        request_id = str(uuid.uuid4())
        save_rp_request(request_id, 0, sender_id, 0, command, user_phrase, sender_first_name)

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Принять", callback_data=f"rp_accept_{request_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"rp_reject_{request_id}")
        )

        results = [
            InlineQueryResultArticle(
                id=request_id,
                title=command.capitalize(),
                input_message_content=InputTextMessageContent(
                    request_text,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                ),
                description=f"RP: {command}",
                reply_markup=markup
            )
        ]
        bot.answer_inline_query(query.id, results, cache_time=1)
    except Exception as e:
        print(f"Inline error: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('rp_'))
def handle_callback_query(call):
    try:
        action, request_id = call.data.split('_', 2)[1:]
        logging.debug(f'Callback received: action={action}, request_id={request_id}, has_message={call.message is not None}, inline_message_id={call.inline_message_id}')
        
        request_data = get_rp_request(request_id)
        if not request_data:
            logging.warning(f'Request not found: request_id={request_id}')
            bot.answer_callback_query(call.id, "Запрос устарел или не найден.")
            return

        chat_id, sender_id, sender_first_name, target_id, command, phrase = request_data
        clicker_id = call.from_user.id
        target_id = clicker_id

        # Получаем display names
        sender_display = escape_html(get_nickname(sender_id) or sender_first_name or "Пользователь")
        target_display = "Неизвестный"
        target_username = None
        target_link = target_display

        if call.message:
            chat_id = str(call.message.chat.id)
            try:
                target_member = bot.get_chat_member(int(chat_id), target_id)
                target_display = escape_html(get_nickname(target_id) or target_member.user.first_name)
                target_username = target_member.user.username.lstrip('@') if target_member.user.username else None
                target_link = f'<a href="https://t.me/{target_username}">{target_display}</a>' if target_username else target_display
            except Exception as e:
                logging.error(f'Error getting target member: {e}')
                target_display = escape_html(get_nickname(target_id) or call.from_user.first_name or "Пользователь")
                target_username = call.from_user.username.lstrip('@') if call.from_user.username else None
                target_link = f'<a href="https://t.me/{target_username}">{target_display}</a>' if target_username else target_display
        else:
            # Для inline в ЛС
            target_display = escape_html(get_nickname(target_id) or call.from_user.first_name or "Пользователь")
            target_username = call.from_user.username.lstrip('@') if call.from_user.username else None
            target_link = f'<a href="https://t.me/{target_username}">{target_display}</a>' if target_username else target_display

        logging.debug(f'Sender: {sender_display} ({sender_id}), Target: {target_display} ({target_id}), Command: {command}')

        # Формируем текст ответа
        effective_commands = get_effective_rp_commands(chat_id)
        if command in effective_commands:
            command_data = effective_commands[command]
            if action == 'accept':
                template = command_data['accept']
            elif action == 'reject':
                template = command_data['reject']
            else:
                return

            random_parts = command_data.get('random_parts', [])
            if '{random_part}' in template and random_parts:
                template = template.replace('{random_part}', random.choice(random_parts))
            template = template.replace('{random_part}', '')
            response_text = template.replace('{sender}', sender_display).replace('{target}', target_link)

            response_text = format_rp_response(
                response_text,
                escape_html(phrase),
                inline=str(chat_id) == "0",
            )

        # Редактирование сообщения
        if call.message:
            try:
                chat_id = str(call.message.chat.id)
                message_id = call.message.message_id
                logging.debug(f'Editing message in chat_id={chat_id}, message_id={message_id}')
                bot.edit_message_text(
                    text=response_text,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                # Обновляем chat_id и target_id в базе
                with db_connection() as cursor:
                    cursor.execute('UPDATE rp_requests SET chat_id = ?, target_id = ? WHERE request_id = ?',
                                  (chat_id, target_id, request_id))
                # Сохраняем цель для sender_id
                save_last_target(chat_id, sender_id, target_id)
                bot.answer_callback_query(call.id, "Действие обработано!")
                logging.debug(f'Message edited successfully in chat_id={chat_id}, message_id={message_id}')
            except Exception as e:
                logging.error(f'Edit message error: {e}')
                bot.answer_callback_query(call.id, f"Ошибка: не удалось изменить сообщение. {str(e)}")
        elif call.inline_message_id:
            try:
                logging.debug(f'Editing inline message with inline_message_id={call.inline_message_id}')
                bot.edit_message_text(
                    text=response_text,
                    inline_message_id=call.inline_message_id,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                # Обновляем target_id в базе, chat_id оставляем 0
                with db_connection() as cursor:
                    cursor.execute('UPDATE rp_requests SET target_id = ? WHERE request_id = ?',
                                  (target_id, request_id))
                # Сохраняем цель для sender_id (используем sender_id как chat_id в ЛС)
                save_last_target(str(sender_id), sender_id, target_id)
                bot.answer_callback_query(call.id, "Действие обработано!")
                logging.debug(f'Inline message edited successfully: inline_message_id={call.inline_message_id}')
            except Exception as e:
                logging.error(f'Edit inline message error: {e}')
                bot.answer_callback_query(call.id, f"Ошибка: не удалось изменить сообщение. {str(e)}")
        else:
            bot.answer_callback_query(call.id, "Команда не найдена.")
    except Exception as e:
        logging.error(f'Callback error: {e}')
        bot.answer_callback_query(call.id, f"Ошибка при обработке действия: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('marriage_'))
def handle_marriage_callback(call):
    try:
        parts = call.data.split('_')
        if len(parts) != 3:
            bot.answer_callback_query(call.id, "Неверный формат данных.")
            return
        _, action, request_id = parts
        request_data = get_marriage_request(request_id)
        if not request_data:
            bot.answer_callback_query(call.id, "Запрос устарел или не найден.")
            return
        chat_id, proposer_id, proposer_first_name, target_id = request_data
        clicker_id = call.from_user.id
        if clicker_id != target_id:
            bot.answer_callback_query(call.id, "Не лезь не в своё дело, это не твоё предложение.")
            return
        proposer_link = get_user_link_sync(proposer_id, int(chat_id))
        target_link = get_user_link_sync(target_id, int(chat_id))
        if action == 'agree':
            if is_married(int(chat_id), proposer_id) or is_married(int(chat_id), target_id):
                response_text = "Один из вас уже состоит в браке. Предложение аннулировано."
            else:
                register_marriage(int(chat_id), proposer_id, target_id)
                response_text = f"Брак заключен между {proposer_link} и {target_link}!"
        elif action == 'reject':
            response_text = f"{target_link} отказался от предложения {proposer_link}. Жаль..."
        else:
            bot.answer_callback_query(call.id, "Неизвестное действие.")
            return
        if call.message:
            bot.edit_message_text(
                text=response_text,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                parse_mode='HTML'
            )
        delete_marriage_request(request_id)
        bot.answer_callback_query(call.id, "Действие обработано!")
    except Exception as e:
        logging.error(f'Marriage callback error: {e}')
        bot.answer_callback_query(call.id, f"Ошибка: {str(e)}")

bot.polling(none_stop=True)
