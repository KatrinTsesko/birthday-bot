import os
import json
import csv
import logging
import requests
from datetime import datetime, time
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# -------------------- НАСТРОЙКА -------------------- #
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

HOLIDAYS = {"01.01", "23.02", "08.03", "01.05", "09.05", "12.06", "04.11"}

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
TZ = os.getenv("TZ", "Europe/Moscow")
RAILWAY_URL = os.getenv("RAILWAY_URL")
PORT = int(os.environ.get("PORT", 8443))

BIRTHDAYS_FILE = "birthdays.json"


# -------------------- ФУНКЦИИ -------------------- #
def load_birthdays():
    try:
        with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_birthdays(birthdays):
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(birthdays, f, ensure_ascii=False, indent=2)
    sync_to_csv(birthdays)

def sync_to_csv(birthdays):
    try:
        with open("import_birthdays.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["Имя", "Дата"])
            writer.writeheader()
            for name, date in birthdays.items():
                writer.writerow({"Имя": name, "Дата": date})
    except Exception as e:
        print(f"Ошибка синхронизации CSV: {e}")


# -------------------- ОБРАБОТЧИКИ -------------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить", callback_data='add')],
        [InlineKeyboardButton("📋 Список", callback_data='list')],
        [InlineKeyboardButton("📥 Импорт CSV", callback_data='import')],
        [InlineKeyboardButton("🆔 Получить ID", callback_data='getid')],
        [InlineKeyboardButton("🔍 Проверка", callback_data='check')],
        [InlineKeyboardButton("💾 Синхронизация", callback_data='sync')],
        [InlineKeyboardButton("❓ Помощь", callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🎂 Company Birthday Bot\nВыберите команду ниже:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    birthdays = context.bot_data.get("birthdays", {})
    cmd_map = {
        'add': lambda u, c: query.edit_message_text("Используйте: /add Имя день.месяц\nПример: /add Иван 15.05"),
        'list': list_birthdays,
        'import': import_birthdays,
        'getid': get_chat_id,
        'check': force_check,
        'sync': sync_files,
        'help': start
    }
    handler = cmd_map.get(query.data)
    if handler:
        await handler(update, context)
    else:
        await query.edit_message_text("Неизвестная команда!")

async def add_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    birthdays = context.bot_data.get("birthdays", {})
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Используйте: /add Имя день.месяц\nПример: /add Иван 15.05")
        return
    try:
        name = ' '.join(context.args[:-1]).strip()
        date_str = context.args[-1].strip()
        day, month = map(int, date_str.split('.'))
        if not (1 <= day <= 31 and 1 <= month <= 12):
            await update.message.reply_text("Неверная дата!")
            return
        birthdays[name] = f"{day:02d}.{month:02d}"
        save_birthdays(birthdays)
        context.bot_data["birthdays"] = birthdays
        await update.message.reply_text(f"✅ {name} добавлен(а): {day:02d}.{month:02d}")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат!")

async def list_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    birthdays = context.bot_data.get("birthdays", {})
    if not birthdays:
        await update.message.reply_text("📭 Список пуст")
        return
    response = "📅 Дни рождения:\n"
    for name, date in sorted(birthdays.items(), key=lambda x: x[1]):
        response += f"• {name}: {date}\n"
    await update.message.reply_text(response)

async def import_birthdays(update: Update, context: ContextTypes.DEFAULT_TYPE):
    birthdays = context.bot_data.get("birthdays", {})
    try:
        imported_count = 0
        with open('import_birthdays.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name, date_str = row['Имя'].strip(), row['Дата'].strip()
                if name and _validate_date(date_str):
                    birthdays[name] = date_str
                    imported_count += 1
        save_birthdays(birthdays)
        context.bot_data["birthdays"] = birthdays
        await update.message.reply_text(f"✅ Импортировано: {imported_count}")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

def _validate_date(date_str):
    try:
        day, month = map(int, date_str.split('.'))
        return 1 <= day <= 31 and 1 <= month <= 12
    except ValueError:
        return False

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID чата: {update.message.chat_id}")

async def force_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_birthday_greetings(context)
    await update.message.reply_text("✅ Проверка выполнена")

async def sync_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    birthdays = context.bot_data.get("birthdays", {})
    save_birthdays(birthdays)
    await update.message.reply_text("💾 Файлы синхронизированы")

async def generate_greeting(full_name):
    first_name = full_name.split()[0]
    if not DEEPSEEK_API_KEY:
        return f"🎉 {first_name}, от всей души поздравляем с днем рождения! 🎂"
    try:
        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты пишешь теплые поздравления для коллег."},
                {"role": "user", "content": f"Поздравление для {first_name}"}
            ],
            "max_tokens": 100,
            "temperature": 0.9
        }
        response = requests.post(url, headers=headers, json=data, timeout=10)
        response.raise_for_status()
        greeting = response.json()['choices'][0]['message']['content'].strip()
        if first_name.lower() not in greeting.lower():
            greeting = f"{first_name}, {greeting}"
        return greeting
    except Exception:
        return f"🎉 {first_name}, от всей души поздравляем с днем рождения! 🎂"

async def send_birthday_greetings(context: ContextTypes.DEFAULT_TYPE):
    birthdays = context.bot_data.get("birthdays", {})
    today = datetime.now(tz=ZoneInfo(TZ)).strftime("%d.%m")
    messages = []
    for name, date in birthdays.items():
        if date == today:
            greeting = await generate_greeting(name)
            messages.append(greeting)
    if messages:
        await context.bot.send_message(chat_id=CHAT_ID, text="\n\n".join(messages))
        print("✅ Отправлены поздравления:", messages)


# -------------------- APPLICATION -------------------- #
def build_application():
    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data["birthdays"] = load_birthdays()
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_birthday))
    app.add_handler(CommandHandler("list", list_birthdays))
    app.add_handler(CommandHandler("import", import_birthdays))
    app.add_handler(CommandHandler("getid", get_chat_id))
    app.add_handler(CommandHandler("check", force_check))
    app.add_handler(CommandHandler("sync", sync_files))
    app.add_handler(CallbackQueryHandler(button_handler))
    # APScheduler
    app.job_queue.run_daily(
        send_birthday_greetings,
        time=time(hour=9, minute=0, tzinfo=ZoneInfo(TZ)),
        name="daily_birthday_check"
    )
    return app


# -------------------- ЗАПУСК -------------------- #
if __name__ == "__main__":
    app = build_application()
    # Устанавливаем webhook и запускаем сервер
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=f"webhook/{BOT_TOKEN}",
        webhook_url=f"{RAILWAY_URL}/webhook/{BOT_TOKEN}"
    )
