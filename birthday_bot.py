import os
import json
import logging
import csv
import requests
import calendar
from datetime import datetime, time, timedelta
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    CallbackContext
)
from zoneinfo import ZoneInfo

# -------------------- НАСТРОЙКА -------------------- #
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

HOLIDAYS = {"01.01", "23.02", "08.03", "01.05", "09.05", "12.06", "04.11"}

class BirthdayBot:
    def __init__(self):
        self.token = os.getenv('BOT_TOKEN')
        self.chat_id = os.getenv('CHAT_ID')
        self.deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        self.timezone = os.getenv('TZ', 'Europe/Moscow')
        self.birthdays_file = 'birthdays.json'
        self.load_birthdays()

    # -------------------- ФАЙЛЫ -------------------- #
    def load_birthdays(self):
        try:
            with open(self.birthdays_file, 'r', encoding='utf-8') as f:
                self.birthdays = json.load(f)
        except FileNotFoundError:
            self.birthdays = {}
            self.save_birthdays()

    def save_birthdays(self):
        with open(self.birthdays_file, 'w', encoding='utf-8') as f:
            json.dump(self.birthdays, f, ensure_ascii=False, indent=2)
        self.sync_to_csv()

    def sync_to_csv(self):
        try:
            with open('import_birthdays.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['Имя', 'Дата'])
                writer.writeheader()
                for name, date in self.birthdays.items():
                    writer.writerow({'Имя': name, 'Дата': date})
        except Exception as e:
            print(f"Ошибка синхронизации CSV: {e}")

    # -------------------- КОМАНДЫ -------------------- #
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Приветствие с кнопками"""
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

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий кнопок"""
        query = update.callback_query
        await query.answer()

        cmd_map = {
            'add': self.add_birthday,
            'list': self.list_birthdays,
            'import': self.import_birthdays,
            'getid': self.get_chat_id,
            'check': self.force_check,
            'sync': self.sync_files,
            'help': self.start
        }

        handler = cmd_map.get(query.data)
        if handler:
            # Вызов функции без аргументов команды
            # Для add нужно будет писать через /add вручную
            # Можно доработать чтобы открывалась инструкция
            if query.data == 'add':
                await query.edit_message_text("Используйте: /add Имя день.месяц\nПример: /add Иван 15.05")
            else:
                await handler(update, context)
        else:
            await query.edit_message_text("Неизвестная команда!")

    async def add_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            self.birthdays[name] = f"{day:02d}.{month:02d}"
            self.save_birthdays()
            await update.message.reply_text(f"✅ {name} добавлен(а): {day:02d}.{month:02d}")
        except ValueError:
            await update.message.reply_text("❌ Неверный формат!")

    async def list_birthdays(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.birthdays:
            await update.message.reply_text("📭 Список пуст")
            return
        response = "📅 Дни рождения:\n"
        for name, date in sorted(self.birthdays.items(), key=lambda x: x[1]):
            response += f"• {name}: {date}\n"
        await update.message.reply_text(response)

    async def import_birthdays(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            imported_count = 0
            with open('import_birthdays.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name, date_str = row['Имя'].strip(), row['Дата'].strip()
                    if name and self._validate_date(date_str):
                        self.birthdays[name] = date_str
                        imported_count += 1
            self.save_birthdays()
            await update.message.reply_text(f"✅ Импортировано: {imported_count}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")

    def _validate_date(self, date_str):
        try:
            day, month = map(int, date_str.split('.'))
            return 1 <= day <= 31 and 1 <= month <= 12
        except ValueError:
            return False

    # -------------------- Генерация поздравлений -------------------- #
    async def generate_greeting(self, full_name):
        first_name = full_name.split()[0]
        if not self.deepseek_api_key:
            return f"🎉 {first_name}, от всей души поздравляем с днем рождения! 🎂"
        try:
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
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

    async def send_birthday_greetings(self, context: CallbackContext):
        today = datetime.now(tz=ZoneInfo(self.timezone)).strftime("%d.%m")
        birthdays_today = {name: date for name, date in self.birthdays.items() if date == today}
        messages = []
        for name in birthdays_today:
            greeting = await self.generate_greeting(name)
            messages.append(greeting)
        if messages:
            await context.bot.send_message(chat_id=self.chat_id, text="\n\n".join(messages))
            print("✅ Отправлены поздравления:", messages)

    async def get_chat_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat_id
        await update.message.reply_text(f"ID чата: {chat_id}")

    async def force_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self.send_birthday_greetings(context)
        await update.message.reply_text("✅ Проверка выполнена")

    async def sync_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.save_birthdays()
        await update.message.reply_text("💾 Файлы синхронизированы")

# -------------------- ЗАПУСК ЧЕРЕЗ WEBHOOK -------------------- #
if __name__ == "__main__":
    bot = BirthdayBot()
    application = Application.builder().token(bot.token).build()

    # Регистрация команд
    handlers = [
        CommandHandler("start", bot.start),
        CommandHandler("add", bot.add_birthday),
        CommandHandler("list", bot.list_birthdays),
        CommandHandler("import", bot.import_birthdays),
        CommandHandler("getid", bot.get_chat_id),
        CommandHandler("check", bot.force_check),
        CommandHandler("sync", bot.sync_files)
    ]
    for handler in handlers:
        application.add_handler(handler)

    # Обработка кнопок
    application.add_handler(CallbackQueryHandler(bot.button_handler))

    # Планировщик 09:00
    application.job_queue.run_daily(
        bot.send_birthday_greetings,
        time=time(hour=9, minute=0, tzinfo=ZoneInfo(bot.timezone)),
        name="daily_birthday_check"
    )

    # Webhook Railway
    url = os.getenv("RAILWAY_URL")
    if not url:
        raise ValueError("Не задан RAILWAY_URL")
    application.bot.set_webhook(f"{url}/webhook/{bot.token}")

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8443)),
        url_path=f"webhook/{bot.token}",
        webhook_url=f"{url}/webhook/{bot.token}"
    )
