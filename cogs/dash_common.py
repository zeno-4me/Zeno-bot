"""
أدوات واجهة مشتركة للداشبورد (ملف مساعد، ما فيه أوامر).
يحتوي: العرض الموحد، أزرار الرجوع، منتقي القنوات/الرتب، ومحرر الرسائل العام (نص أو إمبد).
"""
import traceback
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

import discord

from database import (db, reply, edit_reply, build_message, parse_hex, deep_merge, DEFAULT_MSG)

THUMB_AR = {"avatar": "صورة العضو", "server": "شعار السيرفر", "none": "بدون"}
THUMB_ALIASES = {
    "avatar": "avatar", "صورة": "avatar", "عضو": "avatar", "صورة العضو": "avatar",
    "server": "server", "سيرفر": "server", "شعار": "server", "شعار السيرفر": "server",
    "none": "none", "لا": "none", "بدون": "none", "": "none",
}


def short(text: str, n: int = 80) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def onoff(v) -> str:
    return "✅ مفعل" if v else "❌ معطل"


async def show(interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View):
    """يعرض شاشة (يعدل رسالة اللوحة الحالية)."""
    await edit_reply(interaction, content=None, embed=embed, view=view)


class NavView(discord.ui.View):
    """أساس كل شاشات اللوحة: للإداريين فقط + معالجة أخطاء ظاهرة بدل 'فشل التفاعل'."""

    def __init__(self, timeout: float = 900):
        super().__init__(timeout=timeout)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        perms = getattr(interaction.user, "guild_permissions", None)
        if not perms or not perms.administrator:
            await reply(interaction, "❌ هذه اللوحة للإداريين فقط!", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            await reply(interaction, f"❌ حدث خطأ: `{short(str(error), 150)}`", ephemeral=True)
        except Exception:
            pass

    def add_btn(self, label: str, cb, style=discord.ButtonStyle.secondary, row: Optional[int] = None,
                emoji: Optional[str] = None, disabled: bool = False) -> discord.ui.Button:
        b = discord.ui.Button(label=label, style=style, row=row, emoji=emoji, disabled=disabled)
        b.callback = cb
        self.add_item(b)
        return b

    def add_back(self, target, row: int = 4, label: str = "رجوع"):
        async def _cb(interaction: discord.Interaction):
            await target(interaction)
        return self.add_btn(label, _cb, discord.ButtonStyle.secondary, row=row, emoji="⬅️")


class ModalBase(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            await reply(interaction, f"❌ حدث خطأ: `{short(str(error), 150)}`", ephemeral=True)
        except Exception:
            pass


# ───────────────────────── منتقي قنوات / رتب (قائمة IDs) ─────────────────────────
class _ChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self, guild, current, on_save, placeholder):
        defaults = [discord.SelectDefaultValue(id=i, type=discord.SelectDefaultValueType.channel)
                    for i in (current or [])[:25] if guild and guild.get_channel(i)]
        kwargs = dict(
            placeholder=placeholder,
            channel_types=[discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.voice,
                           discord.ChannelType.forum, discord.ChannelType.category],
            min_values=0, max_values=25, row=0,
        )
        try:
            super().__init__(default_values=defaults, **kwargs)
        except TypeError:
            super().__init__(**kwargs)
        self.on_save = on_save

    async def callback(self, interaction: discord.Interaction):
        await self.on_save(interaction, [c.id for c in self.values])


class _RolesSelect(discord.ui.RoleSelect):
    def __init__(self, guild, current, on_save, placeholder):
        defaults = [discord.SelectDefaultValue(id=i, type=discord.SelectDefaultValueType.role)
                    for i in (current or [])[:25] if guild and guild.get_role(i)]
        kwargs = dict(placeholder=placeholder, min_values=0, max_values=25, row=0)
        try:
            super().__init__(default_values=defaults, **kwargs)
        except TypeError:
            super().__init__(**kwargs)
        self.on_save = on_save

    async def callback(self, interaction: discord.Interaction):
        await self.on_save(interaction, [r.id for r in self.values])


async def show_id_picker(interaction: discord.Interaction, kind: str, current: list, on_save, on_back,
                         title: str, hint: str = ""):
    """kind = channel | role. on_save(interaction, ids) تحفظ وتعيد عرض الشاشة الأم."""
    emb = discord.Embed(title=title, description=(hint + "\n" if hint else "") +
                        "اختر من القائمة (حتى 25). **اترك الاختيار فاضي** لمسح القائمة.",
                        color=discord.Color.blurple())
    view = NavView()
    if kind == "channel":
        view.add_item(_ChannelsSelect(interaction.guild, current, on_save, "📺 اختر القنوات أو الكاتيجوريات..."))
    else:
        view.add_item(_RolesSelect(interaction.guild, current, on_save, "👥 اختر الرتب..."))
    view.add_back(on_back, row=1)
    await show(interaction, emb, view)


def fmt_ids(ids: list, kind: str, limit: int = 12) -> str:
    if not ids:
        return "لا يوجد"
    f = "<#{}>" if kind == "channel" else "<@&{}>"
    s = " ".join(f.format(i) for i in ids[:limit])
    if len(ids) > limit:
        s += f" و{len(ids) - limit} آخرين"
    return s


# ───────────────────────── محرر الرسائل العام ─────────────────────────
@dataclass
class MsgCtx:
    title: str                                       # عنوان الشاشة
    load: Callable[[], Awaitable[dict]]              # يرجع قاموس الرسالة
    save: Callable[[dict], Awaitable[None]]          # يحفظ قاموس الرسالة
    back: Callable[[discord.Interaction], Awaitable[None]]
    vars_help: str = ""
    preview_vars: Optional[Callable[[discord.Interaction], dict]] = None
    allow_embed: bool = True
    extra: List[tuple] = field(default_factory=list)  # [(label, emoji, style, async cb(interaction))]
    extra_info: Optional[Callable[[], Awaitable[str]]] = None


def _parse_thumb(text: str) -> Optional[str]:
    return THUMB_ALIASES.get((text or "").strip().lower())


class MsgTextModal(ModalBase, title="نص الرسالة"):
    def __init__(self, ctx: MsgCtx, msg: dict):
        super().__init__()
        self.ctx = ctx
        self.t_title = discord.ui.TextInput(label="العنوان (يظهر في وضع الإمبد فقط)", required=False,
                                            max_length=256, default=msg.get("title") or None)
        self.t_desc = discord.ui.TextInput(label="نص الرسالة", style=discord.TextStyle.paragraph, required=False,
                                           max_length=2000, default=(msg.get("desc") or "")[:2000] or None)
        self.t_footer = discord.ui.TextInput(label="التذييل (إمبد فقط)", required=False, max_length=200,
                                             default=msg.get("footer") or None)
        for it in (self.t_title, self.t_desc, self.t_footer):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        msg = deep_merge(DEFAULT_MSG, await self.ctx.load())
        msg["title"] = self.t_title.value.strip()
        msg["desc"] = self.t_desc.value
        msg["footer"] = self.t_footer.value.strip()
        await self.ctx.save(msg)
        await show_msg_editor(interaction, self.ctx)


class MsgLookModal(ModalBase, title="مظهر الإمبد"):
    def __init__(self, ctx: MsgCtx, msg: dict):
        super().__init__()
        self.ctx = ctx
        self.t_color = discord.ui.TextInput(label="اللون (Hex)", required=False, max_length=7,
                                            placeholder="#5865F2", default=msg.get("color") or None)
        self.t_image = discord.ui.TextInput(label="رابط الصورة الكبيرة", required=False, max_length=500,
                                            placeholder="https://...", default=msg.get("image") or None)
        self.t_thumb = discord.ui.TextInput(label="الصورة الجانبية: avatar / server / none", required=False,
                                            max_length=20, default=msg.get("thumb") or "none")
        for it in (self.t_color, self.t_image, self.t_thumb):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        color = self.t_color.value.strip()
        if color and parse_hex(color) is None:
            return await reply(interaction, "❌ اللون لازم يكون Hex مثل `#5865F2`.", ephemeral=True)
        thumb = _parse_thumb(self.t_thumb.value)
        if thumb is None:
            return await reply(interaction, "❌ الصورة الجانبية: اكتب `avatar` أو `server` أو `none`.", ephemeral=True)
        msg = deep_merge(DEFAULT_MSG, await self.ctx.load())
        msg["color"] = ("#" + color.lstrip("#")) if color else "#5865F2"
        msg["image"] = self.t_image.value.strip()
        msg["thumb"] = thumb
        await self.ctx.save(msg)
        await show_msg_editor(interaction, self.ctx)


async def send_preview(interaction: discord.Interaction, ctx_or_msg, variables: dict):
    msg = ctx_or_msg if isinstance(ctx_or_msg, dict) else await ctx_or_msg.load()
    m = deep_merge(DEFAULT_MSG, msg)
    kw = build_message(m, variables, member=interaction.user, guild=interaction.guild,
                       content_prefix=interaction.user.mention if m.get("as_embed") else None)
    await reply(interaction, ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(), **kw)


class MsgEditorView(NavView):
    def __init__(self, ctx: MsgCtx, msg: dict):
        super().__init__()
        self.ctx = ctx

        async def edit_text(i: discord.Interaction):
            await i.response.send_modal(MsgTextModal(ctx, deep_merge(DEFAULT_MSG, await ctx.load())))

        async def edit_look(i: discord.Interaction):
            await i.response.send_modal(MsgLookModal(ctx, deep_merge(DEFAULT_MSG, await ctx.load())))

        async def toggle_embed(i: discord.Interaction):
            m = deep_merge(DEFAULT_MSG, await ctx.load())
            m["as_embed"] = not m["as_embed"]
            await ctx.save(m)
            await show_msg_editor(i, ctx)

        async def preview(i: discord.Interaction):
            vars_ = ctx.preview_vars(i) if ctx.preview_vars else {}
            await send_preview(i, ctx, vars_)

        self.add_btn("النص والعنوان", edit_text, discord.ButtonStyle.primary, row=0, emoji="✏️")
        self.add_btn("المظهر", edit_look, discord.ButtonStyle.secondary, row=0, emoji="🎨",
                     disabled=not msg.get("as_embed"))
        if ctx.allow_embed:
            self.add_btn("تحويل إلى نص عادي" if msg.get("as_embed") else "تحويل إلى إمبد", toggle_embed,
                         discord.ButtonStyle.secondary, row=0, emoji="🔀")
        self.add_btn("معاينة", preview, discord.ButtonStyle.success, row=1, emoji="👁️")
        for label, emoji, style, cb in ctx.extra[:3]:
            self.add_btn(label, cb, style, row=1, emoji=emoji)
        self.add_back(ctx.back, row=1)


async def show_msg_editor(interaction: discord.Interaction, ctx: MsgCtx):
    msg = deep_merge(DEFAULT_MSG, await ctx.load())
    emb = discord.Embed(title=f"✏️ {ctx.title}", color=discord.Color.blurple())
    emb.add_field(name="النوع", value="🖼️ إمبد" if msg["as_embed"] else "💬 نص عادي", inline=True)
    if msg["as_embed"]:
        emb.add_field(name="اللون", value=f"`{msg['color']}`", inline=True)
        emb.add_field(name="الصورة الجانبية", value=THUMB_AR.get(msg["thumb"], "بدون"), inline=True)
        emb.add_field(name="العنوان", value=msg["title"] or "—", inline=False)
    body = (msg["desc"] or "—").replace("```", "'''")
    emb.add_field(name="النص", value=f"```{body[:900]}```", inline=False)
    if msg["as_embed"] and (msg["footer"] or msg["image"]):
        emb.add_field(name="تفاصيل أخرى", value=f"التذييل: {short(msg['footer'], 60) or '—'}\nصورة كبيرة: {'✅' if msg['image'] else '—'}", inline=False)
    if ctx.extra_info:
        info = await ctx.extra_info()
        if info:
            emb.add_field(name="معلومات", value=info, inline=False)
    if ctx.vars_help:
        emb.add_field(name="🔤 المتغيرات المتاحة", value=ctx.vars_help, inline=False)
    await show(interaction, emb, MsgEditorView(ctx, msg))


async def setup(bot):
    """ملف مساعد فقط، لا يضيف أوامر."""
    pass
