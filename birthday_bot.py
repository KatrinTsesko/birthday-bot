import os
import json
import logging
import csv
import requests
from datetime import datetime, time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackContext
from zoneinfo import ZoneInfo

# -------------------- НАСТРОЙКА -------------------- #
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class BirthdayBot:
    def __init__(self):
        self.token = os.getenv('BOT_TOKEN')
        self.chat_id = os.getenv('CHAT_ID')
        self.deepseek_api_key = os.getenv('DEEPSEEK_API_KEY')
        self.timezone = os.getenv('TZ', 'Europe/Moscow')
        self.birthdays_file = 'birthdays.json'
        self.load_birthdays()

    # -------------------- РАБОТА С ФАЙЛАМИ -------------------- #
    def load_birthdays(self):
        """Загрузка дней рождения из JSON файла"""
        try:
            with open(self.birthdays_file, 'r', encoding='utf-8') as f:
                self.birthdays = json.load(f)
        except FileNotFoundError:
            self.birthdays = {}
            self.save_birthdays()

    def save_birthdays(self):
        """Сохранение дней рождения в JSON и автоматическая синхронизация с CSV"""
        with open(self.birthdays_file, 'w', encoding='utf-8') as f:
            json.dump(self.birthdays, f, ensure_ascii=False, indent=2)
        
        # Автоматическая синхронизация с CSV
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

    # -------------------- КОМАНДЫ БОТА -------------------- #
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Приветственное сообщение"""
        commands = [
            "/add имя день.месяц - добавить день рождения",
            "/list - показать все дни рождения", 
            "/import - импорт из CSV файла",
            "/getid - получить ID чата",
            "/check - принудительная проверка",
            "/sync - синхронизация файлов",
            "/help - помощь"
        ]
        
        await update.message.reply_text(
            "🎂 Бот-поздравлятор\n\n" +
            "Команды:\n" + "\n".join(f"• {cmd}" for cmd in commands)
        )

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

    async def generate_greeting(self, full_name):
        """Генерация поздравления через DeepSeek API"""
        first_name = full_name.split()[0]  # Извлекаем только имя
    
        try:
            if not self.deepseek_api_key:
                # Fallback на шаблонное поздравление если нет API ключа
                return f"🎉 Дорогой {first_name}, от всей души поздравляем с днем рождения! 🎂"
        
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
                        "content": "Ты профессиональный копирайтер, который пишет теплые и искренние поздравления с днем рождения коллегам. Поздравления должны быть краткими (1-2 предложения), дружескими и профессиональными. Пиши УНИКАЛЬНЫЕ поздравления для каждого человека. Избегай шаблонных фраз. Учитывай что в один день может быть несколько именинников.Пиши от имени компании. ОБЯЗАТЕЛЬНО используй имя человека в начале поздравления."
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
            return f"🎉 Дорогой {first_name}, от всей души поздравляем с днем рождения! 🎂"
   
    # -------------------- ПРОВЕРКА И ОТПРАВКА -------------------- #
    def get_today_birthdays(self):
        """Получение списка именинников на сегодня"""
        today = datetime.now(tz=ZoneInfo(self.timezone)).strftime("%d.%m")
        return [name for name, date in self.birthdays.items() if date == today]

    async def send_birthday_greetings(self, context: CallbackContext):
        """Отправка поздравлений с учетом выходных дней"""
        today = datetime.now(tz=ZoneInfo(self.timezone))
        today_str = today.strftime("%d.%m")
    
        # Проверяем является ли сегодня рабочим днем
        is_weekend = today.weekday() >= 5  # 5=суббота, 6=воскресенье
    
        birthdays_today = [name for name, date in self.birthdays.items() if date == today_str]
        
        if not birthdays_today:
            print("📅 Сегодня никто не празднует")
            return
        
        print(f"🎂 Найдены именинники: {birthdays_today}")

        # Если сегодня выходной - отправляем особое сообщение
        if is_weekend:
            weekend_message = await self.generate_weekend_greeting(birthdays_today, today)
            await context.bot.send_message(chat_id=self.chat_id, text=weekend_message)
            print(f"✅ Отправлено поздравление для выходного дня")
            return
        
        if len(birthdays_today) == 1:
            # Один именинник
            name = birthdays_today[0]
            greeting = await self.generate_greeting(name)
            await context.bot.send_message(chat_id=self.chat_id, text=f"🎉 {greeting}")
            print(f"✅ Отправлено поздравление для {name}")
            
        else:
            # Несколько именинников
            message = f"🎉 Сегодня {len(birthdays_today)} именинника! 🎊\n\n"
            for name in birthdays_today:
                greeting = await self.generate_greeting(name)
                message += f"🎂 {greeting}\n\n"
            
            message += "🎉 От всего коллектива желаем счастья и улыбок! 🥳"
            await context.bot.send_message(chat_id=self.chat_id, text=message)
            print(f"✅ Отправлено объединенное поздравление")

    async def generate_multi_birthday_greeting(self, birthdays):
        """Генерация поздравления для нескольких именинников через DeepSeek"""
        try:
            if not self.deepseek_api_key:
                return self.generate_fallback_multi_greeting(birthdays)
        
            url = "https://api.deepseek.com/v1/chat/completions"
            headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}", 
            "Content-Type": "application/json"
            }
        
            names_list = ", ".join(birthdays)
            first_names = [name.split()[0] for name in birthdays]
        
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

    async def force_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Принудительная проверка через DeepSeek"""
        birthdays_today = self.get_today_birthdays()
    
        if not birthdays_today:
            await update.message.reply_text("📅 Сегодня никто не празднует")
            return
    
        try:
            if len(birthdays_today) == 1:
                name = birthdays_today[0]
                greeting = await self.generate_greeting(name)
                message = f"🎉 Тест: {greeting}"
            else:
                # Генерируем единое поздравление для всех
                message = await self.generate_multi_birthday_greeting(birthdays_today)
                message = f"🎉 Тест: {message}"
        
            await update.message.reply_text(message)
        
        except Exception as e:
            # Запасной вариант
            message = f"🎉 Тест: сегодня празднуют {len(birthdays_today)} человека!\n\n"
            for name in birthdays_today:
                greeting = await self.generate_greeting(name)
                message += f"🎂 {greeting}\n\n"
            await update.message.reply_text(message)

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
            CommandHandler("help", self.start)
        ]
        
        for handler in handlers:
            application.add_handler(handler)

        # Настройка планировщика
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_daily(
                self.send_birthday_greetings,
                time=time(hour=8, minute=10, tzinfo=ZoneInfo(self.timezone)),
                name="daily_birthday_check"
            )
            print(f"⏰ Планировщик настроен на 09:00 ({self.timezone})")

        print("🚀 Бот запущен...")
        application.run_polling()

if __name__ == "__main__":
    bot = BirthdayBot()
    bot.run()