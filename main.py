import re
import subprocess
import telebot
import os
import json
import random
import sqlite3
import uuid 

from datetime import datetime, timedelta
from telebot import types, util
import logging
import traceback
import asyncio
from telebot.types import InlineQueryResultArticle, InputTextMessageContent
from telebot.types import InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton

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

# Initialize SQLite database
def init_sqlite_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
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
        CREATE TABLE IF NOT EXISTS user_data (
            chat_id TEXT,
            user_id TEXT,
            date TEXT,
            message_count INTEGER,
            last_activity TEXT,
            PRIMARY KEY (chat_id, user_id, date)
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
        CREATE TABLE IF NOT EXISTS rp_requests (
            request_id TEXT PRIMARY KEY,
            chat_id TEXT,
            sender_id INTEGER,
            target_id INTEGER,
            command TEXT,
            phrase TEXT,
            created_at TEXT
        )
    ''')

    # Проверяем, существует ли столбец last_mentioned_target в user_data
    cursor.execute("PRAGMA table_info(user_data)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'last_mentioned_target' not in columns:
        cursor.execute('ALTER TABLE user_data ADD COLUMN last_mentioned_target TEXT')
        print('DEBUG: Added last_mentioned_target column to user_data table.')
    
    conn.commit()
    conn.close()
    print('DEBUG: SQLite database initialized.')

init_sqlite_db()

############ WORK WITH DBs ##########

def read_db():
    print('DEBUG: Чтение db.json...')
    with open('db.json', 'r') as openfile:
        db = json.load(openfile)
        print(f"DEBUG: Прочитанный токен: {db.get('token', 'Токен не найден')}")
        print(f"DEBUG: Прочитанный owner_id: {db.get('owner_id', 'owner_id не найден')}")
        print(f"DEBUG: Прочитанные beta_testers: {db.get('beta_testers', 'beta_testers не найдены')}")
        return db

def write_db(db):
    js = json.dumps(db, indent=2)
    with open('db.json', 'w') as outfile:
        outfile.write(js)

known_errs = {
    'A request to the Telegram API was unsuccessful. Error code: 400. Description: Bad Request: not enough rights to restrict/unrestrict chat member': 'Увы, но у бота не хватает прав для этого.'
}

import io
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
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

def get_last_target(chat_id, user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT last_mentioned_target FROM user_data 
        WHERE chat_id = ? AND user_id = ? AND date = ? LIMIT 1
    ''', (str(chat_id), str(user_id), datetime.now().strftime('%Y-%m-%d')))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result and result[0] else None

def save_rp_request(request_id, chat_id, sender_id, target_id, command, phrase):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('INSERT INTO rp_requests (request_id, chat_id, sender_id, target_id, command, phrase, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (request_id, str(chat_id), sender_id, target_id, command, phrase, created_at))
    conn.commit()
    conn.close()

def get_rp_request(request_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, sender_id, target_id, command, phrase FROM rp_requests WHERE request_id = ?', (request_id,))
    result = cursor.fetchone()
    conn.close()
    return result if result else None

def read_users():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT hashed_username, user_id FROM users')
    users = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return users

def write_users(hashed_username, user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (hashed_username, user_id) VALUES (?, ?)', (hashed_username, user_id))
    conn.commit()
    conn.close()

def get_nickname(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT nickname FROM user_profiles WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_nickname(user_id, nickname):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    # Создаём строку, если не существует (не трогаем существующие поля)
    cursor.execute('INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)', (user_id,))
    # Обновляем только ник
    cursor.execute('UPDATE user_profiles SET nickname = ? WHERE user_id = ?', (nickname, user_id))
    conn.commit()
    conn.close()

def remove_nickname(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE user_profiles SET nickname = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_description(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT description FROM user_profiles WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_description(user_id, description):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    # Создаём строку, если не существует (не трогаем существующие поля)
    cursor.execute('INSERT OR IGNORE INTO user_profiles (user_id) VALUES (?)', (user_id,))
    # Обновляем только описание
    cursor.execute('UPDATE user_profiles SET description = ? WHERE user_id = ?', (description, user_id))
    conn.commit()
    conn.close()

def remove_description(user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE user_profiles SET description = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def read_la():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id, username FROM low_admins')
    la = {}
    for chat_id, username in cursor.fetchall():
        if chat_id not in la:
            la[chat_id] = []
        la[chat_id].append(username)
    conn.close()
    return la

def write_la(la):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM low_admins')
    for chat_id, usernames in la.items():
        for username in usernames:
            cursor.execute('INSERT INTO low_admins (chat_id, username) VALUES (?, ?)', (chat_id, username))
    conn.commit()
    conn.close()

from xxhash import xxh32

def sha(text):
    text = str(text)
    return xxh32(text).hexdigest()

def get_admins(message):
    try:
        if bot.get_chat(message.chat.id).type == 'private':
            return []
        else:
            admins = bot.get_chat_administrators(chat_id=message.chat.id)
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
                username = username.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                return f"@{username}"
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
                username = username.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                return f"@{username}"
            else:
                return "пользователь"
        target_user = message.reply_to_message.from_user
        display_name = get_nickname(target_user.id) or target_user.first_name
        display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f'<a href="tg://user?id={target_user.id}">{display_name}</a>'
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
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
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
    conn.close()
    return data

def save_data(data, filename):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

user_warns = load_data('warns.json')

user_data = load_data('user_data.json')

def get_user_daily_stats(chat_id, user_id):
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT message_count FROM user_data WHERE chat_id = ? AND user_id = ? AND date = ?',
                   (str(chat_id), str(user_id), today))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def get_user_weekly_stats(chat_id, user_id):
    week_ago = datetime.now() - timedelta(days=7)
    week_ago_str = week_ago.strftime('%Y-%m-%d')
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(message_count) FROM user_data WHERE chat_id = ? AND user_id = ? AND date >= ?',
                   (str(chat_id), str(user_id), week_ago_str))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result[0] else 0

def get_user_monthly_stats(chat_id, user_id):
    month_ago = datetime.now() - timedelta(days=30)
    month_ago_str = month_ago.strftime('%Y-%m-%d')
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(message_count) FROM user_data WHERE chat_id = ? AND user_id = ? AND date >= ?',
                   (str(chat_id), str(user_id), month_ago_str))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result[0] else 0

def get_user_all_time_stats(chat_id, user_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(message_count) FROM user_data WHERE chat_id = ? AND user_id = ?',
                   (str(chat_id), str(user_id)))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result[0] else 0

def get_daily_stats(chat_id):
    today = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, message_count FROM user_data WHERE chat_id = ? AND date = ?',
                   (str(chat_id), today))
    daily_stats = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return daily_stats

def get_weekly_stats(chat_id):
    week_ago = datetime.now() - timedelta(days=7)
    week_ago_str = week_ago.strftime('%Y-%m-%d')
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, SUM(message_count) FROM user_data WHERE chat_id = ? AND date >= ? GROUP BY user_id',
                   (str(chat_id), week_ago_str))
    weekly_stats = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return weekly_stats

def get_monthly_stats(chat_id):
    month_ago = datetime.now() - timedelta(days=30)
    month_ago_str = month_ago.strftime('%Y-%m-%d')
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, SUM(message_count) FROM user_data WHERE chat_id = ? AND date >= ? GROUP BY user_id',
                   (str(chat_id), month_ago_str))
    monthly_stats = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return monthly_stats

def get_all_time_stats(chat_id):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, SUM(message_count) FROM user_data WHERE chat_id = ? GROUP BY user_id',
                   (str(chat_id),))
    all_time_stats = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()
    return all_time_stats

def warn_user(message, user_id):
    user_warns = load_data('warns.json')
    if user_id not in user_warns:
        user_warns[user_id] = {'warn_count': 1, 'last_warn_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        bot.reply_to(message, f"{get_name(message)}, Ая-яй, вредим значит? Так нельзя. Пока что просто предупреждаю. Максимум 3 преда, потом - забаню.", parse_mode='HTML')
    else:
        user_warns[user_id]['warn_count'] += 1
        user_warns[user_id]['last_warn_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        bot.reply_to(message, f"{get_name(message)}, Ты опять вредишь? Напоминаю что максимум 3 преда, потом - забаню.", parse_mode='HTML')

    if user_warns[user_id]['warn_count'] >= 3:
        bot.reply_to(message, "Я предупреждал...", parse_mode='HTML')
        target = get_target(message)
        if target:
            bot.ban_chat_member(message.chat.id, target)

    save_data(user_warns, 'warns.json')

def remove_warn(user_id):
    user_warns = load_data('warns.json')
    if user_id in user_warns:
        user_warns[user_id]['warn_count'] -= 1
        if user_warns[user_id]['warn_count'] <= 0:
            del user_warns[user_id]
        save_data(user_warns, 'warns.json')
        return True
    else:
        return False

db = read_db()
print('DEBUG: Инициализация бота...')
bot = telebot.TeleBot(db['token'])
print('DEBUG: Бот успешно инициализирован. Запуск polling...')

def get_user_link_sync(user_id, chat_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        display_name = get_nickname(user_id) or member.user.first_name
        display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if member.user.username:
            # Формируем ссылку вида https://t.me/username
            username = member.user.username.lstrip('@')  # Убираем @ из ника
            return f'<a href="https://t.me/{username}">{display_name}</a>'
        else:
            # Если ника нет, возвращаем просто имя без ссылки
            return display_name
    except Exception as e:
        print(f"Error getting user link for ID {user_id} in chat {chat_id}: {e}")
        return f"Пользователь {user_id}"

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
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO chats (chat_id, chat_title) VALUES (?, ?)', (str(chat_id), chat_title))
    conn.commit()
    conn.close()

def get_all_chats():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT chat_id FROM chats')
    chats = [row[0] for row in cursor.fetchall()]
    conn.close()
    return chats

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
    text = "Топ пользователей за сегодня:\n"
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
    text = "Топ пользователей за неделю:\n"
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
    text = "Топ пользователей за месяц:\n"
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
    text = "Топ пользователей за всё время:\n"
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
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT message_count FROM user_data WHERE chat_id = ? AND user_id = ? AND date = ?',
                       (chat_id, user_id, date))
        result = cursor.fetchone()
        if result:
            cursor.execute('UPDATE user_data SET message_count = ?, last_activity = ? WHERE chat_id = ? AND user_id = ? AND date = ?',
                           (result[0] + 1, current_time if message.text.upper() != 'КТО Я' else '', chat_id, user_id, date))
        else:
            cursor.execute('INSERT INTO user_data (chat_id, user_id, date, message_count, last_activity) VALUES (?, ?, ?, ?, ?)',
                           (chat_id, user_id, date, 1, current_time if message.text.upper() != 'КТО Я' else ''))
        conn.commit()
        conn.close()

    db = read_db()
    owner_id = db['owner_id']

    if message.text == 'bot?':
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        bot.reply_to(message, f'Hello. I see you, {username}')

    if message.text.upper() == "КАКАЯ НАГРУЗКА":
        uptime_output = get_uptime()
        bot.reply_to(message, "Выполняю команду uptime:\n" + uptime_output)

    if message.text.upper().startswith('БАРБАРИС СКАЖИ '):
        text_to_say = message.text[14:]
        user = message.from_user.first_name
        user_id = message.from_user.id
        bot.send_message(message.chat.id, f"[{user}](tg://user?id={user_id}) заставил меня сказать:{text_to_say}", parse_mode='Markdown')

    if message.text.upper().startswith('БАРБАРИС, СКАЖИ '):
        text_to_say = message.text[15:]
        user = message.from_user.first_name
        user_id = message.from_user.id
        bot.send_message(message.chat.id, f"[{user}](tg://user?id={user_id}) заставил меня сказать:{text_to_say}", parse_mode='Markdown')

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
        member = bot.get_chat_member(message.chat.id, user_id)
        display_name = get_nickname(user_id) or member.user.first_name
        display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        username = f'<a href="tg://user?id={user_id}">{display_name}</a>'
        daily_count = get_user_daily_stats(chat_id, user_id)
        weekly_count = get_user_weekly_stats(chat_id, user_id)
        monthly_count = get_user_monthly_stats(chat_id, user_id)
        all_time_count = get_user_all_time_stats(chat_id, user_id)
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        cursor.execute('SELECT last_activity FROM user_data WHERE chat_id = ? AND user_id = ? LIMIT 1',
                    (chat_id, user_id))
        result = cursor.fetchone()
        last_active_time = format_time_ago(result[0]) if result and result[0] else "Нет данных"
        conn.close()
        owner_text = "\n🌟 Владелец бота" if int(user_id) == owner_id else ""
        beta_text = "\n💠 Бета-тестер бота" if int(user_id) in beta_testers else ""
        # Добавляем статус "Просто пользователь", если пользователь не владелец и не бета-тестер
        status_text = "\n👤 Просто пользователь" if not owner_text and not beta_text else ""
        description_text = f"\n📝 {get_description(user_id)}" if get_description(user_id) else ""
        reply_text = (
            f"Ты <b>{username}</b>{owner_text}{beta_text}{status_text}{description_text}\n\n"
            f"Последний твой актив:\n{last_active_time}\n"
            f"Краткая стата (д|н|м|вся):\n{daily_count}|{weekly_count}|{monthly_count}|{all_time_count}"
        )
        bot.reply_to(message, reply_text, parse_mode='HTML')

    if message.text.upper().startswith('КТО ТЫ'):
        try:
            db = read_db()
            owner_id = db['owner_id']
            beta_testers = db.get('beta_testers', [])
            target_user_id = None
            target_user_name = None
            if message.reply_to_message:
                target_user_id = message.reply_to_message.from_user.id
                member = bot.get_chat_member(message.chat.id, target_user_id)
                display_name = get_nickname(target_user_id) or member.user.first_name
                display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                target_user_name = f'<a href="tg://user?id={target_user_id}">{display_name}</a>'
            else:
                spl = message.text.split()
                if len(spl) > 2 and spl[2][0] == '@':
                    username_from_command = spl[2][1:]
                    hashed_username = sha(username_from_command.lower())
                    users = read_users()
                    if hashed_username in users:
                        target_user_id = users[hashed_username]
                        member = bot.get_chat_member(message.chat.id, target_user_id)
                        display_name = get_nickname(target_user_id) or member.user.first_name
                        display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        target_user_name = f'<a href="tg://user?id={target_user_id}">{display_name}</a>'
                    else:
                        bot.reply_to(message, "Пользователь с таким юзернеймом не найден в моей базе.")
                        return
                elif len(spl) > 1 and spl[1][0] == '@':
                    username_from_command = spl[1][1:]
                    hashed_username = sha(username_from_command.lower())
                    users = read_users()
                    if hashed_username in users:
                        target_user_id = users[hashed_username]
                        member = bot.get_chat_member(message.chat.id, target_user_id)
                        display_name = get_nickname(target_user_id) or member.user.first_name
                        display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        target_user_name = f'<a href="tg://user?id={target_user_id}">{display_name}</a>'
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
                conn = sqlite3.connect('bot_data.db')
                cursor = conn.cursor()
                cursor.execute('SELECT last_activity FROM user_data WHERE chat_id = ? AND user_id = ? LIMIT 1',
                            (chat_id, target_user_id))
                result = cursor.fetchone()
                last_active_time = format_time_ago(result[0]) if result and result[0] else "Нет данных"
                conn.close()
                owner_text = "\n🌟 Владелец бота" if int(target_user_id) == owner_id else ""
                beta_text = "\n💠 Бета-тестер бота" if int(target_user_id) in beta_testers else ""
                # Добавляем статус "Просто пользователь", если пользователь не владелец и не бета-тестер
                status_text = "\n👤 Просто пользователь" if not owner_text and not beta_text else ""
                description_text = f"\n📝 {get_description(target_user_id)}" if get_description(target_user_id) else ""
                reply_text = (
                    f"Это <b>{target_user_name}</b>{owner_text}{beta_text}{status_text}{description_text}\n\n"
                    f"Последний актив:\n{last_active_time}\n"
                    f"Краткая стата (д|н|м|вся):\n{daily_count}|{weekly_count}|{monthly_count}|{all_time_count}"
                )
                bot.reply_to(message, reply_text, parse_mode='HTML')
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

    if message.text.upper() == 'ВАРН':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                if message.reply_to_message:
                    user_id = message.reply_to_message.from_user.id
                    warn_user(message, user_id)
                else:
                    bot.reply_to(message, "Команда должна быть ответом на сообщение нарушителя.")
        except:
            return 0

    if message.text.upper() == 'СНЯТЬ ВАРН':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                if message.reply_to_message:
                    user_id = message.reply_to_message.from_user.id
                    if remove_warn(user_id):
                        bot.reply_to(message, f"Ладно, {get_name(message)}, прощаю последний твой косяк.", parse_mode='HTML')
                    else:
                        bot.reply_to(message, "Этот человек очень даже хороший в моём видении.")
                else:
                    bot.reply_to(message, "Команда должна быть ответом на сообщение пользователя.")
        except:
            return 0

    if message.text.upper().startswith('МУТ'):
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                target = get_target(message)
                time = get_time(message)
                if target:
                    if time:
                        bot.restrict_chat_member(message.chat.id, target, until_date=message.date + time[1])
                        answer = f'Я заклеил ему рот на {time[0]} {time[2]}. Маловато как по мне, ну ладно.'
                    else:
                        bot.restrict_chat_member(message.chat.id, target, until_date=message.date)
                        answer = f'Я заклеил ему рот.'
                    try:
                        bot.reply_to(message, answer, parse_mode='HTML')
                    except:
                        bot.reply_to(message, answer)
                else:
                    catch_error(message, 'None', 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper().startswith('РАЗМУТ'):
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                target = get_target(message)
                if target:
                    bot.restrict_chat_member(message.chat.id, target, can_send_messages=True,
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
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                target = get_target(message)
                if target:
                    bot.ban_chat_member(message.chat.id, target)
                    bot.unban_chat_member(message.chat.id, target)
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
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                target = get_target(message)
                if target:
                    bot.ban_chat_member(message.chat.id, target)
                    bot.reply_to(message, f'''Этот плохиш был изгнан с сие великой группы и не имеет права прощения!
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "РАЗБАН":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                target = get_target(message)
                if target:
                    bot.unban_chat_member(message.chat.id, target)
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
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                bot.set_chat_permissions(message.chat.id, telebot.types.ChatPermissions(can_send_messages=False, can_send_other_messages=False, can_send_polls=False))
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
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                bot.set_chat_permissions(message.chat.id, telebot.types.ChatPermissions(can_send_messages=True, can_send_other_messages=True, can_send_polls=True))
                bot.reply_to(message, 'Ладно, мне надоела тишина. Открываю чат..')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() in ["ПИН", "ЗАКРЕП"]:
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                bot.pin_chat_message(message.chat.id, message.reply_to_message.id)
                bot.reply_to(message, "Видимо это что то важное.. кхм... Закрепил!")
        except:
            return 0

    if message.text.upper() == "АНПИН":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                bot.unpin_chat_message(message.chat.id, message.reply_to_message.id)
                bot.reply_to(message, "Больше не важное, лол.. кхм... Открепил!")
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '+АДМИН':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                user_id = message.reply_to_message.from_user.id
                chat_id = message.chat.id
                bot.promote_chat_member(chat_id, user_id, can_manage_chat=True, can_change_info=True, can_delete_messages=True, can_restrict_members=True, can_invite_users=True, can_pin_messages=True, can_manage_video_chats=True, can_manage_voice_chats=True, can_post_stories=True, can_edit_stories=True, can_delete_stories=True)
                bot.reply_to(message, "Теперь у этого человечка есть власть над чатом!! Бойтесь.")
        except:
            return 0

    if message.text.upper() == '-АДМИН':
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                user_id = message.reply_to_message.from_user.id
                chat_id = message.chat.id
                bot.promote_chat_member(chat_id, user_id, can_manage_chat=False, can_change_info=False, can_delete_messages=False, can_restrict_members=False, can_invite_users=False, can_pin_messages=False, can_manage_video_chats=False, can_manage_voice_chats=False, can_post_stories=False, can_edit_stories=False, can_delete_stories=False)
                bot.reply_to(message, "Лох, понижен в должности. Теперь его можно не бояться")
        except:
            return 0

    if message.text.upper() == "-СМС":
        try:
            if have_rights(message):
                db = read_db()
                owner_id = db['owner_id']
                if message.from_user.id == owner_id:
                    bot.send_message(message.chat.id, "Так точно, создатель!")
                bot.delete_message(message.chat.id, message.reply_to_message.id)
                bot.delete_message(message.chat.id, message.id)
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

    if message.text.upper() == ".ХЕЛП":
        bot.reply_to(message, '''Помощь по командам:

<blockquote expandable><b>Основные команды бота</b>
+ник {ник} / -ник - Установить/сбросить кастомный ник (отображается в топе и РП)
+описание {описание} / -описание - Установить/сбросить описание (отображается в кто я/кто ты)
Какая нагрузка - выполняет команду uptime и отправляет её вывод
Топ день / Топ дня - Топ пользователей за день в этом чате.
Топ неделя / Топ недели - Топ пользователей за неделю в этом чате.
Топ месяц / Топ месяца - Топ пользователей за месяц в этом чате.
Топ все / Топ вся - Топ пользователей за все время в этом чате.
Кто ты @username / reply - Показывает инфу о пользователе.
Бан/Разбан - Блокировка/разблокировка пользователя
Кик - Изгнание пользователя
Мут/Размут [2m/2h] - Лишение/выдача права слова пользователю (m - минуты, h - часы)
Варн/Снять варн - Выдача/Снятие предупреждения пользователю
Закреп||Пин - Прикрепить сообщение
Анпин - открепить сообщение
Рандом a b - Случайный выбор числа в диапазоне a..b
.Хелп - Этот список
Пинг/Кинг/Бот - Для проверки бота
Что с ботом? - ..)
+чат/-чат - Открытие/закрытие чата
+админ/-админ - Выдача/снятие прав администратора пользователя
Барбарис, скажи - Повторяет за вами (запятая кст не обязательна, но и с ней оно работает)
</blockquote>
<blockquote expandable><b>РП-Команды</b>
Обнять
Поцеловать
Погладить
Покормить
Дать пять
Забрать в рабство
Пригласить на чай
Кусь
Отсосать
Поздравить
Прижать
Пнуть
Расстрелять
Испугать
Изнасиловать
Отдаться
Отравить
Ударить
Убить
Понюхать
Кастрировать
Пожать руку
Выебать
Извиниться
Лизнуть
Шлёпнуть
Послать нахуй
Похвалить
Сжечь
Трахнуть
Ущипнуть
Уебать
Записать на ноготочки
Делать секс
Связать
Заставить
Повесить
Уничтожить
Продать
Щекотать
Взорвать
Шмальнуть
Засосать
Лечь
Унизить
Арестовать
Наорать
Рассмешить
Ушатать
Порвать
Выкопать
Выпороть
Закопать
Выпить
Мой/Моя
Наказать
Разорвать очко
Довести до сквирта
Пощупать
Подарить
Обкончать
Подрочить
Самоотсос
Напоить
Потискать
Отправить в дурку
Оторвать член
Подстричь налысо
Помериться
Выебать мозги
Переехать
Цыц
Цыц!
Сожрать</blockquote>''', parse_mode='HTML')

##############       RP COMMANDS        #################

    if message.text: # Убедимся, что сообщение не пустое
            match = re.match(r'\bСАМООТСОС\b\s*(.*)', message.text, re.IGNORECASE)
            if match:
                display_name = get_nickname(message.from_user.id) or message.from_user.first_name
                display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Извлекаем фразу, которая теперь будет в оригинальном регистре
                user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Формируем ответ
                response_text = f'Великий одиночка {display_name} отсосал сам у себя от отчаяния.'
                if user_phrase: # Добавляем фразу, только если она есть
                    response_text += f'\nСо словами: {user_phrase}'
                try:
                    bot.reply_to(message, response_text, parse_mode='HTML')
                except Exception as e:
                    catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОВЕСИТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name},\n\nF.'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    ######## IGNORE RP ######

    if not message.reply_to_message:
        return

    if message.text: # Убедимся, что сообщение не пустое
        if message.reply_to_message: # Новая проверка
            match = re.match(r'\bОБНЯТЬ\b\s*(.*)', message.text, re.IGNORECASE)
            if match:
                display_name = get_nickname(message.from_user.id) or message.from_user.first_name
                display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Извлекаем фразу, которая теперь будет в оригинальном регистре
                user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Формируем ответ
                response_text = f'{display_name} крепко обнял {get_name(message)}'
                if user_phrase: # Добавляем фразу, только если она есть
                    response_text += f'\nСо словами: {user_phrase}'
                try:
                    bot.reply_to(message, response_text, parse_mode='HTML')
                except Exception as e:
                    catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЦЕЛОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} нежно поцеловал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОГЛАДИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} погладил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОКОРМИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} покормил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bДАТЬ ПЯТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} дал пять {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЗДРАВИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} поздравил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПРИЖАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} прижал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} пнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bРАССТРЕЛЯТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} расстрелял {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bИСПУГАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} испугал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bИЗНАСИЛОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} изнасиловал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТДАТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} отдался {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТРАВИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} отравил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУДАРИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} ударил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУБИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} убил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОНЮХАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} понюхал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bКАСТРИРОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} кастрировал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАБРАТЬ В РАБСТВО\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} забрал к себе в свои рабы {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЖАТЬ РУКУ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} крепко и с уважением пожал руку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)


    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПРИГЛАСИТЬ НА ЧАЙ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} пригласил к себе попить чаёчку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bКУСЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} кусьнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТСОСАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} глубоко отсосал у {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫЕБАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} аккуратненько так вошёл в {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bИЗВИНИТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} раскаялся перед {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЛИЗНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} облизнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bШЛЁПНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} шлёпнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОСЛАТЬ НАХУЙ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} послал куда подальше {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bТП\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} магическим образом тепнулся к {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОХВАЛИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} радостно похвалил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bСЖЕЧЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} сжёг до тла {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bТРАХНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} в ускоренном ритме побывал в {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУЩИПНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} неожиданно ущипнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУЕБАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            # Логика случайного выбора части тела (без изменений)
            rand = random.randint(1, 5)
            if (rand == 1):
                work = "в глаз"
            elif (rand == 2):
                work = "по щеке"
            elif (rand == 3):
                work = "в челюсть"
            elif (rand == 4):
                work = "в живот"
            elif (rand == 5):
                work = "по виску"

            # Формируем ответ
            response_text = f'{display_name} уебал со всей дури {get_name(message)} и попал {work}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'

            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОМЕРИТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} померился хозяйством с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОБКОНЧАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            # Логика случайного выбора части тела (без изменений)
            rand = random.randint(1, 7)
            if (rand == 1):
                work = "в глаз"
            elif (rand == 2):
                work = "в рот"
            elif (rand == 3):
                work = "внутрь"
            elif (rand == 4):
                work = "на лицо"
            elif (rand == 5):
                work = "на грудь"
            elif (rand == 6):
                work = "на попку"
            elif (rand == 7):
                work = "на животик"

            # Формируем ответ
            response_text = f'{display_name} смачно накончал {work} {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'

            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАПИСАТЬ НА НОГОТОЧКИ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} записал на маник {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bДЕЛАТЬ СЕКС\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} уединился с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bСВЯЗАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} крепко связал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАСТАВИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} принудительно заставил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОВЕСИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} превратил в черешенку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУНИЧТОЖИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} низвёл до атомов.. ну или аннигилировал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПРОДАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} продал за дёшево {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЩЕКОТАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} щекотками довёл до истирического смеха {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЗОРВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} заминировал и подорвал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bШМАЛЬНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} шмальнул {get_name(message)} и тот улетел ну ооооооочень далеко'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАСОСАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} оставил отметку в виде засоса у {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЛЕЧЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} прилёг рядом с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУНИЗИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} унизил ниже плинтуса {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bАРЕСТОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Походу кто то мусорнулся и {display_name} арестовал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bНАОРАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} очень громко наорал на {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bРАССМЕШИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Юморист {display_name} чуть ли не до смерти рассмешил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУШАТАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} к хренам ушатал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОРВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} порвал {get_name(message)} как Тузик грелку'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫКОПАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} нашёл археологическую ценность в виде {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bСОЖРАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} кусьн.. СОЖРАЛ НАХРЕН {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОДСТРИЧЬ НАЛЫСО\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Недо-меллстрой под ником {display_name} подстриг налысо {get_name(message)} за НИ-ЧЕ-ГО'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫЕБАТЬ МОЗГИ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} конкретно так заебал {get_name(message)} и, заодно, трахнул мозги'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПЕРЕЕХАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} пару раз переехал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫПОРОТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} выпорол до красна {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАКОПАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} похоронил заживо {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)
    
    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЩУПАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} тщательно пощупал всего {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОДРОЧИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} передёрнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОТИСКАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} потискал {get_name(message)} за его мягкие щёчки. Милотаа..'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОДАРИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} подарил от всего сердца подарочек {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫПИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} разделил пару бокалов с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bНАКАЗАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Суровый {display_name} наказал проказника {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bРАЗОРВАТЬ ОЧКО\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} порвал напрочь задний проход {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bДОВЕСТИ ДО СКВИРТА\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} довёл до мощного и струйного фонтана {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bНАПОИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} споил в стельку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text.upper() == 'ЦЫЦ!' and message.reply_to_message:
        display_name = get_nickname(message.from_user.id) or message.from_user.first_name
        display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        response_text = f'Уууу.. {display_name} закрыл ротик {get_name(message)} и привязал к кроватке. Знаешь.. я не думаю что тебе что то хорошее светит.. а хотя может.. хз крч.'
        try:
            print(f"DEBUG: Отправка response_text: {response_text}")
            bot.reply_to(message, response_text, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)
        return

    if message.text.upper() == 'ЦЫЦ' and message.reply_to_message:
        display_name = get_nickname(message.from_user.id) or message.from_user.first_name
        display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        response_text = f'{display_name} заткнул {get_name(message)} используя кляп и кинул в подвал. А нехер выделываться было.'
        try:
            print(f"DEBUG: Отправка response_text: {response_text}")
            bot.reply_to(message, response_text, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)
        return

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТПРАВИТЬ В ДУРКУ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{display_name} отправил прямиком в диспансер {get_name(message)}. Шизоид, быстро в палату!'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТОРВАТЬ ЧЛЕН\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            display_name = get_nickname(message.from_user.id) or message.from_user.first_name
            display_name = display_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'АЙ..\n\n<tg-spoiler>{display_name} оторвал к херам наследство у {get_name(message)}.</tg-spoiler>'
            if user_phrase: # Добавляем фразу, только если она есть
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

        # Разделяем запрос на слова и обрабатываем команды с пробелами
        words = text.split()
        command = words[0]
        user_phrase = ' '.join(words[1:]).strip() if len(words) > 1 else ''

        # Поддержка многословных команд
        if command == 'записать' and len(words) > 1 and words[1] == 'на':
            command = 'записать на ноготочки'
            user_phrase = ' '.join(words[3:]).strip() if len(words) > 3 else ''
        elif command == 'делать' and len(words) > 1 and words[1] == 'секс':
            command = 'делать секс'
            user_phrase = ' '.join(words[2:]).strip() if len(words) > 2 else ''
        elif command == 'подстричь' and len(words) > 1 and words[1] == 'налысо':
            command = 'подстричь налысо'
            user_phrase = ' '.join(words[2:]).strip() if len(words) > 2 else ''
        elif command == 'выебать' and len(words) > 1 and words[1] == 'мозги':
            command = 'выебать мозги'
            user_phrase = ' '.join(words[2:]).strip() if len(words) > 2 else ''
        elif command == 'разорвать' and len(words) > 1 and words[1] == 'очко':
            command = 'разорвать очко'
            user_phrase = ' '.join(words[2:]).strip() if len(words) > 2 else ''
        elif command == 'довести' and len(words) > 1 and words[1] == 'до':
            command = 'довести до сквирта'
            user_phrase = ' '.join(words[3:]).strip() if len(words) > 3 else ''
        elif command == 'отправить' and len(words) > 1 and words[1] == 'в':
            command = 'отправить в дурку'
            user_phrase = ' '.join(words[3:]).strip() if len(words) > 3 else ''
        elif command == 'оторвать' and len(words) > 1 and words[1] == 'член':
            command = 'оторвать член'
            user_phrase = ' '.join(words[2:]).strip() if len(words) > 2 else ''

        sender_id = query.from_user.id
        sender_nickname = get_nickname(sender_id) or query.from_user.first_name
        sender_display = sender_nickname.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        # Формируем текст без указания цели
        request_text = ""
        if command == 'поцеловать':
            request_text = f"{sender_display} хочет поцеловать"
        elif command == 'обнять':
            request_text = f"{sender_display} хочет обнять"
        elif command == 'уебать':
            request_text = f"{sender_display} хочет уебать"
        elif command == 'отсосать':
            request_text = f"{sender_display} хочет отсосать"
        elif command == 'трахнуть':
            request_text = f"{sender_display} хочет трахнуть"
        elif command == 'ущипнуть':
            request_text = f"{sender_display} хочет ущипнуть"
        elif command == 'помериться':
            request_text = f"{sender_display} хочет помериться"
        elif command == 'обкончать':
            request_text = f"{sender_display} хочет обкончать"
        elif command == 'записать на ноготочки':
            request_text = f"{sender_display} хочет записать на ноготочки"
        elif command == 'делать секс':
            request_text = f"{sender_display} хочет делать секс"
        elif command == 'связать':
            request_text = f"{sender_display} хочет связать"
        elif command == 'заставить':
            request_text = f"{sender_display} хочет заставить"
        elif command == 'повесить':
            request_text = f"{sender_display} хочет повесить"
        elif command == 'уничтожить':
            request_text = f"{sender_display} хочет уничтожить"
        elif command == 'продать':
            request_text = f"{sender_display} хочет продать"
        elif command == 'щекотать':
            request_text = f"{sender_display} хочет щекотать"
        elif command == 'взорвать':
            request_text = f"{sender_display} хочет взорвать"
        elif command == 'шмальнуть':
            request_text = f"{sender_display} хочет шмальнуть"
        elif command == 'засосать':
            request_text = f"{sender_display} хочет засосать"
        elif command == 'лечь':
            request_text = f"{sender_display} хочет лечь"
        elif command == 'унизить':
            request_text = f"{sender_display} хочет унизить"
        elif command == 'арестовать':
            request_text = f"{sender_display} хочет арестовать"
        elif command == 'наорать':
            request_text = f"{sender_display} хочет наорать"
        elif command == 'рассмешить':
            request_text = f"{sender_display} хочет рассмешить"
        elif command == 'ушатать':
            request_text = f"{sender_display} хочет ушатать"
        elif command == 'порвать':
            request_text = f"{sender_display} хочет порвать"
        elif command == 'выкопать':
            request_text = f"{sender_display} хочет выкопать"
        elif command == 'сожрать':
            request_text = f"{sender_display} хочет сожрать"
        elif command == 'подстричь налысо':
            request_text = f"{sender_display} хочет подстричь налысо"
        elif command == 'выебать мозги':
            request_text = f"{sender_display} хочет выебать мозги"
        elif command == 'переехать':
            request_text = f"{sender_display} хочет переехать"
        elif command == 'выпороть':
            request_text = f"{sender_display} хочет выпороть"
        elif command == 'закопать':
            request_text = f"{sender_display} хочет закопать"
        elif command == 'пощупать':
            request_text = f"{sender_display} хочет пощупать"
        elif command == 'подрочить':
            request_text = f"{sender_display} хочет подрочить"
        elif command == 'потисать':
            request_text = f"{sender_display} хочет потискать"
        elif command == 'подарить':
            request_text = f"{sender_display} хочет подарить"
        elif command == 'выпить':
            request_text = f"{sender_display} хочет выпить"
        elif command == 'наказать':
            request_text = f"{sender_display} хочет наказать"
        elif command == 'разорвать очко':
            request_text = f"{sender_display} хочет разорвать очко"
        elif command == 'довести до сквирта':
            request_text = f"{sender_display} хочет довести до сквирта"
        elif command == 'напоить':
            request_text = f"{sender_display} хочет напоить"
        elif command == 'отправить в дурку':
            request_text = f"{sender_display} хочет отправить в дурку"
        elif command == 'оторвать член':
            request_text = f"{sender_display} хочет оторвать член"
        elif command == 'цыц' or command == 'цыц!':
            request_text = f"{sender_display} хочет заткнуть ({command})"

        if not request_text:
            return

        if user_phrase:
            request_text += f'\nФраза: {user_phrase}'

        request_id = str(uuid.uuid4())
        save_rp_request(request_id, 0, sender_id, 0, command, user_phrase)

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("Принять", callback_data=f"rp_accept_{request_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"rp_reject_{request_id}")
        )

        results = [
            InlineQueryResultArticle(
                id=request_id,
                title=f"{command.capitalize()}",
                input_message_content=InputTextMessageContent(
                    request_text,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                ),
                description=user_phrase[:50] if user_phrase else f"RP: {command}",
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

        chat_id, sender_id, _, command, phrase = request_data
        sender_nickname = get_nickname(sender_id) or call.from_user.first_name
        sender_display = sender_nickname.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        # Цель определяется на основе того, кто нажал кнопку
        clicker_id = call.from_user.id
        clicker_nickname = get_nickname(clicker_id) or call.from_user.first_name
        clicker_display = clicker_nickname.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        target_id = clicker_id
        target_username = call.from_user.username or clicker_nickname
        target_display = clicker_display
        target_link = f'<a href="https://t.me/{target_username}">{target_display}</a>' if target_username else target_display
        logging.debug(f'Sender: {sender_display} ({sender_id}), Target: {target_display} ({target_id}), Command: {command}')

        # Формируем текст ответа без второй строки
        response_text = ""
        if action == 'accept':
            if command == 'поцеловать':
                response_text = f"{sender_display} нежно поцеловал {target_link}"
            elif command == 'обнять':
                response_text = f"{sender_display} крепко обнял {target_link}"
            elif command == 'уебать':
                rand = random.randint(1, 5)
                parts = ["в глаз", "по щеке", "в челюсть", "в живот", "по виску"]
                work = parts[rand - 1]
                response_text = f"{sender_display} уебал со всей дури {target_link} и попал {work}"
            elif command == 'отсосать':
                response_text = f"{sender_display} глубоко отсосал у {target_link}"
            elif command == 'трахнуть':
                response_text = f"{sender_display} в ускоренном ритме побывал в {target_link}"
            elif command == 'ущипнуть':
                response_text = f"{sender_display} неожиданно ущипнул {target_link}"
            elif command == 'помериться':
                response_text = f"{sender_display} померился хозяйством с {target_link}"
            elif command == 'обкончать':
                rand = random.randint(1, 7)
                parts = ["в глаз", "в рот", "внутрь", "на лицо", "на грудь", "на попку", "на животик"]
                work = parts[rand - 1]
                response_text = f"{sender_display} смачно накончал {work} {target_link}"
            elif command == 'записать на ноготочки':
                response_text = f"{sender_display} записал на маник {target_link}"
            elif command == 'делать секс':
                response_text = f"{sender_display} уединился с {target_link}"
            elif command == 'связать':
                response_text = f"{sender_display} крепко связал {target_link}"
            elif command == 'заставить':
                response_text = f"{sender_display} принудительно заставил {target_link}"
            elif command == 'повесить':
                response_text = f"{sender_display} превратил в черешенку {target_link}"
            elif command == 'уничтожить':
                response_text = f"{sender_display} низвёл до атомов.. ну или аннигилировал {target_link}"
            elif command == 'продать':
                response_text = f"{sender_display} продал за дёшево {target_link}"
            elif command == 'щекотать':
                response_text = f"{sender_display} щекотками довёл до истирического смеха {target_link}"
            elif command == 'взорвать':
                response_text = f"{sender_display} заминировал и подорвал {target_link}"
            elif command == 'шмальнуть':
                response_text = f"{sender_display} шмальнул {target_link} и тот улетел ну ооооооочень далеко"
            elif command == 'засосать':
                response_text = f"{sender_display} оставил отметку в виде засоса у {target_link}"
            elif command == 'лечь':
                response_text = f"{sender_display} прилёг рядом с {target_link}"
            elif command == 'унизить':
                response_text = f"{sender_display} унизил ниже плинтуса {target_link}"
            elif command == 'арестовать':
                response_text = f"Походу кто то мусорнулся и {sender_display} арестовал {target_link}"
            elif command == 'наорать':
                response_text = f"{sender_display} очень громко наорал на {target_link}"
            elif command == 'рассмешить':
                response_text = f"Юморист {sender_display} чуть ли не до смерти рассмешил {target_link}"
            elif command == 'ушатать':
                response_text = f"{sender_display} к хренам ушатал {target_link}"
            elif command == 'порвать':
                response_text = f"{sender_display} порвал {target_link} как Тузик грелку"
            elif command == 'выкопать':
                response_text = f"{sender_display} нашёл археологическую ценность в виде {target_link}"
            elif command == 'сожрать':
                response_text = f"{sender_display} кусьн.. СОЖРАЛ НАХРЕН {target_link}"
            elif command == 'подстричь налысо':
                response_text = f"Недо-меллстрой под ником {sender_display} подстриг налысо {target_link} за НИ-ЧЕ-ГО"
            elif command == 'выебать мозги':
                response_text = f"{sender_display} конкретно так заебал {target_link} и, заодно, трахнул мозги"
            elif command == 'переехать':
                response_text = f"{sender_display} пару раз переехал {target_link}"
            elif command == 'выпороть':
                response_text = f"{sender_display} выпорол до красна {target_link}"
            elif command == 'закопать':
                response_text = f"{sender_display} похоронил заживо {target_link}"
            elif command == 'пощупать':
                response_text = f"{sender_display} тщательно пощупал всего {target_link}"
            elif command == 'подрочить':
                response_text = f"{sender_display} передёрнул {target_link}"
            elif command == 'потисать':
                response_text = f"{sender_display} потискал {target_link} за его мягкие щёчки. Милотаа.."
            elif command == 'подарить':
                response_text = f"{sender_display} подарил от всего сердца подарочек {target_link}"
            elif command == 'выпить':
                response_text = f"{sender_display} разделил пару бокалов с {target_link}"
            elif command == 'наказать':
                response_text = f"Суровый {sender_display} наказал проказника {target_link}"
            elif command == 'разорвать очко':
                response_text = f"{sender_display} порвал напрочь задний проход {target_link}"
            elif command == 'довести до сквирта':
                response_text = f"{sender_display} довёл до мощного и струйного фонтана {target_link}"
            elif command == 'напоить':
                response_text = f"{sender_display} споил в стельку {target_link}"
            elif command == 'отправить в дурку':
                response_text = f"{sender_display} отправил прямиком в диспансер {target_link}. Шизоид, быстро в палату!"
            elif command == 'оторвать член':
                response_text = f"АЙ..\n\n<tg-spoiler>{sender_display} оторвал к херам наследство у {target_link}.</tg-spoiler>"
            elif command == 'цыц':
                response_text = f"{sender_display} заткнул {target_link} используя кляп и кинул в подвал. А нехер выделываться было."
            elif command == 'цыц!':
                response_text = f"Уууу.. {sender_display} закрыл ротик {target_link} и привязал к кроватке. Знаешь.. я не думаю что тебе что то хорошее светит.. а хотя может.. хз крч."
        elif action == 'reject':
            if command == 'поцеловать':
                response_text = f"{target_link} увернулся от поцелуя {sender_display}"
            elif command == 'обнять':
                response_text = f"{target_link} вырвался из объятий {sender_display}"
            elif command == 'уебать':
                response_text = f"{target_link} ловко уклонился от удара {sender_display}"
            elif command == 'отсосать':
                response_text = f"{target_link} отказался от предложения {sender_display}"
            elif command == 'трахнуть':
                response_text = f"{target_link} отбился от настойчивых попыток {sender_display}"
            elif command == 'ущипнуть':
                response_text = f"{target_link} отскочил от щипка {sender_display}"
            elif command == 'помериться':
                response_text = f"{target_link} отказался меряться с {sender_display}"
            elif command == 'обкончать':
                response_text = f"{target_link} увернулся от потока {sender_display}"
            elif command == 'записать на ноготочки':
                response_text = f"{target_link} отказался от записи на маникюр от {sender_display}"
            elif command == 'делать секс':
                response_text = f"{target_link} не захотел уединяться с {sender_display}"
            elif command == 'связать':
                response_text = f"{target_link} вырвался из верёвок {sender_display}"
            elif command == 'заставить':
                response_text = f"{target_link} сопротивлялся принуждению {sender_display}"
            elif command == 'повесить':
                response_text = f"{target_link} сорвался с петли {sender_display}"
            elif command == 'уничтожить':
                response_text = f"{target_link} выжил после попытки уничтожения {sender_display}"
            elif command == 'продать':
                response_text = f"{target_link} сбежал с аукциона {sender_display}"
            elif command == 'щекотать':
                response_text = f"{target_link} не поддался щекотке {sender_display}"
            elif command == 'взорвать':
                response_text = f"{target_link} обезвредил бомбу {sender_display}"
            elif command == 'шмальнуть':
                response_text = f"{target_link} увернулся от выстрела {sender_display}"
            elif command == 'засосать':
                response_text = f"{target_link} оттолкнул {sender_display} от засоса"
            elif command == 'лечь':
                response_text = f"{target_link} не лёг рядом с {sender_display}"
            elif command == 'унизить':
                response_text = f"{target_link} не поддался унижению от {sender_display}"
            elif command == 'арестовать':
                response_text = f"{target_link} скрылся от ареста {sender_display}"
            elif command == 'наорать':
                response_text = f"{target_link} заткнул уши от крика {sender_display}"
            elif command == 'рассмешить':
                response_text = f"{target_link} остался серьёзным несмотря на шутки {sender_display}"
            elif command == 'ушатать':
                response_text = f"{target_link} устоял после ушатывания {sender_display}"
            elif command == 'порвать':
                response_text = f"{target_link} не дал себя порвать {sender_display}"
            elif command == 'выкопать':
                response_text = f"{target_link} зарылся глубже от {sender_display}"
            elif command == 'сожрать':
                response_text = f"{target_link} вырвался из пасти {sender_display}"
            elif command == 'подстричь налысо':
                response_text = f"{target_link} уклонился от ножниц {sender_display}"
            elif command == 'выебать мозги':
                response_text = f"{target_link} игнорировал вынос мозга {sender_display}"
            elif command == 'переехать':
                response_text = f"{target_link} перепрыгнул через машину {sender_display}"
            elif command == 'выпороть':
                response_text = f"{target_link} увернулся от порки {sender_display}"
            elif command == 'закопать':
                response_text = f"{target_link} выбрался из ямы {sender_display}"
            elif command == 'пощупать':
                response_text = f"{target_link} отошёл от {sender_display}"
            elif command == 'подрочить':
                response_text = f"{target_link} прервал процесс {sender_display}"
            elif command == 'потисать':
                response_text = f"{target_link} не дал себя потискать {sender_display}"
            elif command == 'подарить':
                response_text = f"{target_link} вернул подарок {sender_display}"
            elif command == 'выпить':
                response_text = f"{target_link} отказался пить с {sender_display}"
            elif command == 'наказать':
                response_text = f"{target_link} избежал наказания от {sender_display}"
            elif command == 'разорвать очко':
                response_text = f"{target_link} защитил задний проход от {sender_display}"
            elif command == 'довести до сквирта':
                response_text = f"{target_link} не поддался доведению {sender_display}"
            elif command == 'напоить':
                response_text = f"{target_link} протрезвел от попыток {sender_display}"
            elif command == 'отправить в дурку':
                response_text = f"{target_link} доказал свою нормальность {sender_display}"
            elif command == 'оторвать член':
                response_text = f"{target_link} сохранил своё наследство от {sender_display}"
            elif command == 'цыц':
                response_text = f"{target_link} продолжил говорить несмотря на {sender_display}"
            elif command == 'цыц!':
                response_text = f"{target_link} вырвался из кроватки {sender_display}"

        if phrase:
            response_text += f"\nСо словами: {phrase}"
        logging.debug(f'Response text: {response_text}')

        # Проверяем, можно ли отредактировать сообщение
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
                conn = sqlite3.connect('bot_data.db')
                cursor = conn.cursor()
                cursor.execute('UPDATE rp_requests SET chat_id = ?, target_id = ? WHERE request_id = ?',
                              (chat_id, target_id, request_id))
                conn.commit()
                conn.close()
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
                conn = sqlite3.connect('bot_data.db')
                cursor = conn.cursor()
                cursor.execute('UPDATE rp_requests SET target_id = ? WHERE request_id = ?',
                              (target_id, request_id))
                conn.commit()
                conn.close()
                # Сохраняем цель для sender_id (используем sender_id как chat_id в ЛС)
                save_last_target(str(sender_id), sender_id, target_id)
                bot.answer_callback_query(call.id, "Действие обработано!")
                logging.debug(f'Inline message edited successfully: inline_message_id={call.inline_message_id}')
            except Exception as e:
                logging.error(f'Edit inline message error: {e}')
                bot.answer_callback_query(call.id, f"Ошибка: не удалось изменить сообщение. {str(e)}")
        else:
            # В предпросмотре молча игнорируем callback
            logging.debug(f'Ignoring callback in preview mode: request_id={request_id}')
            bot.answer_callback_query(call.id)

    except Exception as e:
        logging.error(f'Callback error: {e}')
        bot.answer_callback_query(call.id, f"Ошибка при обработке действия: {str(e)}")

bot.polling(none_stop=True)