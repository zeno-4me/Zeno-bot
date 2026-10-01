import asyncpg
import math
import time
from datetime import datetime
import discord
import os

class Database:
    """Comprehensive Database Manager for ProBot features using PostgreSQL."""
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.pool = None

    async def connect(self):
        """Initializes database connection pool."""
        if not self.pool:
            if not self.db_url:
                raise ValueError("DATABASE_URL environment variable is missing!")
            self.pool = await asyncpg.create_pool(self.db_url)
            await self.init_db()

    async def init_db(self):
        """Initializes database tables for all features."""
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id BIGINT PRIMARY KEY,
                    log_channel_id BIGINT DEFAULT 0,
                    welcome_channel_id BIGINT DEFAULT 0,
                    welcome_msg TEXT DEFAULT 'مرحباً بك {user} في سيرفر {server}!',
                    leave_channel_id BIGINT DEFAULT 0,
                    leave_msg TEXT DEFAULT 'وداعاً {user}، نتمنى لك التوفيق!',
                    auto_role_id BIGINT DEFAULT 0,
                    ticket_category_id BIGINT DEFAULT 0,
                    ticket_log_channel_id BIGINT DEFAULT 0,
                    ticket_support_role_id BIGINT DEFAULT 0,
                    text_xp_enabled INT DEFAULT 1,
                    voice_xp_enabled INT DEFAULT 1,
                    text_xp_rate INT DEFAULT 15,
                    voice_xp_rate INT DEFAULT 10,
                    level_up_channel_id BIGINT DEFAULT 0,
                    automod_enabled INT DEFAULT 1,
                    automod_badwords TEXT DEFAULT '',
                    anti_links INT DEFAULT 0,
                    anti_invites INT DEFAULT 0,
                    anti_spam INT DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS level_rewards (
                    guild_id BIGINT,
                    level INT,
                    role_id BIGINT,
                    PRIMARY KEY (guild_id, level)
                );

                CREATE TABLE IF NOT EXISTS user_levels (
                    guild_id BIGINT,
                    user_id BIGINT,
                    text_xp INT DEFAULT 0,
                    text_level INT DEFAULT 1,
                    voice_xp INT DEFAULT 0,
                    voice_level INT DEFAULT 1,
                    voice_time_seconds INT DEFAULT 0,
                    last_msg_timestamp DOUBLE PRECISION DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS warnings (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    moderator_id BIGINT,
                    reason TEXT,
                    timestamp TEXT
                );

                CREATE TABLE IF NOT EXISTS economy (
                    guild_id BIGINT,
                    user_id BIGINT,
                    credits INT DEFAULT 100,
                    last_daily DOUBLE PRECISION DEFAULT 0,
                    rep INT DEFAULT 0,
                    last_rep DOUBLE PRECISION DEFAULT 0,
                    title TEXT DEFAULT 'عضو مميز',
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS auto_responses (
                    guild_id BIGINT,
                    trigger_text TEXT,
                    response_text TEXT,
                    PRIMARY KEY (guild_id, trigger_text)
                );

                CREATE TABLE IF NOT EXISTS custom_aliases (
                    guild_id BIGINT,
                    alias TEXT,
                    command_name TEXT,
                    PRIMARY KEY (guild_id, alias)
                );

                CREATE TABLE IF NOT EXISTS button_roles (
                    guild_id BIGINT,
                    button_label TEXT,
                    role_id BIGINT,
                    PRIMARY KEY (guild_id, button_label)
                );

                CREATE TABLE IF NOT EXISTS activity_log (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    user_id BIGINT,
                    activity_type TEXT, 
                    amount INT,
                    timestamp DOUBLE PRECISION
                );
            """)

    async def get_guild_settings(self, guild_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM guild_settings WHERE guild_id = $1", guild_id)
            if not row:
                await conn.execute("INSERT INTO guild_settings (guild_id) VALUES ($1)", guild_id)
                return await self.get_guild_settings(guild_id)
            return row

    async def update_guild_setting(self, guild_id: int, column: str, value):
        async with self.pool.acquire() as conn:
            await conn.execute(f"UPDATE guild_settings SET {column} = $1 WHERE guild_id = $2", value, guild_id)

    async def add_level_reward(self, guild_id: int, level: int, role_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO level_rewards (guild_id, level, role_id) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, level) DO UPDATE SET role_id = EXCLUDED.role_id
            """, guild_id, level, role_id)

    async def get_level_rewards(self, guild_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT level, role_id FROM level_rewards WHERE guild_id = $1 ORDER BY level ASC", guild_id)

    async def get_user_data(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM user_levels WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
            if not row:
                await conn.execute("INSERT INTO user_levels (guild_id, user_id) VALUES ($1, $2)", guild_id, user_id)
                return await self.get_user_data(guild_id, user_id)
            return row

    async def set_user_xp_level(self, guild_id: int, user_id: int, text_xp: int, text_lvl: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_levels SET text_xp = $1, text_level = $2 WHERE guild_id = $3 AND user_id = $4
            """, text_xp, text_lvl, guild_id, user_id)

    async def add_text_xp(self, guild_id: int, user_id: int, xp_amount: int):
        data = await self.get_user_data(guild_id, user_id)
        current_xp = data['text_xp'] + xp_amount
        current_lvl = data['text_level']
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_levels SET text_xp = $1, text_level = $2, last_msg_timestamp = $3 
                WHERE guild_id = $4 AND user_id = $5
            """, current_xp, new_lvl, time.time(), guild_id, user_id)
        return leveled_up, new_lvl

    async def add_voice_xp(self, guild_id: int, user_id: int, xp_amount: int, time_add: int):
        data = await self.get_user_data(guild_id, user_id)
        current_xp = data['voice_xp'] + xp_amount
        current_lvl = data['voice_level']
        total_time = data['voice_time_seconds'] + time_add
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_levels SET voice_xp = $1, voice_level = $2, voice_time_seconds = $3 
                WHERE guild_id = $4 AND user_id = $5
            """, current_xp, new_lvl, total_time, guild_id, user_id)
        return leveled_up, new_lvl

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str):
        async with self.pool.acquire() as conn:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            await conn.execute("""
                INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp) 
                VALUES ($1, $2, $3, $4, $5)
            """, guild_id, user_id, moderator_id, reason, now_str)

    async def get_warnings(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT id, moderator_id, reason, timestamp FROM warnings 
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)

    async def clear_warnings(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM warnings WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

    async def get_economy_data(self, guild_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM economy WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
            if not row:
                await conn.execute("INSERT INTO economy (guild_id, user_id) VALUES ($1, $2)", guild_id, user_id)
                return await self.get_economy_data(guild_id, user_id)
            return row

    async def update_credits(self, guild_id: int, user_id: int, amount: int):
        data = await self.get_economy_data(guild_id, user_id)
        new_credits = max(0, data['credits'] + amount)
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE economy SET credits = $1 WHERE guild_id = $2 AND user_id = $3", new_credits, guild_id, user_id)
        return new_credits

    async def set_daily_claimed(self, guild_id: int, user_id: int, amount: int):
        data = await self.get_economy_data(guild_id, user_id)
        new_credits = data['credits'] + amount
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE economy SET credits = $1, last_daily = $2 WHERE guild_id = $3 AND user_id = $4
            """, new_credits, time.time(), guild_id, user_id)

    async def add_rep(self, guild_id: int, target_id: int, sender_id: int):
        target_data = await self.get_economy_data(guild_id, target_id)
        new_rep = target_data['rep'] + 1
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE economy SET rep = $1 WHERE guild_id = $2 AND user_id = $3", new_rep, guild_id, target_id)
            await conn.execute("UPDATE economy SET last_rep = $1 WHERE guild_id = $2 AND user_id = $3", time.time(), guild_id, sender_id)

    async def set_title(self, guild_id: int, user_id: int, title_text: str):
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE economy SET title = $1 WHERE guild_id = $2 AND user_id = $3", title_text, guild_id, user_id)

    async def add_auto_response(self, guild_id: int, trigger: str, response: str):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO auto_responses (guild_id, trigger_text, response_text) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, trigger_text) DO UPDATE SET response_text = EXCLUDED.response_text
            """, guild_id, trigger.lower(), response)

    async def get_auto_responses(self, guild_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT trigger_text, response_text FROM auto_responses WHERE guild_id = $1", guild_id)

    async def delete_auto_response(self, guild_id: int, trigger: str):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM auto_responses WHERE guild_id = $1 AND trigger_text = $2", guild_id, trigger.lower())

    async def add_custom_alias(self, guild_id: int, alias: str, command_name: str):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO custom_aliases (guild_id, alias, command_name) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, alias) DO UPDATE SET command_name = EXCLUDED.command_name
            """, guild_id, alias.lower(), command_name.lower())

    async def get_custom_aliases(self, guild_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT alias, command_name FROM custom_aliases WHERE guild_id = $1", guild_id)

    async def delete_custom_alias(self, guild_id: int, alias: str):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM custom_aliases WHERE guild_id = $1 AND alias = $2", guild_id, alias.lower())

    async def get_command_for_alias(self, guild_id: int, alias: str):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT command_name FROM custom_aliases WHERE guild_id = $1 AND alias = $2", guild_id, alias.lower())
            return row['command_name'] if row else None

    async def add_button_role(self, guild_id: int, button_label: str, role_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO button_roles (guild_id, button_label, role_id) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, button_label) DO UPDATE SET role_id = EXCLUDED.role_id
            """, guild_id, button_label, role_id)

    async def get_button_roles(self, guild_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT button_label, role_id FROM button_roles WHERE guild_id = $1", guild_id)

    async def log_activity(self, guild_id: int, user_id: int, activity_type: str, amount: int = 1):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO activity_log (guild_id, user_id, activity_type, amount, timestamp)
                VALUES ($1, $2, $3, $4, $5)
            """, guild_id, user_id, activity_type, amount, time.time())

    async def get_timeframe_stats(self, guild_id: int, user_id: int, timeframe: str):
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

        async with self.pool.acquire() as conn:
            results = await conn.fetch("""
                SELECT activity_type, SUM(amount) as total
                FROM activity_log 
                WHERE guild_id = $1 AND user_id = $2 AND timestamp >= $3
                GROUP BY activity_type
            """, guild_id, user_id, start_time)
            
        stats = {'text_xp': 0, 'voice_xp': 0, 'image_count': 0, 'video_count': 0, 'video_duration': 0}
        for row in results:
            act_type = row['activity_type']
            total = row['total']
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
    rewards = await db.get_level_rewards(guild.id)
    for row in rewards:
        lvl, role_id = row['level'], row['role_id']
        if new_level >= lvl:
            role = guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="رتبة مكافأة اللفل")
                except Exception:
                    pass
