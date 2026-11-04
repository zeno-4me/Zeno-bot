import asyncio
import json
import os
import re
import shutil
import tempfile
import time
from urllib.parse import urlparse

import aiohttp
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
DOWNLOAD_TIMEOUT = 120               # ثواني (yt-dlp)
HTTP_TIMEOUT = 30                    # ثواني لطلبات الـ API
FILE_TIMEOUT = 120                   # ثواني لتحميل الملف من الرابط المباشر
COMPRESS_TIMEOUT = 150               # ثواني
USER_COOLDOWN = 4                    # ثواني بين كل رسالة وأخرى لنفس العضو
MAX_PARALLEL = 2                     # عدد التحميلات المتزامنة

# ───────────── مصادر التحميل ─────────────
# Cobalt: يفضّل تشغيل نسختك الخاصة (Docker) لأن النسخ العامة غالباً تطلب مفتاح أو تقفل.
#   COBALT_API_URL = رابط واحد أو أكثر مفصولة بفاصلة، مثال: https://cobalt.example.com/
#   COBALT_API_KEY = (اختياري) مفتاح الـ API إذا النسخة تطلبه
COBALT_URLS = [u.strip() for u in os.getenv("COBALT_API_URL", "").split(",") if u.strip()]
COBALT_KEY = os.getenv("COBALT_API_KEY", "").strip()
# (اختياري) ملف cookies لـ yt-dlp بصيغة Netscape، يساعد مع الانستا
YTDLP_COOKIES = os.getenv("YTDLP_COOKIES", "").strip()

# ترتيب المحاولة لكل منصة: أول مصدر ينجح يكفي
PROVIDER_ORDER = {
    "instagram": ["ytdlp"],
    "tiktok": ["tikwm", "cobalt", "ytdlp"],
    "x": ["fxtwitter", "cobalt", "ytdlp"],
    "youtube": ["cobalt", "ytdlp"],
    "snapchat": ["cobalt", "ytdlp"],
    "facebook": ["cobalt", "ytdlp"],
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

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
        self._session = None

    async def cog_unload(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers={"User-Agent": UA})
        return self._session

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

        # فيه رابط مدعوم أصلاً؟ (فحص سريع قبل أي استعلام قاعدة بيانات)
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
        all_items = [(u, key) for u, key in found if platforms.get(key, True)]
        if not all_items:
            return
        items = all_items[:MAX_LINKS_PER_MESSAGE]

        perms = message.channel.permissions_for(message.guild.me)
        if not (perms.send_messages and perms.attach_files):
            return

        # الوضع الفعلي: ما نحذف إلا إذا عندنا صلاحية، وكل الروابط بنحولها
        mode = cfg.get("mode", "keep")
        if mode == "delete" and not (perms.manage_messages and len(items) == len(all_items)):
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
            for u, _ in items:
                rest = rest.replace(u, "")
            rest = rest.strip()[:500]
            caption = f"🎬 {message.author.mention}" + (f"\n{rest}" if rest else "")

        try:
            await message.add_reaction("⏳")
        except discord.HTTPException:
            pass

        results = []
        try:
            for i, (url, key) in enumerate(items):
                ok = await self._process(message, url, key, max_duration,
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
    async def _process(self, message: discord.Message, url: str, platform: str, max_duration: int,
                       use_reply: bool, content=None) -> bool:
        """يرجع True إذا انرسل الفيديو."""
        limit = max(message.guild.filesize_limit - 300_000, 1_000_000)
        async with self._sem:
            tmp = tempfile.mkdtemp(prefix="linkfix_")
            try:
                path, duration = await self._fetch(url, platform, tmp, max_duration)
                if not path:
                    return False

                if os.path.getsize(path) > limit:
                    path = await self._compress(path, duration, limit, tmp)
                    if not path or os.path.getsize(path) > limit:
                        await self._send(message, True, content="❌ الفيديو كبير وما قدرت أصغّره لحجم يناسب السيرفر.",
                                         delete_after=8)
                        return False

                await self._send(message, use_reply, path=path, content=content)
                return True
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
        await message.channel.send(allowed_mentions=discord.AllowedMentions.none(), **build())

    # ───────────── اختيار المصدر ─────────────
    async def _fetch(self, url: str, platform: str, tmp: str, max_duration: int):
        """يجرب مصادر المنصة بالترتيب. يرجع (مسار الملف، المدة) أو (None, None)."""
        for provider in PROVIDER_ORDER.get(platform, ["ytdlp"]):
            try:
                if provider == "ytdlp":
                    if yt_dlp is None:
                        continue
                    path, duration = await asyncio.wait_for(
                        asyncio.to_thread(self._download_ytdlp, url, tmp, max_duration),
                        timeout=DOWNLOAD_TIMEOUT)
                else:
                    if provider == "cobalt" and not COBALT_URLS:
                        continue
                    if provider == "tikwm":
                        direct, duration = await self._api_tikwm(url)
                    elif provider == "fxtwitter":
                        direct, duration = await self._api_fxtwitter(url)
                    else:
                        direct, duration = await self._api_cobalt(url)
                    if not direct:
                        continue
                    if duration and duration > max_duration:
                        print(f"[linkfix] {provider}: الفيديو أطول من الحد ({duration}s): {url}")
                        return None, None
                    path = await self._download_file(direct, tmp)
                    if path and not duration:
                        duration = await self._probe_duration(path)
                        if duration and duration > max_duration:
                            print(f"[linkfix] {provider}: الفيديو أطول من الحد ({duration}s): {url}")
                            return None, None

                if path:
                    print(f"[linkfix] نجح {platform} عبر {provider}")
                    return path, duration
            except asyncio.TimeoutError:
                print(f"[linkfix] {provider}: انتهت المهلة ({platform}): {url}")
            except Exception as e:
                print(f"[linkfix] {provider} فشل ({platform}): {type(e).__name__}: {e}")
        return None, None

    # ───────────── مصادر الـ API ─────────────
    async def _get_json(self, url: str, **kw):
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with self._http().get(url, timeout=timeout, **kw) as r:
            return await r.json(content_type=None)

    async def _api_tikwm(self, url: str):
        data = await self._get_json("https://www.tikwm.com/api/", params={"url": url, "hd": "1"})
        if not isinstance(data, dict) or data.get("code") != 0:
            raise RuntimeError(f"tikwm: {str((data or {}).get('msg'))[:100]}")
        d = data.get("data") or {}
        link = d.get("hdplay") or d.get("play")
        if not link:
            return None, None  # غالباً سلايد صور مو فيديو
        if link.startswith("/"):
            link = "https://www.tikwm.com" + link
        return link, d.get("duration")

    async def _api_fxtwitter(self, url: str):
        m = re.search(r"/(\w+)/status/(\d+)", url)
        if not m:
            return None, None
        data = await self._get_json(f"https://api.fxtwitter.com/{m.group(1)}/status/{m.group(2)}")
        tweet = (data or {}).get("tweet") or {}
        videos = ((tweet.get("media") or {}).get("videos")) or []
        if not videos:
            return None, None
        v = videos[0]
        return v.get("url"), v.get("duration")

    async def _api_cobalt(self, url: str):
        payload = {"url": url, "videoQuality": "720", "youtubeVideoCodec": "h264", "filenameStyle": "basic"}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if COBALT_KEY:
            headers["Authorization"] = f"Api-Key {COBALT_KEY}"
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)

        last_err = None
        for base in COBALT_URLS:
            try:
                async with self._http().post(base, json=payload, headers=headers, timeout=timeout) as r:
                    data = await r.json(content_type=None)
                status = (data or {}).get("status")
                if status in ("tunnel", "redirect", "stream"):
                    return data.get("url"), None
                if status == "picker":
                    for item in data.get("picker") or []:
                        if item.get("type") in (None, "video") and item.get("url"):
                            return item["url"], None
                    last_err = "picker بدون فيديو"
                    continue
                err = (data or {}).get("error")
                code = err.get("code") if isinstance(err, dict) else err
                last_err = f"{base}: {code or status}"
            except Exception as e:
                last_err = f"{base}: {type(e).__name__}: {e}"
        raise RuntimeError(f"cobalt: {last_err}")

    # ───────────── تحميل ملف من رابط مباشر ─────────────
    async def _download_file(self, direct_url: str, tmp: str):
        path = os.path.join(tmp, "video.mp4")
        timeout = aiohttp.ClientTimeout(total=FILE_TIMEOUT)
        host = urlparse(direct_url).netloc
        headers = {"Referer": f"https://{host}/"}
        size = 0
        async with self._http().get(direct_url, timeout=timeout, headers=headers) as r:
            if r.status != 200:
                raise RuntimeError(f"تحميل الملف رجع HTTP {r.status}")
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "text/html" in ctype or "json" in ctype:
                raise RuntimeError(f"الرابط المباشر مو فيديو ({ctype})")
            clen = r.content_length
            if clen and clen > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("الملف أكبر من الحد المسموح للتحميل")
            with open(path, "wb") as f:
                async for chunk in r.content.iter_chunked(256 * 1024):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise RuntimeError("الملف أكبر من الحد المسموح للتحميل")
                    f.write(chunk)
        if size < 1000:
            raise RuntimeError("الملف فاضي")
        return path

    async def _probe_duration(self, path: str):
        """يستخرج مدة الفيديو من مخرجات ffmpeg (بدون ffprobe)."""
        if not FFMPEG:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                FFMPEG, "-i", path,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
            _, err = await asyncio.wait_for(proc.communicate(), timeout=20)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err.decode("utf-8", "ignore"))
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
        return None

    # ───────────── التحميل عبر yt-dlp (يشتغل في thread) ─────────────
    def _download_ytdlp(self, url: str, tmp: str, max_duration: int):
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
        if YTDLP_COOKIES and os.path.exists(YTDLP_COOKIES):
            opts["cookiefile"] = YTDLP_COOKIES

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if not info:
            return None, None
        if info.get("entries"):
            entries = [e for e in info["entries"] if e]
            if not entries:
                return None, None
            info = entries[0]

        files = [
            os.path.join(tmp, f) for f in os.listdir(tmp)
            if f.lower().endswith((".mp4", ".mov", ".webm", ".mkv"))
        ]
        if not files:
            return None, info.get("duration")
        files.sort(key=os.path.getsize, reverse=True)
        return files[0], info.get("duration")

    # ───────────── الضغط عند تجاوز حد الرفع ─────────────
    async def _compress(self, path: str, duration, limit: int, tmp: str):
        if not FFMPEG:
            return None
        if not duration:
            duration = await self._probe_duration(path)
        if not duration:
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
