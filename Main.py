import os, sqlite3, tempfile, asyncio, aiohttp, discord
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
from moviepy.editor import VideoFileClip
from discord import app_commands
from discord.ext import commands

# --- HTTP Health Check Server for Render ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Live!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

Thread(target=run_health_server, daemon=True).start()

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

DB_NAME = "media_points.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id INTEGER PRIMARY KEY,
            image_points REAL DEFAULT 1.0,
            gif_points REAL DEFAULT 2.0,
            video_points REAL DEFAULT 1.0,
            video_minute_points REAL DEFAULT 4.0,
            allowed_channels TEXT DEFAULT '',
            allowed_categories TEXT DEFAULT ''
        )
    """)
    c.execute("""
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
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS tracked_messages (
            message_id INTEGER PRIMARY KEY,
            guild_id INTEGER,
            user_id INTEGER,
            points_awarded REAL,
            media_type TEXT,
            duration_sec INTEGER
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_config(guild_id: int):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT image_points, gif_points, video_points, video_minute_points, allowed_channels, allowed_categories FROM guild_config WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO guild_config (guild_id) VALUES (?)", (guild_id,))
        conn.commit()
        config = (1.0, 2.0, 1.0, 4.0, "", "")
    else:
        config = row
    conn.close()
    
    allowed_channels = [int(x) for x in config[4].split(",") if x.strip()]
    allowed_categories = [int(x) for x in config[5].split(",") if x.strip()]
    
    return {
        "image_points": config[0],
        "gif_points": config[1],
        "video_points": config[2],
        "video_minute_points": config[3],
        "allowed_channels": allowed_channels,
        "allowed_categories": allowed_categories
    }

async def get_video_duration(url: str) -> float:
    tmp_path = None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
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
            except:
                pass
    return 0.0

@bot.event
async def on_ready():
    print(f"✨ Logged in successfully as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🚀 Synced {len(synced)} Slash Commands.")
    except Exception as e:
        print(f"❌ Command Sync Error: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    cfg = get_config(message.guild.id)
    ch_ok = not cfg["allowed_channels"] or message.channel.id in cfg["allowed_channels"]
    cat_ok = not cfg["allowed_categories"] or (message.channel.category_id and message.channel.category_id in cfg["allowed_categories"])
    
    if not (ch_ok or cat_ok):
        return

    media_items = []
    for attachment in message.attachments:
        content_type = attachment.content_type or ""
        filename = attachment.filename.lower()

        if "image/gif" in content_type or filename.endswith('.gif'):
            media_items.append(('gif', cfg["gif_points"], 0))
        elif content_type.startswith("image/"):
            media_items.append(('image', cfg["image_points"], 0))
        elif content_type.startswith("video/") or filename.endswith(('.mp4', '.mov', '.avi', '.mkv')):
            duration = await get_video_duration(attachment.url)
            pts = cfg["video_points"] + ((duration / 60.0) * cfg["video_minute_points"])
            media_items.append(('video', pts, int(duration)))

    if media_items:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        total_pts = sum(m[1] for m in media_items)
        imgs = sum(1 for m in media_items if m[0] == 'image')
        gifs = sum(1 for m in media_items if m[0] == 'gif')
        vids = sum(1 for m in media_items if m[0] == 'video')
        secs = sum(m[2] for m in media_items if m[0] == 'video')

        c.execute("""
            INSERT INTO user_points (guild_id, user_id, points, images_count, gifs_count, videos_count, video_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                points = points + ?,
                images_count = images_count + ?,
                gifs_count = gifs_count + ?,
                videos_count = videos_count + ?,
                video_seconds = video_seconds + ?
        """, (message.guild.id, message.author.id, total_pts, imgs, gifs, vids, secs,
              total_pts, imgs, gifs, vids, secs))

        for m_type, pts, dur in media_items:
            c.execute("INSERT INTO tracked_messages VALUES (?, ?, ?, ?, ?, ?)",
                      (message.id, message.guild.id, message.author.id, pts, m_type, dur))

        conn.commit()
        conn.close()

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT points_awarded, media_type, duration_sec FROM tracked_messages WHERE message_id = ?", (message.id,))
    records = c.fetchall()

    if records:
        total_pts = sum(r[0] for r in records)
        imgs = sum(1 for r in records if r[1] == 'image')
        gifs = sum(1 for r in records if r[1] == 'gif')
        vids = sum(1 for r in records if r[1] == 'video')
        secs = sum(r[2] for r in records if r[1] == 'video')

        c.execute("""
            UPDATE user_points SET
                points = max(0, points - ?),
                images_count = max(0, images_count - ?),
                gifs_count = max(0, gifs_count - ?),
                videos_count = max(0, videos_count - ?),
                video_seconds = max(0, video_seconds - ?)
            WHERE guild_id = ? AND user_id = ?
        """, (total_pts, imgs, gifs, vids, secs, message.guild.id, message.author.id))

        c.execute("DELETE FROM tracked_messages WHERE message_id = ?", (message.id,))
        conn.commit()

    conn.close()

@bot.tree.command(name="setup_points", description="⚙️ إعداد نظام النقاط ومعدل الاحتساب")
@app_commands.checks.has_permissions(administrator=True)
async def setup_points(
    interaction: discord.Interaction, 
    image_points: float, 
    gif_points: float, 
    video_points: float, 
    video_minute_points: float
):
    await interaction.response.defer()
    
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        INSERT INTO guild_config (guild_id, image_points, gif_points, video_points, video_minute_points)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            image_points = ?,
            gif_points = ?,
            video_points = ?,
            video_minute_points = ?
    """, (interaction.guild_id, image_points, gif_points, video_points, video_minute_points,
          image_points, gif_points, video_points, video_minute_points))
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="⚙️ تم تحديث إعدادات النقاط بنجاح",
        color=discord.Color.blue()
    )
    embed.add_field(name="🖼️ نقاط الصورة", value=f"`{image_points}`", inline=True)
    embed.add_field(name="🎞️ نقاط الـ GIF", value=f"`{gif_points}`", inline=True)
    embed.add_field(name="🎥 نقاط الفيديو", value=f"`{video_points}`", inline=True)
    embed.add_field(name="⏱️ نقاط دقيقة الفيديو", value=f"`{video_minute_points}`", inline=True)
    embed.set_footer(text=f"بواسطة: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="setup_channels", description="📌 تحديد الرومات أو الكاتجوري المسموح بها")
@app_commands.checks.has_permissions(administrator=True)
async def setup_channels(
    interaction: discord.Interaction, 
    channel: discord.TextChannel = None, 
    category: discord.CategoryChannel = None
):
    await interaction.response.defer(ephemeral=True)
    
    cfg = get_config(interaction.guild_id)
    chs, cats = cfg["allowed_channels"], cfg["allowed_categories"]

    if channel and channel.id not in chs:
        chs.append(channel.id)
    if category and category.id not in cats:
        cats.append(category.id)

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE guild_config SET allowed_channels = ?, allowed_categories = ? WHERE guild_id = ?",
              (",".join(map(str, chs)), ",".join(map(str, cats)), interaction.guild_id))
    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="✅ تم تحديث الرومات المسموحة",
        color=discord.Color.green()
    )
    if channel:
        embed.add_field(name="💬 الروم المضاف", value=channel.mention, inline=False)
    if category:
        embed.add_field(name="📁 الكاتجوري المضاف", value=f"**{category.name}**", inline=False)
    
    embed.set_footer(text="سيتم احتساب النقاط فقط في الرومات المحددة.")
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="points", description="📊 عرض تفاصيل النقاط والإحصائيات الخاصة بك أو بعضو آخر")
async def points(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer()
    target = user or interaction.user
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT points, images_count, gifs_count, videos_count, video_seconds FROM user_points WHERE guild_id = ? AND user_id = ?",
              (interaction.guild_id, target.id))
    row = c.fetchone()
    conn.close()

    pts, imgs, gifs, vids, secs = row if row else (0.0, 0, 0, 0, 0)
    mins = round(secs / 60.0, 1)

    embed = discord.Embed(
        title=f"📊 إحصائيات ونقاط {target.display_name}",
        color=discord.Color.purple()
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🏆 إجمالي النقاط", value=f"```fix\n{round(pts, 2)} نقطة\n```", inline=False)
    embed.add_field(name="🖼️ الصور", value=f"**{imgs}** صورة", inline=True)
    embed.add_field(name="🎞️ الـ GIF", value=f"**{gifs}** متحركة", inline=True)
    embed.add_field(name="🎥 الفيديوهات", value=f"**{vids}** فيديو\n(`{mins}` دقيقة)", inline=True)
    embed.set_footer(text=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="leaderboard", description="🏆 عرض قائمة صدارة الأعضاء الأعلى نقاطاً")
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, points FROM user_points WHERE guild_id = ? ORDER BY points DESC LIMIT 10", (interaction.guild_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        await interaction.followup.send("❌ لا توجد بيانات نقاط حتى الآن في هذا السيرفر.")
        return

    embed = discord.Embed(
        title="🏆 قائمة الصدارة (Top 10)",
        description="أعلى الأعضاء جمعاً للنقاط من الوسائط والمشاركات:",
        color=discord.Color.gold()
    )

    medals = ["🥇", "🥈", "🥉"]
    leaderboard_text = ""

    for i, (user_id, pts) in enumerate(rows):
        member = interaction.guild.get_member(user_id)
        mention = member.mention if member else f"<@{user_id}>"
        rank_icon = medals[i] if i < 3 else f"**#{i+1}**"
        leaderboard_text += f"{rank_icon} | {mention} — **{round(pts, 2)}** نقطة\n"

    embed.description = leaderboard_text
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
    embed.set_footer(text=f"طلب بواسطة: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="reset_points", description="🔄 إعادة ضبط وتصفير النقاط")
@app_commands.checks.has_permissions(administrator=True)
async def reset_points(interaction: discord.Interaction, target_user: discord.Member = None):
    await interaction.response.defer()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    if target_user:
        c.execute("DELETE FROM user_points WHERE guild_id = ? AND user_id = ?", (interaction.guild_id, target_user.id))
        msg = f"🔄 تم تصفير نقاط {target_user.mention} بنجاح."
    else:
        c.execute("DELETE FROM user_points WHERE guild_id = ?", (interaction.guild_id,))
        msg = "💥 تم تصفير جميع نقاط الأعضاء في السيرفر."

    conn.commit()
    conn.close()

    embed = discord.Embed(
        title="🗑️ إعادة ضبط النقاط",
        description=msg,
        color=discord.Color.red()
    )
    await interaction.followup.send(embed=embed)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("Error: DISCORD_TOKEN missing.")
