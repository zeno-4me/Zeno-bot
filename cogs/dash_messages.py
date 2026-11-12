"""
واجهة تخصيص الرسائل التلقائية (تنبيهات الحماية، التحذيرات، العقوبات، الاقتصاد...) داخل /dashboard
"""
import discord

from database import db, reply, MESSAGE_DEFS, parse_hex

try:
    from cogs.dash_common import (NavView, ModalBase, show, short, onoff)
except ImportError:
    from dash_common import (NavView, ModalBase, show, short, onoff)


async def open_messages(interaction: discord.Interaction, back):
    await show_messages_home(interaction, back)


async def show_messages_home(interaction: discord.Interaction, back):
    gid = interaction.guild_id
    cats = {}
    for key, d in MESSAGE_DEFS.items():
        c = await db.get_message_cfg(gid, key)
        mark = ("🟢" if c["enabled"] else "⏸️") + ("✏️" if c["custom"] else "")
        cats.setdefault(d["cat"], []).append(f"{mark} {d['label']}")
    emb = discord.Embed(
        title="💬 الرسائل التلقائية", color=discord.Color.blurple(),
        description=("خصص كل رسالة يرسلها البوت تلقائياً: النص، تحويلها لإمبد، مدة الحذف، أو تعطيلها بالكامل.\n"
                     "🟢 مفعلة • ⏸️ معطلة • ✏️ معدلة من الإدارة\n"
                     "ℹ️ رسائل الترحيب واللفل ليها لوحات خاصة في الداشبورد."))
    for cat, lines in cats.items():
        emb.add_field(name=cat, value="\n".join(lines), inline=False)
    await show(interaction, emb, MessagesHomeView(back))


class _PickMessage(discord.ui.Select):
    def __init__(self, back):
        opts = [discord.SelectOption(label=d["label"], value=k, description=d["cat"]) for k, d in MESSAGE_DEFS.items()][:25]
        super().__init__(placeholder="✏️ اختر رسالة لتخصيصها...", options=opts, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await show_message_detail(interaction, self.values[0], self.back)


class MessagesHomeView(NavView):
    def __init__(self, back):
        super().__init__()
        self.add_item(_PickMessage(back))
        self.add_back(back, row=1, label="رجوع للوحة")


class EditMessageModal(ModalBase, title="تعديل الرسالة"):
    def __init__(self, key, cfg, back):
        super().__init__()
        self.key, self.back = key, back
        self.text = discord.ui.TextInput(label="نص الرسالة", style=discord.TextStyle.paragraph, max_length=1500,
                                         default=cfg["text"][:1500])
        self.t_title = discord.ui.TextInput(label="العنوان (لوضع الإمبد فقط)", required=False, max_length=256,
                                            default=cfg["title"] or None)
        self.color = discord.ui.TextInput(label="لون الإمبد (Hex)", required=False, max_length=7, default=cfg["color"])
        self.da = discord.ui.TextInput(label="حذف تلقائي بعد (ثواني، 0 = لا)", max_length=6, default=str(cfg["delete_after"]))
        for it in (self.text, self.t_title, self.color, self.da):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        c = self.color.value.strip()
        if c and parse_hex(c) is None:
            return await reply(interaction, "❌ اللون لازم يكون Hex مثل `#ED4245`.", ephemeral=True)
        try:
            da = int(self.da.value.strip() or 0)
        except ValueError:
            return await reply(interaction, "❌ مدة الحذف لازم تكون رقم.", ephemeral=True)
        await db.set_message_cfg(interaction.guild_id, self.key, {
            "text": self.text.value, "title": self.t_title.value.strip(),
            "color": ("#" + c.lstrip("#")) if c else "#ED4245", "delete_after": max(0, min(86400, da))})
        await show_message_detail(interaction, self.key, self.back)


async def show_message_detail(interaction: discord.Interaction, key: str, back):
    gid = interaction.guild_id
    d = MESSAGE_DEFS[key]
    c = await db.get_message_cfg(gid, key)

    async def to_home(i): await show_messages_home(i, back)
    async def refresh(i): await show_message_detail(i, key, back)

    emb = discord.Embed(title=f"💬 {d['label']}", color=discord.Color.green() if c["enabled"] else discord.Color.light_grey())
    emb.add_field(name="الحالة", value=onoff(c["enabled"]), inline=True)
    emb.add_field(name="النمط", value="🖼️ إمبد" if c["style"] == "embed" else "💬 نص", inline=True)
    emb.add_field(name="حذف تلقائي", value=f"{c['delete_after']} ثانية" if c["delete_after"] else "لا", inline=True)
    emb.add_field(name="النص الحالي", value=f"```{c['text'][:900].replace('```', chr(39) * 3)}```", inline=False)
    emb.add_field(name="🔤 المتغيرات المتاحة", value=d["vars"], inline=False)
    if "_dm" in key:
        emb.set_footer(text="رسالة خاصة: لو العضو قافل الخاص ما توصله")

    view = NavView()

    async def edit(i): await i.response.send_modal(EditMessageModal(key, c, back))

    async def toggle(i):
        cur = await db.get_message_cfg(gid, key)
        await db.set_message_cfg(gid, key, {"enabled": not cur["enabled"]}); await refresh(i)

    async def style(i):
        cur = await db.get_message_cfg(gid, key)
        await db.set_message_cfg(gid, key, {"style": "text" if cur["style"] == "embed" else "embed"}); await refresh(i)

    async def reset(i):
        await db.reset_message_cfg(gid, key); await refresh(i)

    async def preview(i):
        sample = {"user": i.user.mention, "name": i.user.display_name, "server": i.guild.name, "channel": i.channel.mention,
                  "moderator": i.user.mention, "reason": "سبب تجريبي", "count": 3, "minutes": 10, "amount": "300",
                  "time": "5h 20m", "target": i.user.mention, "target_name": i.user.display_name, "word": "كلمة"}
        kw = await db.auto_kwargs(gid, key, **sample)
        if not kw:
            return await reply(i, "⏸️ هذي الرسالة معطلة حالياً.", ephemeral=True)
        kw.pop("delete_after", None)
        await reply(i, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kw)

    view.add_btn("تعديل النص", edit, discord.ButtonStyle.primary, row=0, emoji="✏️")
    view.add_btn("تفعيل / تعطيل", toggle, discord.ButtonStyle.success if c["enabled"] else discord.ButtonStyle.danger, row=0, emoji="🔘")
    view.add_btn("نص / إمبد", style, discord.ButtonStyle.secondary, row=0, emoji="🎨")
    view.add_btn("معاينة", preview, discord.ButtonStyle.success, row=1, emoji="👁️")
    view.add_btn("رجوع للافتراضي", reset, discord.ButtonStyle.secondary, row=1, emoji="↩️")
    view.add_back(to_home, row=1)
    await show(interaction, emb, view)


async def setup(bot):
    """ملف واجهة فقط، لا يضيف أوامر."""
    pass
