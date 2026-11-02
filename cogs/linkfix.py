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
MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024
DOWNLOAD_TIMEOUT = 120               # ثواني
COMPRESS_TIMEOUT = 150               # ثواني
USER_COOLDOWN = 4                    # ثواني بين كل رسالة وأخرى لنفس العضو
MAX_PARALLEL = 2                     # عدد التحميلات المتزامنة

# المنصات المدعومة: (مفتاح المنصة، النمط). روابط الفيديو القصير فقط، مو فيديوهات يوتيوب الطويلة
SUPPORTED = [
    ("youtube", re.compile(r"^https?://(?:www\.|m\.)?youtube\.com/shorts/[\w-]+", re.I)),
    ("tiktok", re.compile(r"^https?://(?:www\.|m\.|vm\.|vt\.)?tiktok\.com/\S+", re.I)),
    ("instagram", re.compile(r"^https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:reels?|p|tv)/[\w-]+", re.I)),
    ("snapchat", re.compile(r"^https?://(?:www\.)?snapchat\.com/(?:spotlight|t)/\S+", re.I)),
    ("snapchat", re.compile(r"^https?://story\.snapchat\.com/\S+", re.I)),
    ("x", re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/\w+/status/\d+", re.I)),
    ("facebook", re.compile(r"^https?://(?:www\.|m\.|web\.)?facebook\.com/(?:reel/|watch/?\?|[\w.]+/videos/)\S*", re.I)),
    ("facebook", re.compile(r"^https?://fb\.watch/\S+", re.I)),
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


def match_platform(url: str):
    for key, pattern in SUPPORTED:
        if pattern.match(url):
            return key
    return None


def _hits(ids: set, selected) -> bool:
    return bool(ids & set(selected or []))


class LinkFix(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._sem = asyncio.Semaphore(MAX_PARALLEL)
        self._cooldown = {}

    # ───────────── فلاتر القنوات والرتب ─────────────
    @staticmethod
    def _channel_allowed(message: discord.Message, cfg: dict) -> bool:
        mode = cfg.get("channel_mode", "all")
        if mode not in ("include", "exclude"):
            return True
        ch = message.channel
        ids = {ch.id}
        parent_id = getattr(ch, "parent_id", None)          # ثريد/بوست فورم
        if parent_id:
            ids.add(parent_id)
        cat_id = getattr(ch, "category_id", None)
        if cat_id:
            ids.add(cat_id)
        parent = getattr(ch, "parent", None)
        if parent is not None and getattr(parent, "category_id", None):
            ids.add(parent.category_id)
        hit = _hits(ids, cfg.get("channels"))
        return hit if mode == "include" else not hit

    @staticmethod
    def _member_allowed(message: discord.Message, cfg: dict) -> bool:
        mode = cfg.get("role_mode", "all")
        if mode not in ("include", "exclude"):
            return True
        role_ids = {r.id for r in getattr(message.author, "roles", [])}
        hit = _hits(role_ids, cfg.get("roles"))
        return hit if mode == "include" else not hit

    # ───────────── الاستماع للرسائل ─────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content:
            return
        if yt_dlp is None:
            return

        # اللي فيه رابط مدعوم أصلاً؟ (فحص سريع قبل أي استعلام قاعدة بيانات)
        found = []
        for m in URL_RE.finditer(message.content):
            u = m.group(0).rstrip(".,!?)]}'\"")
            key = match_platform(u)
            if key and all(u != f[0] for f in found):
                found.append((u, key))
        if not found:
            return

        settings = await db.get_guild_settings(message.guild.id)
        enabled = settings.get('link_embed_enabled')
        if enabled is not None and not enabled:
            return
        # إذا منع الروابط شغال (والعضو مو إداري) الرسالة بتنحذف، فلا نحولها
        if (settings.get('automod_enabled') and settings.get('anti_links')
                and not message.author.guild_permissions.manage_messages):
            return

        cfg = await db.get_link_config(message.guild.id)
        if not self._channel_allowed(message, cfg) or not self._member_allowed(message, cfg):
            return

        platforms = cfg.get("platforms", {})
        all_urls = [u for u, key in found if platforms.get(key, True)]
        if not all_urls:
            return
        urls = all_urls[:MAX_LINKS_PER_MESSAGE]

        perms = message.channel.permissions_for(message.guild.me)
        if not (perms.send_messages and perms.attach_files):
            return

        # الوضع الفعلي: ما نحذف إلا إذا عندنا صلاحية، وكل الروابط بنحولها
        mode = cfg.get("mode", "keep")
        if mode == "delete" and not (perms.manage_messages and len(urls) == len(all_urls)):
            mode = "keep"
        if mode == "suppress" and not perms.manage_messages:
            mode = "keep"

        now = time.monotonic()
        if now - self._cooldown.get(message.author.id, 0) < USER_COOLDOWN:
            return
        self._cooldown[message.author.id] = now
        if len(self._cooldown) > 1000:
            self._cooldown = {k: v for k, v in self._cooldown.items() if now - v < USER_COOLDOWN}

        max_duration = int(cfg.get("max_duration") or 180)
        caption = None
        if mode == "delete":
            rest = message.content
            for u in urls:
                rest = rest.replace(u, "")
            rest = rest.strip()[:500]
            caption = f"🎬 {message.author.mention}" + (f"\n{rest}" if rest else "")

        try:
            await message.add_reaction("⏳")
        except discord.HTTPException:
            pass

        results = []
        try:
            for i, url in enumerate(urls):
                ok = await self._process(message, url, max_duration,
                                         use_reply=(mode != "delete"),
                                         content=caption if i == 0 else None)
                results.append(ok)
        finally:
            try:
                await message.remove_reaction("⏳", self.bot.user)
            except discord.HTTPException:
                pass

        try:
            if mode == "delete" and results and all(results):
                await message.delete()
            elif mode == "suppress" and any(results):
                await message.edit(suppress=True)
        except discord.HTTPException:
            pass

    # ───────────── المعالجة ─────────────
    async def _process(self, message: discord.Message, url: str, max_duration: int,
                       use_reply: bool, content=None) -> bool:
        """يرجع True إذا انرسل الفيديو."""
        limit = max(message.guild.filesize_limit - 300_000, 1_000_000)
        async with self._sem:
            tmp = tempfile.mkdtemp(prefix="linkfix_")
            try:
                path, info = await asyncio.wait_for(
                    asyncio.to_thread(self._download, url, tmp, max_duration), timeout=DOWNLOAD_TIMEOUT)
                if not path:
                    return False

                if os.path.getsize(path) > limit:
                    path = await self._compress(path, info.get("duration"), limit, tmp)
                    if not path or os.path.getsize(path) > limit:
                        await self._send(message, True, content="❌ الفيديو كبير وما قدرت أصغّره لحجم يناسب السيرفر.",
                                         delete_after=8)
                        return False

                await self._send(message, use_reply, path=path, content=content)
                return True
            except asyncio.TimeoutError:
                print(f"[linkfix] انتهت مهلة التحميل: {url}")
            except Exception as e:
                # ما نرسل أخطاء للروم: الرابط ممكن يكون صورة/ستوري خاص ... إلخ
                print(f"[linkfix] فشل تحويل {url}: {type(e).__name__}: {e}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        return False

    async def _send(self, message: discord.Message, use_reply: bool, path=None, **kwargs):
        """يرسل الرسالة (رد أو رسالة عادية). الملف يتنشأ من جديد في كل محاولة لأن ديسكورد يغلقه بعد الإرسال."""
        def build():
            kw = dict(kwargs)
            if path:
                kw["file"] = discord.File(path, filename=os.path.basename(path))
            return kw

        if use_reply:
            try:
                await message.reply(mention_author=False, **build())
                return
            except discord.HTTPException:
                pass  # الرسالة الأصلية انحذفت؟ نرسل عادي
        try:
            await message.channel.send(allowed_mentions=discord.AllowedMentions.none(), **build())
        except discord.HTTPException as e:
            raise

    # ───────────── التحميل (يشتغل في thread) ─────────────
    def _download(self, url: str, tmp: str, max_duration: int):
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
            "match_filter": yt_dlp.utils.match_filter_func(f"duration <=? {max_duration}"),
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
