from aiogram import Bot, Dispatcher, types
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import sqlite3
import asyncio
from datetime import datetime, timedelta
import calendar
import os
import logging

# Налаштування логування
logging.basicConfig(level=logging.INFO)

# ВАЖЛИВО: Замініть на ваш справжній токен!
API_TOKEN = "ВАШ_СПРАВЖНІЙ_ТОКЕН_ТУТУТ"

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
scheduler = AsyncIOScheduler()

# --- Стани для FSM ---
class ReminderStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_time = State()
    waiting_for_days = State()
    editing_reminder = State()
    editing_text = State()
    editing_time = State()
    editing_days = State()

# --- База даних ---
def init_db():
    try:
        conn = sqlite3.connect("reminders.db")
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            text TEXT,
            hour INTEGER,
            minute INTEGER,
            days TEXT,
            one_time INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS schedule_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            photo_file_id TEXT,
            schedule_type TEXT,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
        conn.close()
        print("✅ База даних ініціалізована")
    except Exception as e:
        print(f"❌ Помилка ініціалізації БД: {e}")

# --- Допоміжні функції ---
def get_db_connection():
    return sqlite3.connect("reminders.db")

def schedule_reminder(reminder):
    try:
        reminder_id, chat_id, text, hour, minute, days, one_time = reminder[:7]
        
        if one_time == 1:
            # Для однократних нагадувань
            run_date = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_date <= datetime.now():
                run_date += timedelta(days=1)
            
            scheduler.add_job(
                send_reminder,
                trigger='date',
                run_date=run_date,
                args=[chat_id, text, reminder_id],
                id=f"reminder_{reminder_id}",
                replace_existing=True
            )
        else:
            # Для повторюваних нагадувань
            trigger = CronTrigger(hour=hour, minute=minute, day_of_week=days)
            scheduler.add_job(
                send_reminder,
                trigger=trigger,
                args=[chat_id, text, reminder_id],
                id=f"reminder_{reminder_id}",
                replace_existing=True
            )
        print(f"✅ Нагадування {reminder_id} заплановано")
    except Exception as e:
        print(f"❌ Помилка планування нагадування {reminder_id}: {e}")

async def send_reminder(chat_id, text, reminder_id):
    try:
        await bot.send_message(chat_id, f"🔔 Нагадування:\n{text}")
        
        # Якщо це однократне нагадування, видаляємо його з БД
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT one_time FROM reminders WHERE id=?", (reminder_id,))
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            cursor.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
            conn.commit()
        conn.close()
        print(f"✅ Нагадування {reminder_id} відправлено")
    except Exception as e:
        print(f"❌ Помилка надсилання нагадування: {e}")

def load_all_reminders():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders WHERE is_active=1")
        reminders = cursor.fetchall()
        conn.close()
        
        for rem in reminders:
            schedule_reminder(rem)
        print(f"✅ Завантажено {len(reminders)} нагадувань")
    except Exception as e:
        print(f"❌ Помилка завантаження нагадувань: {e}")

def get_days_emoji(days_str):
    days_map = {
        'mon': '🟢', 'tue': '🟡', 'wed': '🔵', 'thu': '🟠', 
        'fri': '🔴', 'sat': '🟣', 'sun': '⚪'
    }
    if not days_str:
        return ""
    
    days_list = [d.strip().lower() for d in days_str.split(',')]
    return ' '.join([days_map.get(day, '⚫') for day in days_list])

# --- Клавіатури ---
def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(KeyboardButton("➕ Додати"), KeyboardButton("📝 Мої нагадування"))
    keyboard.add(KeyboardButton("📅 Розклад"), KeyboardButton("📸 Фото розкладу"))
    keyboard.add(KeyboardButton("ℹ️ Допомога"))
    return keyboard

def get_schedule_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("📅 Сьогодні", callback_data="schedule_today"),
        InlineKeyboardButton("📆 Завтра", callback_data="schedule_tomorrow")
    )
    keyboard.add(
        InlineKeyboardButton("🗓️ Цей тиждень", callback_data="schedule_week"),
        InlineKeyboardButton("📊 Цей місяць", callback_data="schedule_month")
    )
    return keyboard

def get_days_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("Будні", callback_data="days_weekdays"),
        InlineKeyboardButton("Вихідні", callback_data="days_weekend")
    )
    keyboard.add(
        InlineKeyboardButton("Щодня", callback_data="days_daily"),
        InlineKeyboardButton("Вибрати дні", callback_data="days_custom")
    )
    return keyboard

def get_photo_type_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("📅 День", callback_data="photo_day"),
        InlineKeyboardButton("🗓️ Тиждень", callback_data="photo_week")
    )
    keyboard.add(
        InlineKeyboardButton("📊 Місяць", callback_data="photo_month"),
        InlineKeyboardButton("❌ Скасувати", callback_data="cancel")
    )
    return keyboard

# --- Обробники команд ---
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    await message.reply(
        "🤖 Привіт! Я твій персональний бот-нагадувач!\n\n"
        "Я можу:\n"
        "➕ Створювати нагадування\n"
        "✏️ Редагувати їх\n"
        "📅 Показувати розклад\n"
        "📸 Зберігати фото розкладу\n\n"
        "Використовуй кнопки нижче або команди:",
        reply_markup=get_main_keyboard()
    )

@dp.message_handler(text="ℹ️ Допомога")
@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    help_text = """
🤖 **Команди бота:**

**Основні:**
/start - Почати роботу
/help - Показати допомогу

**Нагадування:**
/add - Додати нагадування
/list - Показати всі нагадування
/edit - Редагувати нагадування
/delete - Видалити нагадування

**Розклад:**
/schedule - Показати розклад
/today - Нагадування на сьогодні
/week - Нагадування на тиждень

**Фото:**
/photos - Переглянути збережені фото
/add_photo - Додати фото розкладу

**Формат додавання нагадування:**
Натисни "➕ Додати" і слідуй інструкціям, або використовуй:
`/add 14:30 Зробити домашнє завдання Будні`
    """
    await message.reply(help_text, parse_mode='Markdown')

# --- Додавання нагадувань ---
@dp.message_handler(text="➕ Додати")
@dp.message_handler(commands=['add'])
async def add_reminder_start(message: types.Message, state: FSMContext):
    # Виправлення проблеми з get_args()
    if message.text.startswith('/add ') and len(message.text.split()) > 1:
        await add_reminder_quick(message)
        return
    
    await message.reply("📝 Введіть текст нагадування:")
    await ReminderStates.waiting_for_text.set()

async def add_reminder_quick(message: types.Message):
    """Швидке додавання через команду з аргументами"""
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            await message.reply("❌ Неправильний формат. Використовуйте:\n/add 14:30 Текст_нагадування Будні")
            return
        
        _, time_str, text, days_text = parts
        hour, minute = map(int, time_str.split(":"))
        
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            await message.reply("❌ Неправильний час. Використовуйте формат ГГ:ХХ")
            return
        
        days_map = {
            "Будні": "mon,tue,wed,thu,fri",
            "Вихідні": "sat,sun",
            "Щодня": "mon,tue,wed,thu,fri,sat,sun"
        }
        days = days_map.get(days_text, days_text.lower())
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (chat_id,text,hour,minute,days,one_time) VALUES (?,?,?,?,?,?)",
            (message.chat.id, text, hour, minute, days, 0)
        )
        conn.commit()
        reminder_id = cursor.lastrowid
        conn.close()
        
        schedule_reminder((reminder_id, message.chat.id, text, hour, minute, days, 0))
        
        await message.reply(
            f"✅ Нагадування додано!\n\n"
            f"📝 Текст: {text}\n"
            f"⏰ Час: {hour:02d}:{minute:02d}\n"
            f"📅 Дні: {days_text} {get_days_emoji(days)}"
        )
        
    except Exception as e:
        await message.reply(f"❌ Помилка додавання: {str(e)}")

@dp.message_handler(state=ReminderStates.waiting_for_text)
async def process_reminder_text(message: types.Message, state: FSMContext):
    await state.update_data(text=message.text)
    await message.reply("⏰ Введіть час у форматі ГГ:ХХ (наприклад, 14:30):")
    await ReminderStates.waiting_for_time.set()

@dp.message_handler(state=ReminderStates.waiting_for_time)
async def process_reminder_time(message: types.Message, state: FSMContext):
    try:
        hour, minute = map(int, message.text.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        
        await state.update_data(hour=hour, minute=minute)
        await message.reply("📅 Оберіть дні для нагадування:", reply_markup=get_days_keyboard())
        await ReminderStates.waiting_for_days.set()
    except:
        await message.reply("❌ Неправильний формат часу. Введіть у форматі ГГ:ХХ:")

@dp.callback_query_handler(lambda c: c.data.startswith('days_'), state=ReminderStates.waiting_for_days)
async def process_reminder_days(callback_query: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    days_map = {
        'days_weekdays': ('mon,tue,wed,thu,fri', 'Будні'),
        'days_weekend': ('sat,sun', 'Вихідні'),
        'days_daily': ('mon,tue,wed,thu,fri,sat,sun', 'Щодня')
    }
    
    if callback_query.data in days_map:
        days, days_text = days_map[callback_query.data]
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reminders (chat_id,text,hour,minute,days,one_time) VALUES (?,?,?,?,?,?)",
            (callback_query.from_user.id, data['text'], data['hour'], data['minute'], days, 0)
        )
        conn.commit()
        reminder_id = cursor.lastrowid
        conn.close()
        
        schedule_reminder((reminder_id, callback_query.from_user.id, data['text'], data['hour'], data['minute'], days, 0))
        
        await callback_query.message.edit_text(
            f"✅ Нагадування створено!\n\n"
            f"📝 Текст: {data['text']}\n"
            f"⏰ Час: {data['hour']:02d}:{data['minute']:02d}\n"
            f"📅 Дні: {days_text} {get_days_emoji(days)}"
        )
        
        await state.finish()
    
    await callback_query.answer()

# --- Перегляд нагадувань ---
@dp.message_handler(text="📝 Мої нагадування")
@dp.message_handler(commands=['list'])
async def list_reminders(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reminders WHERE chat_id=? AND is_active=1 ORDER BY hour, minute", (message.chat.id,))
    reminders = cursor.fetchall()
    conn.close()
    
    if not reminders:
        await message.reply("📭 У вас немає активних нагадувань.")
        return
    
    text = "📝 **Ваші нагадування:**\n\n"
    for r in reminders:
        days_emoji = get_days_emoji(r[5])
        text += f"🔹 **ID {r[0]}:** {r[2]}\n"
        text += f"⏰ {r[3]:02d}:{r[4]:02d} {days_emoji}\n"
        text += f"📅 {r[5]}\n\n"
    
    text += "Для редагування: /edit [ID]\nДля видалення: /delete [ID]"
    
    await message.reply(text, parse_mode='Markdown')

# --- Редагування нагадувань ---
@dp.message_handler(commands=['edit'])
async def edit_reminder_start(message: types.Message):
    try:
        # Виправлення для отримання аргументів
        args_text = message.text.replace('/edit', '').strip()
        if not args_text:
            await message.reply("❌ Вкажіть ID нагадування: /edit 123")
            return
        
        reminder_id = args_text
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminders WHERE id=? AND chat_id=? AND is_active=1", 
                      (reminder_id, message.chat.id))
        reminder = cursor.fetchone()
        conn.close()
        
        if not reminder:
            await message.reply("❌ Нагадування не знайдено.")
            return
        
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("📝 Текст", callback_data=f"edit_text_{reminder_id}"))
        keyboard.add(InlineKeyboardButton("⏰ Час", callback_data=f"edit_time_{reminder_id}"))
        keyboard.add(InlineKeyboardButton("📅 Дні", callback_data=f"edit_days_{reminder_id}"))
        keyboard.add(InlineKeyboardButton("❌ Скасувати", callback_data="cancel"))
        
        text = f"✏️ **Редагування нагадування ID {reminder_id}:**\n\n"
        text += f"📝 Текст: {reminder[2]}\n"
        text += f"⏰ Час: {reminder[3]:02d}:{reminder[4]:02d}\n"
        text += f"📅 Дні: {reminder[5]} {get_days_emoji(reminder[5])}\n\n"
        text += "Що хочете змінити?"
        
        await message.reply(text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        await message.reply(f"❌ Помилка: {str(e)}")

# --- Видалення нагадувань ---
@dp.message_handler(commands=['delete'])
async def delete_reminder(message: types.Message):
    try:
        args_text = message.text.replace('/delete', '').strip()
        if not args_text:
            await message.reply("❌ Вкажіть ID нагадування: /delete 123")
            return
        
        reminder_id = args_text
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reminders WHERE id=? AND chat_id=?", 
                      (reminder_id, message.chat.id))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            # Видаляємо з планувальника
            try:
                scheduler.remove_job(f"reminder_{reminder_id}")
            except:
                pass
            
            await message.reply(f"✅ Нагадування {reminder_id} видалено.")
        else:
            await message.reply("❌ Нагадування не знайдено.")
            
    except Exception as e:
        await message.reply(f"❌ Помилка видалення: {str(e)}")

# --- Розклад ---
@dp.message_handler(text="📅 Розклад")
@dp.message_handler(commands=['schedule'])
async def show_schedule_menu(message: types.Message):
    await message.reply("📅 Оберіть період для перегляду розкладу:", 
                       reply_markup=get_schedule_keyboard())

@dp.callback_query_handler(lambda c: c.data.startswith('schedule_'))
async def process_schedule_request(callback_query: types.CallbackQuery):
    period = callback_query.data.split('_')[1]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now = datetime.now()
    
    if period == 'today':
        day_name = calendar.day_name[now.weekday()].lower()[:3]
        cursor.execute("""
            SELECT * FROM reminders 
            WHERE chat_id=? AND is_active=1 AND (days LIKE ? OR days LIKE ?)
            ORDER BY hour, minute
        """, (callback_query.from_user.id, f'%{day_name}%', '%mon,tue,wed,thu,fri,sat,sun%'))
        title = f"📅 Розклад на сьогодні ({now.strftime('%d.%m.%Y')})"
        
    elif period == 'tomorrow':
        tomorrow = now + timedelta(days=1)
        day_name = calendar.day_name[tomorrow.weekday()].lower()[:3]
        cursor.execute("""
            SELECT * FROM reminders 
            WHERE chat_id=? AND is_active=1 AND (days LIKE ? OR days LIKE ?)
            ORDER BY hour, minute
        """, (callback_query.from_user.id, f'%{day_name}%', '%mon,tue,wed,thu,fri,sat,sun%'))
        title = f"📆 Розклад на завтра ({tomorrow.strftime('%d.%m.%Y')})"
        
    elif period == 'week':
        cursor.execute("""
            SELECT * FROM reminders 
            WHERE chat_id=? AND is_active=1
            ORDER BY hour, minute
        """, (callback_query.from_user.id,))
        title = "🗓️ Розклад на тиждень"
        
    elif period == 'month':
        cursor.execute("""
            SELECT * FROM reminders 
            WHERE chat_id=? AND is_active=1
            ORDER BY hour, minute
        """, (callback_query.from_user.id,))
        title = "📊 Розклад на місяць"
    
    reminders = cursor.fetchall()
    conn.close()
    
    if not reminders:
        await callback_query.message.edit_text(f"{title}\n\n📭 Немає запланованих нагадувань.")
        await callback_query.answer()
        return
    
    text = f"{title}\n\n"
    for r in reminders:
        days_emoji = get_days_emoji(r[5])
        text += f"⏰ {r[3]:02d}:{r[4]:02d} - {r[2]}\n"
        text += f"📅 {r[5]} {days_emoji}\n\n"
    
    await callback_query.message.edit_text(text)
    await callback_query.answer()

# --- Фото розкладу ---
@dp.message_handler(text="📸 Фото розкладу")
@dp.message_handler(commands=['add_photo'])
async def add_photo_start(message: types.Message):
    await message.reply("📸 Надішліть фото розкладу:", reply_markup=get_photo_type_keyboard())

@dp.message_handler(content_types=['photo'])
async def process_photo(message: types.Message):
    # Отримуємо найбільше фото
    photo = message.photo[-1]
    
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("📅 День", callback_data=f"save_photo_day_{photo.file_id}"),
        InlineKeyboardButton("🗓️ Тиждень", callback_data=f"save_photo_week_{photo.file_id}")
    )
    keyboard.add(
        InlineKeyboardButton("📊 Місяць", callback_data=f"save_photo_month_{photo.file_id}"),
        InlineKeyboardButton("❌ Скасувати", callback_data="cancel")
    )
    
    await message.reply("📸 Фото отримано! Для якого періоду це розклад?", 
                       reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('save_photo_'))
async def save_photo(callback_query: types.CallbackQuery):
    parts = callback_query.data.split('_')
    schedule_type = parts[2]
    file_id = '_'.join(parts[3:])  # Виправлення для file_id з підкресленнями
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO schedule_photos (chat_id, photo_file_id, schedule_type, description)
        VALUES (?, ?, ?, ?)
    """, (callback_query.from_user.id, file_id, schedule_type, f"Розклад ({schedule_type})"))
    conn.commit()
    conn.close()
    
    type_names = {'day': 'день', 'week': 'тиждень', 'month': 'місяць'}
    
    await callback_query.message.edit_text(
        f"✅ Фото розкладу на {type_names[schedule_type]} збережено!\n\n"
        f"Переглянути: /photos"
    )
    await callback_query.answer()

@dp.message_handler(commands=['photos'])
async def show_photos(message: types.Message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM schedule_photos 
        WHERE chat_id=? 
        ORDER BY created_at DESC 
        LIMIT 10
    """, (message.chat.id,))
    photos = cursor.fetchall()
    conn.close()
    
    if not photos:
        await message.reply("📭 У вас немає збережених фото розкладу.")
        return
    
    await message.reply(f"📸 Ваші збережені фото розкладу ({len(photos)}):")
    
    for photo in photos:
        caption = f"📅 {photo[4]} (ID: {photo[0]})\n📆 {photo[6]}"
        try:
            await bot.send_photo(message.chat.id, photo[2], caption=caption)
        except Exception as e:
            await message.reply(f"❌ Помилка відправки фото ID {photo[0]}: {str(e)}")

# --- Скасування операцій ---
@dp.callback_query_handler(lambda c: c.data == 'cancel', state='*')
async def cancel_operation(callback_query: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await callback_query.message.edit_text("❌ Операцію скасовано.")
    await callback_query.answer()

# Обробка невідомих повідомлень
@dp.message_handler(state='*')
async def unknown_message(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.reply(
            "🤔 Я не розумію цю команду.\n"
            "Використовуйте кнопки меню або /help для допомоги.",
            reply_markup=get_main_keyboard()
        )

# Запуск бота
async def on_startup(dp):
    print("🤖 Бот запускається...")
    try:
        init_db()
        scheduler.start()
        load_all_reminders()
        print("✅ Бот успішно запущено!")
    except Exception as e:
        print(f"❌ Помилка запуску: {e}")

async def on_shutdown(dp):
    print("🔄 Зупинка бота...")
    scheduler.shutdown()
    print("✅ Бот зупинено")

if __name__ == "__main__":
    try:
        executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
    except Exception as e:
        print(f"❌ Критична помилка: {e}")
