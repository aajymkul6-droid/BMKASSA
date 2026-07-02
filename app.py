import os
import sqlite3
import time
import threading
from datetime import datetime
from flask import Flask
import telebot
from telebot import types

# 1. ЗАЩИТА ОТ ПУСТОГО ТОКЕНА
TOKEN = os.environ.get("TOKEN_REF")

if not TOKEN:
    print("\n" + "="*50)
    print("❌ КРИТИЧЕСКАЯ ОШИБКА: Переменная 'TOKEN_REF' не найдена!")
    print("Пожалуйста, проверьте вкладку Environment на Render.")
    print("Ключ должен называться строго: TOKEN_REF")
    print("="*50 + "\n")
    # Временная заглушка для логов
    TOKEN = "123456789:AAA_PlaceholderTokenForRenderLogs"

# 2. НАСТРОЙКА ГЛАВНОГО АДМИНИСТРАТОРА
# Замени 8763658506 на свой реальный ID, если не используешь переменные окружения!
MAIN_ADMIN = int(os.environ.get("MAIN_ADMIN", 8349263362))

SUPPORT = "@KONS_TZ"
CHANNEL_ID = "@BMKASSA24"
BOT_USERNAME = "KGBMkasa_bot"

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
bot_active = True
temp_data = {}
payment_timers = {}

def init_db():
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY, 
                    join_date TEXT, 
                    referrer_id INTEGER, 
                    balance REAL DEFAULT 0.0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (chat_id INTEGER PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS deposits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id INTEGER, 
                    amount REAL, 
                    account_id TEXT, 
                    photo_id TEXT, 
                    status TEXT, 
                    date TEXT, 
                    timestamp INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS qr_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, 
                    user_id INTEGER, 
                    elqr_photo TEXT, 
                    id_photo TEXT, 
                    sms_code TEXT, 
                    status TEXT, 
                    date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS ref_withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount REAL,
                    target_id TEXT,
                    status TEXT,
                    date TEXT)''')
    
    # Всегда принудительно добавляем актуальный MAIN_ADMIN в базу данных
    c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (MAIN_ADMIN,))
    conn.commit()
    conn.close()

def get_admins():
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT chat_id FROM admins')
    admins = [row[0] for row in c.fetchall()]
    conn.close()
    
    # Железная гарантия, что главный админ всегда в списке и кнопка сработает
    if MAIN_ADMIN not in admins:
        admins.append(MAIN_ADMIN)
        
    return admins

def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_ID, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except:
        return True

def add_user(chat_id, referrer_id=None):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT chat_id FROM users WHERE chat_id = ?', (chat_id,))
    user_exists = c.fetchone()
    if not user_exists:
        c.execute('INSERT OR IGNORE INTO users (chat_id, join_date, referrer_id) VALUES (?, ?, ?)', 
                  (chat_id, datetime.now().strftime("%d.%m.%Y %H:%M"), referrer_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_user_data(chat_id):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT referrer_id, balance FROM users WHERE chat_id = ?', (chat_id,))
    row = c.fetchone()
    conn.close()
    return row if row else (None, 0.0)

def get_referrals_count(user_id):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users WHERE referrer_id = ?', (user_id,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_all_users():
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT chat_id FROM users')
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def add_admin(chat_id):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (chat_id,))
    conn.commit()
    conn.close()

def add_deposit(user_id, amount, account_id, photo_id):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    now = datetime.now()
    current_ts = int(time.time())
    c.execute('INSERT INTO deposits (user_id, amount, account_id, photo_id, status, date, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)',
              (user_id, amount, account_id, photo_id, 'pending', now.strftime("%d.%m.%Y %H:%M:%S"), current_ts))
    dep_id = c.lastrowid
    conn.commit()
    conn.close()
    return dep_id

# 3. НАЧИСЛЕНИЕ РЕФЕРАЛЬНЫХ 5% ПРИ ОДОБРЕНИИ СЧЕТА
def update_deposit_status(dep_id, status):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('UPDATE deposits SET status = ? WHERE id = ?', (status, dep_id))
    if status == "approved":
        c.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (dep_id,))
        dep = c.fetchone()
        if dep:
            u_id, amount = dep
            c.execute('SELECT referrer_id FROM users WHERE chat_id = ?', (u_id,))
            ref = c.fetchone()
            if ref and ref[0]:
                # Изменено с 0.03 на 0.05 (5%)
                bonus = amount * 0.05
                c.execute('UPDATE users SET balance = balance + ? WHERE chat_id = ?', (bonus, ref[0]))
                try:
                    bot.send_message(ref[0], f"<b>💰 Вам начислено реферальное вознаграждение {bonus:.2f} сом!</b>", parse_mode='HTML')
                except:
                    pass
    conn.commit()
    conn.close()

def add_withdrawal(user_id, elqr, id_photo, code):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('INSERT INTO withdrawals (user_id, elqr_photo, id_photo, sms_code, status, date) VALUES (?, ?, ?, ?, ?, ?)',
              (user_id, elqr, id_photo, code, 'pending', datetime.now().strftime("%d.%m.%Y %H:%M")))
    w_id = c.lastrowid
    conn.commit()
    conn.close()
    return w_id

def add_ref_withdrawal(user_id, amount, target_id):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('INSERT INTO ref_withdrawals (user_id, amount, target_id, status, date) VALUES (?, ?, ?, ?, ?)',
              (user_id, amount, target_id, 'pending', datetime.now().strftime("%d.%m.%Y %H:%M")))
    rw_id = c.lastrowid
    conn.commit()
    conn.close()
    return rw_id

def get_pending_deposits():
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT id, user_id, amount, account_id, photo_id, date, timestamp FROM deposits WHERE status = "pending"')
    rows = c.fetchall()
    conn.close()
    return rows

def save_qr(file_id):
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('INSERT INTO qr_codes (file_id, date) VALUES (?, ?)', (file_id, datetime.now().strftime("%d.%m.%Y %H:%M")))
    conn.commit()
    conn.close()

def get_last_qr():
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_stats():
    conn = sqlite3.connect('kgbmkasa_main.db')
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM users')
    users = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM deposits WHERE status="pending"')
    pending = c.fetchone()[0]
    c.execute('SELECT SUM(amount) FROM deposits WHERE status="approved"')
    total = c.fetchone()[0] or 0
    conn.close()
    return {'users': users, 'pending': pending, 'total': total}

init_db()

def cancel_payment(user_id):
    if user_id in temp_data:
        del temp_data[user_id]
        try:
            bot.send_message(user_id, "⏰ <b>ВРЕМЯ ОПЛАТЫ ИСТЕКЛО!</b>\n\nЗаявка отменена.", parse_mode='HTML')
        except:
            pass

def subscription_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔗 Подписаться", url="https://t.me/BMKASSA24"),
        types.InlineKeyboardButton("✅ Проверить", callback_data="check_sub")
    )
    return markup

def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("🌲 Пополнить", "🔻 Вывести")
    markup.add("👥 Рефералы", "👨‍💻 Поддержка")
    if user_id in get_admins():
        markup.add("⚙️ Админ")
    return markup

def admin_menu():
    global bot_active
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📋 Заявки", "📊 Статистика")
    markup.add("🖼 Изменить QR", "➕ Админ")
    markup.add("📢 Рассылка")
    status_btn = "🔴 ВЫКЛ" if bot_active else "🟢 ВКЛ"
    markup.add(status_btn)
    markup.add("🔙 Главное меню")
    return markup

def back_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Назад")
    return markup

@bot.message_handler(commands=['start'])
def start(msg):
    args = msg.text.split()
    referrer_id = None
    if len(args) > 1 and args[1].isdigit():
        ref_potential = int(args[1])
        if ref_potential != msg.chat.id:
            referrer_id = ref_potential

    is_new = add_user(msg.chat.id, referrer_id)
    if is_new and referrer_id:
        try:
            ref_username = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.first_name
            bot.send_message(referrer_id, f"<b>➕ У вас новый реферал:</b> {ref_username}", parse_mode='HTML')
        except:
            pass

    if not check_subscription(msg.chat.id):
        bot.send_message(msg.chat.id, "<b>Для доступа к боту нужно подписаться на канал:</b>", parse_mode='HTML', reply_markup=subscription_markup())
        return

    welcome_text = f"""🚀 <b>Добро пожаловать в BMKASSA</b>

🌀 Пополнения и Выводы
🟠 Без процентов

⚡️ Быстрая скорость обработка заявок

❓ Помощь: {SUPPORT}"""

    bot.send_message(msg.chat.id, welcome_text, parse_mode='HTML', reply_markup=main_menu(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "🔙 Назад")
def back_to_main(msg):
    start(msg)

@bot.message_handler(func=lambda m: m.text == "👨‍💻 Поддержка")
def support(msg):
    if not check_subscription(msg.chat.id): return
    bot.send_message(msg.chat.id, f"<b>❓ Помощь:</b> {SUPPORT}", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "🔙 Главное меню")
def back(msg):
    start(msg)

# 4. ОБНОВЛЕННОЕ ОПИСАНИЕ РЕФЕРАЛОВ ДО 5%
@bot.message_handler(func=lambda m: m.text == "👥 Рефералы")
def referrals_menu(msg):
    if not check_subscription(msg.chat.id): return
    _, balance = get_user_data(msg.chat.id)
    ref_count = get_referrals_count(msg.chat.id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start={msg.chat.id}"
    
    text = f"""🔥 <b>Реферальная Система</b>

Приглашай друзей и получай стабильный доход!
За каждое пополнение друга ты получаешь <b>5%</b>.

🎯 <b>Твоя ссылка для приглашений:</b>
<code>{ref_link}</code>

👥 <b>Приглашено друзей:</b> {ref_count} чел.
💰 <b>Баланс для вывода:</b> {balance:.2f} сом"""
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Вывести средства", callback_data="withdraw_referral"),
        types.InlineKeyboardButton("Главное меню", callback_data="go_to_main")
    )
    bot.send_message(msg.chat.id, text, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)

@bot.message_handler(func=lambda m: m.text == "⚙️ Админ" and m.from_user.id in get_admins())
def admin_panel(msg):
    bot.send_message(msg.chat.id, "⚙️ Админ панель", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "➕ Админ" and m.from_user.id in get_admins())
def add_admin_btn(msg):
    bot.send_message(msg.chat.id, "👤 Введите ID:")
    bot.register_next_step_handler(msg, process_add_admin)

def process_add_admin(msg):
    try:
        add_admin(int(msg.text))
        bot.send_message(msg.chat.id, "✅ Админ добавлен!", reply_markup=admin_menu())
    except:
        bot.send_message(msg.chat.id, "❌ Ошибка!")

@bot.message_handler(func=lambda m: m.text in ["🔴 ВЫКЛ", "🟢 ВКЛ"] and m.from_user.id in get_admins())
def toggle_bot(msg):
    global bot_active
    bot_active = (msg.text == "🟢 ВКЛ")
    bot.send_message(msg.chat.id, f"{'🟢 Бот ВКЛЮЧЕН' if bot_active else '🔴 Бот ВЫКЛЮЧЕН'}", reply_markup=admin_menu())

@bot.message_handler(func=lambda m: m.text == "🖼 Изменить QR" and m.from_user.id in get_admins())
def change_qr(msg):
    bot.send_message(msg.chat.id, "🖼 Отправьте новый QR-код (фото):", reply_markup=back_menu())
    bot.register_next_step_handler(msg, save_new_qr)

def save_new_qr(msg):
    if msg.text == "🔙 Назад":
        admin_panel(msg)
        return
    if msg.photo:
        file_id = msg.photo[-1].file_id
        save_qr(file_id)
        bot.send_message(msg.chat.id, "✅ QR-код успешно сохранен!", reply_markup=admin_menu())
    else:
        bot.send_message(msg.chat.id, "❌ Отправьте фото QR-кода!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, save_new_qr)

@bot.message_handler(func=lambda m: m.text == "🌲 Пополнить")
def deposit(msg):
    if not check_subscription(msg.chat.id): return
    bot.send_message(msg.chat.id, "<b>🆔 Введите ID счета 1xBet:</b>", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_account_id)

def get_account_id(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    temp_data[msg.chat.id] = {"account_id": msg.text}
    bot.send_message(msg.chat.id, "<b>💰 Введите сумму (сом):</b>", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, get_amount)

def get_amount(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    try:
        amount = float(msg.text.replace(',', '.'))
    except:
        bot.send_message(msg.chat.id, "❌ Введите число!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return
        
    if amount < 50 or amount > 100000:
        bot.send_message(msg.chat.id, "❌ Сумма от 50 до 100 000 сом!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_amount)
        return
    
    user_id = msg.chat.id
    user_1xbet_id = temp_data.get(user_id, {}).get("account_id", "Не указан")
    temp_data[user_id]["amount"] = amount
    
    qr_file_id = get_last_qr()
    if qr_file_id:
        try:
            bot.send_photo(msg.chat.id, qr_file_id, caption=f"📱 <b>ОПЛАТИТЕ {amount:,.2f} сом</b>\n⏳ 5 минут на оплату", parse_mode='HTML')
        except:
            bot.send_message(msg.chat.id, "❌ Ошибка отправки QR-кода")
    else:
        bot.send_message(msg.chat.id, "📱 QR-код временно отсутствует.")
    
    text = f"""📎 <b>Прикрепите скриншот чека</b>

━━━━━━━━━━━━━━━━━━━━━

🆔 <b>Аккаунт ID:</b> <code>{user_1xbet_id}</code>
💰 <b>Сумма:</b> {amount:,.2f} сом ✅

━━━━━━━━━━━━━━━━━━━━━

⚠️ <b>Оплатите и отправьте скриншот чека в течение 5 минут!</b>"""
    
    bot.send_message(msg.chat.id, text, parse_mode='HTML', reply_markup=back_menu())
    
    timer = threading.Timer(300, cancel_payment, args=[user_id])
    payment_timers[user_id] = timer
    timer.start()
    
    bot.register_next_step_handler(msg, get_check_photo)

def get_check_photo(msg):
    if msg.text == "🔙 Назад":
        if msg.chat.id in payment_timers:
            payment_timers[msg.chat.id].cancel()
        start(msg)
        return
    if not msg.photo:
        bot.send_message(msg.chat.id, "❌ Отправьте фото чека!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, get_check_photo)
        return
    
    user_id = msg.chat.id
    if user_id in payment_timers:
        payment_timers[user_id].cancel()
    
    account_id = temp_data[user_id].get("account_id")
    amount = temp_data[user_id].get("amount")
    photo_id = msg.photo[-1].file_id
    
    if not account_id or not amount:
        bot.send_message(msg.chat.id, "❌ Ошибка! Начните заново.")
        start(msg)
        return
    
    dep_id = add_deposit(user_id, amount, account_id, photo_id)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{dep_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{dep_id}")
    )
    
    for admin in admins:
        try:
            bot.send_photo(admin, photo_id, 
                caption=f"🆕 ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id}\n👤 {user_id}\n💰 {amount:,.2f} сом\n🆔 {account_id}",
                reply_markup=markup)
        except:
            pass
    
    bot.send_message(msg.chat.id, 
        f"✅ <b>ЗАЯВКА ПРИНЯТА!</b>\n\n🆔 ID: {account_id}\n💰 СУММА: {amount:,.2f} сом\n\n⏳ ОЖИДАЙТЕ ОБРАБОТКИ ОПЕРАТОРОМ...", 
        parse_mode='HTML', reply_markup=main_menu(user_id))
    
    del temp_data[user_id]

@bot.message_handler(func=lambda m: m.text == "🔻 Вывести")
def withdraw_start(msg):
    if not check_subscription(msg.chat.id): return
    
    instruction = """📌 <b>Как вывести средства с 1ХБЕТ</b>

1️⃣ Зайдите в раздел “Настройки”
2️⃣ Выберите способ вывода — “MOBCASH”
3️⃣ При заполнении данных укажите:

📍 Город: <b>Бишкек</b>
🚩 Улица: <b>BMkassa</b>

━━━━━━━━━━━━━━━━━━━━━

💳 <b>Шаг 1:</b> Прикрепите ваш <b>ELQR</b> (фотографией):"""
    
    bot.send_message(msg.chat.id, instruction, parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_elqr)

def withdraw_get_elqr(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.photo:
        bot.send_message(msg.chat.id, "❌ Отправьте ваш ELQR в виде фото!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_elqr)
        return
    
    temp_data[msg.chat.id] = {"elqr": msg.photo[-1].file_id}
    bot.send_message(msg.chat.id, "📸 <b>Шаг 2:</b> Отправьте фото (скриншот) вашего <b>ID 1xbet</b>:", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_id_photo)

def withdraw_get_id_photo(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.photo:
        bot.send_message(msg.chat.id, "❌ Отправьте скриншот ID 1xbet в виде фото!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_id_photo)
        return
    
    temp_data[msg.chat.id]["id_photo"] = msg.photo[-1].file_id
    bot.send_message(msg.chat.id, "✉️ <b>Шаг 3:</b> После оформления заявки на 1xBet пришлите полученный <b>код подтверждения</b> боту:", parse_mode='HTML', reply_markup=back_menu())
    bot.register_next_step_handler(msg, withdraw_get_code)

def withdraw_get_code(msg):
    if msg.text == "🔙 Назад":
        start(msg)
        return
    if not msg.text or msg.text.strip() == "":
        bot.send_message(msg.chat.id, "❌ Отправьте текстовый код!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, withdraw_get_code)
        return
    
    user_id = msg.chat.id
    elqr = temp_data[user_id].get("elqr")
    id_photo = temp_data[user_id].get("id_photo")
    code = msg.text
    
    w_id = add_withdrawal(user_id, elqr, id_photo, code)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Готово", callback_data=f"w_done_{w_id}"),
        types.InlineKeyboardButton("❌ Отказать", callback_data=f"w_cancel_{w_id}")
    )
    
    for admin in admins:
        try:
            bot.send_photo(admin, id_photo, caption=f"💸 ЗАЯВКА НА ВЫВОД #{w_id}\n👤 Юзер: {user_id}\n🔑 Код: <code>{code}</code>", parse_mode='HTML')
            bot.send_photo(admin, elqr, caption=f"💳 ELQR для выплаты по заявке #{w_id}", reply_markup=markup)
        except:
            pass
            
    bot.send_message(msg.chat.id, "✅ Ваша заявка на вывод принята оператором! Ожидайте выплаты.", reply_markup=main_menu(user_id))
    del temp_data[user_id]

def ref_withdraw_get_amount(msg):
    if msg.text == "🔙 Назад":
        referrals_menu(msg)
        return
    
    _, balance = get_user_data(msg.chat.id)
    try:
        amount = float(msg.text.replace(',', '.'))
    except ValueError:
        bot.send_message(msg.chat.id, "❌ Введите корректное число!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return
        
    if amount < 100:
        bot.send_message(msg.chat.id, "❌ Минимальный вывод: 100 сом!", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return
        
    if amount > balance:
        bot.send_message(msg.chat.id, f"❌ Недостаточно средств! Ваш баланс: {balance:.2f} сом", reply_markup=back_menu())
        bot.register_next_step_handler(msg, ref_withdraw_get_amount)
        return

    temp_data[msg.chat.id] = {"ref_amount": amount}
    bot.send_message(msg.chat.id, "🆔 Введите ваш <b>ID счета 1xBet</b> для зачисления реферальных средств:", parse_mode="HTML", reply_markup=back_menu())
    bot.register_next_step_handler(msg, ref_withdraw_get_id)

def ref_withdraw_get_id(msg):
    if msg.text == "🔙 Назад":
        referrals_menu(msg)
        return
        
    user_id = msg.chat.id
    target_id = msg.text
    amount = temp_data[user_id].get("ref_amount")
    
    if not amount:
        bot.send_message(msg.chat.id, "❌ Произошла ошибка. Попробуйте снова.")
        start(msg)
        return
        
    rw_id = add_ref_withdrawal(user_id, amount, target_id)
    
    admins = get_admins()
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Выплат. реф ID", callback_data=f"rw_approve_{rw_id}"),
        types.InlineKeyboardButton("❌ Отклонить реф", callback_data=f"rw_reject_{rw_id}")
    )
    
    for admin in admins:
        try:
            bot.send_message(admin, f"👥 <b>ЗАЯВКА НА ВЫВОД РЕФЕРАЛЬНЫХ #{rw_id}</b>\n\n👤 От: {user_id}\n💰 Сумма: {amount:,.2f} сом\n🎯 На ID 1xBet: <code>{target_id}</code>", parse_mode="HTML", reply_markup=markup)
        except:
            pass
            
    bot.send_message(user_id, f"✅ Заявка на вывод реферальных {amount:,.2f} сом на ID {target_id} успешно отправлена операторам!", reply_markup=main_menu(user_id))
    del temp_data[user_id]

@bot.message_handler(func=lambda m: m.text == "📋 Заявки" and m.from_user.id in get_admins())
def view_requests(msg):
    deposits = get_pending_deposits()
    if not deposits:
        bot.send_message(msg.chat.id, "📭 Нет активных заявок на пополнение")
        return
    for dep in deposits:
        dep_id, user_id, amount, account_id, photo_id, date, timestamp = dep
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{dep_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{dep_id}")
        )
        try:
            bot.send_photo(msg.chat.id, photo_id, 
                caption=f"🆕 ЗАЯВКА #{dep_id}\n👤 {user_id}\n💰 {amount:,.2f} сом\n🆔 {account_id}", reply_markup=markup)
        except:
            pass

@bot.message_handler(func=lambda m: m.text == "📊 Статистика" and m.from_user.id in get_admins())
def stats(msg):
    s = get_stats()
    bot.send_message(msg.chat.id, f"📊 СТАТИСТИКА\n\n👥 Пользователей: {s['users']}\n⏳ Заявок: {s['pending']}\n💰 Всего: {s['total']:.2f} сом")

@bot.message_handler(func=lambda m: m.text == "📢 Рассылка" and m.from_user.id in get_admins())
def broadcast_start(msg):
    bot.send_message(msg.chat.id, "📝 Отправьте сообщение для рассылки:")
    bot.register_next_step_handler(msg, broadcast_send)

def broadcast_send(msg):
    users = get_all_users()
    success = 0
    for user_id in users:
        try:
            bot.send_message(user_id, msg.text)
            success += 1
        except:
            pass
        time.sleep(0.05)
    bot.send_message(msg.chat.id, f"✅ Рассылка: {success}/{len(users)}", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: True)
def handle_call(call):
    if call.data == "check_sub":
        if check_subscription(call.message.chat.id):
            bot.answer_callback_query(call.id, "✅ Подписка подтверждена!")
            bot.delete_message(call.message.chat.id, call.message.message_id)
            start(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Вы все еще не подписались!", show_alert=True)
        return

    if call.data == "go_to_main":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        start(call.message)
        return

    if call.data == "withdraw_referral":
        _, balance = get_user_data(call.message.chat.id)
        if balance < 100:
            bot.answer_callback_query(call.id, "❌ Минимальный вывод реферальных средств — 100 сом!", show_alert=True)
        else:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_message(call.message.chat.id, f"💰 Введите сумму реферального вывода (доступно: {balance:.2f} сом):", reply_markup=back_menu())
            bot.register_next_step_handler(call.message, ref_withdraw_get_amount)
            bot.answer_callback_query(call.id)
        return

    admin_id = call.from_user.id
    if admin_id not in get_admins():
        bot.answer_callback_query(call.id, "❌ Нет прав!")
        return
    
    data = call.data
    
    if data.startswith('approve_'):
        dep_id = int(data.split('_')[1])
        conn = sqlite3.connect('kgbmkasa_main.db')
        c = conn.cursor()
        c.execute('SELECT user_id, amount, account_id, timestamp FROM deposits WHERE id = ?', (dep_id,))
        result = c.fetchone()
        conn.close()
        if result:
            user_id, amount, account_id, timestamp = result
            update_deposit_status(dep_id, "approved")
            bot.answer_callback_query(call.id, "✅ Одобрено!")
            
            elapsed_time = int(time.time()) - timestamp
            
            success_text = f"""✅ <b>Ваш баланс пополнен!</b>

💰 <b>Сумма:</b> {amount:,.2f} сом
<b>1xBet Счет:</b> {account_id}
⏱️ <b>Закрыта за:</b> {elapsed_time}s"""
            
            try:
                bot.send_message(user_id, success_text, parse_mode='HTML')
            except:
                pass
            bot.edit_message_text(f"✅ ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id} ОДОБРЕНА", call.message.chat.id, call.message.message_id)
    
    elif data.startswith('reject_'):
        dep_id = int(data.split('_')[1])
        conn = sqlite3.connect('kgbmkasa_main.db')
        c = conn.cursor()
        c.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (dep_id,))
        result = c.fetchone()
        conn.close()
        if result:
            user_id, amount = result
            update_deposit_status(dep_id, "rejected")
            bot.answer_callback_query(call.id, "❌ Отклонено!")
            try:
                bot.send_message(user_id, f"❌ ЗАЯВКА {amount:,.2f} сом ОТКЛОНЕНА!\n📞 Помощь: {SUPPORT}")
            except:
                pass
            bot.edit_message_text(f"❌ ЗАЯВКА НА ПОПОЛНЕНИЕ #{dep_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id)

    elif data.startswith('w_done_'):
        w_id = int(data.split('_')[2])
        conn = sqlite3.connect('kgbmkasa_main.db')
        c = conn.cursor()
        c.execute('UPDATE withdrawals SET status = "completed" WHERE id = ?', (w_id,))
        c.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,))
        u_id = c.fetchone()[0]
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Вывод выполнен")
        try:
            bot.send_message(u_id, f"✅ Ваша заявка на вывод #{w_id} успешно обработана! Средства отправлены.")
        except:
            pass
        bot.edit_message_caption(f"✅ ЗАЯВКА НА ВЫВОД #{w_id} ВЫПОЛНЕНА", call.message.chat.id, call.message.message_id)

    elif data.startswith('w_cancel_'):
        w_id = int(data.split('_')[2])
        conn = sqlite3.connect('kgbmkasa_main.db')
        c = conn.cursor()
        c.execute('UPDATE withdrawals SET status = "rejected" WHERE id = ?', (w_id,))
        c.execute('SELECT user_id FROM withdrawals WHERE id = ?', (w_id,))
        u_id = c.fetchone()[0]
        conn.commit()
        conn.close()
        bot.answer_callback_query(call.id, "❌ Отклонено")
        try:
            bot.send_message(u_id, f"❌ Ваша заявка на вывод #{w_id} отклонена оператором. Поддержка: {SUPPORT}")
        except:
            pass
        bot.edit_message_caption(f"❌ ЗАЯВКА НА ВЫВОД #{w_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id)

    elif data.startswith('rw_approve_'):
        rw_id = int(data.split('_')[2])
        conn = sqlite3.connect('kgbmkasa_main.db')
        c = conn.cursor()
        c.execute('SELECT user_id, amount, target_id, status FROM ref_withdrawals WHERE id = ?', (rw_id,))
        result = c.fetchone()
        if result and result[3] == 'pending':
            user_id, amount, target_id, _ = result
            c.execute('SELECT balance FROM users WHERE chat_id = ?', (user_id,))
            current_balance = c.fetchone()[0]
            if current_balance >= amount:
                c.execute('UPDATE ref_withdrawals SET status = "completed" WHERE id = ?', (rw_id,))
                c.execute('UPDATE users SET balance = balance - ? WHERE chat_id = ?', (amount, user_id))
                conn.commit()
                bot.answer_callback_query(call.id, "✅ Реф-вывод одобрен!")
                try:
                    bot.send_message(user_id, f"✅ Ваша заявка на вывод реферальных средств #{rw_id} одобрена!\n💰 {amount:,.2f} сом зачислены на ваш ID: {target_id}")
                except:
                    pass
                bot.edit_message_text(f"✅ РЕФ-ЗАЯВКА #{rw_id} ОДОБРЕНА И ВЫПЛАЧЕНА", call.message.chat.id, call.message.message_id)
        conn.close()

    elif data.startswith('rw_reject_'):
        rw_id = int(data.split('_')[2])
        conn = sqlite3.connect('kgbmkasa_main.db')
        c = conn.cursor()
        c.execute('SELECT user_id, amount FROM ref_withdrawals WHERE id = ?', (rw_id,))
        result = c.fetchone()
        if result:
            user_id, amount = result
            c.execute('UPDATE ref_withdrawals SET status = "rejected" WHERE id = ?', (rw_id,))
            conn.commit()
            bot.answer_callback_query(call.id, "❌ Реф-вывод отклонен")
            try:
                bot.send_message(user_id, f"❌ Ваша заявка на вывод реферальных средств в размере {amount:,.2f} сом была отклонена оператором.")
            except:
                pass
            bot.edit_message_text(f"❌ РЕФ-ЗАЯВКА #{rw_id} ОТКЛОНЕНА", call.message.chat.id, call.message.message_id)
        conn.close()

def run_bot():
    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=20)
        except:
            time.sleep(5)

threading.Thread(target=run_bot, daemon=True).start()

@app.route('/')
def home():
    return f"@{BOT_USERNAME} is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
