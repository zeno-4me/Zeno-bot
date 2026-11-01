import asyncio
import asyncpg
import copy
import math
import time
from datetime import datetime
import discord
import os
import json

SETTINGS_TTL = 60     # ثانية
AUTORESP_TTL = 120
ALIAS_TTL = 120
PANEL_TTL = 600


class Database:
    def __init__(self, db_url: str = None):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.pool = None
        self._lock = None
        # كاش بالذاكرة: يقلل الاستعلامات على كل رسالة/ضغطة زر. يُمسح تلقائياً عند أي تعديل.
        self._settings_cache = {}
        self._autoresp_cache = {}
        self._alias_cache = {}
        self._panel_cache = {}

    async def connect(self):
        if self.pool:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self.pool:
                return
            self.db_url = self.db_url or os.getenv("DATABASE_URL")
            if not self.db_url:
                raise ValueError("DATABASE_URL environment variable is missing!")
            self.pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=10, command_timeout=30)
            await self._create_tables()

    async def _ensure_connection(self):
        if not self.pool:
            await self.connect()

    async def init_db(self):
        await self.connect()

    async def _create_tables(self):
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
                    ticket_support_role_ids TEXT DEFAULT '[]',
                    custom_embeds TEXT DEFAULT '{}',
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

                CREATE TABLE IF NOT EXISTS panels (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    name TEXT,
                    ptype TEXT,
                    embed TEXT,
                    config TEXT,
                    channel_id BIGINT DEFAULT 0,
                    message_id BIGINT DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    channel_id BIGINT PRIMARY KEY,
                    guild_id BIGINT,
                    panel_id INT,
                    owner_id BIGINT,
                    number INT,
                    status TEXT DEFAULT 'open',
                    claimed_by BIGINT DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS ticket_counters (
                    guild_id BIGINT PRIMARY KEY,
                    last_number INT DEFAULT 0
                );
            """)

            alter_queries = [
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS text_xp_enabled INT DEFAULT 1;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS voice_xp_enabled INT DEFAULT 1;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS text_xp_rate INT DEFAULT 15;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS voice_xp_rate INT DEFAULT 10;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS level_up_channel_id BIGINT DEFAULT 0;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS automod_enabled INT DEFAULT 1;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS automod_badwords TEXT DEFAULT '';",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS anti_links INT DEFAULT 0;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS anti_invites INT DEFAULT 0;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS anti_spam INT DEFAULT 0;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ticket_support_role_ids TEXT DEFAULT '[]';",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS custom_embeds TEXT DEFAULT '{}';",
                "CREATE INDEX IF NOT EXISTS idx_activity_lookup ON activity_log (guild_id, user_id, timestamp);",
                "CREATE INDEX IF NOT EXISTS idx_tickets_lookup ON tickets (guild_id, panel_id, owner_id);"
            ]

            for query in alter_queries:
                try:
                    await conn.execute(query)
                except Exception:
                    pass

    async def get_guild_settings(self, guild_id: int):
        hit = self._settings_cache.get(guild_id)
        if hit and time.time() - hit[0] < SETTINGS_TTL:
            return dict(hit[1])

        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM guild_settings WHERE guild_id = $1", guild_id)
            if not row:
                await conn.execute(
                    "INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING", guild_id)
                row = await conn.fetchrow("SELECT * FROM guild_settings WHERE guild_id = $1", guild_id)

        res = dict(row)
        try:
            if isinstance(res.get('ticket_support_role_ids'), str):
                res['ticket_support_role_ids'] = json.loads(res['ticket_support_role_ids'])
        except Exception:
            res['ticket_support_role_ids'] = []
        try:
            if isinstance(res.get('custom_embeds'), str):
                res['custom_embeds'] = json.loads(res['custom_embeds'])
        except Exception:
            res['custom_embeds'] = {}

        self._settings_cache[guild_id] = (time.time(), res)
        return dict(res)

    async def update_guild_setting(self, guild_id: int, column: str, value):
        await self._ensure_connection()
        if isinstance(value, (list, dict)):
            value = json.dumps(value)

        async with self.pool.acquire() as conn:
            await conn.execute(f"UPDATE guild_settings SET {column} = $1 WHERE guild_id = $2", value, guild_id)
        self._settings_cache.pop(guild_id, None)

    # --- دوال نظام اللوحات (Panels) والتذاكر المفقودة سابقاً ---
    async def get_panels(self, guild_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM panels WHERE guild_id = $1 ORDER BY id DESC", guild_id)
            return [dict(r) for r in rows]

    async def get_panel(self, panel_id: int):
        hit = self._panel_cache.get(panel_id)
        if hit and time.time() - hit[0] < PANEL_TTL:
            return copy.deepcopy(hit[1])

        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM panels WHERE id = $1", panel_id)
        if not row:
            return None
        res = dict(row)
        try:
            res['embed'] = json.loads(res['embed']) if res['embed'] else {}
        except Exception:
            res['embed'] = {}
        try:
            res['config'] = json.loads(res['config']) if res['config'] else {}
        except Exception:
            res['config'] = {}
        self._panel_cache[panel_id] = (time.time(), res)
        return copy.deepcopy(res)

    async def get_panel_by_name(self, guild_id: int, name: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id FROM panels WHERE guild_id = $1 AND name = $2", guild_id, name)
            return row['id'] if row else None

    async def create_panel(self, guild_id: int, name: str, ptype: str, embed: dict, config: dict):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO panels (guild_id, name, ptype, embed, config)
                VALUES ($1, $2, $3, $4, $5) RETURNING id
            """, guild_id, name, ptype, json.dumps(embed), json.dumps(config))
            return row['id']

    async def update_panel(self, panel_id: int, **kwargs):
        await self._ensure_connection()
        allowed_cols = ['name', 'ptype', 'embed', 'config', 'channel_id', 'message_id']
        updates = []
        values = []
        idx = 1
        for k, v in kwargs.items():
            if k in allowed_cols:
                if isinstance(v, (dict, list)):
                    v = json.dumps(v)
                updates.append(f"{k} = ${idx}")
                values.append(v)
                idx += 1
        if not updates:
            return
        values.append(panel_id)
        async with self.pool.acquire() as conn:
            await conn.execute(f"UPDATE panels SET {', '.join(updates)} WHERE id = ${idx}", *values)
        self._panel_cache.pop(panel_id, None)

    async def delete_panel(self, panel_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM panels WHERE id = $1", panel_id)
        self._panel_cache.pop(panel_id, None)

    async def next_ticket_number(self, guild_id: int) -> int:
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT last_number FROM ticket_counters WHERE guild_id = $1", guild_id)
            if not row:
                await conn.execute("INSERT INTO ticket_counters (guild_id, last_number) VALUES ($1, 1)", guild_id)
                return 1
            new_num = row['last_number'] + 1
            await conn.execute("UPDATE ticket_counters SET last_number = $1 WHERE guild_id = $2", new_num, guild_id)
            return new_num

    async def create_ticket(self, channel_id: int, guild_id: int, panel_id: int, owner_id: int, number: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO tickets (channel_id, guild_id, panel_id, owner_id, number, status)
                VALUES ($1, $2, $3, $4, $5, 'open')
            """, channel_id, guild_id, panel_id, owner_id, number)

    async def get_ticket(self, channel_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tickets WHERE channel_id = $1", channel_id)
            return dict(row) if row else None

    async def get_open_tickets(self, guild_id: int, panel_id: int, owner_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM tickets WHERE guild_id = $1 AND panel_id = $2 AND owner_id = $3 AND status = 'open'
            """, guild_id, panel_id, owner_id)
            return [dict(r) for r in rows]

    async def close_ticket(self, channel_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE tickets SET status = 'closed' WHERE channel_id = $1", channel_id)

    async def set_ticket_claim(self, channel_id: int, user_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE tickets SET claimed_by = $1 WHERE channel_id = $2", user_id, channel_id)

    # --- نظام متغيرات الإمبدز وقائمة روابط الرسائل (Message URLs) ---
    async def save_custom_embed(self, guild_id: int, embed_name: str, embed_dict: dict, new_message_url: str = None):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT custom_embeds FROM guild_settings WHERE guild_id = $1", guild_id)
            embeds = {}
            if row and row['custom_embeds']:
                try:
                    embeds = json.loads(row['custom_embeds'])
                except:
                    embeds = {}
            
            current_data = embeds.get(embed_name, {})
            if not isinstance(current_data, dict):
                current_data = {"embed": current_data, "message_urls": []}
            
            urls_list = current_data.get("message_urls", [])
            if new_message_url and new_message_url not in urls_list:
                urls_list.append(new_message_url)

            current_data["embed"] = embed_dict
            current_data["message_urls"] = urls_list
            
            embeds[embed_name] = current_data
            await conn.execute("UPDATE guild_settings SET custom_embeds = $1 WHERE guild_id = $2", json.dumps(embeds), guild_id)
            self._settings_cache.pop(guild_id, None)

    async def get_custom_embed(self, guild_id: int, embed_name: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT custom_embeds FROM guild_settings WHERE guild_id = $1", guild_id)
            if row and row['custom_embeds']:
                try:
                    embeds = json.loads(row['custom_embeds'])
                    data = embeds.get(embed_name)
                    if isinstance(data, dict):
                        return data
                    elif data:
                        return {"embed": data, "message_urls": []}
                except:
                    return None
            return None

    async def get_all_custom_embeds(self, guild_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT custom_embeds FROM guild_settings WHERE guild_id = $1", guild_id)
            if row and row['custom_embeds']:
                try:
                    raw_embeds = json.loads(row['custom_embeds'])
                    formatted = {}
                    for name, data in raw_embeds.items():
                        if isinstance(data, dict) and "embed" in data:
                            formatted[name] = data
                        else:
                            formatted[name] = {"embed": data, "message_urls": []}
                    return formatted
                except:
                    return {}
            return {}

    async def delete_custom_embed(self, guild_id: int, embed_name: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT custom_embeds FROM guild_settings WHERE guild_id = $1", guild_id)
            if row and row['custom_embeds']:
                try:
                    embeds = json.loads(row['custom_embeds'])
                    if embed_name in embeds:
                        del embeds[embed_name]
                        await conn.execute("UPDATE guild_settings SET custom_embeds = $1 WHERE guild_id = $2", json.dumps(embeds), guild_id)
                        self._settings_cache.pop(guild_id, None)
                except:
                    pass

    # --- باقي الجداول والدوال (لفل، اقتصاد، حماية، إلخ) ---
    async def add_level_reward(self, guild_id: int, level: int, role_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO level_rewards (guild_id, level, role_id) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, level) DO UPDATE SET role_id = EXCLUDED.role_id
            """, guild_id, level, role_id)

    async def get_level_rewards(self, guild_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT level, role_id FROM level_rewards WHERE guild_id = $1 ORDER BY level ASC", guild_id)

    async def _user_row(self, conn, guild_id: int, user_id: int, lock: bool = False):
        q = "SELECT * FROM user_levels WHERE guild_id = $1 AND user_id = $2" + (" FOR UPDATE" if lock else "")
        row = await conn.fetchrow(q, guild_id, user_id)
        if not row:
            await conn.execute(
                "INSERT INTO user_levels (guild_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", guild_id, user_id)
            row = await conn.fetchrow(q, guild_id, user_id)
        return row

    async def get_user_data(self, guild_id: int, user_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await self._user_row(conn, guild_id, user_id)

    async def set_user_xp_level(self, guild_id: int, user_id: int, text_xp: int, text_lvl: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE user_levels SET text_xp = $1, text_level = $2 WHERE guild_id = $3 AND user_id = $4
            """, text_xp, text_lvl, guild_id, user_id)

    async def add_text_xp(self, guild_id: int, user_id: int, xp_amount: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await self._user_row(conn, guild_id, user_id, lock=True)
                current_xp = data['text_xp'] + xp_amount
                current_lvl = data['text_level']
                new_lvl = int(math.sqrt(current_xp / 100)) + 1
                leveled_up = new_lvl > current_lvl
                await conn.execute("""
                    UPDATE user_levels SET text_xp = $1, text_level = $2, last_msg_timestamp = $3
                    WHERE guild_id = $4 AND user_id = $5
                """, current_xp, new_lvl, time.time(), guild_id, user_id)
        return leveled_up, new_lvl

    async def add_voice_xp(self, guild_id: int, user_id: int, xp_amount: int, time_add: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await self._user_row(conn, guild_id, user_id, lock=True)
                current_xp = data['voice_xp'] + xp_amount
                current_lvl = data['voice_level']
                total_time = data['voice_time_seconds'] + time_add
                new_lvl = int(math.sqrt(current_xp / 100)) + 1
                leveled_up = new_lvl > current_lvl
                await conn.execute("""
                    UPDATE user_levels SET voice_xp = $1, voice_level = $2, voice_time_seconds = $3
                    WHERE guild_id = $4 AND user_id = $5
                """, current_xp, new_lvl, total_time, guild_id, user_id)
        return leveled_up, new_lvl

    async def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            await conn.execute("""
                INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp) 
                VALUES ($1, $2, $3, $4, $5)
            """, guild_id, user_id, moderator_id, reason, now_str)

    async def get_warnings(self, guild_id: int, user_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT id, moderator_id, reason, timestamp FROM warnings 
                WHERE guild_id = $1 AND user_id = $2
            """, guild_id, user_id)

    async def clear_warnings(self, guild_id: int, user_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM warnings WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

    async def get_economy_data(self, guild_id: int, user_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM economy WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
            if not row:
                await self._ensure_economy_row(conn, guild_id, user_id)
                row = await conn.fetchrow("SELECT * FROM economy WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
            return row

    async def _ensure_economy_row(self, conn, guild_id: int, user_id: int):
        await conn.execute(
            "INSERT INTO economy (guild_id, user_id) VALUES ($1, $2) ON CONFLICT (guild_id, user_id) DO NOTHING",
            guild_id, user_id)

    async def update_credits(self, guild_id: int, user_id: int, amount: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await self._ensure_economy_row(conn, guild_id, user_id)
            row = await conn.fetchrow(
                "UPDATE economy SET credits = GREATEST(0, credits + $1::bigint) "
                "WHERE guild_id = $2 AND user_id = $3 RETURNING credits",
                amount, guild_id, user_id)
            return row['credits']

    async def transfer_credits(self, guild_id: int, from_id: int, to_id: int, amount: int):
        """تحويل ذرّي بين عضوين. يرجع (نجح؟, رصيد المرسل)."""
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_economy_row(conn, guild_id, from_id)
                await self._ensure_economy_row(conn, guild_id, to_id)
                rows = await conn.fetch(
                    "SELECT user_id, credits FROM economy WHERE guild_id = $1 AND user_id = ANY($2::bigint[]) "
                    "ORDER BY user_id FOR UPDATE", guild_id, [from_id, to_id])
                balances = {r['user_id']: r['credits'] for r in rows}
                if balances.get(from_id, 0) < amount:
                    return False, balances.get(from_id, 0)
                await conn.execute(
                    "UPDATE economy SET credits = credits - $1::bigint WHERE guild_id = $2 AND user_id = $3",
                    amount, guild_id, from_id)
                await conn.execute(
                    "UPDATE economy SET credits = credits + $1::bigint WHERE guild_id = $2 AND user_id = $3",
                    amount, guild_id, to_id)
                return True, balances[from_id] - amount

    async def claim_daily(self, guild_id: int, user_id: int, amount: int, cooldown: int = 86400):
        """استلام يومي ذرّي. يرجع (نجح؟, الثواني المتبقية)."""
        await self._ensure_connection()
        now = time.time()
        async with self.pool.acquire() as conn:
            await self._ensure_economy_row(conn, guild_id, user_id)
            row = await conn.fetchrow(
                "UPDATE economy SET credits = credits + $1::bigint, last_daily = $2 "
                "WHERE guild_id = $3 AND user_id = $4 AND last_daily <= $5 RETURNING credits",
                amount, now, guild_id, user_id, now - cooldown)
            if row:
                return True, 0
            last = await conn.fetchval(
                "SELECT last_daily FROM economy WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)
            return False, max(1, int(cooldown - (now - (last or 0))))

    async def claim_rep(self, guild_id: int, sender_id: int, target_id: int, cooldown: int = 43200):
        """إعطاء سمعة ذرّي مع الكولداون. يرجع (نجح؟, الثواني المتبقية)."""
        await self._ensure_connection()
        now = time.time()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_economy_row(conn, guild_id, sender_id)
                await self._ensure_economy_row(conn, guild_id, target_id)
                row = await conn.fetchrow(
                    "UPDATE economy SET last_rep = $1 WHERE guild_id = $2 AND user_id = $3 AND last_rep <= $4 "
                    "RETURNING user_id", now, guild_id, sender_id, now - cooldown)
                if not row:
                    last = await conn.fetchval(
                        "SELECT last_rep FROM economy WHERE guild_id = $1 AND user_id = $2", guild_id, sender_id)
                    return False, max(1, int(cooldown - (now - (last or 0))))
                await conn.execute(
                    "UPDATE economy SET rep = rep + 1 WHERE guild_id = $1 AND user_id = $2", guild_id, target_id)
                return True, 0

    async def set_daily_claimed(self, guild_id: int, user_id: int, amount: int):
        await self._ensure_connection()
        data = await self.get_economy_data(guild_id, user_id)
        new_credits = data['credits'] + amount
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE economy SET credits = $1, last_daily = $2 WHERE guild_id = $3 AND user_id = $4
            """, new_credits, time.time(), guild_id, user_id)

    async def add_rep(self, guild_id: int, target_id: int, sender_id: int):
        await self._ensure_connection()
        target_data = await self.get_economy_data(guild_id, target_id)
        new_rep = target_data['rep'] + 1
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE economy SET rep = $1 WHERE guild_id = $2 AND user_id = $3", new_rep, guild_id, target_id)
            await conn.execute("UPDATE economy SET last_rep = $1 WHERE guild_id = $2 AND user_id = $3", time.time(), guild_id, sender_id)

    async def set_title(self, guild_id: int, user_id: int, title_text: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO economy (guild_id, user_id, title) VALUES ($2, $3, $1)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET title = EXCLUDED.title
            """, title_text, guild_id, user_id)

    async def add_auto_response(self, guild_id: int, trigger: str, response: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO auto_responses (guild_id, trigger_text, response_text) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, trigger_text) DO UPDATE SET response_text = EXCLUDED.response_text
            """, guild_id, trigger.lower(), response)
        self._autoresp_cache.pop(guild_id, None)

    async def get_auto_responses(self, guild_id: int):
        hit = self._autoresp_cache.get(guild_id)
        if hit and time.time() - hit[0] < AUTORESP_TTL:
            return hit[1]
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            rows = list(await conn.fetch(
                "SELECT trigger_text, response_text FROM auto_responses WHERE guild_id = $1", guild_id))
        self._autoresp_cache[guild_id] = (time.time(), rows)
        return rows

    async def delete_auto_response(self, guild_id: int, trigger: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM auto_responses WHERE guild_id = $1 AND trigger_text = $2", guild_id, trigger.lower())
        self._autoresp_cache.pop(guild_id, None)

    async def add_custom_alias(self, guild_id: int, alias: str, command_name: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO custom_aliases (guild_id, alias, command_name) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, alias) DO UPDATE SET command_name = EXCLUDED.command_name
            """, guild_id, alias.lower(), command_name.lower())
        self._alias_cache.pop(guild_id, None)

    async def get_custom_aliases(self, guild_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT alias, command_name FROM custom_aliases WHERE guild_id = $1", guild_id)

    async def delete_custom_alias(self, guild_id: int, alias: str):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM custom_aliases WHERE guild_id = $1 AND alias = $2", guild_id, alias.lower())
        self._alias_cache.pop(guild_id, None)

    async def get_command_for_alias(self, guild_id: int, alias: str):
        hit = self._alias_cache.get(guild_id)
        if hit and time.time() - hit[0] < ALIAS_TTL:
            return hit[1].get(alias.lower())
        rows = await self.get_custom_aliases(guild_id)
        mapping = {r['alias']: r['command_name'] for r in rows}
        self._alias_cache[guild_id] = (time.time(), mapping)
        return mapping.get(alias.lower())

    async def add_button_role(self, guild_id: int, button_label: str, role_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO button_roles (guild_id, button_label, role_id) VALUES ($1, $2, $3)
                ON CONFLICT (guild_id, button_label) DO UPDATE SET role_id = EXCLUDED.role_id
            """, guild_id, button_label, role_id)

    async def get_button_roles(self, guild_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT button_label, role_id FROM button_roles WHERE guild_id = $1", guild_id)

    async def log_activity(self, guild_id: int, user_id: int, activity_type: str, amount: int = 1):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO activity_log (guild_id, user_id, activity_type, amount, timestamp)
                VALUES ($1, $2, $3, $4, $5)
            """, guild_id, user_id, activity_type, amount, time.time())

    async def get_timeframe_stats(self, guild_id: int, user_id: int, timeframe: str):
        await self._ensure_connection()
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
            
        stats = {
            'text_xp': 0, 
            'voice_xp': 0, 
            'message_count': 0, 
            'image_count': 0, 
            'video_count': 0, 
            'video_duration': 0
        }
        for row in results:
            act_type = row['activity_type']
            total = row['total']
            if act_type in stats:
                stats[act_type] = total or 0
                
        return stats

    async def get_top_levels(self, guild_id: int, limit: int = 10):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT user_id, text_xp, voice_xp 
                FROM user_levels 
                WHERE guild_id = $1 
                ORDER BY (text_xp + voice_xp) DESC 
                LIMIT $2
            """, guild_id, limit)

    async def get_top_credits(self, guild_id: int, limit: int = 10):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT user_id, credits 
                FROM economy 
                WHERE guild_id = $1 
                ORDER BY credits DESC 
                LIMIT $2
            """, guild_id, limit)

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


# ─────────────── أدوات الرد على التفاعلات (تعمل سواء تم الرد/الـdefer أو لا) ───────────────
async def reply(interaction: discord.Interaction, content=None, **kwargs):
    """بديل آمن لـ interaction.response.send_message: يتحول تلقائياً لـ followup إذا انتهت فرصة الرد الأول."""
    if interaction.response.is_done():
        return await interaction.followup.send(content, **kwargs)
    try:
        return await interaction.response.send_message(content, **kwargs)
    except discord.InteractionResponded:
        return await interaction.followup.send(content, **kwargs)
    except discord.HTTPException as e:
        if e.code != 40060:  # Interaction has already been acknowledged
            raise
        return await interaction.followup.send(content, **kwargs)


async def edit_reply(interaction: discord.Interaction, **kwargs):
    """بديل آمن لـ interaction.response.edit_message."""
    if interaction.response.is_done():
        return await interaction.edit_original_response(**kwargs)
    try:
        return await interaction.response.edit_message(**kwargs)
    except discord.InteractionResponded:
        return await interaction.edit_original_response(**kwargs)
    except discord.HTTPException as e:
        if e.code != 40060:
            raise
        return await interaction.edit_original_response(**kwargs)
