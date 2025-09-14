import os
import json
import logging
import csv
import requests
import calendar
from datetime import datetime, time, timedelta
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext
from zoneinfo import ZoneInfo
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler

# -------------------- НАСТРОЙКА -------------------- #
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Базовый список праздников (можно вынести в файл и редактировать)
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
        """Загрузка дней рождения из JSON файла"""
        try:
            with open(self.birthdays_file, 'r', encoding='utf-8') as f:
                self.birthdays = json.load(f)
        except FileNotFoundError:
            self.birthdays = {}
            self.save_birthdays()

    def save_birthdays(self):
        """Сохранение дней рождения в JSON и синхронизация с CSV"""
        with open(self.birthdays_file, 'w', encoding='utf-8') as f:
            json.dump(self.birthdays, f, ensure_ascii=False, indent=2)
        # Синхронизируем CSV автоматически
        self.sync_to_csv()

    def sync_to_csv(self):
        """Синхронизация данных в CSV файл"""
        try:
            with open('import_birthdays.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['Имя', 'Дата'])
                writer.writeheader()
                for name, date in self.birthdays.items():
                    writer.writerow({'Имя': name, 'Дата': date})
        except Exception as e:
            print(f"Ошибка синхронизации CSV: {e}")

    # -------------------- КНОПКИ -------------------- #
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        keyboard = [
            [InlineKeyboardButton("➕ Добавить день рождения", callback_data="add")],
            [InlineKeyboardButton("📋 Показать все дни рождения", callback_data="list")],
            [InlineKeyboardButton("📥 Импорт из CSV", callback_data="import")],
            [InlineKeyboardButton("🆔 Получить ID чата", callback_data="getid")],
            [InlineKeyboardButton("🔍 Принудительная проверка", callback_data="check")],
            [InlineKeyboardButton("💾 Синхронизация файлов", callback_data="sync")],
            [InlineKeyboardButton("❓ Помощь", callback_data="help")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🎂 Company Birthday Bot\n\nВыберите действие:", reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        if query.data == "add":
            await query.message.reply_text("Введите команду: /add Имя день.месяц")
        elif query.data == "list":
            await self.list_birthdays(update, context)
        elif query.data == "import":
            await self.import_birthdays(update, context)
        elif query.data == "getid":
            await self.get_chat_id(update, context)
        elif query.data == "check":
            await self.force_check(update, context)
        elif query.data == "sync":
            await self.sync_files(update, context)
        elif query.data == "help":
            await self.start(update, context)

    async def add_birthday(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Добавление дня рождения"""
        if not context.args or len(context.args) < 2:
            await update.message.reply_text("Используйте: /add Имя день.месяц\nПример: /add Иван 15.05")
            return

        try:
            name = ' '.join(context.args[:-1]).strip()
            date_str = context.args[-1].strip()

            if not name:
                await update.message.reply_text("Имя не может быть пустым!")
                return

            # Проверка и парсинг даты
            day, month = map(int, date_str.split('.'))
            if not (1 <= day <= 31 and 1 <= month <= 12):
                await update.message.reply_text("Неверная дата! Формат: день.месяц (01-31.01-12)")
                return

            # Сохранение
            self.birthdays[name] = f"{day:02d}.{month:02d}"
            self.save_birthdays()

            await update.message.reply_text(f"✅ {name} добавлен(а): {day:02d}.{month:02d}")

        except ValueError:
            await update.message.reply_text("❌ Неверный формат! Используйте: /add Имя день.месяц")

    async def import_birthdays(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Импорт дней рождения из CSV файла"""
        try:
            imported_count = 0

            with open('import_birthdays.csv', 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if all(key in row for key in ['Имя', 'Дата']):
                        name = row['Имя'].strip()
                        date_str = row['Дата'].strip()

                        if name and date_str and self._validate_date(date_str):
                            self.birthdays[name] = date_str
                            imported_count += 1

            if imported_count > 0:
                self.save_birthdays()
                await update.message.reply_text(f"✅ Импортировано записей: {imported_count}")
            else:
                await update.message.reply_text("❌ Файл import_birthdays.csv не найден или пуст")

        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка импорта: {str(e)}")

    def _validate_date(self, date_str):
        """Проверка корректности даты"""
        try:
            day, month = map(int, date_str.split('.'))
            return 1 <= day <= 31 and 1 <= month <= 12
        except ValueError:
            return False

    async def list_birthdays(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать все дни рождения"""
        if not self.birthdays:
            await update.message.reply_text("📭 Список дней рождения пуст")
            return

        response = "📅 Дни рождения:\n\n"
        for name, date in sorted(self.birthdays.items(), key=lambda x: x[1]):
            response += f"• {name}: {date}\n"

        await update.message.reply_text(response)

    async def sync_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Принудительная синхронизация файлов"""
        try:
            self.sync_to_csv()
            count = len(self.birthdays)
            await update.message.reply_text(f"✅ Синхронизировано! Записей: {count}")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка синхронизации: {e}")

    # -------------------- ГЕНЕРАЦИЯ ПОЗДРАВЛЕНИЙ -------------------- #
    async def generate_greeting(self, full_name):
        """Генерация поздравления через DeepSeek API (fallback — шаблон)"""
        first_name = full_name.split()[0]  # Извлекаем только имя

        try:
            if not self.deepseek_api_key:
                # Fallback на шаблонное поздравление если нет API ключа
                return f"🎉 {first_name}, от всей души поздравляем с днем рождения! 🎂"

            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Ты профессиональный копирайтер, который пишет теплые и искренние поздравления с днем рождения коллегам. "
                            "Поздравления должны быть краткими (1-2 предложения), дружескими и профессиональными. Пиши УНИКАЛЬНЫЕ поздравления для каждого человека. "
                            "Избегай шаблонных фраз. Пиши от имени компании. ОБЯЗАТЕЛЬНО используй имя человека в начале поздравления."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Напиши короткое поздравление с днем рождения для коллеги по имени {first_name}. Только текст поздравления, без подписи."
                    }
                ],
                "max_tokens": 100,
                "temperature": 0.9
            }

            response = requests.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            result = response.json()

            greeting = result['choices'][0]['message']['content'].strip()

            # Гарантируем что имя есть в поздравлении
            if first_name.lower() not in greeting.lower():
                greeting = f"{first_name}, {greeting}"

            return greeting

        except Exception as e:
            print(f"Ошибка DeepSeek: {e}")
            # Fallback если API недоступно
            return f"🎉 {first_name}, от всей души поздравляем с днем рождения! 🎂"

    async def generate_multi_birthday_greeting(self, birthdays):
        """Генерация поздравления для нескольких именинников через DeepSeek (или fallback)"""
        try:
            if not self.deepseek_api_key:
                return self.generate_fallback_multi_greeting(birthdays)

            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.deepseek_api_key}",
                "Content-Type": "application/json"
            }

            names_list = ", ".join(birthdays)
            data = {
                "model": "deepseek-chat",
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты профессиональный копирайтер. Пиши теплые поздравления с днем рождения для нескольких коллег. Сделай поздравление единым текстом, а не списком."
                    },
                    {
                        "role": "user",
                        "content": f"Напиши общее поздравление с днем рождения для коллег: {names_list}. Сделай текст единым и теплым, от имени компании."
                    }
                ],
                "max_tokens": 200,
                "temperature": 0.8
            }

            response = requests.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()
            result = response.json()

            greeting = result['choices'][0]['message']['content'].strip()
            # Возвращаем уже с emoji, т.к. это единый текст
            return f"🎉 {greeting}"

        except Exception as e:
            print(f"Ошибка DeepSeek для нескольких именинников: {e}")
            return self.generate_fallback_multi_greeting(birthdays)

    def generate_fallback_multi_greeting(self, birthdays):
        """Запасной вариант для нескольких именинников"""
        names_list = ", ".join(birthdays)
        return (
            f"🎉 Сегодня {len(birthdays)} именинника! 🎊\n\n"
            f"Поздравляем наших коллег {names_list} с днем рождения! "
            f"От всей компании желаем счастья, здоровья, профессиональных успехов и ярких достижений! "
            f"Пусть каждый день приносит радость и удовлетворение от работы! 🥳"
        )

    # -------------------- ВСПОМОГАТЕЛЬНЫЕ ДЛЯ ВЫХОДНЫХ/ПРАЗДНИКОВ -------------------- #
    def get_weekend_birthdays(self):
        """Возвращает ДР за прошедшие выходные (если сегодня понедельник)."""
        today = datetime.now(tz=ZoneInfo(self.timezone))
        if today.weekday() == 0:  # понедельник
            saturday = (today - timedelta(days=2)).strftime("%d.%m")
            sunday = (today - timedelta(days=1)).strftime("%d.%m")
            return {name: date for name, date in self.birthdays.items() if date in [saturday, sunday]}
        return {}

    def get_holiday_birthdays(self):
        """Возвращает ДР за вчера, если вчера был праздник."""
        today = datetime.now(tz=ZoneInfo(self.timezone))
        yesterday = (today - timedelta(days=1)).strftime("%d.%m")
        if yesterday in HOLIDAYS:
            return {name: date for name, date in self.birthdays.items() if date == yesterday}
        return {}

    # -------------------- ОТПРАВКА ПОЗДРАВЛЕНИЙ -------------------- #
    async def send_birthday_greetings(self, context: CallbackContext, target_chat_id: str = None, test: bool = False):
        """
        Основной метод отправки поздравлений.
        - target_chat_id: если указан, отправка пойдёт в этот чат (используется /check).
        - test: если True, добавляется префикс "ТЕСТ" и отправка идёт в target_chat_id.
        """
        chat_id = target_chat_id or self.chat_id
        today = datetime.now(tz=ZoneInfo(self.timezone))
        today_str = today.strftime("%d.%m")

        birthdays_today = {name: date for name, date in self.birthdays.items() if date == today_str}
        weekend_birthdays = self.get_weekend_birthdays()
        holiday_birthdays = self.get_holiday_birthdays()

        all_birthdays = {
            "Сегодня": birthdays_today,
            "В выходные": weekend_birthdays,
            "В праздник": holiday_birthdays
        }

        messages = []
        for label, bdays in all_birthdays.items():
            if not bdays:
                continue

            if label == "Сегодня":
                if len(bdays) == 1:
                    name = next(iter(bdays))
                    greeting = await self.generate_greeting(name)
                    messages.append(greeting if greeting.startswith("🎉") else f"🎉 {greeting}")
                else:
                    multi_greeting = await self.generate_multi_birthday_greeting(list(bdays.keys()))
                    messages.append(multi_greeting)

            elif label == "В выходные":
                # Формат: "В субботу у Марии был день рождения!\n[поздравление]"
                for name, date in bdays.items():
                    # определяем день недели по дате (год неважен, ставим ближайший високосный/не - берем 2025)
                    try:
                        weekday_idx = datetime.strptime(date + ".2025", "%d.%m.%Y").weekday()
                        weekday_name_en = calendar.day_name[weekday_idx]
                        weekday_ru = {"Saturday": "в субботу", "Sunday": "в воскресенье"}.get(weekday_name_en, "в выходные")
                    except Exception:
                        weekday_ru = "в выходные"

                    greeting = await self.generate_greeting(name)
                    greeting_text = greeting if greeting.startswith("🎉") else f"🎉 {greeting}"
                    messages.append(f"🎉 {weekday_ru.capitalize()} у {name} был день рождения!\n{greeting_text}")

            elif label == "В праздник":
                # Формат: "В праздничный день (dd.mm) у Марии был день рождения!\n[поздравление]"
                for name, date in bdays.items():
                    greeting = await self.generate_greeting(name)
                    greeting_text = greeting if greeting.startswith("🎉") else f"🎉 {greeting}"
                    messages.append(f"🎉 В праздничный день ({date}) у {name} был день рождения!\n{greeting_text}")

        if messages:
            full_message = "\n\n".join(messages)
            if test:
                full_message = "🎯 ТЕСТОВАЯ ПРОВЕРКА:\n\n" + full_message
            await context.bot.send_message(chat_id=chat_id, text=full_message)
            print("✅ Отправлены поздравления:", messages)
        else:
            print("📅 Сегодня и в ближайшие дни нет именинников")

    async def force_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Принудительная проверка (вызывает боевую send_birthday_greetings).
        Результат отправляется в чат, где вызвали команду, и помечается как тест.
        """
        # Проверяем, есть ли вообще именинники (локально)
        birthdays_today = self.get_today_birthdays()
        if not birthdays_today:
            await update.message.reply_text("📅 Сегодня никто не празднует")
            return

        try:
            # Выполняем боевую функцию, но отправляем результат в чат, где вызвали команду
            await update.message.reply_text("🔍 Тестовая проверка поздравлений...")
            await self.send_birthday_greetings(context, target_chat_id=update.message.chat_id, test=True)
            await update.message.reply_text("✅ Тест завершён (результат выше).")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка теста: {e}")

    def get_today_birthdays(self):
        """Получение списка именинников на сегодня (только имена в виде списка)"""
        today = datetime.now(tz=ZoneInfo(self.timezone)).strftime("%d.%m")
        return [name for name, date in self.birthdays.items() if date == today]

    async def get_chat_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда для получения ID чата"""
        chat_id = update.message.chat_id
        await update.message.reply_text(f"ID этого чата: {chat_id}")
        print(f"Получен ID чата: {chat_id}")

    # -------------------- ЗАПУСК БОТА -------------------- #
    def run(self):
        """Запуск и настройка бота"""
        application = Application.builder().token(self.token).build()

        # Регистрация команд
        handlers = [
            CommandHandler("start", self.start),
            CommandHandler("add", self.add_birthday),
            CommandHandler("list", self.list_birthdays),
            CommandHandler("import", self.import_birthdays),
            CommandHandler("getid", self.get_chat_id),
            CommandHandler("check", self.force_check),
            CommandHandler("sync", self.sync_files),
            CommandHandler("help", self.start),
            CallbackQueryHandler(self.button_handler)
        ]

        for handler in handlers:
            application.add_handler(handler)

        # Настройка планировщика (ежедневно в 09:00 по TZ)
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_daily(
                self.send_birthday_greetings,
                time=time(hour=9, minute=0, tzinfo=ZoneInfo(self.timezone)),
                name="daily_birthday_check"
            )
            print(f"⏰ Планировщик настроен на 09:00 ({self.timezone})")

        print("🚀 Бот запущен...")
        application.run_polling()


if __name__ == "__main__":
    bot = BirthdayBot()
    #bot.run()
    bot.run()

