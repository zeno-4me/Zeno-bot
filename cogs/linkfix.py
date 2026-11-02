import asyncio
import os
import re
import shutil
import tempfile
import time

import discord
from discord.ext import commands

from database import db

try:
    import yt_dlp
except ImportError:  # يتثبت من requirements.txt
    yt_dlp = None

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = shutil.which("ffmpeg")

# ───────────── إعدادات ─────────────
MAX_LINKS_PER_MESSAGE = 2            # أقصى عدد روابط يتحول من رسالة وحدة
MAX_DURATION = 180                   # ثواني (أطول من كذا يتجاهله)
MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024
DOWNLOAD_TIMEOUT = 90                # ثواني
COMPRESS_TIMEOUT = 150               # ثواني
USER_COOLDOWN = 4                    # ثواني بين كل رسالة وأخرى لنفس العضو
MAX_PARALLEL = 2                     # عدد التحميلات المتزامنة

# المنصات المدعومة (روابط الفيديو القصير فقط، مو فيديوهات يوتيوب الطويلة)
SUPPORTED = [
    re.compile(r"^https?://(?:www\.|m\.)?youtube\.com/shorts/[\w-]+", re.I),
    re.compile(r"^https?://(?:www\.|m\.|vm\.|vt\.)?tiktok\.com/\S+", re.I),
    re.compile(r"^https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/[\w-]+", re.I),
    re.compile(r"^https?://(?:www\.)?snapchat\.com/(?:spotlight|t)/\S+", re.I),
    re.compile(r"^https?://story\.snapchat\.com/\S+", re.I),
    re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/\w+/status/\d+", re.I),
    re.compile(r"^https?://(?:www\.|m\.|web\.)?facebook\.com/(?:reel/|watch/?\?|[\w.]+/videos/)\S*", re.I),
    re.compile(r"^https?://fb\.watch/\S+", re.I),
]

# (?<!<) يتجاهل الروابط اللي بين < > (العضو قصد يخفي المعاينة)
URL_RE = re.compile(r"(?<!<)https?://[^\s<>]+", re.I)

# يفضّل H.264 عشان يشتغل على كل الأجهزة داخل ديسكورد
YTDLP_FORMAT = (
    "bv*[vcodec~='^(avc|h264)'][height<=720]+ba"
    "/b[vcodec~='^(avc|h264)'][height<=720]"
    "/bv*[height<=720]+ba"
    "/b[height<=720]"
    "/b"
)


class LinkFix(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._sem = asyncio.Semaphore(MAX_PARALLEL)
        self._cooldown = {}

    # ───────────── الاستماع للرسائل ─────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        if yt_dlp is None:
            return

        urls = []
        for m in URL_RE.finditer(message.content):
            u = m.group(0).rstrip(".,!?)]}'\"")
            if u not in urls and any(p.match(u) for p in SUPPORTED):
                urls.append(u)
        if not urls:
            return
        urls = urls[:MAX_LINKS_PER_MESSAGE]

        settings = await db.get_guild_settings(message.guild.id)
        enabled = settings.get('link_embed_enabled')
        if enabled is not None and not enabled:
            return
        # إذا منع الروابط شغال (والعضو مو إداري) الرسالة بتنحذف، فلا نحولها
        if (settings.get('automod_enabled') and settings.get('anti_links')
                and not message.author.guild_permissions.manage_messages):
            return

        perms = message.channel.permissions_for(message.guild.me)
        if not (perms.send_messages and perms.attach_files):
            return

        now = time.monotonic()
        if now - self._cooldown.get(message.author.id, 0) < USER_COOLDOWN:
            return
        self._cooldown[message.author.id] = now
        if len(self._cooldown) > 1000:
            self._cooldown = {k: v for k, v in self._cooldown.items() if now - v < USER_COOLDOWN}

        try:
            await message.add_reaction("⏳")
        except discord.HTTPException:
            pass
        try:
            for url in urls:
                await self._process(message, url)
        finally:
            try:
                await message.remove_reaction("⏳", self.bot.user)
            except discord.HTTPException:
                pass

    # ───────────── المعالجة ─────────────
    async def _process(self, message: discord.Message, url: str):
        limit = max(message.guild.filesize_limit - 300_000, 1_000_000)
        async with self._sem:
            tmp = tempfile.mkdtemp(prefix="linkfix_")
            try:
                path, info = await asyncio.wait_for(
                    asyncio.to_thread(self._download, url, tmp), timeout=DOWNLOAD_TIMEOUT)
                if not path:
                    return

                if os.path.getsize(path) > limit:
                    path = await self._compress(path, info.get("duration"), limit, tmp)
                    if not path or os.path.getsize(path) > limit:
                        await self._safe_send(message, content="❌ الفيديو كبير وما قدرت أصغّره لحجم يناسب السيرفر.",
                                              delete_after=8)
                        return

                await self._safe_send(message, file=discord.File(path, filename=os.path.basename(path)))
            except asyncio.TimeoutError:
                print(f"[linkfix] انتهت مهلة التحميل: {url}")
            except Exception as e:
                # ما نرسل أخطاء للروم: الرابط ممكن يكون صورة/ستوري خاص ... إلخ
                print(f"[linkfix] فشل تحويل {url}: {type(e).__name__}: {e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    async def _safe_send(self, message: discord.Message, **kwargs):
        try:
            await message.reply(mention_author=False, **kwargs)
        except discord.HTTPException:
            # الرسالة الأصلية انحذفت أو ما نقدر نرد عليها
            if "file" in kwargs:
                kwargs["file"].reset()
            try:
                await message.channel.send(**kwargs)
            except discord.HTTPException as e:
                print(f"[linkfix] فشل الإرسال: {e}")

    # ───────────── التحميل (يشتغل في thread) ─────────────
    def _download(self, url: str, tmp: str):
        opts = {
            "outtmpl": os.path.join(tmp, "%(id)s.%(ext)s"),
            "format": YTDLP_FORMAT,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 15,
            "retries": 2,
            "max_filesize": MAX_DOWNLOAD_BYTES,
            "match_filter": yt_dlp.utils.match_filter_func(f"duration <=? {MAX_DURATION}"),
        }
        if FFMPEG:
            opts["ffmpeg_location"] = FFMPEG

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if not info:
            return None, {}
        if info.get("entries"):
            entries = [e for e in info["entries"] if e]
            if not entries:
                return None, {}
            info = entries[0]

        files = [
            os.path.join(tmp, f) for f in os.listdir(tmp)
            if f.lower().endswith((".mp4", ".mov", ".webm", ".mkv"))
        ]
        if not files:
            return None, info
        files.sort(key=os.path.getsize, reverse=True)
        return files[0], info

    # ───────────── الضغط عند تجاوز حد الرفع ─────────────
    async def _compress(self, path: str, duration, limit: int, tmp: str):
        if not FFMPEG or not duration:
            return None
        audio_k = 96
        video_k = int((limit * 8 * 0.90) / duration / 1000 - audio_k)
        if video_k < 150:
            return None

        height = 480 if video_k < 600 else 720
        out = os.path.join(tmp, "compressed.mp4")
        cmd = [
            FFMPEG, "-y", "-i", path,
            "-vf", f"scale=-2:'min({height},ih)'",
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", f"{video_k}k", "-maxrate", f"{int(video_k * 1.2)}k", "-bufsize", f"{video_k * 2}k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{audio_k}k",
            "-movflags", "+faststart",
            out,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.wait(), timeout=COMPRESS_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return None
        if proc.returncode != 0 or not os.path.exists(out):
            return None
        return out


async def setup(bot):
    await bot.add_cog(LinkFix(bot))
