import os
import sqlite3
import tempfile
from flask import Flask
from threading import Thread
import aiohttp
from moviepy.editor import VideoFileClip
import discord
from discord import app_commands
from discord.ext import commands

# --- Web Server for Render Keep-Alive ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

t = Thread(target=run)
t.daemon = True
t.start()

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

DB_NAME = "media_points.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            image_points REAL DEFAULT 1.0,
            gif_points REAL DEFAULT 2.0,
            video_points REAL DEFAULT 1.0,
            video_minute_points REAL DEFAULT 4.0,
            allowed_channels TEXT DEFAULT '',
            allowed_categories TEXT DEFAULT ''
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_points (
            guild_id INTEGER,
            user_id INTEGER,
            points REAL DEFAULT 0.0,
            images_count INTEGER DEFAULT 0,
            gifs_count INTEGER DEFAULT 0,
            videos_count INTEGER DEFAULT 0,
            video_seconds INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracked_messages (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER,
            user_id INTEGER,
            points_awarded REAL,
            media_type TEXT,
            duration_sec INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_config(guild_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT image_points, gif_points, video_points, video_minute_points, allowed_channels, allowed_categories FROM guild_config WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        conn.commit()
        config = (1.0, 2.0, 1.0, 4.0, "", "")
    else:
        config = row
    conn.close()
    return {
        "image_points": config[0],
        "gif_points": config[1],
        "video_points": config[2],
        "video_minute_points": config[3],
        "allowed_channels": [int(x) for x in config[4].split(",") if x.strip()],
        "allowed_categories": [int(x) for x in config[5].split(",") if x.strip()]
    }

async def get_video_duration(url: str) -> float:
    tmp_path = None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                        tmp.write(await resp.read())
                        tmp_path = tmp.name
                    clip = VideoFileClip(tmp_path)
                    duration = clip.duration
                    clip.close()
                    return duration
    except Exception as e:
        print(f"Error reading video duration: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return 0.0

@bot.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"تم تزامُن {len(synced)} من أوامر السلاش.")
    except Exception as e:
        print(f"خطأ في مزامنة الأوامر: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    config = get_config(message.guild.id)
    
    channel_ok = not config["allowed_channels"] or message.channel.id in config["allowed_channels"]
    category_ok = not config["allowed_categories"] or (message.channel.category_id and message.channel.category_id in config["allowed_categories"])
    
    if not (channel_ok or category_ok):
        return

    detected_media = []

    for attachment in message.attachments:
        content_type = attachment.content_type or ""
        filename = attachment.filename.lower()

        if "image/gif" in content_type or filename.endswith('.gif'):
            pts = config["gif_points"]
            detected_media.append(('gif', pts, 0))
        elif content_type.startswith("image/"):
            pts = config["image_points"]
            detected_media.append(('image', pts, 0))
        elif content_type.startswith("video/") or filename.endswith(('.mp4', '.mov', '.avi', '.mkv')):
            duration = await get_video_duration(attachment.url)
            minutes = duration / 60.0
            pts = config["video_points"] + (minutes * config["video_minute_points"])
            detected_media.append(('video', pts, int(duration)))

    if detected_media:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        batch_pts = sum(item[1] for item in detected_media)
        batch_imgs = sum(1 for item in detected_media if item[0] == 'image')
        batch_gifs = sum(1 for item in detected_media if item[0] == 'gif')
        batch_vids = sum(1 for item in detected_media if item[0] == 'video')
        batch_secs = sum(item[2] for item in detected_media if item[0] == 'video')

        cursor.execute('''
            INSERT INTO user_points (guild_id, user_id, points, images_count, gifs_count, videos_count, video_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                points = points + ?,
                images_count = images_count + ?,
                gifs_count = gifs_count + ?,
                videos_count = videos_count + ?,
                video_seconds = video_seconds + ?
        ''', (message.guild.id, message.author.id, batch_pts, batch_imgs, batch_gifs, batch_vids, batch_secs,
              batch_pts, batch_imgs, batch_gifs, batch_vids, batch_secs))

        for m_type, pts, dur in detected_media:
            cursor.execute('''
                INSERT INTO tracked_messages (message_id, guild_id, user_id, points_awarded, media_type, duration_sec)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (message.id, message.guild.id, message.author.id, pts, m_type, dur))

        conn.commit()
        conn.close()

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT points_awarded, media_type, duration_sec FROM tracked_messages WHERE message_id = ?", (message.id,))
    records = cursor.fetchall()

    if records:
        del_pts = sum(r[0] for r in records)
        del_imgs = sum(1 for r in records if r[1] == 'image')
        del_gifs = sum(1 for r in records if r[1] == 'gif')
        del_vids = sum(1 for r in records if r[1] == 'video')
        del_secs = sum(r[2] for r in records if r[1] == 'video')

        cursor.execute('''
            UPDATE user_points SET
                points = max(0, points - ?),
                images_count = max(0, images_count - ?),
                gifs_count = max(0, gifs_count - ?),
                videos_count = max(0, videos_count - ?),
                video_seconds = max(0, video_seconds - ?)
            WHERE guild_id = ? AND user_id = ?
        ''', (del_pts, del_imgs, del_gifs, del_vids, del_secs, message.guild.id, message.author.id))

        cursor.execute("DELETE FROM tracked_messages WHERE message_id = ?", (message.id,))
        conn.commit()

    conn.close()

# ----------------- SLASH COMMANDS ----------------- #

@bot.tree.command(name="setup_points", description="تعديل آلية احتساب النقاط للملفات (للإدارة فقط)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_points(interaction: discord.Interaction, image_points: float, gif_points: float, video_points: float, video_minute_points: float):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO guild_config (guild_id, image_points, gif_points, video_points, video_minute_points)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            image_points = ?, gif_points = ?, video_points = ?, video_minute_points = ?
    ''', (interaction.guild_id, image_points, gif_points, video_points, video_minute_points,
          image_points, gif_points, video_points, video_minute_points))
    conn.commit()
    conn.close()

    embed = discord.Embed(title="⚙️ تم تحديث إعدادات النقاط بنجاح", color=discord.Color.green())
    embed.add_field(name="الصورة الواحدة", value=f"`{image_points}` نقطة", inline=True)
    embed.add_field(name="ملف GIF", value=f"`{gif_points}` نقطة", inline=True)
    embed.add_field(name="الفيديو (أساسي)", value=f"`{video_points}` نقطة", inline=True)
    embed.add_field(name="لكل دقيقة فيديو", value=f"`{video_minute_points}` نقاط", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="setup_channels", description="تحديد الرومات أو الكاتيجوري التي يعمل بها البوت")
@app_commands.checks.has_permissions(administrator=True)
async def setup_channels(interaction: discord.Interaction, channel: discord.TextChannel = None, category: discord.CategoryChannel = None):
    config = get_config(interaction.guild_id)
    channels = config["allowed_channels"]
    categories = config["allowed_categories"]

    if channel and channel.id not in channels:
        channels.append(channel.id)
    if category and category.id not in categories:
        categories.append(category.id)

    ch_str = ",".join(map(str, channels))
    cat_str = ",".join(map(str, categories))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE guild_config SET allowed_channels = ?, allowed_categories = ? WHERE guild_id = ?", (ch_str, cat_str, interaction.guild_id))
    conn.commit()
    conn.close()

    await interaction.response.send_message("✅ تم إضافة التحديد بنجاح! البوت يعمل الآن في الرومات/الكاتيجوري المحددة.", ephemeral=True)

@bot.tree.command(name="points", description="عرض النقاط والإحصائيات الخاصة بعضو معين")
async def points(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT points, images_count, gifs_count, videos_count, video_seconds FROM user_points WHERE guild_id = ? AND user_id = ?", (interaction.guild_id, target.id))
    row = cursor.fetchone()
    conn.close()

    if not row:
        pts, imgs, gifs, vids, secs = 0, 0, 0, 0, 0
    else:
        pts, imgs, gifs, vids, secs = row

    total_minutes = round(secs / 60, 1)

    embed = discord.Embed(title=f"📊 إحصائيات النقاط لـ {target.display_name}", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🏆 مجموع النقاط", value=f"**{round(pts, 2)}** نقطة", inline=False)
    embed.add_field(name="🖼️ الصور", value=f"تم إرسال `{imgs}` صورة", inline=False)
    embed.add_field(name="🎥 الفيديوهات", value=f"`{vids}` فيديو بمجموع دقائق `{total_minutes}`", inline=False)
    embed.add_field(name="جيفات GIF", value=f"`{gifs}` gif", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="عرض متصدري السيرفر في النقاط (Top 10)")
async def leaderboard(interaction: discord.Interaction):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, points FROM user_points 
        WHERE guild_id = ? ORDER BY points DESC LIMIT 10
    ''', (interaction.guild_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("لا يوجد بيانات نقاط مسجلة بعد في هذا السيرفر.")
        return

    embed = discord.Embed(title="🏆 قائمة صدارة الأعضاء (Top 10)", color=discord.Color.gold())
    description = ""
    for idx, (user_id, pts) in enumerate(rows, 1):
        member = interaction.guild.get_member(user_id)
        name = member.mention if member else f"عضو مغادر ({user_id})"
        description += f"**#{idx}** | {name} - **{round(pts, 2)}** نقطة\n"

    embed.description = description
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="reset_points", description="تصفير نقاط عضو معين أو جميع الأعضاء (لالمشرفين فقط)")
@app_commands.checks.has_permissions(administrator=True)
async def reset_points(interaction: discord.Interaction, target_user: discord.Member = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if target_user:
        cursor.execute("DELETE FROM user_points WHERE guild_id = ? AND user_id = ?", (interaction.guild_id, target_user.id))
        msg = f"🔄 تم تصفير نقاط العضو {target_user.mention} بنجاح."
    else:
        cursor.execute("DELETE FROM user_points WHERE guild_id = ?", (interaction.guild_id,))
        msg = "💥 تم تصفير نقاط **جميع الأعضاء** في السيرفر بنجاح."

    conn.commit()
    conn.close()
    await interaction.response.send_message(msg)

TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN environment variable not set.")
# Database Setup
DB_NAME = "media_points.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    # Table for guild configurations
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            image_points REAL DEFAULT 1.0,
            gif_points REAL DEFAULT 2.0,
            video_points REAL DEFAULT 1.0,
            video_minute_points REAL DEFAULT 4.0,
            allowed_channels TEXT DEFAULT '',
            allowed_categories TEXT DEFAULT ''
        )
    ''')
    # Table for user points and media stats
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_points (
            guild_id INTEGER,
            user_id INTEGER,
            points REAL DEFAULT 0.0,
            images_count INTEGER DEFAULT 0,
            gifs_count INTEGER DEFAULT 0,
            videos_count INTEGER DEFAULT 0,
            video_seconds INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
    ''')
    # Table to track messages for deletion handling
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracked_messages (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER,
            user_id INTEGER,
            points_awarded REAL,
            media_type TEXT,
            duration_sec INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Helper Functions for DB
def get_config(guild_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT image_points, gif_points, video_points, video_minute_points, allowed_channels, allowed_categories FROM guild_config WHERE guild_id = ?", (guild_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        conn.commit()
        config = (1.0, 2.0, 1.0, 4.0, "", "")
    else:
        config = row
    conn.close()
    return {
        "image_points": config[0],
        "gif_points": config[1],
        "video_points": config[2],
        "video_minute_points": config[3],
        "allowed_channels": [int(x) for x in config[4].split(",") if x.strip()],
        "allowed_categories": [int(x) for x in config[5].split(",") if x.strip()]
    }

def update_user_points(guild_id: int, user_id: int, points_delta: float, media_type: str, duration_sec: int = 0, is_add: bool = True):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    sign = 1 if is_add else -1
    img_inc = (1 if media_type == 'image' else 0) * sign
    gif_inc = (1 if media_type == 'gif' else 0) * sign
    vid_inc = (1 if media_type == 'video' else 0) * sign
    sec_inc = duration_sec * sign

    cursor.execute('''
        INSERT INTO user_points (guild_id, user_id, points, images_count, gifs_count, videos_count, video_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET
            points = max(0, points + ?),
            images_count = max(0, images_count + ?),
            gifs_count = max(0, gifs_count + ?),
            videos_count = max(0, videos_count + ?),
            video_seconds = max(0, video_seconds + ?)
    ''', (guild_id, user_id, max(0, points_delta * sign), max(0, img_inc), max(0, gif_inc), max(0, vid_inc), max(0, sec_inc),
          points_delta * sign, img_inc, gif_inc, vid_inc, sec_inc))
    
    conn.commit()
    conn.close()

# Video Duration Calculator
async def get_video_duration(url: str) -> float:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp:
                        tmp.write(await resp.read())
                        tmp_path = tmp.name
                    clip = VideoFileClip(tmp_path)
                    duration = clip.duration
                    clip.close()
                    os.remove(tmp_path)
                    return duration
    except Exception as e:
        print(f"Error reading video duration: {e}")
    return 0.0

@bot.event
async def on_ready():
    print(f"تم تسجيل الدخول بنجاح باسم: {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"تم تزامُن {len(synced)} من أوامر السلاش.")
    except Exception as e:
        print(f"خطأ في مزامنة الأوامر: {e}")

# Media Detection Logic
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    config = get_config(message.guild.id)
    
    # Check Channel & Category Restrictions
    channel_ok = not config["allowed_channels"] or message.channel.id in config["allowed_channels"]
    category_ok = not config["allowed_categories"] or (message.channel.category_id and message.channel.category_id in config["allowed_categories"])
    
    if not (channel_ok or category_ok):
        return

    total_points = 0.0
    detected_media = []

    # Check Attachments
    for attachment in message.attachments:
        content_type = attachment.content_type or ""
        filename = attachment.filename.lower()

        if "image/gif" in content_type or filename.endswith('.gif'):
            pts = config["gif_points"]
            total_points += pts
            detected_media.append(('gif', pts, 0))
        elif content_type.startswith("image/"):
            pts = config["image_points"]
            total_points += pts
            detected_media.append(('image', pts, 0))
        elif content_type.startswith("video/") or filename.endswith(('.mp4', '.mov', '.avi', '.mkv')):
            duration = await get_video_duration(attachment.url)
            minutes = duration / 60.0
            pts = config["video_points"] + (minutes * config["video_minute_points"])
            total_points += pts
            detected_media.append(('video', pts, int(duration)))

    # Save to Tracked Messages & User Points
    if detected_media:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        for m_type, pts, dur in detected_media:
            update_user_points(message.guild.id, message.author.id, pts, m_type, dur, is_add=True)
            cursor.execute('''
                INSERT INTO tracked_messages (message_id, guild_id, user_id, points_awarded, media_type, duration_sec)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (message.id, message.guild.id, message.author.id, pts, m_type, dur))
        conn.commit()
        conn.close()

    await bot.process_commands(message)

# Handle Deleted Messages (Deduct Points)
@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT points_awarded, media_type, duration_sec FROM tracked_messages WHERE message_id = ?", (message.id,))
    records = cursor.fetchall()

    if records:
        for pts, m_type, dur in records:
            update_user_points(message.guild.id, message.author.id, pts, m_type, dur, is_add=False)
        cursor.execute("DELETE FROM tracked_messages WHERE message_id = ?", (message.id,))
        conn.commit()

    conn.close()

# ----------------- SLASH COMMANDS ----------------- #

# 1. Setup Points Setup
@bot.tree.command(name="setup_points", description="تعديل آلية احتساب النقاط للملفات (للإدارة فقط)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_points(interaction: discord.Interaction, image_points: float, gif_points: float, video_points: float, video_minute_points: float):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO guild_config (guild_id, image_points, gif_points, video_points, video_minute_points)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            image_points = ?, gif_points = ?, video_points = ?, video_minute_points = ?
    ''', (interaction.guild_id, image_points, gif_points, video_points, video_minute_points,
          image_points, gif_points, video_points, video_minute_points))
    conn.commit()
    conn.close()

    embed = discord.Embed(title="⚙️ تم تحديث إعدادات النقاط بنجاح", color=discord.Color.green())
    embed.add_field(name="الصورة الواحدة", value=f"`{image_points}` نقطة", inline=True)
    embed.add_field(name="ملف GIF", value=f"`{gif_points}` نقطة", inline=True)
    embed.add_field(name="الفيديو (أساسي)", value=f"`{video_points}` نقطة", inline=True)
    embed.add_field(name="لكل دقيقة فيديو", value=f"`{video_minute_points}` نقاط", inline=True)
    await interaction.response.send_message(embed=embed)

# 2. Setup Allowed Channels/Categories
@bot.tree.command(name="setup_channels", description="تحديد الرومات أو الكاتيجوري التي يعمل بها البوت")
@app_commands.checks.has_permissions(administrator=True)
async def setup_channels(interaction: discord.Interaction, channel: discord.TextChannel = None, category: discord.CategoryChannel = None):
    config = get_config(interaction.guild_id)
    channels = config["allowed_channels"]
    categories = config["allowed_categories"]

    if channel and channel.id not in channels:
        channels.append(channel.id)
    if category and category.id not in categories:
        categories.append(category.id)

    ch_str = ",".join(map(str, channels))
    cat_str = ",".join(map(str, categories))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE guild_config SET allowed_channels = ?, allowed_categories = ? WHERE guild_id = ?", (ch_str, cat_str, interaction.guild_id))
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"✅ تم إضافة التحديد بنجاح! البوت يعمل الآن في الرومات/الكاتيجوري المحددة.", ephemeral=True)

# 3. View Points for User
@bot.tree.command(name="points", description="عرض النقاط والإحصائيات الخاصة بعضو معين")
async def points(interaction: discord.Interaction, user: discord.Member = None):
    target = user or interaction.user
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT points, images_count, gifs_count, videos_count, video_seconds FROM user_points WHERE guild_id = ? AND user_id = ?", (interaction.guild_id, target.id))
    row = cursor.fetchone()
    conn.close()

    if not row:
        pts, imgs, gifs, vids, secs = 0, 0, 0, 0, 0
    else:
        pts, imgs, gifs, vids, secs = row

    total_minutes = round(secs / 60, 1)

    embed = discord.Embed(title=f"📊 إحصائيات النقاط لـ {target.display_name}", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🏆 مجموع النقاط", value=f"**{round(pts, 2)}** نقطة", inline=False)
    embed.add_field(name="🖼️ الصور", value=f"تم إرسال `{imgs}` صورة", inline=False)
    embed.add_field(name="🎥 الفيديوهات", value=f"`{vids}` فيديو بمجموع دقائق `{total_minutes}`", inline=False)
    embed.add_field(name="جيفات GIF", value=f"`{gifs}` gif", inline=False)

    await interaction.response.send_message(embed=embed)

# 4. Leaderboard Command
@bot.tree.command(name="leaderboard", description="عرض متصدري السيرفر في النقاط (Top 10)")
async def leaderboard(interaction: discord.Interaction):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, points FROM user_points 
        WHERE guild_id = ? ORDER BY points DESC LIMIT 10
    ''', (interaction.guild_id,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("لا يوجد بيانات نقاط مسجلة بعد في هذا السيرفر.")
        return

    embed = discord.Embed(title="🏆 قائمة صدارة الأعضاء (Top 10)", color=discord.Color.gold())
    description = ""
    for idx, (user_id, pts) in enumerate(rows, 1):
        member = interaction.guild.get_member(user_id)
        name = member.mention if member else f"عضو مغادر ({user_id})"
        description += f"**#{idx}** | {name} - **{round(pts, 2)}** نقطة\n"

    embed.description = description
    await interaction.response.send_message(embed=embed)

# 5. Reset Points Command
@bot.tree.command(name="reset_points", description="تصفير نقاط عضو معين أو جميع الأعضاء (للمشرفين فقط)")
@app_commands.checks.has_permissions(administrator=True)
async def reset_points(interaction: discord.Interaction, target_user: discord.Member = None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if target_user:
        cursor.execute("DELETE FROM user_points WHERE guild_id = ? AND user_id = ?", (interaction.guild_id, target_user.id))
        msg = f"🔄 تم تصفير نقاط العضو {target_user.mention} بنجاح."
    else:
        cursor.execute("DELETE FROM user_points WHERE guild_id = ?", (interaction.guild_id,))
        msg = "💥 تم تصفير نقاط **جميع الأعضاء** في السيرفر بنجاح."

    conn.commit()
    conn.close()
    await interaction.response.send_message(msg)

# Run Bot
TOKEN = os.getenv("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("Error: DISCORD_TOKEN environment variable not set.")
