"""
أدوات الإيموجي والستيكرز:
  /copyem  → نسخ أي إيموجي / ستيكر من أي سيرفر (يرسله كصورة أو GIF، أو يضيفه مباشرة)
  /addem   → إضافة إيموجي أو ستيكر من رابط صورة / GIF (أو مرفق)
  وأمر بالضغط يمين على أي رسالة: Apps ← Copy Emoji/Sticker (الطريقة الوحيدة لنسخ ستيكر من رسالة بسهولة)
"""
import asyncio
import io
import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import List, Literal, Optional
from urllib.parse import urlparse, urljoin

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from database import reply

EMOJI_RE = re.compile(r"<(a?):(\w{2,32}):(\d{15,25})>")
MSG_LINK_RE = re.compile(r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)")
STICKER_URL_RE = re.compile(r"(?:cdn|media)\.discordapp\.(?:com|net)/stickers/(\d+)")
EMOJI_URL_RE = re.compile(r"cdn\.discordapp\.com/emojis/(\d+)\.(\w+)")
ID_RE = re.compile(r"^\d{15,25}$")

MAX_DOWNLOAD = 8 * 1024 * 1024
MAX_ITEMS = 20
EMOJI_MAX_BYTES = 256 * 1024
STICKER_MAX_BYTES = 512 * 1024


class CopyError(Exception):
    """خطأ مفهوم نعرضه للمستخدم كما هو."""


@dataclass
class Item:
    kind: str            # emoji | sticker
    name: str
    ident: int
    url: str
    animated: bool = False
    lottie: bool = False
    related: str = "🙂"
    description: str = ""


# ═══════════════════════════ تحميل آمن ═══════════════════════════
def _host_is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def detect_format(data: bytes) -> str:
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "apng" if b"acTL" in data[:4096] else "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return "unknown"


async def fetch_image(url: str):
    """يحمّل صورة من رابط مباشر. يرجع (bytes, format)."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise CopyError("الرابط لازم يبدأ بـ http:// أو https://")
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (ZenoBot)"}) as session:
        current = url.strip()
        for _ in range(4):  # نتتبع التحويلات يدوياً ونفحص كل عنوان
            host = urlparse(current).hostname or ""
            if not await asyncio.to_thread(_host_is_public, host):
                raise CopyError("هذا الرابط غير مسموح.")
            try:
                async with session.get(current, allow_redirects=False) as r:
                    if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                        current = urljoin(current, r.headers["Location"])
                        continue
                    if r.status != 200:
                        raise CopyError(f"الرابط رجّع خطأ (الحالة {r.status}).")
                    if r.content_length and r.content_length > MAX_DOWNLOAD:
                        raise CopyError("الملف كبير جداً (الحد 8MB).")
                    data = await r.content.read(MAX_DOWNLOAD + 1)
            except aiohttp.ClientError:
                raise CopyError("تعذر تحميل الرابط.")
            except asyncio.TimeoutError:
                raise CopyError("انتهت مهلة تحميل الرابط.")
            if len(data) > MAX_DOWNLOAD:
                raise CopyError("الملف كبير جداً (الحد 8MB).")
            fmt = detect_format(data)
            if fmt == "unknown":
                raise CopyError("الرابط ما هو صورة مباشرة. استخدم رابط ينتهي بـ .png أو .gif "
                                "(روابط صفحات Tenor/Giphy ما تنفع، افتح الصورة وانسخ رابطها المباشر).")
            return data, fmt
        raise CopyError("الرابط يحوّل كثير.")


# ═══════════════════════════ معالجة الصور (Pillow) ═══════════════════════════
def _process(data: bytes, fmt: str, max_bytes: int, dims: List[int], allow_apng: bool):
    """يحول/يصغّر الصورة لتناسب حدود ديسكورد. يرجع (bytes, ext)."""
    from PIL import Image, ImageSequence

    # لا نحتاج تعديل: صيغة مقبولة وحجم مناسب
    ok_formats = ("png", "gif") + (("apng",) if allow_apng else ())
    if fmt in ok_formats and len(data) <= max_bytes:
        return data, ("png" if fmt == "apng" else fmt)

    im = Image.open(io.BytesIO(data))
    n = getattr(im, "n_frames", 1)
    animated = n > 1
    out_gif = animated and fmt != "apng" or (animated and not allow_apng)

    frames, durations = [], []
    if animated:
        step = 1 if n <= 120 else -(-n // 120)
        for idx, fr in enumerate(ImageSequence.Iterator(im)):
            if idx % step == 0:
                frames.append(fr.convert("RGBA"))
                durations.append(int(fr.info.get("duration", 100)) * step)
    else:
        frames = [im.convert("RGBA")]

    for dim in dims:
        sized = []
        for f in frames:
            c = f.copy()
            c.thumbnail((dim, dim), Image.LANCZOS)
            sized.append(c)
        buf = io.BytesIO()
        if not animated:
            sized[0].save(buf, format="PNG", optimize=True)
            ext = "png"
        elif out_gif:
            sized[0].save(buf, format="GIF", save_all=True, append_images=sized[1:], duration=durations,
                          loop=0, disposal=2, optimize=True)
            ext = "gif"
        else:
            sized[0].save(buf, format="PNG", save_all=True, append_images=sized[1:], duration=durations, loop=0)
            ext = "png"
        if buf.tell() <= max_bytes:
            return buf.getvalue(), ext
    raise CopyError("الصورة كبيرة حتى بعد التصغير. جرب صورة أصغر أو أقل إطارات.")


async def prepare(data: bytes, fmt: str, kind: str):
    if kind == "emoji":
        return await asyncio.to_thread(_process, data, fmt, EMOJI_MAX_BYTES, [128, 96, 64, 48], False)
    return await asyncio.to_thread(_process, data, fmt, STICKER_MAX_BYTES, [320, 256, 192, 128], True)


# ═══════════════════════════ استخراج العناصر ═══════════════════════════
def emoji_item(animated: bool, name: str, ident: int) -> Item:
    ext = "gif" if animated else "png"
    return Item("emoji", name, ident, f"https://cdn.discordapp.com/emojis/{ident}.{ext}?size=128", animated)


def sticker_item(s) -> Item:
    fmt = s.format
    return Item("sticker", s.name, s.id, s.url,
                animated=fmt in (discord.StickerFormatType.apng, discord.StickerFormatType.gif),
                lottie=fmt == discord.StickerFormatType.lottie)


async def items_from_message(message: discord.Message) -> List[Item]:
    items: List[Item] = []
    for a, name, i in EMOJI_RE.findall(message.content or ""):
        items.append(emoji_item(bool(a), name, int(i)))
    for r in message.reactions:
        e = r.emoji
        if getattr(e, "id", None):
            items.append(emoji_item(bool(e.animated), e.name, e.id))
    for s in message.stickers:
        it = sticker_item(s)
        try:
            full = await s.fetch()
            it.description = getattr(full, "description", "") or ""
            it.related = str(getattr(full, "emoji", "") or "🙂")
        except discord.HTTPException:
            pass
        items.append(it)
    return items


def dedupe(items: List[Item]) -> List[Item]:
    seen, out = set(), []
    for it in items:
        k = (it.kind, it.ident)
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out[:MAX_ITEMS]


async def resolve_source(bot: commands.Bot, source: str) -> List[Item]:
    items: List[Item] = []
    source = source.strip()

    m = MSG_LINK_RE.search(source)
    if m:
        _, ch_id, msg_id = map(int, m.groups())
        try:
            channel = bot.get_channel(ch_id) or await bot.fetch_channel(ch_id)
            message = await channel.fetch_message(msg_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            raise CopyError("ما قدرت أوصل لهذي الرسالة. لازم يكون البوت موجود في ذلك السيرفر. "
                            "الأسهل: اضغط يمين على الرسالة ← Apps ← Copy Emoji/Sticker.")
        items += await items_from_message(message)

    for a, name, i in EMOJI_RE.findall(source):
        items.append(emoji_item(bool(a), name, int(i)))

    for i, ext in EMOJI_URL_RE.findall(source):
        items.append(emoji_item(ext.lower() == "gif", f"emoji_{i[-4:]}", int(i)))

    for i in STICKER_URL_RE.findall(source):
        items.append(await _sticker_by_id(bot, int(i)))

    if ID_RE.match(source):
        items.append(await _sticker_by_id(bot, int(source)))

    items = dedupe(items)
    if not items:
        raise CopyError("ما لقيت إيموجي أو ستيكر في المدخل. الصق الإيموجي نفسه، أو رابط رسالة، أو ID/رابط ستيكر.\n"
                        "💡 للستيكرات الأسهل: اضغط يمين على الرسالة ← Apps ← **Copy Emoji/Sticker**.")
    return items


async def _sticker_by_id(bot: commands.Bot, sid: int) -> Item:
    try:
        s = await bot.fetch_sticker(sid)
        it = sticker_item(s)
        it.description = getattr(s, "description", "") or ""
        it.related = str(getattr(s, "emoji", "") or "🙂")
        return it
    except discord.HTTPException:
        return Item("sticker", f"sticker_{str(sid)[-4:]}", sid, f"https://cdn.discordapp.com/stickers/{sid}.png", True)


# ═══════════════════════════ التنفيذ ═══════════════════════════
def clean_emoji_name(name: str) -> str:
    n = re.sub(r"[^0-9a-zA-Z_]", "_", name or "")[:32]
    return n if len(n) >= 2 else (n + "_em")[:32] if n else "emoji_new"


def clean_sticker_name(name: str) -> str:
    n = (name or "").strip()[:30]
    return n if len(n) >= 2 else "sticker_new"


def human_http_error(e: discord.HTTPException) -> str:
    codes = {30008: "وصلت الحد الأقصى للإيموجيات", 30039: "وصلت الحد الأقصى للستيكرات",
             50035: "الصورة أو الاسم غير مقبولين من ديسكورد", 50013: "البوت ما عنده صلاحية"}
    return codes.get(e.code, e.text or "خطأ من ديسكورد")


async def add_item(guild: discord.Guild, user, item: Item, data: bytes, fmt: str, kind: str, name: Optional[str],
                   related: Optional[str] = None) -> str:
    """يضيف الصورة كإيموجي أو ستيكر. يرجع سطر نتيجة."""
    try:
        img, ext = await prepare(data, fmt, kind)
    except CopyError as e:
        return f"❌ **{item.name}**: {e}"
    except Exception:
        return f"❌ **{item.name}**: تعذر معالجة الصورة."
    reason = f"نسخ بواسطة {user}"
    try:
        if kind == "emoji":
            animated = ext == "gif"
            used = sum(1 for e in guild.emojis if e.animated == animated)
            if used >= guild.emoji_limit:
                return f"❌ **{item.name}**: مكان الإيموجيات {'المتحركة ' if animated else ''}ممتلئ ({guild.emoji_limit})."
            emoji = await guild.create_custom_emoji(name=clean_emoji_name(name or item.name), image=img, reason=reason)
            return f"✅ {emoji} `:{emoji.name}:`"
        if len(guild.stickers) >= guild.sticker_limit:
            return f"❌ **{item.name}**: مكان الستيكرات ممتلئ ({guild.sticker_limit})."
        sname = clean_sticker_name(name or item.name)
        sticker = await guild.create_sticker(
            name=sname, description=(item.description or sname)[:100] if len(item.description or sname) >= 2 else sname,
            emoji=related or item.related or "🙂", file=discord.File(io.BytesIO(img), filename=f"{sname}.{ext}"),
            reason=reason)
        return f"✅ ستيكر **{sticker.name}**"
    except discord.Forbidden:
        return f"❌ **{item.name}**: البوت ما عنده صلاحية Manage Expressions."
    except discord.HTTPException as e:
        return f"❌ **{item.name}**: {human_http_error(e)}"


def can_add(interaction: discord.Interaction) -> Optional[str]:
    if not interaction.guild:
        return "❌ هذا الأمر داخل السيرفرات فقط."
    if not interaction.user.guild_permissions.manage_emojis_and_stickers:
        return "❌ تحتاج صلاحية **Manage Expressions** (إدارة الإيموجي والستيكرات) عشان تضيف."
    if not interaction.guild.me.guild_permissions.manage_emojis_and_stickers:
        return "❌ البوت يحتاج صلاحية **Manage Expressions** عشان يضيف."
    return None


class CopyActionView(discord.ui.View):
    def __init__(self, cog: "EmojiTools", items: List[Item], owner_id: int):
        super().__init__(timeout=180)
        self.cog, self.items, self.owner_id = cog, items, owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await reply(interaction, "❌ هذي القائمة ليست لك.", ephemeral=True)
            return False
        return True

    async def _run(self, interaction: discord.Interaction, action: str):
        await interaction.response.defer(ephemeral=True)
        await self.cog.perform(interaction, self.items, action, None, hidden=True)

    @discord.ui.button(label="إرسال كصور", emoji="📤", style=discord.ButtonStyle.primary)
    async def b_send(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run(interaction, "send")

    @discord.ui.button(label="إضافة كإيموجي", emoji="😀", style=discord.ButtonStyle.success)
    async def b_emoji(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run(interaction, "emoji")

    @discord.ui.button(label="إضافة كستيكر", emoji="🏷️", style=discord.ButtonStyle.success)
    async def b_sticker(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._run(interaction, "sticker")


class EmojiTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(name="Copy Emoji/Sticker", callback=self.ctx_copy)
        bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    # ───────────── التنفيذ المشترك ─────────────
    async def perform(self, interaction: discord.Interaction, items: List[Item], action: str,
                      name: Optional[str], hidden: bool = True, related: Optional[str] = None):
        """action: send | emoji | sticker — لازم تكون الاستجابة مؤجلة (defer) قبل الاستدعاء."""
        if action in ("emoji", "sticker"):
            err = can_add(interaction)
            if err:
                return await reply(interaction, err, ephemeral=True)

        files, lines = [], []
        for idx, it in enumerate(items):
            if it.lottie:
                lines.append(f"⚠️ **{it.name}**: ستيكر Lottie (متحرك JSON) ما ينسخ كصورة.")
                continue
            try:
                data, fmt = await fetch_image(it.url)
            except CopyError as e:
                lines.append(f"❌ **{it.name}**: {e}")
                continue

            if action == "send":
                if len(files) >= 10:
                    lines.append(f"⚠️ **{it.name}**: تخطيته (الحد 10 ملفات في الرسالة).")
                    continue
                ext = {"gif": "gif", "png": "png", "apng": "png", "jpg": "jpg", "webp": "webp"}[fmt]
                files.append(discord.File(io.BytesIO(data), filename=f"{clean_emoji_name(it.name)}.{ext}"))
            else:
                kind = "emoji" if action == "emoji" else "sticker"
                lines.append(await add_item(interaction.guild, interaction.user, it, data, fmt, kind,
                                            name if len(items) == 1 else None, related))

        if action == "send":
            text = "📤 تم! احفظ الصورة (أو GIF) من الرسالة.\n" + "\n".join(lines) if files else "\n".join(lines) or "❌ ما قدرت أجيب شي."
            if files:
                await reply(interaction, text.strip(), files=files, ephemeral=hidden)
            else:
                await reply(interaction, text, ephemeral=True)
        else:
            await reply(interaction, "\n".join(lines)[:1900] or "❌ ما صار شي.", ephemeral=hidden,
                        allowed_mentions=discord.AllowedMentions.none())

    # ───────────── /copyem ─────────────
    @app_commands.command(name="copyem", description="نسخ إيموجي أو ستيكر من أي سيرفر (كصورة/GIF أو إضافة مباشرة)")
    @app_commands.describe(
        source="الإيموجي نفسه، أو رابط رسالة فيها إيموجي/ستيكر، أو ID/رابط ستيكر",
        action="وش تبي أسوي فيه؟ (الافتراضي: إرسال كصورة)",
        name="اسم جديد (اختياري، لو عنصر واحد فقط)",
        hidden="إخفاء الرد عن الباقين (الافتراضي نعم)")
    @app_commands.guild_only()
    async def copyem(self, interaction: discord.Interaction, source: str,
                     action: Literal["إرسال كصورة / GIF", "إضافة كإيموجي", "إضافة كستيكر"] = "إرسال كصورة / GIF",
                     name: Optional[str] = None, hidden: bool = True):
        await interaction.response.defer(ephemeral=hidden)
        mode = {"إرسال كصورة / GIF": "send", "إضافة كإيموجي": "emoji", "إضافة كستيكر": "sticker"}[action]
        try:
            items = await resolve_source(self.bot, source)
        except CopyError as e:
            return await reply(interaction, f"❌ {e}", ephemeral=True)
        await self.perform(interaction, items, mode, name, hidden=hidden)

    # ───────────── قائمة الضغط يمين على رسالة ─────────────
    @app_commands.guild_only()
    async def ctx_copy(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)
        items = dedupe(await items_from_message(message))
        if not items:
            return await reply(interaction, "❌ هذي الرسالة ما فيها إيموجي مخصص أو ستيكر.", ephemeral=True)
        names = "، ".join(f"`{i.name}`" for i in items[:10])
        await reply(interaction, f"لقيت **{len(items)}** عنصر: {names}\nوش تبي أسوي فيهم؟",
                    view=CopyActionView(self, items, interaction.user.id), ephemeral=True)

    # ───────────── /addem ─────────────
    @app_commands.command(name="addem", description="إضافة إيموجي أو ستيكر من رابط صورة أو GIF")
    @app_commands.describe(
        kind="نوع الإضافة", name="الاسم (الإيموجي: حروف إنجليزية وأرقام و_ فقط)",
        url="رابط مباشر للصورة أو GIF", file="أو ارفق الصورة مباشرة بدل الرابط",
        related_emoji="للستيكر فقط: إيموجي مرتبط فيه (مثل 😂)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_emojis_and_stickers=True)
    @app_commands.checks.bot_has_permissions(manage_emojis_and_stickers=True)
    async def addem(self, interaction: discord.Interaction, kind: Literal["إيموجي", "ستيكر"], name: str,
                    url: Optional[str] = None, file: Optional[discord.Attachment] = None, related_emoji: str = "🙂"):
        if not url and not file:
            return await reply(interaction, "❌ حط رابط الصورة في `url` أو ارفق صورة في `file`.", ephemeral=True)
        await interaction.response.defer()
        src = file.url if file else url
        try:
            data, fmt = await fetch_image(src)
        except CopyError as e:
            return await reply(interaction, f"❌ {e}", ephemeral=True)
        k = "emoji" if kind == "إيموجي" else "sticker"
        item = Item(k, name, 0, src)
        line = await add_item(interaction.guild, interaction.user, item, data, fmt, k, name, related_emoji)
        await reply(interaction, line, allowed_mentions=discord.AllowedMentions.none(),
                    ephemeral=line.startswith("❌"))


async def setup(bot):
    await bot.add_cog(EmojiTools(bot))
