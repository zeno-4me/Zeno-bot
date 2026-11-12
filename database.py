import asyncio
import asyncpg
import copy
import math
import time
from datetime import datetime
import discord
import os
import re
import json

LINK_PLATFORMS = {
    "youtube": "يوتيوب شورتس",
    "tiktok": "تيك توك",
    "instagram": "ريلز انستغرام",
    "snapchat": "سناب شات",
    "x": "تويتر / X",
    "facebook": "فيسبوك",
}
DEFAULT_LINK_CONFIG = {
    "mode": "keep",            # keep = يبقى الرابط + الفيديو كرد | suppress = يبقى ويخفي المعاينة | delete = يحذف الرابط ويرسل الفيديو
    "channel_mode": "all",     # all | include | exclude
    "channels": [],
    "role_mode": "all",        # all | include | exclude
    "roles": [],
    "platforms": {k: True for k in LINK_PLATFORMS},
    "max_duration": 180,       # ثواني
}

# ═══════════════════════ أدوات عامة (إعدادات JSON / رسائل / تواريخ) ═══════════════════════
def deep_merge(base, over):
    """دمج عميق: القيم المخزنة تتغلب على الافتراضية، وأي مفتاح جديد يضاف تلقائياً."""
    out = copy.deepcopy(base)
    if isinstance(over, dict):
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = deep_merge(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
    return out


def parse_hex(text):
    t = (text or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", t):
        return int(t, 16)
    return None


def fmt_vars(text: str, variables: dict) -> str:
    text = text or ""
    for k, v in (variables or {}).items():
        text = text.replace("{" + k + "}", str(v))
    return text


# شكل أي رسالة قابلة للتخصيص (ترحيب / مغادرة / لفل / اختصار ...)
DEFAULT_MSG = {
    "as_embed": False,     # False = نص عادي | True = إمبد
    "title": "",
    "desc": "",
    "color": "#5865F2",
    "image": "",
    "thumb": "none",       # avatar | server | none
    "footer": "",
}


def build_message(msg: dict, variables: dict = None, member=None, guild=None, content_prefix=None) -> dict:
    """يحول قاموس الرسالة إلى kwargs جاهزة لـ send / reply: {content, embed}"""
    m = deep_merge(DEFAULT_MSG, msg or {})
    desc = fmt_vars(m.get("desc"), variables)
    if not m.get("as_embed"):
        return {"content": (desc[:2000] or "—"), "embed": None}
    emb = discord.Embed(color=discord.Color(parse_hex(m.get("color")) or 0x5865F2))
    title = fmt_vars(m.get("title"), variables)[:256]
    if title:
        emb.title = title
    if desc:
        emb.description = desc[:4000]
    footer = fmt_vars(m.get("footer"), variables)[:2000]
    if footer:
        emb.set_footer(text=footer)
    img = (m.get("image") or "").strip()
    if img.startswith(("http://", "https://")):
        emb.set_image(url=img)
    thumb = m.get("thumb")
    if thumb == "avatar" and member is not None:
        emb.set_thumbnail(url=member.display_avatar.url)
    elif thumb == "server" and guild is not None and guild.icon:
        emb.set_thumbnail(url=guild.icon.url)
    if not (title or desc or img):
        emb.description = "—"
    return {"content": content_prefix, "embed": emb}


# ─────────────── الترحيب ───────────────
DEFAULT_WELCOME = {
    "enabled": True,
    "trigger": "join",          # join = عند الدخول | role = عند أخذ رتبة من رتب الرسائل
    "mention": True,            # منشن للعضو خارج الإمبد (عشان يوصله تنبيه)
    "delete_after": 0,
    "fallback_minutes": 0,      # وضع الرتبة: لو ما أخذ رتبة بعد كم دقيقة يرسل الافتراضية (0 = لا)
    "tz_offset": 3,             # فرق التوقيت عن UTC (للمناسبات)
    "dm_enabled": False,
    "dm_text": "أهلاً بك في **{server}** 🌟 نتمنى لك وقتاً ممتعاً!",
    "default": {**DEFAULT_MSG, "desc": "مرحباً بك {user} في سيرفر {server}! 🎉"},
    "roles": [],                # [{"role_id": 1, "msg": {...}}]
    "rare": {"enabled": False, "chance": 5.0, "messages": []},   # messages: [msg, ...]
    "events": [],               # [{"name","enabled","calendar","start","end","msg"}]
    "leave": {"enabled": True, "msg": {**DEFAULT_MSG, "desc": "وداعاً {name}، نتمنى لك التوفيق! 👋"}},
}

WELCOME_VARS = "{user} منشن • {name} الاسم • {username} اليوزر • {server} السيرفر • {count} عدد الأعضاء • {role} الرتبة • {date} تاريخ الدخول • {created} عمر الحساب"

# ─────────────── اللفل ───────────────
DEFAULT_LEVEL = {
    "base_xp": 100,             # صعوبة اللفل: الخبرة المطلوبة = (اللفل-1)² × base
    "cooldown": 60,             # ثواني بين كل احتساب خبرة كتابية
    "text_xp_max": 0,           # لو أكبر من الحد الأدنى: عشوائي بينهم
    "reward_mode": "stack",     # stack = تبقى الرتب القديمة | replace = تبقى الأعلى فقط
    "ignored_channels": [],
    "ignored_roles": [],
    "multipliers": [],          # [{"role_id": 1, "mult": 1.5}]
    "voice_require_others": False,
    "voice_count_muted": False,
    "rank_color": "#F1C40F",
    "bar": "blocks",
    "announce": {
        "enabled": True,
        "dest": "channel",      # channel = قناة التنبيهات (أو نفس الشات) | current = نفس الشات | dm = خاص
        "ping": True,
        "delete_after": 0,
        "msg": {**DEFAULT_MSG, "desc": "🎉 مبروك {user}! ارتفع مستواك الأساسي إلى **{level}**"},
    },
}
LEVEL_VARS = "{user} منشن • {name} الاسم • {level} اللفل الجديد • {old_level} اللفل القديم • {xp} إجمالي الخبرة • {server} السيرفر • {reward} الرتبة المكتسبة"

BAR_STYLES = {
    "blocks": ("▰", "▱", "مربعات ممتلئة ▰▰▰▱▱"),
    "squares": ("■", "□", "مربعات ■■■□□"),
    "smooth": ("█", "░", "متدرج ███░░"),
    "dots": ("●", "○", "نقاط ●●●○○"),
}


def level_from_xp(xp: int, base: int = 100) -> int:
    return int(math.sqrt(max(0, xp) / max(1, base))) + 1


def xp_for_level(level: int, base: int = 100) -> int:
    """الخبرة اللازمة للوصول لهذا اللفل."""
    return ((max(1, level) - 1) ** 2) * max(1, base)


# ─────────────── الرسائل التلقائية القابلة للتخصيص ───────────────
MESSAGE_DEFS = {
    "automod_badword": {"cat": "🛡️ الحماية", "label": "كلمة ممنوعة", "delete_after": 5,
        "text": "⚠️ {user} تم حذف رسالتك لاحتوائها على كلمات محظورة.",
        "vars": "{user} {name} {server} {channel}"},
    "automod_link": {"cat": "🛡️ الحماية", "label": "منع الروابط", "delete_after": 5,
        "text": "⚠️ {user} يمنع إرسال الروابط هنا.",
        "vars": "{user} {name} {server} {channel}"},
    "automod_invite": {"cat": "🛡️ الحماية", "label": "منع دعوات السيرفرات", "delete_after": 5,
        "text": "⚠️ {user} يمنع إرسال دعوات السيرفرات.",
        "vars": "{user} {name} {server} {channel}"},
    "warn_public": {"cat": "⚖️ العقوبات", "label": "تحذير (يظهر في الشات)", "delete_after": 0,
        "text": "⚠️ تم تحذير {user} | السبب: **{reason}**",
        "vars": "{user} {name} {moderator} {reason} {count} {server}"},
    "warn_dm": {"cat": "⚖️ العقوبات", "label": "تحذير (خاص للعضو)", "enabled": False, "delete_after": 0,
        "text": "⚠️ وصلك تحذير في سيرفر **{server}**\nالسبب: {reason}\nإجمالي تحذيراتك: {count}",
        "vars": "{name} {moderator} {reason} {count} {server}"},
    "ban_public": {"cat": "⚖️ العقوبات", "label": "حظر (يظهر في الشات)", "delete_after": 0,
        "text": "⛔ تم حظر {user} | السبب: {reason}",
        "vars": "{user} {name} {moderator} {reason} {server}"},
    "ban_dm": {"cat": "⚖️ العقوبات", "label": "حظر (خاص للعضو)", "enabled": False, "delete_after": 0,
        "text": "⛔ تم حظرك من سيرفر **{server}**\nالسبب: {reason}",
        "vars": "{name} {moderator} {reason} {server}"},
    "kick_public": {"cat": "⚖️ العقوبات", "label": "طرد (يظهر في الشات)", "delete_after": 0,
        "text": "🚨 تم طرد {user} | السبب: {reason}",
        "vars": "{user} {name} {moderator} {reason} {server}"},
    "kick_dm": {"cat": "⚖️ العقوبات", "label": "طرد (خاص للعضو)", "enabled": False, "delete_after": 0,
        "text": "🚨 تم طردك من سيرفر **{server}**\nالسبب: {reason}",
        "vars": "{name} {moderator} {reason} {server}"},
    "timeout_public": {"cat": "⚖️ العقوبات", "label": "كتم (يظهر في الشات)", "delete_after": 0,
        "text": "🤐 تم كتم {user} لمدة `{minutes}` دقيقة | السبب: {reason}",
        "vars": "{user} {name} {moderator} {reason} {minutes} {server}"},
    "timeout_dm": {"cat": "⚖️ العقوبات", "label": "كتم (خاص للعضو)", "enabled": False, "delete_after": 0,
        "text": "🤐 تم كتمك في **{server}** لمدة {minutes} دقيقة\nالسبب: {reason}",
        "vars": "{name} {moderator} {reason} {minutes} {server}"},
    "unmute_public": {"cat": "⚖️ العقوبات", "label": "فك الكتم", "delete_after": 0,
        "text": "🔊 تم فك الكتم عن {user}",
        "vars": "{user} {name} {moderator} {server}"},
    "daily_ok": {"cat": "💰 الاقتصاد", "label": "استلام المكافأة اليومية", "delete_after": 0,
        "text": "🎉 مبارك {user}! حصلت على **${amount}** كريدت كمكافأة يومية!",
        "vars": "{user} {name} {amount} {server}"},
    "daily_wait": {"cat": "💰 الاقتصاد", "label": "المكافأة اليومية (لازم تنتظر)", "delete_after": 0,
        "text": "⏳ استلمت مكافأتك اليومية من قبل! ارجع بعد `{time}`.",
        "vars": "{user} {name} {time} {server}"},
    "rep_ok": {"cat": "💰 الاقتصاد", "label": "إعطاء نقطة سمعة", "delete_after": 0,
        "text": "🌟 {user} أعطى نقطة سمعة (+1 Rep) إلى {target}!",
        "vars": "{user} {name} {target} {target_name} {server}"},
}


# ─────────────── المناسبات (ميلادي / هجري) ───────────────
def gregorian_to_hijri(y: int, m: int, d: int):
    """تحويل حسابي تقريبي (قد يختلف يوماً عن الرؤية الرسمية)."""
    a = (14 - m) // 12
    yy = y + 4800 - a
    mm = m + 12 * a - 3
    jd = d + (153 * mm + 2) // 5 + 365 * yy + yy // 4 - yy // 100 + yy // 400 - 32045
    l = jd - 1948440 + 10632
    n = (l - 1) // 10631
    l = l - 10631 * n + 354
    j = ((10985 - l) // 5316) * ((50 * l) // 17719) + (l // 5670) * ((43 * l) // 15238)
    l = l - ((30 - j) // 15) * ((17719 * j) // 50) - (j // 16) * ((15238 * j) // 43) + 29
    hm = (24 * l) // 709
    hd = l - (709 * hm) // 24
    hy = 30 * n + j - 30
    return hy, hm, hd


def parse_event_date(text: str):
    """'MM-DD' أو 'YYYY-MM-DD' → (y|None, m, d) أو None لو خطأ."""
    t = (text or "").strip()
    m = re.fullmatch(r"(?:(\d{4})-)?(\d{1,2})-(\d{1,2})", t)
    if not m:
        return None
    y = int(m.group(1)) if m.group(1) else None
    mo, d = int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return y, mo, d


def event_is_active(ev: dict, tz_offset: float = 3, now: datetime = None) -> bool:
    if not ev.get("enabled", True):
        return False
    from datetime import timedelta, timezone
    now = now or (datetime.now(timezone.utc) + timedelta(hours=tz_offset))
    s, e = parse_event_date(ev.get("start")), parse_event_date(ev.get("end"))
    if not s or not e:
        return False
    if ev.get("calendar") == "hijri":
        _, hm, hd = gregorian_to_hijri(now.year, now.month, now.day)
        cur = (hm, hd)
    else:
        if s[0] and e[0]:   # تاريخ كامل بالسنة
            return (s[0], s[1], s[2]) <= (now.year, now.month, now.day) <= (e[0], e[1], e[2])
        cur = (now.month, now.day)
    a, b = (s[1], s[2]), (e[1], e[2])
    if a <= b:
        return a <= cur <= b
    return cur >= a or cur <= b      # يعبر رأس السنة


SHORTCUT_DEFAULT = {
    "trigger": "", "responses": [], "match": "contains",   # contains | exact | starts | word
    "enabled": True, "style": "text",                      # text | embed
    "title": "", "color": "#5865F2", "image": "",
    "reply": True, "delete_trigger": False, "delete_after": 0, "cooldown": 0,
    "react": "", "mention_author": False,
    "channel_mode": "all", "channels": [], "role_mode": "all", "roles": [],
}

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
        self._shortcut_cache = {}

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
                    anti_spam INT DEFAULT 0,
                    link_embed_enabled INT DEFAULT 1,
                    link_embed_config TEXT DEFAULT '{}',
                    welcome_config TEXT DEFAULT '{}',
                    level_config TEXT DEFAULT '{}',
                    messages_config TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS bot_meta (
                    key TEXT PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS welcome_sent (
                    guild_id BIGINT,
                    user_id BIGINT,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS shortcuts (
                    id SERIAL PRIMARY KEY,
                    guild_id BIGINT,
                    data TEXT
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
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS link_embed_enabled INT DEFAULT 1;",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS link_embed_config TEXT DEFAULT '{}';",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS ticket_support_role_ids TEXT DEFAULT '[]';",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS custom_embeds TEXT DEFAULT '{}';",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS welcome_config TEXT DEFAULT '{}';",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS level_config TEXT DEFAULT '{}';",
                "ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS messages_config TEXT DEFAULT '{}';",
                "CREATE INDEX IF NOT EXISTS idx_shortcuts_guild ON shortcuts (guild_id);",
                "CREATE INDEX IF NOT EXISTS idx_activity_lookup ON activity_log (guild_id, user_id, timestamp);",
                "CREATE INDEX IF NOT EXISTS idx_tickets_lookup ON tickets (guild_id, panel_id, owner_id);"
            ]

            for query in alter_queries:
                try:
                    await conn.execute(query)
                except Exception:
                    pass

            await self._migrate_shortcuts(conn)

    async def _migrate_shortcuts(self, conn):
        """ترحيل الردود التلقائية + الاختصارات القديمة لنظام الاختصارات الجديد (مرة وحدة فقط)."""
        try:
            if await conn.fetchval("SELECT 1 FROM bot_meta WHERE key = 'shortcuts_migrated'"):
                return
            for r in await conn.fetch("SELECT guild_id, trigger_text, response_text FROM auto_responses"):
                data = copy.deepcopy(SHORTCUT_DEFAULT)
                data.update(trigger=r['trigger_text'], match="contains", reply=False,
                            responses=[x.strip() for x in (r['response_text'] or "").split("|") if x.strip()])
                await conn.execute("INSERT INTO shortcuts (guild_id, data) VALUES ($1, $2)", r['guild_id'], json.dumps(data))
            for r in await conn.fetch("SELECT guild_id, alias, command_name FROM custom_aliases"):
                data = copy.deepcopy(SHORTCUT_DEFAULT)
                data.update(trigger=r['alias'], match="starts", reply=True,
                            responses=[f"💡 هذا اختصار للأمر: `/{r['command_name']}`"])
                await conn.execute("INSERT INTO shortcuts (guild_id, data) VALUES ($1, $2)", r['guild_id'], json.dumps(data))
            await conn.execute("INSERT INTO bot_meta (key) VALUES ('shortcuts_migrated') ON CONFLICT DO NOTHING")
        except Exception as e:
            print(f"⚠️ تعذر ترحيل الاختصارات القديمة: {e}")

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

        try:
            if isinstance(res.get('link_embed_config'), str):
                res['link_embed_config'] = json.loads(res['link_embed_config'] or '{}')
        except Exception:
            res['link_embed_config'] = {}

        for col in ('welcome_config', 'level_config', 'messages_config'):
            try:
                v = res.get(col)
                res[col] = json.loads(v) if isinstance(v, str) and v else (v if isinstance(v, dict) else {})
            except Exception:
                res[col] = {}

        self._settings_cache[guild_id] = (time.time(), res)
        return dict(res)

    async def update_guild_setting(self, guild_id: int, column: str, value):
        await self._ensure_connection()
        if isinstance(value, (list, dict)):
            value = json.dumps(value)

        async with self.pool.acquire() as conn:
            await conn.execute(f"UPDATE guild_settings SET {column} = $1 WHERE guild_id = $2", value, guild_id)
        self._settings_cache.pop(guild_id, None)

    # --- إعدادات JSON مدموجة مع الافتراضي ---
    async def get_welcome_cfg(self, guild_id: int) -> dict:
        st = await self.get_guild_settings(guild_id)
        raw = st.get('welcome_config') or {}
        cfg = deep_merge(DEFAULT_WELCOME, raw)
        # ترحيل رسائل النظام القديم (نصوص بسيطة) لو ما انحفظت إعدادات جديدة
        if 'default' not in raw and st.get('welcome_msg'):
            cfg['default']['desc'] = st['welcome_msg']
        leave_raw = raw.get('leave') or {}
        if 'msg' not in leave_raw and st.get('leave_msg'):
            cfg['leave']['msg']['desc'] = st['leave_msg'].replace("{user}", "{name}")
        return cfg

    async def set_welcome_cfg(self, guild_id: int, cfg: dict):
        await self.update_guild_setting(guild_id, "welcome_config", cfg)

    async def get_level_cfg(self, guild_id: int) -> dict:
        st = await self.get_guild_settings(guild_id)
        return deep_merge(DEFAULT_LEVEL, st.get('level_config') or {})

    async def set_level_cfg(self, guild_id: int, cfg: dict):
        await self.update_guild_setting(guild_id, "level_config", cfg)

    async def get_message_cfg(self, guild_id: int, key: str) -> dict:
        """إعدادات رسالة تلقائية واحدة (النص/التفعيل/النمط/الحذف) مدموجة مع الافتراضي."""
        d = MESSAGE_DEFS[key]
        st = await self.get_guild_settings(guild_id)
        ov = (st.get('messages_config') or {}).get(key, {}) or {}
        return {
            "text": ov.get("text") or d["text"],
            "enabled": ov.get("enabled", d.get("enabled", True)),
            "style": ov.get("style", "text"),
            "title": ov.get("title", ""),
            "color": ov.get("color", "#ED4245"),
            "delete_after": ov.get("delete_after", d.get("delete_after", 0)),
            "custom": bool(ov),
        }

    async def set_message_cfg(self, guild_id: int, key: str, values: dict):
        st = await self.get_guild_settings(guild_id)
        all_cfg = dict(st.get('messages_config') or {})
        cur = dict(all_cfg.get(key, {}) or {})
        cur.update(values)
        all_cfg[key] = cur
        await self.update_guild_setting(guild_id, "messages_config", all_cfg)

    async def reset_message_cfg(self, guild_id: int, key: str):
        st = await self.get_guild_settings(guild_id)
        all_cfg = dict(st.get('messages_config') or {})
        all_cfg.pop(key, None)
        await self.update_guild_setting(guild_id, "messages_config", all_cfg)

    async def auto_kwargs(self, guild_id: int, key: str, **variables):
        """kwargs جاهزة للإرسال (content / embed / delete_after) أو None لو الرسالة معطلة من الإدارة."""
        c = await self.get_message_cfg(guild_id, key)
        if not c["enabled"]:
            return None
        msg = {"as_embed": c["style"] == "embed", "title": c["title"], "desc": c["text"], "color": c["color"]}
        kw = build_message(msg, variables)
        if c["delete_after"] and c["delete_after"] > 0:
            kw["delete_after"] = int(c["delete_after"])
        return kw

    # --- الترحيب: تتبع من تم ترحيبه (وضع الرتبة) ---
    async def mark_welcomed(self, guild_id: int, user_id: int) -> bool:
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO welcome_sent (guild_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING RETURNING user_id",
                guild_id, user_id)
        return row is not None

    async def is_welcomed(self, guild_id: int, user_id: int) -> bool:
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval(
                "SELECT 1 FROM welcome_sent WHERE guild_id = $1 AND user_id = $2", guild_id, user_id))

    async def unmark_welcomed(self, guild_id: int, user_id: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM welcome_sent WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

    # --- الاختصارات ---
    async def get_shortcuts(self, guild_id: int):
        hit = self._shortcut_cache.get(guild_id)
        if hit and time.time() - hit[0] < ALIAS_TTL:
            return hit[1]
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, data FROM shortcuts WHERE guild_id = $1 ORDER BY id", guild_id)
        out = []
        for r in rows:
            try:
                d = deep_merge(SHORTCUT_DEFAULT, json.loads(r['data'] or '{}'))
            except Exception:
                continue
            d['id'] = r['id']
            out.append(d)
        self._shortcut_cache[guild_id] = (time.time(), out)
        return out

    async def get_shortcut(self, guild_id: int, sid: int):
        for s in await self.get_shortcuts(guild_id):
            if s['id'] == sid:
                return copy.deepcopy(s)
        return None

    async def add_shortcut(self, guild_id: int, data: dict) -> int:
        await self._ensure_connection()
        payload = deep_merge(SHORTCUT_DEFAULT, data)
        async with self.pool.acquire() as conn:
            sid = await conn.fetchval("INSERT INTO shortcuts (guild_id, data) VALUES ($1, $2) RETURNING id",
                                      guild_id, json.dumps(payload))
        self._shortcut_cache.pop(guild_id, None)
        return sid

    async def update_shortcut(self, guild_id: int, sid: int, data: dict):
        await self._ensure_connection()
        payload = {k: v for k, v in data.items() if k != 'id'}
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE shortcuts SET data = $1 WHERE id = $2 AND guild_id = $3",
                               json.dumps(payload), sid, guild_id)
        self._shortcut_cache.pop(guild_id, None)

    async def delete_shortcut(self, guild_id: int, sid: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM shortcuts WHERE id = $1 AND guild_id = $2", sid, guild_id)
        self._shortcut_cache.pop(guild_id, None)

    async def get_link_config(self, guild_id: int) -> dict:
        """إعدادات ميزة تحويل روابط السوشل لفيديو (مدموجة مع القيم الافتراضية)."""
        st = await self.get_guild_settings(guild_id)
        raw = st.get('link_embed_config')
        cfg = copy.deepcopy(DEFAULT_LINK_CONFIG)
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k == "platforms" and isinstance(v, dict):
                    cfg["platforms"].update({pk: bool(pv) for pk, pv in v.items() if pk in LINK_PLATFORMS})
                elif k in cfg and k != "platforms":
                    cfg[k] = v
        return cfg

    async def set_link_config(self, guild_id: int, cfg: dict):
        await self.update_guild_setting(guild_id, "link_embed_config", cfg)

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

    async def remove_level_reward(self, guild_id: int, level: int):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM level_rewards WHERE guild_id = $1 AND level = $2", guild_id, level)

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

    async def add_text_xp(self, guild_id: int, user_id: int, xp_amount: int, base: int = 100):
        """يضيف خبرة كتابية. يرجع (ارتفع اللفل الأساسي؟, اللفل الأساسي الجديد, القديم)."""
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await self._user_row(conn, guild_id, user_id, lock=True)
                new_text = max(0, data['text_xp'] + xp_amount)
                old_total = data['text_xp'] + data['voice_xp']
                new_total = new_text + data['voice_xp']
                old_main, new_main = level_from_xp(old_total, base), level_from_xp(new_total, base)
                await conn.execute("""
                    UPDATE user_levels SET text_xp = $1, text_level = $2, last_msg_timestamp = $3
                    WHERE guild_id = $4 AND user_id = $5
                """, new_text, level_from_xp(new_text, base), time.time(), guild_id, user_id)
        return new_main > old_main, new_main, old_main

    async def add_voice_xp(self, guild_id: int, user_id: int, xp_amount: int, time_add: int, base: int = 100):
        """يضيف خبرة صوتية. يرجع (ارتفع اللفل الأساسي؟, اللفل الأساسي الجديد, القديم)."""
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await self._user_row(conn, guild_id, user_id, lock=True)
                new_voice = max(0, data['voice_xp'] + xp_amount)
                total_time = data['voice_time_seconds'] + time_add
                old_total = data['text_xp'] + data['voice_xp']
                new_total = data['text_xp'] + new_voice
                old_main, new_main = level_from_xp(old_total, base), level_from_xp(new_total, base)
                await conn.execute("""
                    UPDATE user_levels SET voice_xp = $1, voice_level = $2, voice_time_seconds = $3
                    WHERE guild_id = $4 AND user_id = $5
                """, new_voice, level_from_xp(new_voice, base), total_time, guild_id, user_id)
        return new_main > old_main, new_main, old_main

    async def set_user_xp(self, guild_id: int, user_id: int, text_xp: int = None, voice_xp: int = None, base: int = 100):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                data = await self._user_row(conn, guild_id, user_id, lock=True)
                t = data['text_xp'] if text_xp is None else max(0, text_xp)
                v = data['voice_xp'] if voice_xp is None else max(0, voice_xp)
                await conn.execute("""
                    UPDATE user_levels SET text_xp = $1, text_level = $2, voice_xp = $3, voice_level = $4
                    WHERE guild_id = $5 AND user_id = $6
                """, t, level_from_xp(t, base), v, level_from_xp(v, base), guild_id, user_id)
        return level_from_xp(t + v, base)

    async def get_user_rank(self, guild_id: int, user_id: int):
        """(المركز, إجمالي المرتبين) حسب مجموع الخبرة."""
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            await self._user_row(conn, guild_id, user_id)
            pos = await conn.fetchval("""
                SELECT COUNT(*) + 1 FROM user_levels
                WHERE guild_id = $1 AND (text_xp + voice_xp) >
                    (SELECT text_xp + voice_xp FROM user_levels WHERE guild_id = $1 AND user_id = $2)
            """, guild_id, user_id)
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM user_levels WHERE guild_id = $1 AND (text_xp + voice_xp) > 0", guild_id)
        return int(pos), int(max(total or 0, pos))

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

    async def get_top_levels(self, guild_id: int, limit: int = 10, offset: int = 0, order: str = "main"):
        await self._ensure_connection()
        expr = {"main": "(text_xp + voice_xp)", "text": "text_xp", "voice": "voice_xp"}.get(order, "(text_xp + voice_xp)")
        async with self.pool.acquire() as conn:
            return await conn.fetch(f"""
                SELECT user_id, text_xp, voice_xp
                FROM user_levels
                WHERE guild_id = $1 AND {expr} > 0
                ORDER BY {expr} DESC
                LIMIT $2 OFFSET $3
            """, guild_id, limit, offset)

    async def count_top_levels(self, guild_id: int, order: str = "main") -> int:
        await self._ensure_connection()
        expr = {"main": "(text_xp + voice_xp)", "text": "text_xp", "voice": "voice_xp"}.get(order, "(text_xp + voice_xp)")
        async with self.pool.acquire() as conn:
            return int(await conn.fetchval(f"SELECT COUNT(*) FROM user_levels WHERE guild_id = $1 AND {expr} > 0", guild_id) or 0)

    async def get_top_credits(self, guild_id: int, limit: int = 10, offset: int = 0):
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT user_id, credits
                FROM economy
                WHERE guild_id = $1
                ORDER BY credits DESC
                LIMIT $2 OFFSET $3
            """, guild_id, limit, offset)

    async def count_top_credits(self, guild_id: int) -> int:
        await self._ensure_connection()
        async with self.pool.acquire() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM economy WHERE guild_id = $1", guild_id) or 0)

db = Database()

def calculate_next_level_xp(level: int, base: int = 100) -> int:
    """إجمالي الخبرة اللازمة للوصول للفل التالي."""
    return (level ** 2) * base

def create_progress_bar(current: int, total: int, length: int = 10, style: str = "blocks") -> str:
    full, empty, _ = BAR_STYLES.get(style, BAR_STYLES["blocks"])
    percentage = min(1.0, max(0.0, current / total)) if total else 0.0
    filled = int(percentage * length)
    return full * filled + empty * (length - filled)

def level_progress(total_xp: int, base: int = 100):
    """(اللفل الأساسي, الخبرة داخل اللفل, المطلوب لهذا اللفل)"""
    lvl = level_from_xp(total_xp, base)
    start = xp_for_level(lvl, base)
    need = xp_for_level(lvl + 1, base) - start
    return lvl, total_xp - start, need

async def check_and_grant_level_roles(guild: discord.Guild, member: discord.Member, level: int):
    """يمنح رتب التفاعل (مكافآت اللفل) حسب اللفل الأساسي. يرجع قائمة الرتب اللي انضافت."""
    cfg = await db.get_level_cfg(guild.id)
    rewards = await db.get_level_rewards(guild.id)
    earned = []
    for row in rewards:
        role = guild.get_role(row['role_id'])
        if role and level >= row['level']:
            earned.append((row['level'], role))
    if not earned:
        return []
    if cfg.get('reward_mode') == 'replace':
        top = max(l for l, _ in earned)
        to_add = [r for l, r in earned if l == top and r not in member.roles]
        to_remove = [r for l, r in earned if l != top and r in member.roles]
    else:
        to_add = [r for _, r in earned if r not in member.roles]
        to_remove = []
    try:
        if to_add:
            await member.add_roles(*to_add, reason="رتبة تفاعل (مكافأة اللفل)")
        if to_remove:
            await member.remove_roles(*to_remove, reason="استبدال رتبة التفاعل بالأعلى")
    except Exception:
        return []
    return to_add


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
