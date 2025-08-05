import re
import telebot
import os
import json
import random

from datetime import datetime, timedelta
from telebot import types, util
import logging
import traceback
import asyncio

####### CREATE DB IF NOT EXIST ##########

if not os.path.exists('db.json'):
    # Добавлено 'admin_id_for_errors' со значением по умолчанию None
    db = {'token': 'None', 'admin_id_for_errors': None}
    js = json.dumps(db, indent=2)
    with open('db.json', 'w') as outfile:
        outfile.write(js)

    print('ВНИМАНИЕ: Файл db.json создан. Введи токен в "None" и свой ID администратора в "admin_id_for_errors" (db.json)')
    exit() # Бот завершит работу, пока вы не отредактируете db.json
else:
    print('DEBUG: Файл db.json существует.') # Добавлено отладочное сообщение

if not os.path.exists('users.json'):
        users = {}
        js = json.dumps(users, indent=2)
        with open('users.json', 'w') as outfile:
                outfile.write(js)
        print('DEBUG: Файл users.json создан.') # Добавлено отладочное сообщение

if not os.path.exists('la.json'):
        la = {}
        js = json.dumps(la, indent=2)
        with open('la.json', 'w') as outfile:
                outfile.write(js)
        print('DEBUG: Файл la.json создан.') # Добавлено отладочное сообщение

############ WORK WITH DBs ##########

def read_db():
    print('DEBUG: Чтение db.json...') # Добавлено отладочное сообщение
    with open('db.json', 'r') as openfile:
        db = json.load(openfile)
        print(f"DEBUG: Прочитанный токен: {db.get('token', 'Токен не найден')}") # Добавлено отладочное сообщение для токена
        return db
def write_db(db):
    js = json.dumps(db, indent=2)
    with open('db.json', 'w') as outfile:
        outfile.write(js)

known_errs = {
    'A request to the Telegram API was unsuccessful. Error code: 400. Description: Bad Request: not enough rights to restrict/unrestrict chat member': 'Увы, но у бота не хватает прав для этого.'
}

# Инициализируем log_stream для логирования ошибок
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
    global users
    with open('users.json', 'r') as openfile:
        users = json.load(openfile)
def write_users():
    global users
    js = json.dumps(users, indent=2)
    with open('users.json', 'w') as outfile:
        outfile.write(js)

# LA - Low Admin.
# Admin permissions in bot without admin rights.
def read_la():
    with open('la.json', 'r') as openfile:
        la = json.load(openfile)
    return la
def write_la(la):
    js = json.dumps(la, indent=2)
    with open('la.json', 'w') as outfile:
        outfile.write(js)

####################           FAST HASH              #################
from xxhash import xxh32

# Generate fast hash
def sha(text):
    text = str(text)
    return xxh32(text).hexdigest()

##################FUNCTIONS########

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

# Fix for anon admins, all anon (not premium) users == admins
def is_anon(message):
    if message.from_user.username ==  'Channel_Bot' or message.from_user.username == 'GroupAnonymousBot':
        if message.from_user.is_premium == None:
            return True
    else:
        return False

# Return id from db/chat of user
def get_target(message):
    try:
        global users

        spl = message.text.split()
        if ( len(spl) > 1 and spl[1][0] == '@' ) or ( len(spl) > 2  and spl[2][0] == '@' ):
            for i in spl:
                if i[0] == '@':
                    username = i[1:]
                    break
            read_users()
            if sha(username) in users:
                return users[sha(username)]
            else:
                return None
        else:
            target = message.reply_to_message.from_user.id
            if target not in get_admins(message):
                return target
            else:
                return None
    except:
        return None

def get_name(message):
    try:
        text = message.text.split()
        # Проверяем, есть ли @username
        if len(text) > 1 and text[1].startswith('@'):
            username = text[1][1:]  # Убираем '@'
            # Проверяем, что username содержит только допустимые символы
            if re.match(r'^[a-zA-Z0-9_]+$', username):
                read_users()
                hashed_username = sha(username.lower())
                if hashed_username in users:
                    user_id = users[hashed_username]
                    return get_user_link_sync(user_id, message.chat.id)
                # Экранируем username для безопасного вывода
                username = username.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                return f"@{username}"
            else:
                return "пользователь"  # Некорректный username
        if len(text) > 2 and text[2].startswith('@'):
            username = text[2][1:]  # Убираем '@'
            # Проверяем, что username содержит только допустимые символы
            if re.match(r'^[a-zA-Z0-9_]+$', username):
                read_users()
                hashed_username = sha(username.lower())
                if hashed_username in users:
                    user_id = users[hashed_username]
                    return get_user_link_sync(user_id, message.chat.id)
                # Экранируем username для безопасного вывода
                username = username.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                return f"@{username}"
            else:
                return "пользователь"  # Некорректный username
        # Если это ответ на сообщение
        return telebot.util.user_link(message.reply_to_message.from_user)
    except Exception as e:
        catch_error(message, e)
        return "пользователь"

# Get time for '/mute'
# [time, time_in_sec, format]
def get_time(message):
    formats = {'s':[1, 'секунд(ы)'], 'm':[60, 'минут(ы)'], 'h': [3600,'час(а)'], 'd': [86400,'день/дня']}
    text = message.text.split()[1:] ; time = None

    # Find format in text
    for i in text:
        if time:
            break
        for f in list(formats.keys()):
            if f in i:
                try:
                    time = [i[:-1], int(i[:-1]) * formats[i[-1]][0] , formats[i[-1]][1] ]
                    break
                except:
                    pass

    return time

def have_rights(message, set_la = False):
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
        return False # Explicitly return False if no rights

def key_by_value(dictionary, key):
    for i in dictionary:
        if dictionary[i] == key:
            return i
    return None

def analytic(message):
    global users
    read_users()

    current_user_id = message.from_user.id
    current_username = message.from_user.username

    if current_username is None:
        return

    # Приводим юзернейм к нижнему регистру перед хешированием
    hashed_current_username = sha(current_username.lower())

    users[hashed_current_username] = current_user_id
    write_users()


def save_data(data, filename='warns.json'):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)

def load_data(filename='warns.json'):
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

user_warns = load_data('warns.json')

# Modified user_data structure: {chat_id: {user_id: {date: message_count}}}
# Добавлено поле 'last_activity' для хранения времени последней активности пользователя
# user_data = {chat_id: {user_id: {'stats': {date: message_count}, 'last_activity': timestamp}}}
user_data = load_data('user_data.json') #

# Новые функции для получения статистики конкретного пользователя
def get_user_daily_stats(chat_id, user_id):
    today = datetime.now().strftime('%Y-%m-%d')
    if str(chat_id) in user_data and str(user_id) in user_data[str(chat_id)] and 'stats' in user_data[str(chat_id)][str(user_id)]:
        return user_data[str(chat_id)][str(user_id)]['stats'].get(today, 0) #
    return 0 #

def get_user_weekly_stats(chat_id, user_id):
    week_ago = datetime.now() - timedelta(days=7)
    total_messages = 0
    if str(chat_id) in user_data and str(user_id) in user_data[str(chat_id)] and 'stats' in user_data[str(chat_id)][str(user_id)]:
        for date_str, count in user_data[str(chat_id)][str(user_id)]['stats'].items(): #
            date_obj = datetime.strptime(date_str, '%Y-%m-%d') #
            if date_obj >= week_ago: #
                total_messages += count #
    return total_messages #

def get_user_monthly_stats(chat_id, user_id):
    month_ago = datetime.now() - timedelta(days=30) # Приближенно 30 дней для месяца
    total_messages = 0
    if str(chat_id) in user_data and str(user_id) in user_data[str(chat_id)] and 'stats' in user_data[str(chat_id)][str(user_id)]:
        for date_str, count in user_data[str(chat_id)][str(user_id)]['stats'].items(): #
            date_obj = datetime.strptime(date_str, '%Y-%m-%d') #
            if date_obj >= month_ago: #
                total_messages += count #
    return total_messages #

def get_user_all_time_stats(chat_id, user_id):
    if str(chat_id) in user_data and str(user_id) in user_data[str(chat_id)] and 'stats' in user_data[str(chat_id)][str(user_id)]:
        return sum(user_data[str(chat_id)][str(user_id)]['stats'].values()) #
    return 0 #

def get_daily_stats(chat_id):
    today = datetime.now().strftime('%Y-%m-%d')
    daily_stats = {}
    if str(chat_id) in user_data:
        for user_id, user_info in user_data[str(chat_id)].items(): #
            if 'stats' in user_info and today in user_info['stats']: #
                daily_stats[user_id] = user_info['stats'][today] #
    return daily_stats

def get_weekly_stats(chat_id):
    week_ago = datetime.now() - timedelta(days=7)
    weekly_stats = {}
    if str(chat_id) in user_data:
        for user_id, user_info in user_data[str(chat_id)].items(): #
            total_messages = 0
            if 'stats' in user_info: #
                for date_str, count in user_info['stats'].items(): #
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d') #
                    if date_obj >= week_ago: #
                        total_messages += count #
            if total_messages > 0:
                weekly_stats[user_id] = total_messages
    return weekly_stats

def get_monthly_stats(chat_id):
    month_ago = datetime.now() - timedelta(days=30) # Приближенно 30 дней для месяца
    monthly_stats = {}
    if str(chat_id) in user_data:
        for user_id, user_info in user_data[str(chat_id)].items(): #
            total_messages = 0
            if 'stats' in user_info: #
                for date_str, count in user_info['stats'].items(): #
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d') #
                    if date_obj >= month_ago: #
                        total_messages += count #
            if total_messages > 0:
                monthly_stats[user_id] = total_messages
    return monthly_stats

def get_all_time_stats(chat_id):
    all_time_stats = {}
    if str(chat_id) in user_data:
        for user_id, user_info in user_data[str(chat_id)].items(): #
            total_messages = 0
            if 'stats' in user_info: #
                total_messages = sum(user_info['stats'].values()) #
            if total_messages > 0:
                all_time_stats[user_id] = total_messages
    return all_time_stats

def warn_user(message, user_id):
    if user_id not in user_warns:
        user_warns[user_id] = {'warn_count': 1, 'last_warn_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        bot.reply_to(message, f"{get_name(message)}, Ая-яй, вредим значит? Так нельзя. Пока что просто предупреждаю. Максимум 3 преда, потом - забаню.", parse_mode='HTML')
    else:
        user_warns[user_id]['warn_count'] += 1
        user_warns[user_id]['last_warn_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        bot.reply_to(message, f"{get_name(message)}, Ты опять вредишь? Напоминаю что максимум 3 преда, потом - забаню.", parse_mode='HTML')

    # Логика применения наказаний на основе warn_count
    if user_warns[user_id]['warn_count'] >= 3:
        bot.reply_to(message, "Я предупреждал...", parse_mode = 'HTML')
        target = get_target(message)
        if target:
            bot.ban_chat_member(message.chat.id, target)


    save_data(user_warns, 'warns.json')

def remove_warn(user_id):
    if user_id in user_warns:
        user_warns[user_id]['warn_count'] -= 1
        if user_warns[user_id]['warn_count'] <= 0:
            del user_warns[user_id]
        save_data(user_warns, 'warns.json')
        return True
    else:
        return False

#############TOKEN INIT#####

db = read_db()
read_users()
print('DEBUG: Инициализация бота...') # Добавлено отладочное сообщение
bot = telebot.TeleBot(db['token'])
print('DEBUG: Бот успешно инициализирован. Запуск polling...') # Добавлено отладочное сообщение

# Synchronous version of get_user_link
# It's better to use telebot.util.user_link directly if you have the User object
# Or if you need to fetch the user by ID, do it synchronously.
def get_user_link_sync(user_id, chat_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        first_name = member.user.first_name
        # Экранируем специальные HTML-символы для безопасности
        first_name = first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # Проверяем наличие юзернейма
        if member.user.username:
            # Формируем ссылку вида https://t.me/username с first_name в качестве текста
            return f'<a href="https://t.me/{member.user.username}">{first_name}</a>'
        else:
            # Если юзернейма нет, возвращаем просто first_name без ссылки
            return first_name
    except Exception as e:
        print(f"Error getting user link for ID {user_id} in chat {chat_id}: {e}")
        return f"Пользователь {user_id}"

# НОВАЯ ФУНКЦИЯ: Форматирование времени в "X минут/часов назад"
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
        elif delta.total_seconds() < 86400: # 24 часа
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


## Changed from @bot.message_handler(commands=['top_day'])
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


## Changed from @bot.message_handler(commands=['top_week'])
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

##

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, "Привет, я недо-ирис чат бот. Фанатский форк на Python. Данный бот не имеет ничего общего с командой разработчиков оригинального телеграмм бота Iris. Чтоб вызвать справку отправь .хелп")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    analytic(message)
    # Обновляем счетчик сообщений для пользователя в конкретном чате и время последней активности
    if message.text: # Считаем только текстовые сообщения для простоты
        chat_id = str(message.chat.id) #
        user_id = str(message.from_user.id) #
        date = datetime.now().strftime('%Y-%m-%d') #
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S') #

        if chat_id not in user_data: #
            user_data[chat_id] = {} #
        if user_id not in user_data[chat_id]: #
            user_data[chat_id][user_id] = {'stats': {}, 'last_activity': ''} #
        
        # Обновляем статистику сообщений
        if date not in user_data[chat_id][user_id]['stats']: #
            user_data[chat_id][user_id]['stats'][date] = 1 #
        else: #
            user_data[chat_id][user_id]['stats'][date] += 1 #
        
        # Обновляем время последней активности, исключая команду "КТО Я"
        if message.text.upper() != 'КТО Я': # НОВОЕ УСЛОВИЕ
            user_data[chat_id][user_id]['last_activity'] = current_time #

        save_data(user_data, 'user_data.json') #


    if message.text == 'bot?':
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        bot.reply_to(message, f'Hello. I see you, {username}')

    if message.text.upper() == 'ПИНГ':bot.reply_to(message, f'ПОНГ')

    if message.text.upper() == 'ПИУ':bot.reply_to(message, f'ПАУ')

    if message.text.upper() == 'КИНГ': bot.reply_to(message, f'КОНГ')

    if message.text.upper() == 'БОТ': bot.reply_to(message, f'✅ На месте')

    if message.text.upper().startswith("ЧТО С БОТОМ"): bot.reply_to(message, f'Да тут я.. отойти даже нельзя блин.. Я ТОЖЕ ИМЕЮ ПРАВО НА ОТДЫХ!')

    if message.text.upper() == 'КТО Я':
        user_id = str(message.from_user.id) #
        chat_id = str(message.chat.id) #
        username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;') #

        # Получаем статистику для текущего пользователя
        daily_count = get_user_daily_stats(chat_id, user_id) #
        weekly_count = get_user_weekly_stats(chat_id, user_id) #
        monthly_count = get_user_monthly_stats(chat_id, user_id) #
        all_time_count = get_user_all_time_stats(chat_id, user_id) #

        last_active_time = "Нет данных" #
        if chat_id in user_data and user_id in user_data[chat_id] and 'last_activity' in user_data[chat_id][user_id]: #
            last_active_time = format_time_ago(user_data[chat_id][user_id]['last_activity']) # Используем новую функцию
            
        # Формируем ответ
        reply_text = ( #
            f"Ты <b>{username}</b>\n\n" #
            f"Последний твой актив:\n{last_active_time}\n" #
            f"Краткая стата (д|н|м|вся):\n{daily_count}|{weekly_count}|{monthly_count}|{all_time_count}" #
        ) #
        bot.reply_to(message, reply_text, parse_mode='HTML') #

    if message.text.upper().startswith('КТО ТЫ'):
        try:
            target_user_id = None
            target_user_name = None

            if message.reply_to_message:
                target_user_id = str(message.reply_to_message.from_user.id)
                target_user_name = telebot.util.user_link(message.reply_to_message.from_user)
            else:
                spl = message.text.split()
                if len(spl) > 2 and spl[2][0] == '@': # Ожидаем "КТО ТЫ @username"
                    username_from_command = spl[2][1:] # Убираем '@'
                    # Приводим юзернейм из команды к нижнему регистру перед хешированием
                    hashed_username = sha(username_from_command.lower())
                    read_users()
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
                elif len(spl) > 1 and spl[1][0] == '@': # Ожидаем "КТО @username" (для гибкости)
                    username_from_command = spl[1][1:] # Убираем '@'
                    # Приводим юзернейм из команды к нижнему регистру перед хешированием
                    hashed_username = sha(username_from_command.lower())
                    read_users()
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

                # Получаем статистику для целевого пользователя
                daily_count = get_user_daily_stats(chat_id, target_user_id)
                weekly_count = get_user_weekly_stats(chat_id, target_user_id)
                monthly_count = get_user_monthly_stats(chat_id, target_user_id)
                all_time_count = get_user_all_time_stats(chat_id, target_user_id)

                last_active_time = "Нет данных"
                if chat_id in user_data and target_user_id in user_data[chat_id] and 'last_activity' in user_data[chat_id][target_user_id]:
                    last_active_time = format_time_ago(user_data[chat_id][target_user_id]['last_activity']) # Используем новую функцию

                reply_text = (
                    f"Это <b>{target_user_name}</b>\n\n"
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
            min = ""
            max = ""
            for item in msg:
                if item != " ":
                    min += item
                else:
                    break
            max = msg.replace(f"{min} ", "")
            max, min = int(max), int(min)
            try:
                if max < min:
                    bot.reply_to(message, f"Цифарки местами поменяй, олух")
                if max == min:
                    bot.reply_to(message, f"Да ты гений я смотрю, умом берёшь.")
                else:
                    result = random.randint(min, max)
                    bot.reply_to(message, f"Случайное число из диапазона [{min}..{max}] выпало на {result}")
            except:
                return 0
        except:
            return 0

    if message.text.upper() == 'ВАРН':
        try:
            if have_rights(message):
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
                if message.reply_to_message:
                    user_id = message.reply_to_message.from_user.id
                    if remove_warn(user_id):
                        bot.reply_to(message, f"Ладно, {get_name(message)}, прощаю последний твой косяк.", parse_mode = 'HTML')
                    else:
                        bot.reply_to(message, "Этот человек очень даже хороший в моём видении.")
                else:
                    bot.reply_to(message, "Команда должна быть ответом на сообщение пользователя.")
        except:
            return 0

    if message.text.upper().startswith('МУТ'):
        try:
            if have_rights(message):
                target = get_target(message)
                time = get_time(message)
                if target:
                    if time:
                        bot.restrict_chat_member(message.chat.id, target, until_date = message.date + time[1])
                        answer = f'Я заклеил ему рот на {time[0]} {time[2]}. Маловато как по мне, ну ладно.'
                    else:
                        bot.restrict_chat_member(message.chat.id, target, until_date = message.date)
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
                target = get_target(message)
                if target:
                    bot.restrict_chat_member(message.chat.id, target, can_send_messages=True
                    , can_send_other_messages = True, can_send_polls = True
                    , can_add_web_page_previews = True, until_date = message.date)
                    bot.reply_to(message, f'''Ладно, так и быть, пусть он говорит.
    ''', parse_mode='HTML')
                else:
                    catch_error(message, None, 'no_user')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "КИК":
        try:
            if have_rights(message):
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
                bot.set_chat_permissions(message.chat.id, telebot.types.ChatPermissions(can_send_messages=False, can_send_other_messages = False, can_send_polls = False))
                bot.reply_to(message, 'Крч вы достали админов господа.. и меня тоже. Закрываем чат..)')
            else:
                bot.reply_to(message, f'А, ещё.. <tg-spoiler>ПОПЛАЧ)))))</tg-spoiler>', parse_mode='HTML')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '+ЧАТ':
        try:
            if have_rights(message):
                bot.set_chat_permissions(message.chat.id, telebot.types.ChatPermissions(can_send_messages=True, can_send_other_messages = True, can_send_polls = True))
                bot.reply_to(message, 'Ладно, мне надоела тишина. Открываю чат..')
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == "ПИН" or message.text.upper() == "ЗАКРЕП":
        try:
            if have_rights(message):
                bot.pin_chat_message(message.chat.id, message.reply_to_message.id)
                bot.reply_to(message, "Видимо это что то важное.. кхм... Закрепил!")
        except:
            return 0

    if message.text.upper() == "АНПИН":
        try:
            if have_rights(message):
                bot.unpin_chat_message(message.chat.id, message.reply_to_message.id)
                bot.reply_to(message, "Больше не важное, лол.. кхм... Открепил!")
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == '+АДМИН':
        try:
            if have_rights(message):
                user_id = message.reply_to_message.from_user.id
                chat_id = message.chat.id
                bot.promote_chat_member(chat_id, user_id, can_manage_chat=True, can_change_info=True, can_delete_messages=True, can_restrict_members=True, can_invite_users=True, can_pin_messages=True, can_manage_video_chats=True, can_manage_voice_chats=True, can_post_stories=True, can_edit_stories=True, can_delete_stories=True)
                bot.reply_to(message, "Теперь у этого человечка есть власть над чатом!! Бойтесь.")
        except:
            return 0

    if message.text.upper() == '-АДМИН':
        try:
            if have_rights(message):
                user_id = message.reply_to_message.from_user.id
                chat_id = message.chat.id
                bot.promote_chat_member(chat_id, user_id, can_manage_chat=False, can_change_info=False, can_delete_messages=False, can_restrict_members=False, can_invite_users=False, can_pin_messages=False, can_manage_video_chats=False, can_manage_voice_chats=False, can_post_stories=False, can_edit_stories=False, can_delete_stories=False)
                bot.reply_to(message, "Лох понижен в должности. Теперь его можно не бояться")
        except:
            return 0

    if message.text.upper() == "-СМС":
        try:
            if have_rights(message):
                bot.delete_message(message.chat.id, message.reply_to_message.id)
                bot.delete_message(message.chat.id, message.id)
        except Exception as e:
            catch_error(message, e)

    if message.text.upper() == ".ХЕЛП":
        bot.reply_to(message, '''Помощь по командам:

<blockquote expandable><b>Основные команды бота</b>
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
Сожрать
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
Цыц!</blockquote>''', parse_mode='HTML')

##############       RP COMMANDS        #################

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

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЦЫЦ!\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'Уууу.. {username} закрыл ротик {get_name(message)} и привязал к кроватке. Знаешь.. я не думаю что тебе что то хорошее светит.. а хотя может.. хз крч.'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

    if message.text: # Убедимся, что сообщение не пустое
        match = re.match(r'\bЦЫЦ\b\s*(.*)', message.text, re.IGNORECASE)
        if match:
            username = message.from_user.first_name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Извлекаем фразу, которая теперь будет в оригинальном регистре
            user_phrase = match.group(1).strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Формируем ответ
            response_text = f'{username} заткнул {get_name(message)} используя кляп и кинул в подвал. А нехер выделываться было.'
            if user_phrase: # Добавляем фразу, только если она есть
                response_text += f'\nСо словами: {user_phrase}'
            try:
                bot.reply_to(message, response_text, parse_mode='HTML')
            except Exception as e:
                catch_error(message, e)

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

bot.polling(none_stop=True)