import os, sqlite3, tempfile, asyncio, aiohttp, discord
from flask import Flask
from moviepy.editor import VideoFileClip
from discord import app_commands
from discord.ext import commands

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot Alive"

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

DB_NAME = "media_points.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS guild_config (guild_id INTEGER PRIMARY KEY, image_points REAL DEFAULT 1.0, gif_points REAL DEFAULT 2.0, video_points REAL DEFAULT 1.0, video_minute_points REAL DEFAULT 4.0, allowed_channels TEXT DEFAULT '', allowed_categories TEXT DEFAULT '')")
    c.execute("CREATE TABLE IF NOT EXISTS user_points (guild_id INTEGER, user_id INTEGER, points REAL DEFAULT 0.0, images_count INTEGER DEFAULT 0, gifs_count INTEGER DEFAULT 0, videos_count INTEGER DEFAULT 0, video_seconds INTEGER DEFAULT 0, PRIMARY KEY (guild_id, user_id))")
    c.execute("CREATE TABLE IF NOT EXISTS tracked_messages (message_id INTEGER PRIMARY KEY, guild_id INTEGER, user_id INTEGER, points_awarded REAL, media_type TEXT, duration_sec INTEGER)")
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
    return {"image_points": config[0], "gif_points": config[1], "video_points": config[2], "video_minute_points": config[3], "allowed_channels": [int(x) for x in config[4].split(",") if x.strip()], "allowed_categories": [int(x) for x in config[5].split(",") if x.strip()]}

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
                    dur = clip.duration
                    clip.close()
                    return dur
    except Exception as e:
        print(f"Vid err: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass
    return 0.0

@bot.event
async def on_ready():
    print(f"Logged in: {bot.user}")
    try: await bot.tree.sync()
    except Exception as e: print(f"Sync err: {e}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild: return
    cfg = get_config(message.guild.id)
    ch_ok = not cfg["allowed_channels"] or message.channel.id in cfg["allowed_channels"]
    cat_ok = not cfg["allowed_categories"] or (message.channel.category_id and message.channel.category_id in cfg["allowed_categories"])
    if not (ch_ok or cat_ok): return
    
    media = []
    for a in message.attachments:
        ct, fn = a.content_type or "", a.filename.lower()
        if "image/gif" in ct or fn.endswith('.gif'):
            media.append(('gif', cfg["gif_points"], 0))
        elif ct.startswith("image/"):
            media.append(('image', cfg["image_points"], 0))
        elif ct.startswith("video/") or fn.endswith(('.mp4', '.mov', '.avi', '.mkv')):
            dur = await get_video_duration(a.url)
            pts = cfg["video_points"] + ((dur / 60.0) * cfg["video_minute_points"])
            media.append(('video', pts, int(dur)))

    if media:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        tot_pts = sum(m[1] for m in media)
        imgs = sum(1 for m in media if m[0] == 'image')
        gifs = sum(1 for m in media if m[0] == 'gif')
        vids = sum(1 for m in media if m[0] == 'video')
        secs = sum(m[2] for m in media if m[0] == 'video')
        c.execute("INSERT INTO user_points VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET points=points+?, images_count=images_count+?, gifs_count=gifs_count+?, videos_count=videos_count+?, video_seconds=video_seconds+?", (message.guild.id, message.author.id, tot_pts, imgs, gifs, vids, secs, tot_pts, imgs, gifs, vids, secs))
        for m_type, pts, dur in media:
            c.execute("INSERT INTO tracked_messages VALUES (?, ?, ?, ?, ?, ?)", (message.id, message.guild.id, message.author.id, pts, m_type, dur))
        conn.commit()
        conn.close()

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild: return
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT points_awarded, media_type, duration_sec FROM tracked_messages WHERE message_id = ?", (message.id,))
    recs = c.fetchall()
    if recs:
        pts = sum(r[0] for r in recs)
        imgs = sum(1 for r in recs if r[1] == 'image')
        gifs = sum(1 for r in recs if r[1] == 'gif')
        vids = sum(1 for r in recs if r[1] == 'video')
        secs = sum(r[2] for r in recs if r[1] == 'video')
        c.execute("UPDATE user_points SET points=max(0, points-?), images_count=max(0, images_count-?), gifs_count=max(0, gifs_count-?), videos_count=max(0, videos_count-?), video_seconds=max(0, video_seconds-?) WHERE guild_id=? AND user_id=?", (pts, imgs, gifs, vids, secs, message.guild.id, message.author.id))
        c.execute("DELETE FROM tracked_messages WHERE message_id = ?", (message.id,))
        conn.commit()
    conn.close()

@bot.tree.command(name="setup_points", description="تعديل احتساب النقاط")
@app_commands.checks.has_permissions(administrator=True)
async def setup_points(interaction: discord.Interaction, image_points: float, gif_points: float, video_points: float, video_minute_points: float):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO guild_config (guild_id, image_points, gif_points, video_points, video_minute_points) VALUES (?, ?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET image_points=?, gif_points=?, video_points=?, video_minute_points=?", (interaction.guild_id, image_points, gif_points, video_points, video_minute_points, image_points, gif_points, video_points, video_minute_points))
    conn.commit()
    conn.close()
    await interaction.response.send_message("⚙️ تم تحديث النقاط!")

@bot.tree.command(name="setup_channels", description="تحديد الرومات")
@app_commands.checks.has_permissions(administrator=True)
async def setup_channels(interaction: discord.Interaction, channel: discord.TextChannel = None, category: discord.CategoryChannel = None):
    cfg = get_config(interaction.guild_id)
    chs, cats = cfg["allowed_channels"], cfg["allowed_categories"]
    if channel and channel.id not in chs: chs.append(channel.id)
    if category and category.id not in cats: cats.append(category.id)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE guild_config SET allowed_channels=?, allowed_categories=? WHERE guild_id=?", (",".join(map(str, chs)), ",".join(map(str, cats)), interaction.guild_id))
    conn.commit()
    conn.close()
    await interaction.response.send_message("✅ تم تحديد الرومات!", ephemeral=True)

@bot.tree.command(name="points", description="عرض النقاط")
async def points(interaction: discord.Interaction, user: discord.Member = None):
    t = user or interaction.user
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT points, images_count, gifs_count, videos_count, video_seconds FROM user_points WHERE guild_id=? AND user_id=?", (interaction.guild_id, t.id))
    row = c.fetchone()
    conn.close()
    pts, imgs, gifs, vids, secs = row if row else (0, 0, 0, 0, 0)
    embed = discord.Embed(title=f"📊 نقاط {t.display_name}", color=discord.Color.blue())
    embed.add_field(name="🏆 النقاط", value=f"**{round(pts, 2)}**", inline=False)
    embed.add_field(name="🖼️ الصور", value=f"`{imgs}`", inline=True)
    embed.add_field(name="🎥 الفيديوهات", value=f"`{vids}` ({round(secs/60, 1)} دقيقة)", inline=True)
    embed.add_field(name="GIF", value=f"`{gifs}`", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="عرض التوب 10")
async def leaderboard(interaction: discord.Interaction):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, points FROM user_points WHERE guild_id=? ORDER BY points DESC LIMIT 10", (interaction.guild_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await interaction.response.send_message("لا توجد بيانات.")
        return
    desc = "\n".join([f"**#{i+1}** | {interaction.guild.get_member(u).mention if interaction.guild.get_member(u) else u} - **{round(p, 2)}** نقطة" for i, (u, p) in enumerate(rows)])
    await interaction.response.send_message(embed=discord.Embed(title="🏆 قائمة الصدارة", description=desc, color=discord.Color.gold()))

@bot.tree.command(name="reset_points", description="تصفير النقاط")
@app_commands.checks.has_permissions(administrator=True)
async def reset_points(interaction: discord.Interaction, target_user: discord.Member = None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    if target_user:
        c.execute("DELETE FROM user_points WHERE guild_id=? AND user_id=?", (interaction.guild_id, target_user.id))
        msg = f"🔄 تم تصفير نقاط {target_user.mention}."
    else:
        c.execute("DELETE FROM user_points WHERE guild_id=?", (interaction.guild_id,))
        msg = "💥 تم تصفير نقاط الجميع."
    conn.commit()
    conn.close()
    await interaction.response.send_message(msg)

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if TOKEN:
        loop = asyncio.get_event_loop()
        loop.create_task(bot.start(TOKEN))
    else:
        print("Error: DISCORD_TOKEN missing.")
