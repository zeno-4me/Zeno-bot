import sqlite3
import math
import time
from datetime import datetime
import discord

class Database:
    """Comprehensive Database Manager for ProBot features."""
    def __init__(self, db_name="bot_data.db"):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        """Initializes database tables for all features."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER DEFAULT 0,
                    welcome_channel_id INTEGER DEFAULT 0,
                    welcome_msg TEXT DEFAULT 'مرحباً بك {user} في سيرفر {server}!',
                    leave_channel_id INTEGER DEFAULT 0,
                    leave_msg TEXT DEFAULT 'وداعاً {user}، نتمنى لك التوفيق!',
                    auto_role_id INTEGER DEFAULT 0,
                    ticket_category_id INTEGER DEFAULT 0,
                    ticket_log_channel_id INTEGER DEFAULT 0,
                    ticket_support_role_id INTEGER DEFAULT 0,
                    text_xp_enabled INTEGER DEFAULT 1,
                    voice_xp_enabled INTEGER DEFAULT 1,
                    text_xp_rate INTEGER DEFAULT 15,
                    voice_xp_rate INTEGER DEFAULT 10,
                    level_up_channel_id INTEGER DEFAULT 0,
                    automod_enabled INTEGER DEFAULT 1,
                    automod_badwords TEXT DEFAULT '',
                    anti_links INTEGER DEFAULT 0,
                    anti_invites INTEGER DEFAULT 0,
                    anti_spam INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS level_rewards (
                    guild_id INTEGER,
                    level INTEGER,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, level)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_levels (
                    guild_id INTEGER,
                    user_id INTEGER,
                    text_xp INTEGER DEFAULT 0,
                    text_level INTEGER DEFAULT 1,
                    voice_xp INTEGER DEFAULT 0,
                    voice_level INTEGER DEFAULT 1,
                    voice_time_seconds INTEGER DEFAULT 0,
                    last_msg_timestamp REAL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    moderator_id INTEGER,
                    reason TEXT,
                    timestamp TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS economy (
                    guild_id INTEGER,
                    user_id INTEGER,
                    credits INTEGER DEFAULT 100,
                    last_daily REAL DEFAULT 0,
                    rep INTEGER DEFAULT 0,
                    last_rep REAL DEFAULT 0,
                    title TEXT DEFAULT 'عضو مميز',
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auto_responses (
                    guild_id INTEGER,
                    trigger_text TEXT,
                    response_text TEXT,
                    PRIMARY KEY (guild_id, trigger_text)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS custom_aliases (
                    guild_id INTEGER,
                    alias TEXT,
                    command_name TEXT,
                    PRIMARY KEY (guild_id, alias)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS button_roles (
                    guild_id INTEGER,
                    button_label TEXT,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, button_label)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    activity_type TEXT, 
                    amount INTEGER,
                    timestamp REAL
                )
            """)

            conn.commit()

    def get_guild_settings(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
                conn.commit()
                return self.get_guild_settings(guild_id)
            return row

    def update_guild_setting(self, guild_id: int, column: str, value):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE guild_settings SET {column} = ? WHERE guild_id = ?", (value, guild_id))
            conn.commit()

    def add_level_reward(self, guild_id: int, level: int, role_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)", (guild_id, level, role_id))
            conn.commit()

    def get_level_rewards(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT level, role_id FROM level_rewards WHERE guild_id = ? ORDER BY level ASC", (guild_id,))
            return cursor.fetchall()

    def get_user_data(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO user_levels (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
                conn.commit()
                return self.get_user_data(guild_id, user_id)
            return row

    def set_user_xp_level(self, guild_id: int, user_id: int, text_xp: int, text_lvl: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE user_levels SET text_xp = ?, text_level = ? WHERE guild_id = ? AND user_id = ?", (text_xp, text_lvl, guild_id, user_id))
            conn.commit()

    def add_text_xp(self, guild_id: int, user_id: int, xp_amount: int):
        data = self.get_user_data(guild_id, user_id)
        current_xp = data[2] + xp_amount
        current_lvl = data[3]
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE user_levels SET text_xp = ?, text_level = ?, last_msg_timestamp = ? WHERE guild_id = ? AND user_id = ?", (current_xp, new_lvl, time.time(), guild_id, user_id))
            conn.commit()
        return leveled_up, new_lvl

    def add_voice_xp(self, guild_id: int, user_id: int, xp_amount: int, time_add: int):
        data = self.get_user_data(guild_id, user_id)
        current_xp = data[4] + xp_amount
        current_lvl = data[5]
        total_time = data[6] + time_add
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE user_levels SET voice_xp = ?, voice_level = ?, voice_time_seconds = ? WHERE guild_id = ? AND user_id = ?", (current_xp, new_lvl, total_time, guild_id, user_id))
            conn.commit()
        return leveled_up, new_lvl

    def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (guild_id, user_id, moderator_id, reason, now_str))
            conn.commit()

    def get_warnings(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, moderator_id, reason, timestamp FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            return cursor.fetchall()

    def clear_warnings(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            conn.commit()

    def get_economy_data(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO economy (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
                conn.commit()
                return self.get_economy_data(guild_id, user_id)
            return row

    def update_credits(self, guild_id: int, user_id: int, amount: int):
        data = self.get_economy_data(guild_id, user_id)
        new_credits = max(0, data[2] + amount)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET credits = ? WHERE guild_id = ? AND user_id = ?", (new_credits, guild_id, user_id))
            conn.commit()
        return new_credits

    def set_daily_claimed(self, guild_id: int, user_id: int, amount: int):
        data = self.get_economy_data(guild_id, user_id)
        new_credits = data[2] + amount
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET credits = ?, last_daily = ? WHERE guild_id = ? AND user_id = ?", (new_credits, time.time(), guild_id, user_id))
            conn.commit()

    def add_rep(self, guild_id: int, target_id: int, sender_id: int):
        target_data = self.get_economy_data(guild_id, target_id)
        new_rep = target_data[4] + 1
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET rep = ? WHERE guild_id = ? AND user_id = ?", (new_rep, guild_id, target_id))
            cursor.execute("UPDATE economy SET last_rep = ? WHERE guild_id = ? AND user_id = ?", (time.time(), guild_id, sender_id))
            conn.commit()

    def set_title(self, guild_id: int, user_id: int, title_text: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET title = ? WHERE guild_id = ? AND user_id = ?", (title_text, guild_id, user_id))
            conn.commit()

    def add_auto_response(self, guild_id: int, trigger: str, response: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO auto_responses (guild_id, trigger_text, response_text) VALUES (?, ?, ?)", (guild_id, trigger.lower(), response))
            conn.commit()

    def get_auto_responses(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT trigger_text, response_text FROM auto_responses WHERE guild_id = ?", (guild_id,))
            return cursor.fetchall()

    def delete_auto_response(self, guild_id: int, trigger: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM auto_responses WHERE guild_id = ? AND trigger_text = ?", (guild_id, trigger.lower()))
            conn.commit()

    def add_custom_alias(self, guild_id: int, alias: str, command_name: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO custom_aliases (guild_id, alias, command_name) VALUES (?, ?, ?)", (guild_id, alias.lower(), command_name.lower()))
            conn.commit()

    def get_custom_aliases(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT alias, command_name FROM custom_aliases WHERE guild_id = ?", (guild_id,))
            return cursor.fetchall()

    def delete_custom_alias(self, guild_id: int, alias: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM custom_aliases WHERE guild_id = ? AND alias = ?", (guild_id, alias.lower()))
            conn.commit()

    def get_command_for_alias(self, guild_id: int, alias: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT command_name FROM custom_aliases WHERE guild_id = ? AND alias = ?", (guild_id, alias.lower()))
            row = cursor.fetchone()
            return row[0] if row else None

    def add_button_role(self, guild_id: int, button_label: str, role_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO button_roles (guild_id, button_label, role_id) VALUES (?, ?, ?)", (guild_id, button_label, role_id))
            conn.commit()

    def get_button_roles(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT button_label, role_id FROM button_roles WHERE guild_id = ?", (guild_id,))
            return cursor.fetchall()

    def log_activity(self, guild_id: int, user_id: int, activity_type: str, amount: int = 1):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO activity_log (guild_id, user_id, activity_type, amount, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (guild_id, user_id, activity_type, amount, time.time()))
            conn.commit()

    def get_timeframe_stats(self, guild_id: int, user_id: int, timeframe: str):
        now = time.time()
        if timeframe == "today":
            start_time = now - 86400
        elif timeframe == "week":
            start_time = now - 604800
        elif timeframe == "month":
            start_time = now - 2592000
        elif timeframe == "year":
            start_time = now - 31536000
        else:
            start_time = 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT activity_type, SUM(amount) 
                FROM activity_log 
                WHERE guild_id = ? AND user_id = ? AND timestamp >= ?
                GROUP BY activity_type
            """, (guild_id, user_id, start_time))
            
            results = cursor.fetchall()
            
        stats = {'text_xp': 0, 'voice_xp': 0, 'image_count': 0, 'video_count': 0, 'video_duration': 0}
        for act_type, total in results:
            if act_type in stats:
                stats[act_type] = total or 0
                
        return stats

db = Database()

def calculate_next_level_xp(level: int) -> int:
    return (level ** 2) * 100

def create_progress_bar(current: int, total: int, length: int = 10) -> str:
    percentage = min(1.0, max(0.0, current / total))
    filled = int(percentage * length)
    return "■" * filled + "□" * (length - filled)

async def check_and_grant_level_roles(guild: discord.Guild, member: discord.Member, new_level: int):
    rewards = db.get_level_rewards(guild.id)
    for lvl, role_id in rewards:
        if new_level >= lvl:
            role = guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="رتبة مكافأة اللفل")
                except Exception:
                    pass
