import discord
from discord import app_commands
from discord.ext import commands, tasks
import psycopg2
import asyncio
import time
import math
import os
import re
from datetime import datetime, timezone
from typing import Optional, List
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# === سيرفر خفيف لإعلام Render أن البوت يعمل ===
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is online!")

def run_health_check_server():
    port = int(os.environ.get("PORT", 10000))
    httpd = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    httpd.serve_forever()

threading.Thread(target=run_health_check_server, daemon=True).start()
# ==============================================

# كمل كود البوت الأساسي حقك هنا طبيعي جداً...

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# يجلب رابط الداتابيز من البيئة التي أضفتها في Render
DATABASE_URL = os.getenv("DATABASE_URL")

class Database:
    """Class to manage database connections and tables for guild settings and leveling using PostgreSQL."""
    def __init__(self):
        self.init_db()

    def get_connection(self):
        return psycopg2.connect(DATABASE_URL)

    def init_db(self):
        """Creates necessary PostgreSQL tables if they do not exist."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                # Guild Configuration Table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS guild_settings (
                        guild_id BIGINT PRIMARY KEY,
                        log_channel_id BIGINT DEFAULT 0,
                        welcome_channel_id BIGINT DEFAULT 0,
                        welcome_msg TEXT DEFAULT 'مرحباً بك {user} في سيرفر {server}!',
                        auto_role_id BIGINT DEFAULT 0,
                        ticket_category_id BIGINT DEFAULT 0,
                        text_xp_enabled INT DEFAULT 1,
                        voice_xp_enabled INT DEFAULT 1,
                        text_xp_rate INT DEFAULT 15,
                        voice_xp_rate INT DEFAULT 10,
                        automod_enabled INT DEFAULT 0,
                        automod_badwords TEXT DEFAULT ''
                    );
                """)

                # User Levels Table
                cursor.execute("""
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
                """)
                conn.commit()

    def get_guild_settings(self, guild_id: int):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM guild_settings WHERE guild_id = %s;", (guild_id,))
                row = cursor.fetchone()
                if not row:
                    cursor.execute("INSERT INTO guild_settings (guild_id) VALUES (%s);", (guild_id,))
                    conn.commit()
                    return self.get_guild_settings(guild_id)
                return row

    def update_guild_setting(self, guild_id: int, column: str, value):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"UPDATE guild_settings SET {column} = %s WHERE guild_id = %s;", (value, guild_id))
                conn.commit()

    def get_user_data(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM user_levels WHERE guild_id = %s AND user_id = %s;", (guild_id, user_id))
                row = cursor.fetchone()
                if not row:
                    cursor.execute("INSERT INTO user_levels (guild_id, user_id) VALUES (%s, %s);", (guild_id, user_id))
                    conn.commit()
                    return self.get_user_data(guild_id, user_id)
                return row

    def add_text_xp(self, guild_id: int, user_id: int, xp_amount: int):
        data = self.get_user_data(guild_id, user_id)
        current_xp = data[2] + xp_amount
        current_lvl = data[3]
        
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE user_levels 
                    SET text_xp = %s, text_level = %s, last_msg_timestamp = %s
                    WHERE guild_id = %s AND user_id = %s;
                """, (current_xp, new_lvl, time.time(), guild_id, user_id))
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
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE user_levels 
                    SET voice_xp = %s, voice_level = %s, voice_time_seconds = %s
                    WHERE guild_id = %s AND user_id = %s;
                """, (current_xp, new_lvl, total_time, guild_id, user_id))
                conn.commit()

        return leveled_up, new_lvl

db = Database()

def create_progress_bar(current: int, total: int, length: int = 12) -> str:
    if total <= 0:
        total = 1
    percent = min(max(current / total, 0.0), 1.0)
    filled = int(length * percent)
    return "█" * filled + "░" * (length - filled)

def calculate_next_level_xp(level: int) -> int:
    return (level ** 2) * 100

class WelcomeConfigModal(discord.ui.Modal, title="إعداد الترحيب"):
    welcome_text = discord.ui.TextInput(
        label="رسالة الترحيب",
        style=discord.TextStyle.paragraph,
        placeholder="استخدم {user} لمنشن العضو و {server} لاسم السيرفر",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "welcome_msg", self.welcome_text.value)
        await interaction.response.send_message("✅ تم حفظ رسالة الترحيب بنجاح!", ephemeral=True)

class AutoModConfigModal(discord.ui.Modal, title="إعداد الكلمات الممنوعة"):
    bad_words = discord.ui.TextInput(
        label="قائمة الكلمات الممنوعة (افصل بينها بفاصلة)",
        style=discord.TextStyle.paragraph,
        placeholder="سب1, سب2, رابط_خارجي",
        required=False,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "automod_badwords", self.bad_words.value)
        await interaction.response.send_message("✅ تم تحديث قائمة الكلمات الممنوعة!", ephemeral=True)

class DashboardSelectMenu(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="إعدادات التفاعل واللفل", description="تفعيل اللفل الصوتي والكتابي ومعدل XP", emoji="⭐", value="xp"),
            discord.SelectOption(label="الحماية والتعديل الآلي", description="تفعيل فلتر الكلمات والمناطق الخاطئة", emoji="🛡️", value="automod"),
            discord.SelectOption(label="نظام التذاكر (Tickets)", description="تحديد الفئة وإنشاء زر التذاكر", emoji="🎟️", value="tickets"),
            discord.SelectOption(label="الترحيب واللوق", description="قنوات السجلات والرتب التلقائية", emoji="👋", value="general"),
        ]
        super().__init__(placeholder="اختر القسم المراد تعديله...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        guild_id = interaction.guild_id
        settings = db.get_guild_settings(guild_id)

        if selected == "xp":
            embed = discord.Embed(title="⭐ إعدادات نظام اللفل والـ XP", color=discord.Color.gold())
            embed.add_field(name="اللفل الكتابي", value="✅ مفعل" if settings[6] else "❌ معطل", inline=True)
            embed.add_field(name="اللفل الصوتي", value="✅ مفعل" if settings[7] else "❌ معطل", inline=True)
            embed.add_field(name="معدل خبرة الكتابة", value=f"{settings[8]} XP / رسالة", inline=True)
            embed.add_field(name="معدل خبرة الصوت", value=f"{settings[9]} XP / دقيقة", inline=True)

            view = XPSettingsView()
            await interaction.response.edit_message(embed=embed, view=view)

        elif selected == "automod":
            embed = discord.Embed(title="🛡️ إعدادات الحماية والتعديل الآلي", color=discord.Color.red())
            embed.add_field(name="حالة الحماية", value="✅ مفعلة" if settings[10] else "❌ معطلة", inline=True)
            embed.add_field(name="الكلمات الممنوعة", value=settings[11] if settings[11] else "لا يوجد", inline=False)

            view = AutoModSettingsView()
            await interaction.response.edit_message(embed=embed, view=view)

        elif selected == "tickets":
            embed = discord.Embed(title="🎟️ إعدادات نظام التذاكر", color=discord.Color.blue())
            cat = interaction.guild.get_channel(settings[5])
            embed.add_field(name="فئة التذاكر الحالية", value=cat.mention if cat else "لم تحدد بعد", inline=False)

            view = TicketSettingsView()
            await interaction.response.edit_message(embed=embed, view=view)

        elif selected == "general":
            embed = discord.Embed(title="👋 إعدادات الترحيب والسجلات", color=discord.Color.green())
            w_chan = interaction.guild.get_channel(settings[2])
            l_chan = interaction.guild.get_channel(settings[1])
            a_role = interaction.guild.get_role(settings[4])

            embed.add_field(name="قناة الترحيب", value=w_chan.mention if w_chan else "غير محددة", inline=True)
            embed.add_field(name="قناة اللوق", value=l_chan.mention if l_chan else "غير محددة", inline=True)
            embed.add_field(name="الرتبة التلقائية", value=a_role.mention if a_role else "غير محددة", inline=True)
            embed.add_field(name="رسالة الترحيب", value=settings[3], inline=False)

            view = GeneralSettingsView()
            await interaction.response.edit_message(embed=embed, view=view)

class MainDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DashboardSelectMenu())

class XPSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تبديل اللفل الكتابي", style=discord.ButtonStyle.primary)
    async def toggle_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if settings[6] else 1
        db.update_guild_setting(interaction.guild_id, "text_xp_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} اللفل الكتابي!", ephemeral=True)

    @discord.ui.button(label="تبديل اللفل الصوتي", style=discord.ButtonStyle.primary)
    async def toggle_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if settings[7] else 1
        db.update_guild_setting(interaction.guild_id, "voice_xp_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} اللفل الصوتي!", ephemeral=True)

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القائمة التفاعلية لتعديل إعدادات البوت بالكامل بدون موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class AutoModSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تفعيل/تعطيل الحماية", style=discord.ButtonStyle.danger)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        settings = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if settings[10] else 1
        db.update_guild_setting(interaction.guild_id, "automod_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} نظام الحماية التلقائي!", ephemeral=True)

    @discord.ui.button(label="تعديل الكلمات الممنوعة", style=discord.ButtonStyle.secondary)
    async def edit_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AutoModConfigModal())

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القائمة التفاعلية لتعديل إعدادات البوت بالكامل بدون موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class TicketSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="إرسال لوحة فتح التذاكر", style=discord.ButtonStyle.success)
    async def send_ticket_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎟️ الدعم الفني والتذاكر",
            description="اضغط على الزر أدناه لفتح تذكرة خاصة والتواصل مع إدارة السيرفر.",
            color=discord.Color.blue()
        )
        panel_view = OpenTicketView()
        await interaction.channel.send(embed=embed, view=panel_view)
        await interaction.response.send_message("✅ تم إرسال لوحة التذاكر بنجاح في هذا الشات!", ephemeral=True)

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القائمة التفاعلية لتعديل إعدادات البوت بالكامل بدون موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 فتح تذكرة", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        settings = db.get_guild_settings(guild.id)
        category_id = settings[5]
        
        category = guild.get_channel(category_id) if category_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title="🎟️ تم فتح التذكرة",
            description=f"مرحباً بك {interaction.user.mention}، تفضل بكتابة استفسارك وسيرد عليك طاقم الإدارة قريباً.",
            color=discord.Color.green()
        )
        await channel.send(embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("سيتم إغلاق وحذف التذكرة خلال 5 ثوانٍ...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

class GeneralSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تعديل رسالة الترحيب", style=discord.ButtonStyle.primary)
    async def edit_welcome_msg(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WelcomeConfigModal())

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القائمة التفاعلية لتعديل إعدادات البوت بالكامل بدون موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

@tasks.loop(minutes=1)
async def voice_xp_loop():
    for guild in bot.guilds:
        settings = db.get_guild_settings(guild.id)
        if not settings[7]:
            continue

        voice_rate = settings[9]

        for channel in guild.voice_channels:
            if channel == guild.afk_channel:
                continue

            for member in channel.members:
                if member.bot:
                    continue
                if member.voice.self_deaf or member.voice.self_mute:
                    continue

                leveled_up, new_lvl = db.add_voice_xp(guild.id, member.id, voice_rate, time_add=60)
                if leveled_up:
                    log_chan_id = settings[1]
                    target_channel = guild.get_channel(log_chan_id) or channel
                    try:
                        await target_channel.send(f"🎉 مبروك {member.mention}! لقد ارتفع مستواك الصوتي إلى **المستوى {new_lvl}** 🎤!")
                    except Exception:
                        pass

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("---------------------------------------------")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} Slash Commands successfully!")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")

    if not voice_xp_loop.is_running():
        voice_xp_loop.start()

@bot.event
async def on_member_join(member: discord.Member):
    settings = db.get_guild_settings(member.guild.id)
    
    auto_role_id = settings[4]
    if auto_role_id:
        role = member.guild.get_role(auto_role_id)
        if role:
            try:
                await member.add_roles(role)
            except Exception as e:
                print(f"Failed to give auto role: {e}")

    welcome_channel_id = settings[2]
    if welcome_channel_id:
        channel = member.guild.get_channel(welcome_channel_id)
        if channel:
            msg = settings[3].replace("{user}", member.mention).replace("{server}", member.guild.name)
            embed = discord.Embed(
                title="👋 عضو جديد في السيرفر!",
                description=msg,
                color=discord.Color.green()
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            await channel.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    guild_id = message.guild.id
    settings = db.get_guild_settings(guild_id)

    if settings[10] and settings[11]:
        bad_words = [w.strip().lower() for w in settings[11].split(",") if w.strip()]
        content = message.content.lower()
        if any(word in content for word in bad_words):
            try:
                await message.delete()
                await message.channel.send(f"⚠️ {message.author.mention} تم حذف رسالتك لاحتوائها على كلمات ممنوعة!", delete_after=5)
                return
            except Exception:
                pass

    if settings[6]:
        user_data = db.get_user_data(guild_id, message.author.id)
        last_msg_time = user_data[7]
        
        if time.time() - last_msg_time >= 60:
            xp_rate = settings[8]
            leveled_up, new_lvl = db.add_text_xp(guild_id, message.author.id, xp_rate)
            if leveled_up:
                await message.channel.send(f"🎉 مبروك {message.author.mention}! لقد ارتفع مستواك الكتابي إلى **المستوى {new_lvl}** 💬!")

    await bot.process_commands(message)

@bot.tree.command(name="dashboard", description="فتح لوحة تحكم السيرفر التفاعلية الكاملة")
@app_commands.checks.has_permissions(administrator=True)
async def dashboard(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ لوحة تحكم السيرفر الشاملة (ProBot Style)",
        description="يمكنك التحكم بكافة خصائص البوت مباشرة من هنا دون الحاجة لدخول أي موقع خارجي!",
        color=discord.Color.blurple()
    )
    embed.set_footer(text="اختر الأقسام من القائمة المنسدلة للبدء بالتعديل")
    view = MainDashboardView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="rank", description="عرض بطاقة اللفل والمستوى الكتابي والصوتي")
async def rank(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    data = db.get_user_data(interaction.guild_id, target.id)

    text_xp = data[2]
    text_lvl = data[3]
    voice_xp = data[4]
    voice_lvl = data[5]
    voice_seconds = data[6]

    next_text_xp = calculate_next_level_xp(text_lvl)
    next_voice_xp = calculate_next_level_xp(voice_lvl)

    text_bar = create_progress_bar(text_xp, next_text_xp)
    voice_bar = create_progress_bar(voice_xp, next_voice_xp)

    voice_hours = round(voice_seconds / 3600, 1)

    embed = discord.Embed(title=f"📊 بطاقة المستوى - {target.display_name}", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)

    embed.add_field(
        name="💬 المستوى الكتابي (Text)",
        value=f"**المستوى:** `{text_lvl}` | **الخبرة:** `{text_xp}/{next_text_xp}` XP\n`[{text_bar}]`",
        inline=False
    )
    
    embed.add_field(
        name="🎤 المستوى الصوتي (Voice)",
        value=f"**المستوى:** `{voice_lvl}` | **الخبرة:** `{voice_xp}/{next_voice_xp}` XP\n**الساعات الصوتية:** `{voice_hours}` ساعة\n`[{voice_bar}]`",
        inline=False
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="عرض قائمة المتصدرين في السيرفر")
async def leaderboard(interaction: discord.Interaction):
    with db.get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT user_id, text_level, text_xp FROM user_levels WHERE guild_id = %s ORDER BY text_xp DESC LIMIT 5;", (interaction.guild_id,))
            top_text = cursor.fetchall()

            cursor.execute("SELECT user_id, voice_level, voice_xp FROM user_levels WHERE guild_id = %s ORDER BY voice_xp DESC LIMIT 5;", (interaction.guild_id,))
            top_voice = cursor.fetchall()

    embed = discord.Embed(title="🏆 قائمة المتصدرين (Top 5 Leaderboard)", color=discord.Color.gold())

    text_desc = ""
    for idx, row in enumerate(top_text, 1):
        mem = interaction.guild.get_member(row[0])
        name = mem.display_name if mem else f"مستخدم {row[0]}"
        text_desc += f"**#{idx}** | {name} - Lvl `{row[1]}` (`{row[2]}` XP)\n"
    
    embed.add_field(name="💬 أنشط الأعضاء كتابياً", value=text_desc if text_desc else "لا يوجد بيانات", inline=False)

    voice_desc = ""
    for idx, row in enumerate(top_voice, 1):
        mem = interaction.guild.get_member(row[0])
        name = mem.display_name if mem else f"مستخدم {row[0]}"
        voice_desc += f"**#{idx}** | {name} - Lvl `{row[1]}` (`{row[2]}` XP)\n"

    embed.add_field(name="🎤 أنشط الأعضاء صوتياً", value=voice_desc if voice_desc else "لا يوجد بيانات", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="تطهير ومسح عدد معين من الرسائل")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 تم مسح `{len(deleted)}` رسالة بنجاح!", ephemeral=True)

@bot.tree.command(name="kick", description="طرد عضو من السيرفر")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"🚨 تم طرد {member.mention} | السبب: {reason}")

@bot.tree.command(name="ban", description="حظر عضو من السيرفر")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"⛔ تم حظر {member.mention} | السبب: {reason}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ ليس لديك الصلاحيات الكافية لاستخدام هذا الأمر!", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ حدث خطأ أثناء تنفيذ الأمر: {error}", ephemeral=True)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("⚠️ لم يتم العثور على توكن البوت في DISCORD_BOT_TOKEN!")
    else:
        bot.run(TOKEN)
