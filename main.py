import re
import subprocess
import telebot
import os
import json
import random
import sqlite3

from datetime import datetime, timedelta
from telebot import types, util
import logging
import traceback
import asyncio

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
        return telebot.util.user_link(message.reply_to_message.from_user)
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
        first_name = member.user.first_name
        first_name = first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        if member.user.username:
            return f'<a href="https://t.me/{member.user.username}">{first_name}</a>'
        else:
            return first_name
    except Exception as e:
        print(f"Error getting user link for ID {user_id} in chat {chat_id}: {e}")
        return f"Пользователь {user_id}"

def get_uptime():
    try:
        result = subprocess.run(['uptime'], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Ошибка выполнения команды: {e}")
        return ""
    except FileNotFoundError:
        print("Команда 'uptime' не найдена.")
        return ""

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
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)

@bot.message_handler(func=lambda message: message.text and message.text.upper() in ['ТОП НЕДЕЛЯ', 'ТОП НЕДЕЛИ'])
def handle_top_week(message):
    chat_id = str(message.chat.id)
    weekly_stats = get_weekly_stats(chat_id)
    sorted_stats = sorted(weekly_stats.items(), key=lambda x: x[1], reverse=True)
    text = "Топ пользователей за последнюю неделю:\n"
    total_messages_chat = 0
    if not sorted_stats:
        text = "Статистика за неделю пока пуста."
    else:
        for i, (user_id, count) in enumerate(sorted_stats):
            user_link = get_user_link_sync(int(user_id), message.chat.id)
            text += f"{i+1}. {user_link}: {count} сообщений\n"
            total_messages_chat += count
    text += f"\nВсего сообщений в чате за неделю: {total_messages_chat}"
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)

@bot.message_handler(func=lambda message: message.text and message.text.upper() in ['ТОП МЕСЯЦ', 'ТОП МЕСЯЦА'])
def handle_top_month(message):
    chat_id = str(message.chat.id)
    monthly_stats = get_monthly_stats(chat_id)
    sorted_stats = sorted(monthly_stats.items(), key=lambda x: x[1], reverse=True)
    text = "Топ пользователей за последний месяц:\n"
    total_messages_chat = 0
    if not sorted_stats:
        text = "Статистика за месяц пока пуста."
    else:
        for i, (user_id, count) in enumerate(sorted_stats):
            user_link = get_user_link_sync(int(user_id), message.chat.id)
            text += f"{i+1}. {user_link}: {count} сообщений\n"
            total_messages_chat += count
    text += f"\nВсего сообщений в чате за месяц: {total_messages_chat}"
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)

@bot.message_handler(func=lambda message: message.text and message.text.upper() in ['ТОП ВСЕ', 'ТОП ВСЯ'])
def handle_top_all_time(message):
    chat_id = str(message.chat.id)
    all_time_stats = get_all_time_stats(chat_id)
    sorted_stats = sorted(all_time_stats.items(), key=lambda x: x[1], reverse=True)
    text = "Топ пользователей за все время:\n"
    total_messages_chat = 0
    if not sorted_stats:
        text = "Статистика за все время пока пуста."
    else:
        for i, (user_id, count) in enumerate(sorted_stats):
            user_link = get_user_link_sync(int(user_id), message.chat.id)
            text += f"{i+1}. {user_link}: {count} сообщений\n"
            total_messages_chat += count
    text += f"\nВсего сообщений в чате за все время: {total_messages_chat}"
    bot.send_message(message.chat.id, text, parse_mode='HTML', disable_web_page_preview=True)

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
        user_id = str(message.from_user.id)
        chat_id = str(message.chat.id)
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
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
        reply_text = (
            f"Ты <b>{username}</b>{owner_text}{beta_text}\n\n"
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
                target_user_id = str(message.reply_to_message.from_user.id)
                target_user_name = telebot.util.user_link(message.reply_to_message.from_user)
            else:
                spl = message.text.split()
                if len(spl) > 2 and spl[2][0] == '@':
                    username_from_command = spl[2][1:]
                    hashed_username = sha(username_from_command.lower())
                    users = read_users()
                    if hashed_username in users:
                        target_user_id = str(users[hashed_username])
                        try:
                            member = bot.get_chat_member(message.chat.id, int(target_user_id))
                            target_user_name = telebot.util.user_link(member.user)
                        except Exception:
                            target_user_name = f"@{username_from_command}"
                    else:
                        bot.reply_to(message, "Пользователь с таким юзернеймом не найден в моей базе.")
                        return
                elif len(spl) > 1 and spl[1][0] == '@':
                    username_from_command = spl[1][1:]
                    hashed_username = sha(username_from_command.lower())
                    users = read_users()
                    if hashed_username in users:
                        target_user_id = str(users[hashed_username])
                        try:
                            member = bot.get_chat_member(message.chat.id, int(target_user_id))
                            target_user_name = telebot.util.user_link(member.user)
                        except Exception:
                            target_user_name = f"@{username_from_command}"
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
                reply_text = (
                    f"Это <b>{target_user_name}</b>{owner_text}{beta_text}\n\n"
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

    if message.text.upper() == ".ХЕЛП":
        bot.reply_to(message, '''Помощь по командам:

<blockquote expandable><b>Основные команды бота</b>
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
                username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Извлекаем фразу, которая теперь будет в оригинальном регистре
                user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Формируем ответ
                response_text = f'Великий одиночка {username} отсосал сам у себя от отчаяния.'
                if user_phrase: # Добавляем фразу, только если она есть
                    response_text += f'\nСо словами: {user_phrase}'
                try:
                    bot.reply_to(message, response_text, parse_mode='HTML')
                except Exception as e:
                    catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОВЕСИТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username},\n\nF.'
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
                username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Извлекаем фразу, которая теперь будет в оригинальном регистре
                user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Формируем ответ
                response_text = f'{username} крепко обнял {get_name(message)}'
                if user_phrase: # Добавляем фразу, только если она есть
                    response_text += f'\nСо словами: {user_phrase}'
                try:
                    bot.reply_to(message, response_text, parse_mode='HTML')
                except Exception as e:
                    catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЦЕЛОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} затяжно поцеловал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bДАТЬ ПЯТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} круто дал пять {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОГЛАДИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} нежненько погладил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЗДРАВИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} феерично поздравил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПРИЖАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} прижал к стеночке~~ {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} пнул под зад {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bРАССТРЕЛЯТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} расстрелял со всего что было {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text.upper() == 'МОЙ' and message.reply_to_message:
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        response_text = f'{username} зацеловал до смерти, утащил к себе и приковал к батарее {get_name(message)}'
        try:
            print(f"DEBUG: Отправка response_text: {response_text}")
            bot.reply_to(message, response_text, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)
        return

    if message.text.upper() == 'МОЯ' and message.reply_to_message:
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        response_text = f'{username} зацеловал до смерти, утащил к себе и приковал к батарее {get_name(message)}'
        try:
            print(f"DEBUG: Отправка response_text: {response_text}")
            bot.reply_to(message, response_text, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)
        return

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОКОРМИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} вкусно накормил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОТРОГАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} аккуратно потрогал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bИСПУГАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} напугал до мурашек {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bИЗНАСИЛОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} внезапно и принудительно изнасиловал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТДАТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} добровольно и полностью отдался {get_name(message)}. Хорошего вечера вам)'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТРАВИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} безжалостно отравил чем то {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУДАРИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
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
            response_text = f'{username} ударил {get_name(message)} и попал {work}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'

            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУБИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} жестоко убил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОНЮХАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} аккуратненько понюхал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bКАСТРИРОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} лишил яек (и наследства) {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАБРАТЬ В РАБСТВО\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} забрал к себе в свои рабы {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЖАТЬ РУКУ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} крепко и с уважением пожал руку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)


    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПРИГЛАСИТЬ НА ЧАЙ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} пригласил к себе попить чаёчку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bКУСЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} кусьнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТСОСАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} глубоко отсосал у {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫЕБАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} аккуратненько так вошёл в {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bИЗВИНИТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} раскаялся перед {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЛИЗНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} облизнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bШЛЁПНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} шлёпнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОСЛАТЬ НАХУЙ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} послал куда подальше {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bТП\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} магическим образом тепнулся к {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОХВАЛИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} радостно похвалил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bСЖЕЧЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} сжёг до тла {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bТРАХНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} в ускоренном ритме побывал в {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУЩИПНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} неожиданно ущипнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУЕБАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
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
            response_text = f'{username} уебал со всей дури {get_name(message)} и попал {work}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'

            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОМЕРИТЬСЯ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} померился хозяйством с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОБКОНЧАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
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
            response_text = f'{username} смачно накончал {work} {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'

            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАПИСАТЬ НА НОГОТОЧКИ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} записал на маник {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bДЕЛАТЬ СЕКС\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} уединился с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bСВЯЗАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} крепко связал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАСТАВИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} принудительно заставил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОВЕСИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} превратил в черешенку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУНИЧТОЖИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} низвёл до атомов.. ну или аннигилировал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПРОДАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} продал за дёшево {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЩЕКОТАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} щекотками довёл до истирического смеха {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЗОРВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} заминировал и подорвал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bШМАЛЬНУТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} шмальнул {get_name(message)} и тот улетел ну ооооооочень далеко'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАСОСАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} оставил отметку в виде засоса у {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЛЕЧЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} прилёг рядом с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУНИЗИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} унизил ниже плинтуса {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bАРЕСТОВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Походу кто то мусорнулся и {username} арестовал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bНАОРАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} очень громко наорал на {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bРАССМЕШИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Юморист {username} чуть ли не до смерти рассмешил {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bУШАТАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} к хренам ушатал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОРВАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} порвал {get_name(message)} как Тузик грелку'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫКОПАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} нашёл археологическую ценность в виде {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bСОЖРАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} кусьн.. СОЖРАЛ НАХРЕН {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОДСТРИЧЬ НАЛЫСО\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Недо-меллстрой под ником {username} подстриг налысо {get_name(message)} за НИ-ЧЕ-ГО'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫЕБАТЬ МОЗГИ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} конкретно так заебал {get_name(message)} и, заодно, трахнул мозги'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПЕРЕЕХАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} пару раз переехал {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫПОРОТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} выпорол до красна {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЗАКОПАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} похоронил заживо {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)
    
    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОЩУПАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} тщательно пощупал всего {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОДРОЧИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} передёрнул {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОТИСКАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} потискал {get_name(message)} за его мягкие щёчки. Милотаа..'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bПОДАРИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} подарил от всего сердца подарочек {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bВЫПИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} разделил пару бокалов с {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bНАКАЗАТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Суровый {username} наказал проказника {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bРАЗОРВАТЬ ОЧКО\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} порвал напрочь задний проход {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bДОВЕСТИ ДО СКВИРТА\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} довёл до мощного и струйного фонтана {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bНАПОИТЬ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} споил в стельку {get_name(message)}'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text.upper() == 'ЦЫЦ!' and message.reply_to_message:
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        response_text = f'Уууу.. {username} закрыл ротик {get_name(message)} и привязал к кроватке. Знаешь.. я не думаю что тебе что то хорошее светит.. а хотя может.. хз крч.'
        try:
            print(f"DEBUG: Отправка response_text: {response_text}")
            bot.reply_to(message, response_text, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)
        return

    if message.text.upper() == 'ЦЫЦ' and message.reply_to_message:
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        response_text = f'{username} заткнул {get_name(message)} используя кляп и кинул в подвал. А нехер выделываться было.'
        try:
            print(f"DEBUG: Отправка response_text: {response_text}")
            bot.reply_to(message, response_text, parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)
        return

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТПРАВИТЬ В ДУРКУ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} отправил прямиком в диспансер {get_name(message)}. Шизоид, быстро в палату!'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bОТОРВАТЬ ЧЛЕН\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'АЙ..\n\n<tg-spoiler>{username} оторвал к херам наследство у {get_name(message)}.</tg-spoiler>'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

bot.polling(none_stop=True)