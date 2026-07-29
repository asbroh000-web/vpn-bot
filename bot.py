# bot.py - Complete VPN Bot with All Features

import logging
import os
import sys
import json
import uuid
import random
import string
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any, List, Tuple
import pytz
import asyncio
from functools import wraps

# Third-party imports
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

from sqlalchemy import (
    create_engine, Column, Integer, String, BigInteger, Float, 
    DateTime, Boolean, Text, JSON, ForeignKey, func, select
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session, relationship
from sqlalchemy.exc import SQLAlchemyError

from dotenv import load_dotenv
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Load environment variables
load_dotenv()

# ===================================================================
# CONFIGURATION
# ===================================================================

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    DATABASE_URL = os.getenv('DATABASE_URL')
    PANEL_URL = os.getenv('PANEL_URL')
    PANEL_USERNAME = os.getenv('PANEL_USERNAME')
    PANEL_PASSWORD = os.getenv('PANEL_PASSWORD')
    OWNER_ID = int(os.getenv('OWNER_ID', 0))
    SUPPORT_USERNAME = os.getenv('SUPPORT_USERNAME', 'support')
    CHANNEL_USERNAME = os.getenv('CHANNEL_USERNAME', 'channel')
    GROUP_USERNAME = os.getenv('GROUP_USERNAME', 'group')
    
    # Trial Settings
    TRIAL_DATA = 500  # MB
    TRIAL_DURATION_HOURS = 1
    TRIAL_INBOUND = int(os.getenv('TRIAL_INBOUND', 1))
    
    # Pricing
    PRICE_PER_20GB = 10  # BDT
    PRICE_PER_IP = 10  # BDT
    
    # Referral
    REFERRAL_REWARD_GB = 50
    REFERRAL_REWARD_IP = 1
    REFERRAL_REWARD_DAYS = 30
    REFERRAL_REWARD_COUNT = 20
    
    # Premium Inbound
    PREMIUM_INBOUND = int(os.getenv('PREMIUM_INBOUND', 2))

# ===================================================================
# DATABASE MODELS
# ===================================================================

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(100))
    first_name = Column(String(100))
    last_name = Column(String(100))
    joined_date = Column(DateTime, default=datetime.now(pytz.UTC))
    is_admin = Column(Boolean, default=False)
    is_owner = Column(Boolean, default=False)
    is_blocked = Column(Boolean, default=False)
    referral_code = Column(String(20), unique=True)
    referred_by = Column(BigInteger, nullable=True)
    
    trial = relationship('TrialClient', back_populates='user', uselist=False)
    premium_clients = relationship('PremiumClient', back_populates='user')
    payments = relationship('Payment', back_populates='user')
    referrals_given = relationship('Referral', foreign_keys='Referral.referrer_id', back_populates='referrer')
    referrals_received = relationship('Referral', foreign_keys='Referral.referred_id', back_populates='referred')

class TrialClient(Base):
    __tablename__ = 'trial_clients'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    panel_client_id = Column(String(100), unique=True)
    uuid = Column(String(100))
    data_limit = Column(Float)  # MB
    used_data = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.now(pytz.UTC))
    expiry_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    user = relationship('User', back_populates='trial')

class PremiumClient(Base):
    __tablename__ = 'premium_clients'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    panel_client_id = Column(String(100), unique=True)
    uuid = Column(String(100))
    data_limit = Column(Float)  # GB
    used_data = Column(Float, default=0)
    ip_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now(pytz.UTC))
    expiry_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    auto_renew = Column(Boolean, default=False)
    renewal_notified = Column(Boolean, default=False)
    
    user = relationship('User', back_populates='premium_clients')
    payments = relationship('Payment', back_populates='premium_client')

class Payment(Base):
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    premium_client_id = Column(Integer, ForeignKey('premium_clients.id'), nullable=True)
    order_id = Column(String(100), unique=True)
    amount = Column(Float)
    method = Column(String(50))
    transaction_id = Column(String(200))
    sender_number = Column(String(50))
    screenshot = Column(String(500), nullable=True)
    status = Column(String(20), default='pending')  # pending, approved, declined
    data_gb = Column(Float)
    ip_count = Column(Integer)
    created_at = Column(DateTime, default=datetime.now(pytz.UTC))
    approved_at = Column(DateTime, nullable=True)
    decline_reason = Column(Text, nullable=True)
    
    user = relationship('User', back_populates='payments')
    premium_client = relationship('PremiumClient', back_populates='payments')

class UploadedFile(Base):
    __tablename__ = 'uploaded_files'
    
    id = Column(Integer, primary_key=True)
    file_id = Column(String(200), unique=True)
    caption = Column(Text)
    uploaded_by = Column(BigInteger)
    uploaded_at = Column(DateTime, default=datetime.now(pytz.UTC))
    is_active = Column(Boolean, default=True)
    file_type = Column(String(20), default='document')  # document, video, photo

class RedeemCode(Base):
    __tablename__ = 'redeem_codes'
    
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True)
    data_gb = Column(Float)
    ip_count = Column(Integer)
    created_by = Column(BigInteger)
    created_at = Column(DateTime, default=datetime.now(pytz.UTC))
    is_used = Column(Boolean, default=False)
    used_by = Column(BigInteger, nullable=True)
    used_at = Column(DateTime, nullable=True)

class Referral(Base):
    __tablename__ = 'referrals'
    
    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey('users.id'))
    referred_id = Column(Integer, ForeignKey('users.id'))
    created_at = Column(DateTime, default=datetime.now(pytz.UTC))
    rewarded = Column(Boolean, default=False)
    
    referrer = relationship('User', foreign_keys=[referrer_id], back_populates='referrals_given')
    referred = relationship('User', foreign_keys=[referred_id], back_populates='referrals_received')

class AdminSetting(Base):
    __tablename__ = 'admin_settings'
    
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.now(pytz.UTC), onupdate=datetime.now(pytz.UTC))

class Statistics(Base):
    __tablename__ = 'statistics'
    
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now(pytz.UTC))
    total_users = Column(Integer, default=0)
    today_users = Column(Integer, default=0)
    trial_users = Column(Integer, default=0)
    premium_users = Column(Integer, default=0)
    pending_orders = Column(Integer, default=0)
    completed_orders = Column(Integer, default=0)
    revenue = Column(Float, default=0)
    referral_claims = Column(Integer, default=0)
    redeem_claims = Column(Integer, default=0)

class ActivityLog(Base):
    __tablename__ = 'activity_logs'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger)
    action = Column(String(100))
    details = Column(JSON)
    created_at = Column(DateTime, default=datetime.now(pytz.UTC))

# ===================================================================
# DATABASE CONNECTION
# ===================================================================

engine = create_engine(Config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = scoped_session(sessionmaker(bind=engine))

Base.metadata.create_all(engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===================================================================
# PANEL API INTEGRATION
# ===================================================================

class PanelAPI:
    def __init__(self):
        self.base_url = Config.PANEL_URL.rstrip('/')
        self.username = Config.PANEL_USERNAME
        self.password = Config.PANEL_PASSWORD
        self.session = requests.Session()
        self.session.verify = False  # For development, remove in production
        self.token = None
        self.login()
    
    def login(self):
        try:
            response = self.session.post(
                f"{self.base_url}/login",
                json={"username": self.username, "password": self.password},
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if 'token' in data:
                    self.token = data['token']
                    self.session.headers.update({'Authorization': f'Bearer {self.token}'})
                    logging.info("Panel login successful")
                    return True
            logging.error(f"Panel login failed: {response.text}")
            return False
        except Exception as e:
            logging.error(f"Panel login error: {e}")
            return False
    
    def create_client(self, inbound_id, data_limit_mb, expiry_days, ip_count=1, remark=None):
        """Create client in 3X-UI panel"""
        try:
            payload = {
                "inbound_id": inbound_id,
                "settings": json.dumps({
                    "clients": [{
                        "id": str(uuid.uuid4()),
                        "flow": "",
                        "email": remark or f"VPN-{uuid.uuid4().hex[:8]}",
                        "limitIp": ip_count,
                        "totalGB": int(data_limit_mb / 1024),  # Convert MB to GB
                        "expiryTime": int((datetime.now() + timedelta(days=expiry_days)).timestamp() * 1000),
                        "enable": True,
                        "tgId": "",
                        "subId": ""
                    }]
                })
            }
            
            response = self.session.post(
                f"{self.base_url}/panel/api/inbounds/addClient",
                json=payload,
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'client' in data:
                    client = data['client']
                    client_id = client.get('id')
                    client_uuid = client.get('uuid')
                    return client_id, client_uuid, client
            logging.error(f"Create client failed: {response.text}")
            return None, None, None
        except Exception as e:
            logging.error(f"Create client error: {e}")
            return None, None, None
    
    def delete_client(self, client_id):
        """Delete client from 3X-UI panel"""
        try:
            response = self.session.delete(
                f"{self.base_url}/panel/api/inbounds/deleteClient/{client_id}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if data.get('success', False):
                    return True
            logging.error(f"Delete client failed: {response.text}")
            return False
        except Exception as e:
            logging.error(f"Delete client error: {e}")
            return False
    
    def get_client_stats(self, client_id):
        """Get client usage statistics"""
        try:
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/getClientTraffic/{client_id}",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if 'traffic' in data:
                    return data['traffic'].get('used'), data['traffic'].get('total')
            return None, None
        except Exception as e:
            logging.error(f"Get stats error: {e}")
            return None, None
    
    def reset_client_data(self, client_id):
        """Reset client data usage"""
        try:
            response = self.session.post(
                f"{self.base_url}/panel/api/inbounds/resetClientTraffic/{client_id}",
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            logging.error(f"Reset data error: {e}")
            return False
    
    def get_all_clients(self):
        """Get all clients from panel"""
        try:
            response = self.session.get(
                f"{self.base_url}/panel/api/inbounds/list",
                timeout=10
            )
            if response.status_code == 200:
                data = response.json()
                if 'inbounds' in data:
                    clients = []
                    for inbound in data['inbounds']:
                        if 'settings' in inbound:
                            settings = json.loads(inbound['settings'])
                            if 'clients' in settings:
                                for client in settings['clients']:
                                    client['inbound_id'] = inbound['id']
                                    clients.append(client)
                    return clients
            return []
        except Exception as e:
            logging.error(f"Get all clients error: {e}")
            return []

panel = PanelAPI()

# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def generate_uuid():
    return str(uuid.uuid4())

def generate_order_id():
    return f"ORD-{datetime.now().strftime('%Y%m%d')}-{''.join(random.choices(string.digits, k=6))}"

def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def generate_redeem_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

def calculate_price(gb, ip_count):
    """Calculate price based on GB and IP count"""
    price = (gb / 20) * Config.PRICE_PER_20GB
    price += (ip_count - 1) * Config.PRICE_PER_IP
    return round(price, 2)

def format_bytes(bytes_value):
    """Format bytes to human readable"""
    if bytes_value is None:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"

def format_currency(amount):
    return f"৳{amount:.2f}"

def is_admin(user_id):
    db = next(get_db())
    user = db.query(User).filter(User.telegram_id == user_id).first()
    if user:
        return user.is_admin or user.is_owner
    return False

def is_owner(user_id):
    return user_id == Config.OWNER_ID

def get_user_from_db(telegram_id):
    db = next(get_db())
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    db.close()
    return user

def create_or_update_user(update):
    db = next(get_db())
    telegram_id = update.effective_user.id
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
            last_name=update.effective_user.last_name,
            referral_code=generate_referral_code()
        )
        db.add(user)
        db.commit()
        
        # Check if user was referred
        if update.effective_message and update.effective_message.text:
            text = update.effective_message.text
            if text.startswith('/start'):
                parts = text.split()
                if len(parts) > 1:
                    ref_code = parts[1]
                    referrer = db.query(User).filter(User.referral_code == ref_code).first()
                    if referrer and referrer.telegram_id != telegram_id:
                        referral = Referral(
                            referrer_id=referrer.id,
                            referred_id=user.id
                        )
                        db.add(referral)
                        db.commit()
                        
                        # Check if referrer reached reward threshold
                        referral_count = db.query(Referral).filter(
                            Referral.referrer_id == referrer.id,
                            Referral.rewarded == False
                        ).count()
                        
                        if referral_count >= Config.REFERRAL_REWARD_COUNT:
                            # Add reward to referrer
                            reward_premium = PremiumClient(
                                user_id=referrer.id,
                                panel_client_id=f"reward-{generate_uuid()}",
                                uuid=generate_uuid(),
                                data_limit=Config.REFERRAL_REWARD_GB,
                                ip_count=Config.REFERRAL_REWARD_IP,
                                expiry_at=datetime.now(pytz.UTC) + timedelta(days=Config.REFERRAL_REWARD_DAYS),
                                is_active=True
                            )
                            db.add(reward_premium)
                            db.commit()
                            
                            # Mark referrals as rewarded
                            db.query(Referral).filter(
                                Referral.referrer_id == referrer.id,
                                Referral.rewarded == False
                            ).update({Referral.rewarded: True})
                            db.commit()
    else:
        # Update username if changed
        if update.effective_user.username and user.username != update.effective_user.username:
            user.username = update.effective_user.username
            db.commit()
    
    db.close()
    return user

def log_activity(user_id, action, details=None):
    db = next(get_db())
    log = ActivityLog(
        user_id=user_id,
        action=action,
        details=details or {}
    )
    db.add(log)
    db.commit()
    db.close()

def replace_placeholders(text, replacements):
    """Replace placeholders in text"""
    for key, value in replacements.items():
        text = text.replace(f"{{{key}}}", str(value))
    return text

# ===================================================================
# KEYBOARD FUNCTIONS
# ===================================================================

def get_main_menu():
    keyboard = [
        ["🎁 Free Trial", "💎 Buy Premium"],
        ["👤 My Info", "👥 Refer & Earn"],
        ["🎟 Redeem Code", "🛟 Support"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_menu():
    keyboard = [
        ["📤 Upload File", "📦 Pending Orders"],
        ["📢 Broadcast", "📊 Statistics"],
        ["🔙 Back to Main Menu"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_owner_menu():
    keyboard = [
        ["📤 Upload File", "📦 Pending Orders"],
        ["📢 Broadcast", "📊 Statistics"],
        ["👥 Add Admin", "🗑 Remove Admin"],
        ["💾 Database Backup", "🔄 Database Restore"],
        ["🔙 Back to Main Menu"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_order_confirmation_keyboard():
    keyboard = [
        [InlineKeyboardButton("✅ Confirm", callback_data="confirm_order")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_order")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_payment_methods_keyboard():
    keyboard = [
        [InlineKeyboardButton("bKash", callback_data="payment_bkash")],
        [InlineKeyboardButton("Nagad", callback_data="payment_nagad")],
        [InlineKeyboardButton("Binance", callback_data="payment_binance")],
        [InlineKeyboardButton("Custom Payment", callback_data="payment_custom")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_pending_order_keyboard(order_id):
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{order_id}")],
        [InlineKeyboardButton("❌ Decline", callback_data=f"decline_{order_id}")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_renew_keyboard():
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Renew", callback_data="renew_yes")],
        [InlineKeyboardButton("❌ No, Thanks", callback_data="renew_no")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ===================================================================
# MESSAGE TEMPLATES
# ===================================================================

class Messages:
    HOME = """
🎯 **AS PREMIUM VPN** 
*Your Trusted VPN Service*

📌 *Main Menu*

Choose an option below to get started! 🚀
    """
    
    TRIAL_INFO = """
🎁 **Free Trial Package**

📊 *500 MB Data*
⏱ *1 Hour Duration*
🔒 *1 IP Limit*

Click the button below to start your free trial! 🚀
    """
    
    TRIAL_EXISTS = """
⚠️ **You already have an active trial!**

Your trial will expire at: `{expiry}`

Please wait for it to expire before requesting a new trial.
    """
    
    TRIAL_CREATED = """
✅ **Trial Created Successfully!**

📋 *Trial Details:*
━━━━━━━━━━━━━━━━━━━
🆔 User ID: `{user_id}`
📱 Username: @{username}
📊 Data Limit: 500 MB
⏱ Duration: 1 Hour
🔑 UUID: `{uuid}`
━━━━━━━━━━━━━━━━━━━

Download your config file below ⬇️
    """
    
    PREMIUM_ORDER = """
💎 **Premium VPN Package**

Please enter the amount of data you need (in GB) 📊

*Minimum: 20 GB*
*Maximum: 1000 GB*

Type the number of GB you want: 📝
    """
    
    PREMIUM_IP = """
📱 **IP Configuration**

How many IPs do you need? 🔒

*Current Price:*
━━━━━━━━━━━━━━━━━━━
📊 Data: {data} GB = {data_price}
🔒 Extra IPs: {ip_count} = {ip_price}
━━━━━━━━━━━━━━━━━━━
💰 Total: {total}

Type the number of IPs (minimum 1): 📝
    """
    
    PREMIUM_SUMMARY = """
📋 **Order Summary**

━━━━━━━━━━━━━━━━━━━
📊 Data: {data} GB
🔒 IPs: {ip_count}
💰 Total: {total}
━━━━━━━━━━━━━━━━━━━

Please confirm your order ✅

Click *Confirm* to proceed with payment 💳
    """
    
    PAYMENT_METHODS = """
💳 **Payment Methods**

Select your preferred payment method:

1️⃣ bKash
2️⃣ Nagad
3️⃣ Binance
4️⃣ Custom Payment

Choose an option below: 📝
    """
    
    PAYMENT_DETAILS = """
💳 **Payment Instructions**

🏦 {bank_name}: {bank_number}

💰 Amount: {amount}

After sending payment, please provide:
1. Transaction ID
2. Sender Number
3. Screenshot (optional)

Click *Submit Payment* after sending 💰
    """
    
    PAYMENT_SUBMITTED = """
✅ **Payment Submitted Successfully!**

📋 *Payment Details:*
━━━━━━━━━━━━━━━━━━━
🆔 Order ID: `{order_id}`
💰 Amount: {amount}
💳 Method: {method}
📱 Sender: {sender}
🆔 Transaction: {transaction_id}
━━━━━━━━━━━━━━━━━━━

⏳ *Waiting for admin approval...*

You will be notified once your order is approved! 📨
    """
    
    PAYMENT_APPROVED = """
✅ **Payment Approved!**

🎉 Your premium package is now active!

📋 *Package Details:*
━━━━━━━━━━━━━━━━━━━
📊 Data: {data} GB
🔒 IPs: {ip_count}
⏱ Expiry: {expiry}
━━━━━━━━━━━━━━━━━━━

Download your config file below ⬇️
    """
    
    PAYMENT_DECLINED = """
❌ **Payment Declined**

Your payment for order `{order_id}` has been declined.

Reason: {reason}

Please contact support for more information.
    """
    
    MY_INFO = """
👤 **My Information**

━━━━━━━━━━━━━━━━━━━
🆔 User ID: `{user_id}`
📱 Username: @{username}
📅 Joined: {joined_date}
━━━━━━━━━━━━━━━━━━━

🎁 *Trial Status:* {trial_status}
💎 *Premium Status:* {premium_status}
📊 *Used Data:* {used_data}
📈 *Remaining Data:* {remaining_data}
⏱ *Expiry Date:* {expiry_date}
━━━━━━━━━━━━━━━━━━━
    """
    
    REFERRAL_INFO = """
👥 **Refer & Earn**

📋 *Your Referral Link:*
`{referral_link}`

📊 *Referral Stats:*
━━━━━━━━━━━━━━━━━━━
👤 Total Referrals: {count}
🎯 Reward Progress: {progress}/{target}
━━━━━━━━━━━━━━━━━━━

🎁 *Reward Details:*
━━━━━━━━━━━━━━━━━━━
📊 {reward_gb} GB Data
🔒 {reward_ip} IP
⏱ {reward_days} Days
━━━━━━━━━━━━━━━━━━━

Share your referral link and earn rewards! 🚀
    """
    
    REFERRAL_REWARD_CLAIMED = """
🎉 **Congratulations!**

You have successfully claimed your referral reward!

📋 *Reward Details:*
━━━━━━━━━━━━━━━━━━━
📊 {reward_gb} GB Data
🔒 {reward_ip} IP
⏱ {reward_days} Days
━━━━━━━━━━━━━━━━━━━

Your reward has been added to your account! 🎊
    """
    
    REDEEM_INFO = """
🎟 **Redeem Code**

Please enter your redeem code to claim your reward! 🎁

Type your redeem code below: 📝
    """
    
    REDEEM_SUCCESS = """
✅ **Redeem Code Applied Successfully!**

🎉 You have received:

📋 *Reward Details:*
━━━━━━━━━━━━━━━━━━━
📊 {data_gb} GB Data
🔒 {ip_count} IP
━━━━━━━━━━━━━━━━━━━

Your reward has been added to your account! 🎊
    """
    
    REDEEM_INVALID = """
❌ **Invalid Redeem Code**

The code you entered is invalid or has already been used.

Please check and try again.
    """
    
    SUPPORT = """
🛟 **Support**

━━━━━━━━━━━━━━━━━━━
👑 Owner: @{owner}
🛠 Support: @{support}
📢 Channel: @{channel}
👥 Group: @{group}
━━━━━━━━━━━━━━━━━━━

Feel free to reach out for any assistance! 🤝
    """
    
    ADMIN_PANEL = """
🔐 **Admin Panel**

Welcome, {admin_name}! 👋

Choose an option below:
━━━━━━━━━━━━━━━━━━━
📤 Upload File
📦 Pending Orders
📢 Broadcast
📊 Statistics
━━━━━━━━━━━━━━━━━━━
    """
    
    STATISTICS = """
📊 **Bot Statistics**

━━━━━━━━━━━━━━━━━━━
👥 Total Users: {total_users}
🆕 Today's Users: {today_users}
━━━━━━━━━━━━━━━━━━━
🎁 Trial Users: {trial_users}
💎 Premium Users: {premium_users}
━━━━━━━━━━━━━━━━━━━
📦 Pending Orders: {pending_orders}
✅ Completed Orders: {completed_orders}
💰 Revenue: {revenue}
━━━━━━━━━━━━━━━━━━━
🎟 Referral Claims: {referral_claims}
🎫 Redeem Claims: {redeem_claims}
━━━━━━━━━━━━━━━━━━━
    """
    
    OWNER_PANEL = """
👑 **Owner Panel**

Welcome, Owner! 👋

Additional Permissions:
━━━━━━━━━━━━━━━━━━━
👥 Add Admin
🗑 Remove Admin
💾 Database Backup
🔄 Database Restore
━━━━━━━━━━━━━━━━━━━
    """
    
    FILE_UPLOAD_PROMPT = """
📤 **Upload Config File**

Please upload the config file that will be sent to users when they get a VPN package.

*Supported formats:*
• Document (.txt, .json, .conf)
• Photo
• Video

Also send a caption with the file.
    """
    
    FILE_UPLOAD_SUCCESS = """
✅ **File Uploaded Successfully!**

File has been stored in the database and will be sent to all new VPN users.
    """
    
    BROADCAST_PROMPT = """
📢 **Broadcast Message**

Send the message you want to broadcast to all users.

*Supported formats:*
• Text
• Photo
• Video
• Document

This will be sent to ALL users.
    """
    
    BROADCAST_PROGRESS = """
📢 **Broadcast in Progress...**

📊 Total Users: {total}
✅ Sent: {sent}
❌ Failed: {failed}
    """
    
    BROADCAST_COMPLETE = """
✅ **Broadcast Complete!**

📊 Total Users: {total}
✅ Sent: {sent}
❌ Failed: {failed}
    """
    
    ADD_ADMIN_PROMPT = """
👥 **Add Admin**

Please provide the Telegram ID of the user you want to make an admin.

Type the user ID: 📝
    """
    
    REMOVE_ADMIN_PROMPT = """
🗑 **Remove Admin**

Please provide the Telegram ID of the admin you want to remove.

Type the user ID: 📝
    """
    
    ADMIN_ADDED = """
✅ **Admin Added Successfully!**

User `{user_id}` is now an admin.
    """
    
    ADMIN_REMOVED = """
✅ **Admin Removed Successfully!**

User `{user_id}` is no longer an admin.
    """
    
    USER_NOT_FOUND = """
❌ **User Not Found**

No user found with ID: `{user_id}`
    """
    
    RENEW_NOTIFICATION = """
⏰ **Subscription Expiry Reminder**

Your premium subscription will expire on: `{expiry}`

Would you like to renew your subscription? 🔄

Click *Yes* to renew or *No* to cancel.
    """
    
    RENEW_CONFIRM = """
✅ **Renewal Initiated**

Please proceed with the payment process to renew your subscription.

You will receive your new package details upon approval.
    """
    
    RENEW_CANCELED = """
❌ **Renewal Canceled**

Your subscription will not be renewed.

You can purchase a new package anytime from the main menu.
    """
    
    PREMIUM_EXPIRED = """
⏰ **Subscription Expired**

Your premium subscription has expired.

You can purchase a new package from the main menu.
    """
    
    TRIAL_EXPIRED = """
⏰ **Trial Expired**

Your free trial has expired.

You can purchase a premium package from the main menu.
    """
    
    ERROR = """
❌ **An error occurred**

Please try again later or contact support.

Error: {error}
    """
    
    INVALID_INPUT = """
❌ **Invalid Input**

Please enter a valid value.

{details}
    """

# ===================================================================
# CONVERSATION STATES
# ===================================================================

(
    MAIN_MENU,
    TRIAL_CONFIRM,
    PREMIUM_DATA,
    PREMIUM_IP,
    PREMIUM_CONFIRM,
    PAYMENT_METHOD,
    PAYMENT_DETAILS,
    PAYMENT_TRANSACTION_ID,
    PAYMENT_SENDER_NUMBER,
    PAYMENT_SCREENSHOT,
    REDEEM_CODE,
    ADMIN_ADD,
    ADMIN_REMOVE,
    BROADCAST_MESSAGE,
    FILE_UPLOAD,
    RENEW_CONFIRM
) = range(16)

# ===================================================================
# BOT HANDLERS
# ===================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = create_or_update_user(update)
    
    # Check if user was referred
    if update.effective_message.text and len(update.effective_message.text.split()) > 1:
        ref_code = update.effective_message.text.split()[1]
        db = next(get_db())
        referrer = db.query(User).filter(User.referral_code == ref_code).first()
        if referrer and referrer.telegram_id != user.telegram_id:
            # Check if referral already exists
            existing = db.query(Referral).filter(
                Referral.referrer_id == referrer.id,
                Referral.referred_id == user.id
            ).first()
            if not existing:
                referral = Referral(
                    referrer_id=referrer.id,
                    referred_id=user.id
                )
                db.add(referral)
                db.commit()
                
                # Check reward threshold
                referral_count = db.query(Referral).filter(
                    Referral.referrer_id == referrer.id,
                    Referral.rewarded == False
                ).count()
                
                if referral_count >= Config.REFERRAL_REWARD_COUNT:
                    # Create reward premium
                    reward_premium = PremiumClient(
                        user_id=referrer.id,
                        panel_client_id=f"reward-{generate_uuid()}",
                        uuid=generate_uuid(),
                        data_limit=Config.REFERRAL_REWARD_GB,
                        ip_count=Config.REFERRAL_REWARD_IP,
                        expiry_at=datetime.now(pytz.UTC) + timedelta(days=Config.REFERRAL_REWARD_DAYS),
                        is_active=True
                    )
                    db.add(reward_premium)
                    db.commit()
                    
                    # Mark referrals as rewarded
                    db.query(Referral).filter(
                        Referral.referrer_id == referrer.id,
                        Referral.rewarded == False
                    ).update({Referral.rewarded: True})
                    db.commit()
                    
                    # Notify referrer
                    try:
                        await context.bot.send_message(
                            chat_id=referrer.telegram_id,
                            text=Messages.REFERRAL_REWARD_CLAIMED.format(
                                reward_gb=Config.REFERRAL_REWARD_GB,
                                reward_ip=Config.REFERRAL_REWARD_IP,
                                reward_days=Config.REFERRAL_REWARD_DAYS
                            ),
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass
        db.close()
    
    # Send welcome message with main menu
    await update.message.reply_text(
        Messages.HOME,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )
    
    # Log activity
    log_activity(user.telegram_id, "start", {"username": user.username})

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button presses"""
    text = update.message.text
    
    if text == "🎁 Free Trial":
        await start_trial(update, context)
    elif text == "💎 Buy Premium":
        await start_premium(update, context)
    elif text == "👤 My Info":
        await show_my_info(update, context)
    elif text == "👥 Refer & Earn":
        await show_referral(update, context)
    elif text == "🎟 Redeem Code":
        await start_redeem(update, context)
    elif text == "🛟 Support":
        await show_support(update, context)
    elif text == "🔙 Back to Main Menu":
        await update.message.reply_text(
            Messages.HOME,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu()
        )

# ===================================================================
# TRIAL HANDLERS
# ===================================================================

async def start_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start free trial process"""
    user = get_user_from_db(update.effective_user.id)
    
    if not user:
        user = create_or_update_user(update)
    
    # Check for existing active trial
    db = next(get_db())
    existing_trial = db.query(TrialClient).filter(
        TrialClient.user_id == user.id,
        TrialClient.is_active == True
    ).first()
    db.close()
    
    if existing_trial:
        await update.message.reply_text(
            Messages.TRIAL_EXISTS.format(
                expiry=existing_trial.expiry_at.strftime('%Y-%m-%d %H:%M')
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Create trial in panel
    client_id, client_uuid, client_data = panel.create_client(
        inbound_id=Config.TRIAL_INBOUND,
        data_limit_mb=Config.TRIAL_DATA,
        expiry_days=Config.TRIAL_DURATION_HOURS / 24,  # Convert hours to days
        ip_count=1,
        remark=f"Trial-{user.telegram_id}"
    )
    
    if not client_id:
        await update.message.reply_text(
            Messages.ERROR.format(error="Failed to create trial. Please contact support."),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Save trial in database
    db = next(get_db())
    trial = TrialClient(
        user_id=user.id,
        panel_client_id=client_id,
        uuid=client_uuid,
        data_limit=Config.TRIAL_DATA,
        expiry_at=datetime.now(pytz.UTC) + timedelta(hours=Config.TRIAL_DURATION_HOURS),
        is_active=True
    )
    db.add(trial)
    db.commit()
    db.close()
    
    # Get uploaded file and send to user
    await send_config_file(update, context, user, client_uuid, "trial")
    
    # Log activity
    log_activity(user.telegram_id, "trial_created", {"client_id": client_id})

async def send_config_file(update: Update, context: ContextTypes.DEFAULT_TYPE, user, uuid_value, package_type):
    """Send config file to user with replaced placeholders"""
    db = next(get_db())
    uploaded_file = db.query(UploadedFile).filter(
        UploadedFile.is_active == True
    ).order_by(UploadedFile.uploaded_at.desc()).first()
    db.close()
    
    if not uploaded_file:
        # Send fallback message if no file uploaded
        if package_type == "trial":
            await update.message.reply_text(
                Messages.TRIAL_CREATED.format(
                    user_id=user.telegram_id,
                    username=user.username or "User",
                    uuid=uuid_value
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                Messages.PAYMENT_APPROVED.format(
                    data=context.user_data.get('premium_data', 0),
                    ip_count=context.user_data.get('premium_ip', 1),
                    expiry=(datetime.now(pytz.UTC) + timedelta(days=30)).strftime('%Y-%m-%d %H:%M')
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Replace placeholders in caption
    caption = replace_placeholders(
        uploaded_file.caption,
        {
            "uuid": uuid_value,
            "password": uuid_value,
            "user_id": user.telegram_id,
            "username": user.username or "User"
        }
    )
    
    # Send file based on type
    try:
        if uploaded_file.file_type == 'document':
            await context.bot.send_document(
                chat_id=user.telegram_id,
                document=uploaded_file.file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        elif uploaded_file.file_type == 'photo':
            await context.bot.send_photo(
                chat_id=user.telegram_id,
                photo=uploaded_file.file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
        elif uploaded_file.file_type == 'video':
            await context.bot.send_video(
                chat_id=user.telegram_id,
                video=uploaded_file.file_id,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logging.error(f"Error sending config file: {e}")
        # Send text fallback
        if package_type == "trial":
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=Messages.TRIAL_CREATED.format(
                    user_id=user.telegram_id,
                    username=user.username or "User",
                    uuid=uuid_value
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=Messages.PAYMENT_APPROVED.format(
                    data=context.user_data.get('premium_data', 0),
                    ip_count=context.user_data.get('premium_ip', 1),
                    expiry=(datetime.now(pytz.UTC) + timedelta(days=30)).strftime('%Y-%m-%d %H:%M')
                ),
                parse_mode=ParseMode.MARKDOWN
            )

# ===================================================================
# PREMIUM HANDLERS
# ===================================================================

async def start_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start premium purchase process"""
    context.user_data['premium_data'] = None
    context.user_data['premium_ip'] = 1
    context.user_data['premium_order'] = None
    
    await update.message.reply_text(
        Messages.PREMIUM_ORDER,
        parse_mode=ParseMode.MARKDOWN
    )
    return PREMIUM_DATA

async def handle_premium_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle data GB input"""
    try:
        data_gb = float(update.message.text)
        if data_gb < 20:
            await update.message.reply_text(
                "❌ Minimum data is 20 GB. Please enter a value of at least 20.",
                parse_mode=ParseMode.MARKDOWN
            )
            return PREMIUM_DATA
        if data_gb > 1000:
            await update.message.reply_text(
                "❌ Maximum data is 1000 GB. Please enter a value of at most 1000.",
                parse_mode=ParseMode.MARKDOWN
            )
            return PREMIUM_DATA
        
        context.user_data['premium_data'] = data_gb
        
        # Show IP configuration
        data_price = calculate_price(data_gb, 1)
        await update.message.reply_text(
            Messages.PREMIUM_IP.format(
                data=data_gb,
                data_price=format_currency(data_price),
                ip_count=1,
                ip_price=format_currency(0),
                total=format_currency(data_price)
            ),
            parse_mode=ParseMode.MARKDOWN
        )
        return PREMIUM_IP
    except ValueError:
        await update.message.reply_text(
            Messages.INVALID_INPUT.format(details="Please enter a valid number."),
            parse_mode=ParseMode.MARKDOWN
        )
        return PREMIUM_DATA

async def handle_premium_ip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle IP count input"""
    try:
        ip_count = int(update.message.text)
        if ip_count < 1:
            await update.message.reply_text(
                "❌ Minimum IP count is 1.",
                parse_mode=ParseMode.MARKDOWN
            )
            return PREMIUM_IP
        if ip_count > 10:
            await update.message.reply_text(
                "❌ Maximum IP count is 10.",
                parse_mode=ParseMode.MARKDOWN
            )
            return PREMIUM_IP
        
        context.user_data['premium_ip'] = ip_count
        data_gb = context.user_data['premium_data']
        total_price = calculate_price(data_gb, ip_count)
        data_price = calculate_price(data_gb, 1)
        ip_price = total_price - data_price
        
        # Show order summary with confirmation buttons
        summary_text = Messages.PREMIUM_SUMMARY.format(
            data=data_gb,
            ip_count=ip_count,
            total=format_currency(total_price)
        )
        
        await update.message.reply_text(
            summary_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_order_confirmation_keyboard()
        )
        return PREMIUM_CONFIRM
    except ValueError:
        await update.message.reply_text(
            Messages.INVALID_INPUT.format(details="Please enter a valid number."),
            parse_mode=ParseMode.MARKDOWN
        )
        return PREMIUM_IP

async def handle_order_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle order confirmation"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_order":
        await query.edit_message_text(
            "❌ Order canceled. You can start a new order anytime.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    # Proceed with payment
    await show_payment_methods(query, context)
    return PAYMENT_METHOD

async def show_payment_methods(query, context):
    """Show payment methods to user"""
    await query.edit_message_text(
        Messages.PAYMENT_METHODS,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_payment_methods_keyboard()
    )

async def handle_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment method selection"""
    query = update.callback_query
    await query.answer()
    
    method = query.data.replace('payment_', '')
    context.user_data['payment_method'] = method
    
    data_gb = context.user_data['premium_data']
    ip_count = context.user_data['premium_ip']
    total_price = calculate_price(data_gb, ip_count)
    
    # Get payment details from database
    db = next(get_db())
    payment_details = db.query(AdminSetting).filter(
        AdminSetting.key == f'payment_{method}'
    ).first()
    db.close()
    
    if payment_details:
        details = json.loads(payment_details.value)
        bank_name = details.get('name', method.capitalize())
        bank_number = details.get('number', 'N/A')
    else:
        bank_name = method.capitalize()
        bank_number = 'Please contact support for payment details'
    
    await query.edit_message_text(
        Messages.PAYMENT_DETAILS.format(
            bank_name=bank_name,
            bank_number=bank_number,
            amount=format_currency(total_price)
        ),
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Ask for transaction ID
    await query.message.reply_text(
        "📝 Please enter your **Transaction ID**:",
        parse_mode=ParseMode.MARKDOWN
    )
    return PAYMENT_TRANSACTION_ID

async def handle_payment_transaction_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle transaction ID input"""
    context.user_data['transaction_id'] = update.message.text
    
    await update.message.reply_text(
        "📱 Please enter your **Sender Number**:",
        parse_mode=ParseMode.MARKDOWN
    )
    return PAYMENT_SENDER_NUMBER

async def handle_payment_sender_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle sender number input"""
    context.user_data['sender_number'] = update.message.text
    
    await update.message.reply_text(
        "📸 Please send a **screenshot** of the payment (optional).\n\n"
        "Send /skip to skip.",
        parse_mode=ParseMode.MARKDOWN
    )
    return PAYMENT_SCREENSHOT

async def handle_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment screenshot"""
    screenshot = None
    if update.message.photo:
        screenshot = update.message.photo[-1].file_id
    elif update.message.document:
        screenshot = update.message.document.file_id
    
    context.user_data['screenshot'] = screenshot
    
    # Create payment record
    user = get_user_from_db(update.effective_user.id)
    data_gb = context.user_data['premium_data']
    ip_count = context.user_data['premium_ip']
    total_price = calculate_price(data_gb, ip_count)
    order_id = generate_order_id()
    
    db = next(get_db())
    payment = Payment(
        user_id=user.id,
        order_id=order_id,
        amount=total_price,
        method=context.user_data['payment_method'],
        transaction_id=context.user_data['transaction_id'],
        sender_number=context.user_data['sender_number'],
        screenshot=screenshot,
        data_gb=data_gb,
        ip_count=ip_count,
        status='pending'
    )
    db.add(payment)
    db.commit()
    db.close()
    
    # Notify user
    await update.message.reply_text(
        Messages.PAYMENT_SUBMITTED.format(
            order_id=order_id,
            amount=format_currency(total_price),
            method=context.user_data['payment_method'],
            sender=context.user_data['sender_number'],
            transaction_id=context.user_data['transaction_id']
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )
    
    # Notify admins
    await notify_admins(context.bot, payment)
    
    # Log activity
    log_activity(user.telegram_id, "payment_submitted", {"order_id": order_id})
    
    context.user_data.clear()
    return ConversationHandler.END

async def skip_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip screenshot upload"""
    context.user_data['screenshot'] = None
    
    # Create payment record
    user = get_user_from_db(update.effective_user.id)
    data_gb = context.user_data['premium_data']
    ip_count = context.user_data['premium_ip']
    total_price = calculate_price(data_gb, ip_count)
    order_id = generate_order_id()
    
    db = next(get_db())
    payment = Payment(
        user_id=user.id,
        order_id=order_id,
        amount=total_price,
        method=context.user_data['payment_method'],
        transaction_id=context.user_data['transaction_id'],
        sender_number=context.user_data['sender_number'],
        screenshot=None,
        data_gb=data_gb,
        ip_count=ip_count,
        status='pending'
    )
    db.add(payment)
    db.commit()
    db.close()
    
    # Notify user
    await update.message.reply_text(
        Messages.PAYMENT_SUBMITTED.format(
            order_id=order_id,
            amount=format_currency(total_price),
            method=context.user_data['payment_method'],
            sender=context.user_data['sender_number'],
            transaction_id=context.user_data['transaction_id']
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )
    
    # Notify admins
    await notify_admins(context.bot, payment)
    
    # Log activity
    log_activity(user.telegram_id, "payment_submitted", {"order_id": order_id})
    
    context.user_data.clear()
    return ConversationHandler.END

async def notify_admins(bot, payment):
    """Notify admins about new payment"""
    db = next(get_db())
    admins = db.query(User).filter(
        (User.is_admin == True) | (User.is_owner == True)
    ).all()
    db.close()
    
    user = get_user_from_db(payment.user_id)
    
    message = f"""
📋 **New Payment Pending**

━━━━━━━━━━━━━━━━━━━
🆔 Order ID: `{payment.order_id}`
👤 User: @{user.username or 'N/A'} ({user.telegram_id})
💰 Amount: {format_currency(payment.amount)}
💳 Method: {payment.method}
📱 Sender: {payment.sender_number}
🆔 Transaction: {payment.transaction_id}
📊 Data: {payment.data_gb} GB
🔒 IPs: {payment.ip_count}
━━━━━━━━━━━━━━━━━━━

Click to approve or decline:
    """
    
    for admin in admins:
        try:
            await bot.send_message(
                chat_id=admin.telegram_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_pending_order_keyboard(payment.order_id)
            )
        except:
            pass

# ===================================================================
# PAYMENT APPROVAL HANDLERS
# ===================================================================

async def handle_payment_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment approval/decline"""
    query = update.callback_query
    await query.answer()
    
    action, order_id = query.data.split('_', 1)
    
    db = next(get_db())
    payment = db.query(Payment).filter(Payment.order_id == order_id).first()
    
    if not payment:
        await query.edit_message_text(
            "❌ Payment not found.",
            parse_mode=ParseMode.MARKDOWN
        )
        db.close()
        return
    
    if action == "approve":
        # Create premium client
        client_id, client_uuid, client_data = panel.create_client(
            inbound_id=Config.PREMIUM_INBOUND,
            data_limit_mb=payment.data_gb * 1024,  # Convert GB to MB
            expiry_days=30,  # 30 days subscription
            ip_count=payment.ip_count,
            remark=f"Premium-{payment.user_id}"
        )
        
        if not client_id:
            await query.edit_message_text(
                "❌ Failed to create premium client. Please check panel connection.",
                parse_mode=ParseMode.MARKDOWN
            )
            db.close()
            return
        
        # Save premium client
        premium = PremiumClient(
            user_id=payment.user_id,
            panel_client_id=client_id,
            uuid=client_uuid,
            data_limit=payment.data_gb,
            ip_count=payment.ip_count,
            expiry_at=datetime.now(pytz.UTC) + timedelta(days=30),
            is_active=True
        )
        db.add(premium)
        db.commit()
        
        # Update payment
        payment.status = 'approved'
        payment.approved_at = datetime.now(pytz.UTC)
        payment.premium_client_id = premium.id
        db.commit()
        
        # Get user and send config
        user = db.query(User).filter(User.id == payment.user_id).first()
        db.close()
        
        if user:
            await send_config_file_for_user(
                context.bot, 
                user, 
                client_uuid, 
                payment.data_gb, 
                payment.ip_count,
                30  # days
            )
        
        await query.edit_message_text(
            f"✅ Payment approved! Premium package created for user.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=user.telegram_id,
                text=Messages.PAYMENT_APPROVED.format(
                    data=payment.data_gb,
                    ip_count=payment.ip_count,
                    expiry=(datetime.now(pytz.UTC) + timedelta(days=30)).strftime('%Y-%m-%d %H:%M')
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
        
        log_activity(user.telegram_id, "payment_approved", {"order_id": order_id})
        
    elif action == "decline":
        payment.status = 'declined'
        db.commit()
        db.close()
        
        await query.edit_message_text(
            f"❌ Payment declined.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Notify user
        user = get_user_from_db(payment.user_id)
        if user:
            try:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=Messages.PAYMENT_DECLINED.format(
                        order_id=order_id,
                        reason="Please check your payment details and try again."
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
        
        log_activity(payment.user_id, "payment_declined", {"order_id": order_id})

async def send_config_file_for_user(bot, user, uuid_value, data_gb, ip_count, days):
    """Send config file to user after payment approval"""
    db = next(get_db())
    uploaded_file = db.query(UploadedFile).filter(
        UploadedFile.is_active == True
    ).order_by(UploadedFile.uploaded_at.desc()).first()
    db.close()
    
    caption = Messages.PAYMENT_APPROVED.format(
        data=data_gb,
        ip_count=ip_count,
        expiry=(datetime.now(pytz.UTC) + timedelta(days=days)).strftime('%Y-%m-%d %H:%M')
    )
    
    if uploaded_file:
        caption = replace_placeholders(
            uploaded_file.caption,
            {
                "uuid": uuid_value,
                "password": uuid_value,
                "user_id": user.telegram_id,
                "username": user.username or "User",
                "data": data_gb,
                "ip_count": ip_count,
                "expiry": (datetime.now(pytz.UTC) + timedelta(days=days)).strftime('%Y-%m-%d %H:%M')
            }
        )
        
        try:
            if uploaded_file.file_type == 'document':
                await bot.send_document(
                    chat_id=user.telegram_id,
                    document=uploaded_file.file_id,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif uploaded_file.file_type == 'photo':
                await bot.send_photo(
                    chat_id=user.telegram_id,
                    photo=uploaded_file.file_id,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif uploaded_file.file_type == 'video':
                await bot.send_video(
                    chat_id=user.telegram_id,
                    video=uploaded_file.file_id,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            logging.error(f"Error sending config file: {e}")
            await bot.send_message(
                chat_id=user.telegram_id,
                text=caption,
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await bot.send_message(
            chat_id=user.telegram_id,
            text=caption,
            parse_mode=ParseMode.MARKDOWN
        )

# ===================================================================
# MY INFO HANDLER
# ===================================================================

async def show_my_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user information"""
    user = get_user_from_db(update.effective_user.id)
    
    if not user:
        user = create_or_update_user(update)
    
    db = next(get_db())
    
    # Get trial status
    trial = db.query(TrialClient).filter(
        TrialClient.user_id == user.id,
        TrialClient.is_active == True
    ).first()
    
    # Get premium status
    premium = db.query(PremiumClient).filter(
        PremiumClient.user_id == user.id,
        PremiumClient.is_active == True
    ).first()
    
    # Calculate used and remaining data
    used_data = "0 B"
    remaining_data = "0 B"
    expiry_date = "No active subscription"
    
    if trial:
        used_data = format_bytes(trial.used_data * 1024 * 1024)  # Convert MB to bytes
        remaining_data = format_bytes((trial.data_limit - trial.used_data) * 1024 * 1024)
        expiry_date = trial.expiry_at.strftime('%Y-%m-%d %H:%M')
    elif premium:
        used_data = format_bytes(premium.used_data * 1024 * 1024 * 1024)  # Convert GB to bytes
        remaining_data = format_bytes((premium.data_limit - premium.used_data) * 1024 * 1024 * 1024)
        expiry_date = premium.expiry_at.strftime('%Y-%m-%d %H:%M')
    
    trial_status = "✅ Active" if trial else "❌ Inactive"
    premium_status = "✅ Active" if premium else "❌ Inactive"
    
    db.close()
    
    await update.message.reply_text(
        Messages.MY_INFO.format(
            user_id=user.telegram_id,
            username=user.username or "User",
            joined_date=user.joined_date.strftime('%Y-%m-%d'),
            trial_status=trial_status,
            premium_status=premium_status,
            used_data=used_data,
            remaining_data=remaining_data,
            expiry_date=expiry_date
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )

# ===================================================================
# REFERRAL HANDLER
# ===================================================================

async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show referral information"""
    user = get_user_from_db(update.effective_user.id)
    
    if not user:
        user = create_or_update_user(update)
    
    db = next(get_db())
    
    # Get referral count
    referral_count = db.query(Referral).filter(
        Referral.referrer_id == user.id,
        Referral.rewarded == False
    ).count()
    
    progress = min(referral_count, Config.REFERRAL_REWARD_COUNT)
    
    referral_link = f"https://t.me/{context.bot.username}?start={user.referral_code}"
    
    db.close()
    
    await update.message.reply_text(
        Messages.REFERRAL_INFO.format(
            referral_link=referral_link,
            count=referral_count,
            progress=progress,
            target=Config.REFERRAL_REWARD_COUNT,
            reward_gb=Config.REFERRAL_REWARD_GB,
            reward_ip=Config.REFERRAL_REWARD_IP,
            reward_days=Config.REFERRAL_REWARD_DAYS
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )

# ===================================================================
# REDEEM CODE HANDLER
# ===================================================================

async def start_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start redeem code process"""
    await update.message.reply_text(
        Messages.REDEEM_INFO,
        parse_mode=ParseMode.MARKDOWN
    )
    return REDEEM_CODE

async def handle_redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle redeem code input"""
    code = update.message.text.strip().upper()
    
    db = next(get_db())
    redeem = db.query(RedeemCode).filter(
        RedeemCode.code == code,
        RedeemCode.is_used == False
    ).first()
    
    if not redeem:
        db.close()
        await update.message.reply_text(
            Messages.REDEEM_INVALID,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    
    # Mark as used
    redeem.is_used = True
    redeem.used_by = update.effective_user.id
    redeem.used_at = datetime.now(pytz.UTC)
    db.commit()
    
    # Add reward to user
    user = get_user_from_db(update.effective_user.id)
    
    # Create premium client for reward
    client_id, client_uuid, client_data = panel.create_client(
        inbound_id=Config.PREMIUM_INBOUND,
        data_limit_mb=redeem.data_gb * 1024,  # Convert GB to MB
        expiry_days=30,
        ip_count=redeem.ip_count,
        remark=f"Redeem-{user.telegram_id}"
    )
    
    if client_id:
        premium = PremiumClient(
            user_id=user.id,
            panel_client_id=client_id,
            uuid=client_uuid,
            data_limit=redeem.data_gb,
            ip_count=redeem.ip_count,
            expiry_at=datetime.now(pytz.UTC) + timedelta(days=30),
            is_active=True
        )
        db.add(premium)
        db.commit()
    
    db.close()
    
    await update.message.reply_text(
        Messages.REDEEM_SUCCESS.format(
            data_gb=redeem.data_gb,
            ip_count=redeem.ip_count
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )
    
    log_activity(update.effective_user.id, "redeem_used", {"code": code})
    return ConversationHandler.END

# ===================================================================
# SUPPORT HANDLER
# ===================================================================

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show support information"""
    await update.message.reply_text(
        Messages.SUPPORT.format(
            owner=Config.OWNER_ID,
            support=Config.SUPPORT_USERNAME,
            channel=Config.CHANNEL_USERNAME,
            group=Config.GROUP_USERNAME
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu()
    )

# ===================================================================
# ADMIN HANDLERS
# ===================================================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin panel"""
    user = get_user_from_db(update.effective_user.id)
    
    if not user or not (user.is_admin or user.is_owner):
        await update.message.reply_text(
            "❌ You don't have permission to access this panel.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if user.is_owner:
        keyboard = get_owner_menu()
    else:
        keyboard = get_admin_menu()
    
    await update.message.reply_text(
        Messages.ADMIN_PANEL.format(admin_name=user.first_name or "Admin"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin panel actions"""
    text = update.message.text
    user = get_user_from_db(update.effective_user.id)
    
    if not user or not (user.is_admin or user.is_owner):
        await update.message.reply_text(
            "❌ You don't have permission.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if text == "📤 Upload File":
        await update.message.reply_text(
            Messages.FILE_UPLOAD_PROMPT,
            parse_mode=ParseMode.MARKDOWN
        )
        return FILE_UPLOAD
    
    elif text == "📦 Pending Orders":
        await show_pending_orders(update, context)
    
    elif text == "📢 Broadcast":
        await update.message.reply_text(
            Messages.BROADCAST_PROMPT,
            parse_mode=ParseMode.MARKDOWN
        )
        return BROADCAST_MESSAGE
    
    elif text == "📊 Statistics":
        await show_statistics(update, context)
    
    elif text == "👥 Add Admin" and user.is_owner:
        await update.message.reply_text(
            Messages.ADD_ADMIN_PROMPT,
            parse_mode=ParseMode.MARKDOWN
        )
        return ADMIN_ADD
    
    elif text == "🗑 Remove Admin" and user.is_owner:
        await update.message.reply_text(
            Messages.REMOVE_ADMIN_PROMPT,
            parse_mode=ParseMode.MARKDOWN
        )
        return ADMIN_REMOVE
    
    elif text == "💾 Database Backup" and user.is_owner:
        await create_database_backup(update, context)
    
    elif text == "🔄 Database Restore" and user.is_owner:
        await restore_database_backup(update, context)
    
    elif text == "🔙 Back to Main Menu":
        await update.message.reply_text(
            Messages.HOME,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu()
        )

async def show_pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending orders to admin"""
    db = next(get_db())
    pending = db.query(Payment).filter(Payment.status == 'pending').order_by(
        Payment.created_at.desc()
    ).all()
    db.close()
    
    if not pending:
        await update.message.reply_text(
            "📦 No pending orders.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_admin_menu()
        )
        return
    
    for payment in pending[:10]:  # Show last 10
        user = get_user_from_db(payment.user_id)
        message = f"""
📋 **Order Details**

━━━━━━━━━━━━━━━━━━━
🆔 Order ID: `{payment.order_id}`
👤 User: @{user.username or 'N/A'} ({user.telegram_id})
💰 Amount: {format_currency(payment.amount)}
💳 Method: {payment.method}
📱 Sender: {payment.sender_number}
🆔 Transaction: {payment.transaction_id}
📊 Data: {payment.data_gb} GB
🔒 IPs: {payment.ip_count}
━━━━━━━━━━━━━━━━━━━
        """
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_pending_order_keyboard(payment.order_id)
        )
    
    if len(pending) > 10:
        await update.message.reply_text(
            f"📊 Showing 10 of {len(pending)} pending orders.",
            parse_mode=ParseMode.MARKDOWN
        )

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    db = next(get_db())
    
    total_users = db.query(User).filter(User.is_blocked == False).count()
    
    today = datetime.now(pytz.UTC).date()
    today_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=pytz.UTC)
    today_users = db.query(User).filter(User.joined_date >= today_start).count()
    
    trial_users = db.query(TrialClient).filter(TrialClient.is_active == True).count()
    premium_users = db.query(PremiumClient).filter(PremiumClient.is_active == True).count()
    
    pending_orders = db.query(Payment).filter(Payment.status == 'pending').count()
    completed_orders = db.query(Payment).filter(Payment.status == 'approved').count()
    
    revenue = db.query(func.sum(Payment.amount)).filter(Payment.status == 'approved').scalar() or 0
    
    referral_claims = db.query(Referral).filter(Referral.rewarded == True).count()
    redeem_claims = db.query(RedeemCode).filter(RedeemCode.is_used == True).count()
    
    db.close()
    
    await update.message.reply_text(
        Messages.STATISTICS.format(
            total_users=total_users,
            today_users=today_users,
            trial_users=trial_users,
            premium_users=premium_users,
            pending_orders=pending_orders,
            completed_orders=completed_orders,
            revenue=format_currency(revenue),
            referral_claims=referral_claims,
            redeem_claims=redeem_claims
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_admin_menu()
    )

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file upload from admin"""
    user = get_user_from_db(update.effective_user.id)
    
    if not user or not (user.is_admin or user.is_owner):
        await update.message.reply_text(
            "❌ You don't have permission.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    file_id = None
    file_type = None
    
    if update.message.document:
        file_id = update.message.document.file_id
        file_type = 'document'
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        file_type = 'photo'
    elif update.message.video:
        file_id = update.message.video.file_id
        file_type = 'video'
    
    if not file_id:
        await update.message.reply_text(
            "❌ Please send a document, photo, or video.",
            parse_mode=ParseMode.MARKDOWN
        )
        return FILE_UPLOAD
    
    caption = update.message.caption or "VPN Configuration File"
    
    db = next(get_db())
    uploaded_file = UploadedFile(
        file_id=file_id,
        caption=caption,
        uploaded_by=update.effective_user.id,
        file_type=file_type
    )
    db.add(uploaded_file)
    db.commit()
    db.close()
    
    await update.message.reply_text(
        Messages.FILE_UPLOAD_SUCCESS,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_admin_menu()
    )
    
    log_activity(update.effective_user.id, "file_uploaded", {"file_type": file_type})
    return ConversationHandler.END

async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast message"""
    user = get_user_from_db(update.effective_user.id)
    
    if not user or not (user.is_admin or user.is_owner):
        await update.message.reply_text(
            "❌ You don't have permission.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END
    
    # Get all users
    db = next(get_db())
    users = db.query(User).filter(User.is_blocked == False).all()
    db.close()
    
    total = len(users)
    sent = 0
    failed = 0
    
    status_msg = await update.message.reply_text(
        Messages.BROADCAST_PROGRESS.format(total=total, sent=sent, failed=failed),
        parse_mode=ParseMode.MARKDOWN
    )
    
    for user in users:
        try:
            if update.message.text:
                await context.bot.send_message(
                    chat_id=user.telegram_id,
                    text=update.message.text,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif update.message.photo:
                await context.bot.send_photo(
                    chat_id=user.telegram_id,
                    photo=update.message.photo[-1].file_id,
                    caption=update.message.caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif update.message.video:
                await context.bot.send_video(
                    chat_id=user.telegram_id,
                    video=update.message.video.file_id,
                    caption=update.message.caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            elif update.message.document:
                await context.bot.send_document(
                    chat_id=user.telegram_id,
                    document=update.message.document.file_id,
                    caption=update.message.caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            sent += 1
        except:
            failed += 1
        
        # Update progress every 10 users
        if (sent + failed) % 10 == 0:
            await status_msg.edit_text(
                Messages.BROADCAST_PROGRESS.format(total=total, sent=sent, failed=failed),
                parse_mode=ParseMode.MARKDOWN
            )
    
    await status_msg.edit_text(
        Messages.BROADCAST_COMPLETE.format(total=total, sent=sent, failed=failed),
        parse_mode=ParseMode.MARKDOWN
    )
    
    log_activity(update.effective_user.id, "broadcast_sent", {"total": total, "sent": sent, "failed": failed})
    return ConversationHandler.END

async def handle_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle add admin"""
    try:
        admin_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid Telegram ID (numbers only).",
            parse_mode=ParseMode.MARKDOWN
        )
        return ADMIN_ADD
    
    db = next(get_db())
    user = db.query(User).filter(User.telegram_id == admin_id).first()
    
    if not user:
        db.close()
        await update.message.reply_text(
            Messages.USER_NOT_FOUND.format(user_id=admin_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return ADMIN_ADD
    
    user.is_admin = True
    db.commit()
    db.close()
    
    await update.message.reply_text(
        Messages.ADMIN_ADDED.format(user_id=admin_id),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_owner_menu()
    )
    
    log_activity(update.effective_user.id, "admin_added", {"user_id": admin_id})
    return ConversationHandler.END

async def handle_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle remove admin"""
    try:
        admin_id = int(update.message.text)
    except ValueError:
        await update.message.reply_text(
            "❌ Please enter a valid Telegram ID (numbers only).",
            parse_mode=ParseMode.MARKDOWN
        )
        return ADMIN_REMOVE
    
    if admin_id == Config.OWNER_ID:
        await update.message.reply_text(
            "❌ Cannot remove owner from admin list.",
            parse_mode=ParseMode.MARKDOWN
        )
        return ADMIN_REMOVE
    
    db = next(get_db())
    user = db.query(User).filter(User.telegram_id == admin_id).first()
    
    if not user:
        db.close()
        await update.message.reply_text(
            Messages.USER_NOT_FOUND.format(user_id=admin_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return ADMIN_REMOVE
    
    user.is_admin = False
    db.commit()
    db.close()
    
    await update.message.reply_text(
        Messages.ADMIN_REMOVED.format(user_id=admin_id),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_owner_menu()
    )
    
    log_activity(update.effective_user.id, "admin_removed", {"user_id": admin_id})
    return ConversationHandler.END

async def create_database_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create database backup"""
    try:
        import subprocess
        import tempfile
        
        # Get database URL
        db_url = Config.DATABASE_URL
        # Parse database URL (postgresql://user:password@host/dbname)
        import urllib.parse
        parsed = urllib.parse.urlparse(db_url)
        dbname = parsed.path[1:]  # Remove leading '/'
        user = parsed.username
        password = parsed.password
        host = parsed.hostname
        port = parsed.port or 5432
        
        # Create backup using pg_dump
        with tempfile.NamedTemporaryFile(suffix='.sql', delete=False) as f:
            backup_file = f.name
        
        env = os.environ.copy()
        env['PGPASSWORD'] = password
        
        cmd = [
            'pg_dump',
            '-h', host,
            '-p', str(port),
            '-U', user,
            '-F', 'c',  # Custom format (compressed)
            '-f', backup_file,
            dbname
        ]
        
        result = subprocess.run(cmd, env=env, capture_output=True)
        
        if result.returncode == 0:
            # Send backup file
            with open(backup_file, 'rb') as f:
                await context.bot.send_document(
                    chat_id=update.effective_user.id,
                    document=f,
                    filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
                )
            
            os.unlink(backup_file)
            
            await update.message.reply_text(
                "✅ Database backup created successfully!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_owner_menu()
            )
            
            log_activity(update.effective_user.id, "database_backup_created")
        else:
            await update.message.reply_text(
                f"❌ Backup failed: {result.stderr.decode()}",
                parse_mode=ParseMode.MARKDOWN
            )
            
    except Exception as e:
        await update.message.reply_text(
            f"❌ Backup error: {str(e)}",
            parse_mode=ParseMode.MARKDOWN
        )

async def restore_database_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restore database from backup"""
    await update.message.reply_text(
        "🔄 Please send the backup file (.sql) to restore.",
        parse_mode=ParseMode.MARKDOWN
    )
    # This would need a separate handler for file upload

# ===================================================================
# RENEWAL HANDLERS
# ===================================================================

async def check_expired_premiums():
    """Check and handle expired premium subscriptions"""
    db = next(get_db())
    try:
        expired = db.query(PremiumClient).filter(
            PremiumClient.is_active == True,
            PremiumClient.expiry_at <= datetime.now(pytz.UTC),
            PremiumClient.renewal_notified == False
        ).all()
        
        for premium in expired:
            # Notify user about renewal
            user = db.query(User).filter(User.id == premium.user_id).first()
            if user:
                try:
                    # Send renewal notification
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=Messages.RENEW_NOTIFICATION.format(
                            expiry=premium.expiry_at.strftime('%Y-%m-%d %H:%M')
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=get_renew_keyboard()
                    )
                except:
                    pass
            
            premium.renewal_notified = True
            db.commit()
        
        # Delete expired premiums after 3 days
        delete_expired = db.query(PremiumClient).filter(
            PremiumClient.is_active == True,
            PremiumClient.expiry_at <= datetime.now(pytz.UTC) - timedelta(days=3),
            PremiumClient.renewal_notified == True
        ).all()
        
        for premium in delete_expired:
            # Delete from panel
            panel.delete_client(premium.panel_client_id)
            # Deactivate in database
            premium.is_active = False
            db.commit()
            
            user = db.query(User).filter(User.id == premium.user_id).first()
            if user:
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=Messages.PREMIUM_EXPIRED,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
            
            log_activity(user.telegram_id, "premium_expired", {"client_id": premium.panel_client_id})
        
        db.close()
    except Exception as e:
        logging.error(f"Check expired premiums error: {e}")
        db.close()

async def check_expired_trials():
    """Check and handle expired trial clients"""
    db = next(get_db())
    try:
        expired = db.query(TrialClient).filter(
            TrialClient.is_active == True,
            TrialClient.expiry_at <= datetime.now(pytz.UTC)
        ).all()
        
        for trial in expired:
            # Delete from panel
            panel.delete_client(trial.panel_client_id)
            # Deactivate in database
            trial.is_active = False
            db.commit()
            
            user = db.query(User).filter(User.id == trial.user_id).first()
            if user:
                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=Messages.TRIAL_EXPIRED,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except:
                    pass
            
            log_activity(user.telegram_id, "trial_expired", {"client_id": trial.panel_client_id})
        
        db.close()
    except Exception as e:
        logging.error(f"Check expired trials error: {e}")
        db.close()

async def handle_renew_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle renewal action"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "renew_yes":
        await query.edit_message_text(
            Messages.RENEW_CONFIRM,
            parse_mode=ParseMode.MARKDOWN
        )
        # Start new premium purchase process
        await start_premium(query, context)
        return PREMIUM_DATA
    
    elif query.data == "renew_no":
        await query.edit_message_text(
            Messages.RENEW_CANCELED,
            parse_mode=ParseMode.MARKDOWN
        )
        return ConversationHandler.END

# ===================================================================
# SCHEDULER SETUP
# ===================================================================

def setup_scheduler():
    """Setup background scheduler for automated tasks"""
    scheduler = BackgroundScheduler()
    
    # Check expired trials every 5 minutes
    scheduler.add_job(
        check_expired_trials,
        IntervalTrigger(minutes=5),
        id='check_trials'
    )
    
    # Check expired premiums every 5 minutes
    scheduler.add_job(
        check_expired_premiums,
        IntervalTrigger(minutes=5),
        id='check_premiums'
    )
    
    scheduler.start()
    return scheduler

# ===================================================================
# MAIN APPLICATION
# ===================================================================

def main():
    """Main bot application"""
    # Setup logging
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Create application
    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Setup scheduler
    scheduler = setup_scheduler()
    
    # Create conversation handlers
    premium_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^💎 Buy Premium$"), start_premium),
            CallbackQueryHandler(handle_renew_action, pattern="^renew_")
        ],
        states={
            PREMIUM_DATA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_premium_data)
            ],
            PREMIUM_IP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_premium_ip)
            ],
            PREMIUM_CONFIRM: [
                CallbackQueryHandler(handle_order_confirmation, pattern="^(confirm_order|cancel_order)$")
            ],
            PAYMENT_METHOD: [
                CallbackQueryHandler(handle_payment_method, pattern="^payment_")
            ],
            PAYMENT_TRANSACTION_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_transaction_id)
            ],
            PAYMENT_SENDER_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_sender_number)
            ],
            PAYMENT_SCREENSHOT: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, handle_payment_screenshot),
                CommandHandler('skip', skip_screenshot)
            ]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    
    redeem_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🎟 Redeem Code$"), start_redeem)
        ],
        states={
            REDEEM_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_redeem_code)
            ]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    
    admin_conv = ConversationHandler(
        entry_points=[
            CommandHandler('admin', admin_panel)
        ],
        states={
            FILE_UPLOAD: [
                MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_file_upload)
            ],
            BROADCAST_MESSAGE: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_broadcast)
            ],
            ADMIN_ADD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_admin)
            ],
            ADMIN_REMOVE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_remove_admin)
            ]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    
    # Add handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(admin_conv)
    application.add_handler(premium_conv)
    application.add_handler(redeem_conv)
    application.add_handler(MessageHandler(filters.Regex("^🔙 Back to Main Menu$"), handle_main_menu))
    application.add_handler(MessageHandler(filters.Regex("^🎁 Free Trial$"), start_trial))
    application.add_handler(MessageHandler(filters.Regex("^👤 My Info$"), show_my_info))
    application.add_handler(MessageHandler(filters.Regex("^👥 Refer & Earn$"), show_referral))
    application.add_handler(MessageHandler(filters.Regex("^🛟 Support$"), show_support))
    
    # Admin action handlers
    application.add_handler(MessageHandler(
        filters.Regex("^(📤 Upload File|📦 Pending Orders|📢 Broadcast|📊 Statistics|👥 Add Admin|🗑 Remove Admin|💾 Database Backup|🔄 Database Restore)$"),
        handle_admin_actions
    ))
    
    # Payment action handlers
    application.add_handler(CallbackQueryHandler(handle_payment_action, pattern="^(approve_|decline_)"))
    
    # Start bot
    print("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()
