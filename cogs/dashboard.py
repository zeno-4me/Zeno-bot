import re
import discord
from discord import app_commands
from discord.ext import commands

from database import db, reply, edit_reply, LINK_PLATFORMS

try:
    from cogs.dash_common import NavView, ModalBase, show, onoff
    from cogs.dash_welcome import open_welcome
    from cogs.dash_levels import open_levels
    from cogs.dash_shortcuts import open_shortcuts
    from cogs.dash_messages import open_messages
except ImportError:  # لو الكوجز في نفس مجلد المشروع
    from dash_common import NavView, ModalBase, show, onoff
    from dash_welcome import open_welcome
    from dash_levels import open_levels
    from dash_shortcuts import open_shortcuts
    from dash_messages import open_messages


def main_embed() -> discord.Embed:
    return discord.Embed(
        title="⚙️ لوحة تحكم السيرفر الشاملة",
        description=("اختر القسم الذي تريد تعديله من القائمة:\n\n"
                     "👋 **الترحيب والمغادرة** — رسائل حسب الرتبة، نادرة، مناسبات\n"
                     "⭐ **اللفل والخبرة** — معدلات، تنبيهات، رتب التفاعل، شكل /rank\n"
                     "⚡ **الاختصارات** — ردود تلقائية قابلة للتعديل والحذف\n"
                     "💬 **الرسائل التلقائية** — تنبيهات الحماية والتحذيرات والعقوبات\n"
                     "🛡️ **الحماية** — منع الروابط والدعوات والكلمات + تحويل السوشل\n"
                     "🧰 **عام** — قناة السجلات والرتبة التلقائية\n\n"
                     "📌 *الإمبد والتذاكر وأزرار الرتب من أمر* `/panels`"),
        color=discord.Color.blurple())


async def show_main(interaction: discord.Interaction):
    await edit_reply(interaction, content=None, embed=main_embed(), view=MainDashboardView())


class EditBadwordsModal(discord.ui.Modal, title="إدارة الكلمات الممنوعة"):
    bad_words = discord.ui.TextInput(label="الكلمات الممنوعة (افصل بفاصلة)", style=discord.TextStyle.paragraph, placeholder="كلمة1, كلمة2, رابط", required=False)
    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "automod_badwords", self.bad_words.value)
        await reply(interaction, "✅ تم حفظ قائمة الكلمات الممنوعة!", ephemeral=True)


# ───────────────── عام: السجلات + الرتبة التلقائية ─────────────────
class _GenChannel(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(placeholder="📜 اختر قناة السجلات (Logs)...", channel_types=[discord.ChannelType.text],
                         min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "log_channel_id", self.values[0].id)
        await show_general(interaction)


class _GenRole(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="🎖️ اختر الرتبة التلقائية للأعضاء الجدد...", min_values=1, max_values=1, row=1)

    async def callback(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "auto_role_id", self.values[0].id)
        await show_general(interaction)


async def show_general(interaction: discord.Interaction):
    st = await db.get_guild_settings(interaction.guild_id)
    lg = interaction.guild.get_channel(st['log_channel_id']) if st['log_channel_id'] else None
    ar = interaction.guild.get_role(st['auto_role_id']) if st['auto_role_id'] else None
    embed = discord.Embed(title="🧰 الإعدادات العامة", color=discord.Color.green(),
                          description="قناة الترحيب والمغادرة من قسم **الترحيب**.")
    embed.add_field(name="📜 قناة السجلات", value=lg.mention if lg else "غير محددة", inline=True)
    embed.add_field(name="🎖️ الرتبة التلقائية", value=ar.mention if ar else "غير محددة", inline=True)

    view = NavView()
    view.add_item(_GenChannel())
    view.add_item(_GenRole())

    async def clear_role(i):
        await db.update_guild_setting(i.guild_id, "auto_role_id", 0)
        await show_general(i)
    view.add_btn("إلغاء الرتبة التلقائية", clear_role, discord.ButtonStyle.danger, row=2, emoji="🧹")
    view.add_back(show_main, row=2, label="رجوع للوحة")
    await show(interaction, embed, view)

def build_automod_embed(st: dict):
    embed = discord.Embed(title="🛡️ إعدادات الحماية والتعديل الآلي", color=discord.Color.red())
    embed.add_field(name="الحماية العامة", value="✅ مفعلة" if st['automod_enabled'] else "❌ معطلة", inline=True)
    embed.add_field(name="منع الروابط", value="✅ مفعل" if st['anti_links'] else "❌ معطل", inline=True)
    embed.add_field(name="منع الدعوات", value="✅ مفعل" if st['anti_invites'] else "❌ معطل", inline=True)
    embed.add_field(name="تحويل روابط السوشل لفيديو", value="❌ معطل" if st.get('link_embed_enabled') == 0 else "✅ مفعل", inline=True)
    embed.add_field(name="الكلمات الممنوعة", value=st['automod_badwords'] if st['automod_badwords'] else "لا توجد كلمات ممنوعة", inline=False)
    return embed


# ───────────────── لوحة تحويل روابط السوشل ميديا لفيديو ─────────────────
LINK_MODE_ORDER = ["keep", "suppress", "delete"]
LINK_MODE_LABELS = {
    "keep": "📎 يبقى رابط العضو + يرسل الفيديو كرد عليه",
    "suppress": "🙈 يبقى رابط العضو بدون معاينة + يرسل الفيديو كرد",
    "delete": "🗑️ يحذف رابط العضو + يرسل الفيديو مكانه",
}
LINK_FILTER_ORDER = ["all", "include", "exclude"]
LINK_CHANNEL_FILTER_LABELS = {
    "all": "كل القنوات",
    "include": "فقط القنوات المحددة",
    "exclude": "كل القنوات ما عدا المحددة",
}
LINK_ROLE_FILTER_LABELS = {
    "all": "كل الأعضاء",
    "include": "فقط أصحاب الرتب المحددة",
    "exclude": "كل الأعضاء ما عدا أصحاب الرتب المحددة",
}


def _next_in(order, cur):
    i = order.index(cur) if cur in order else -1
    return order[(i + 1) % len(order)]


def _fmt_ids(ids, kind):
    if not ids:
        return "لا يوجد"
    fmt = "<#{}>" if kind == "channel" else "<@&{}>"
    shown = " ".join(fmt.format(i) for i in ids[:15])
    if len(ids) > 15:
        shown += f" و{len(ids) - 15} آخرين"
    return shown


def build_link_embed(enabled, cfg: dict):
    embed = discord.Embed(
        title="🎬 تحويل روابط السوشل ميديا إلى فيديو",
        description="أي عضو يرسل رابط شورت/تيك توك/ريل/سبوتلايت، البوت يحوله لفيديو تلقائياً حسب الإعدادات تحت.",
        color=discord.Color.green() if enabled else discord.Color.red(),
    )
    embed.add_field(name="الحالة", value="✅ مفعلة" if enabled else "❌ معطلة", inline=False)
    embed.add_field(name="رسالة الرابط", value=LINK_MODE_LABELS.get(cfg["mode"], LINK_MODE_LABELS["keep"]), inline=False)

    ch_mode = cfg["channel_mode"] if cfg["channel_mode"] in LINK_FILTER_ORDER else "all"
    ch_val = LINK_CHANNEL_FILTER_LABELS[ch_mode]
    if ch_mode != "all":
        ch_val += "\n" + _fmt_ids(cfg["channels"], "channel")
        if ch_mode == "include" and not cfg["channels"]:
            ch_val += "\n⚠️ ما حددت أي قناة، فالميزة ما بتشتغل في أي مكان."
    embed.add_field(name="📺 وين تشتغل", value=ch_val, inline=False)

    r_mode = cfg["role_mode"] if cfg["role_mode"] in LINK_FILTER_ORDER else "all"
    r_val = LINK_ROLE_FILTER_LABELS[r_mode]
    if r_mode != "all":
        r_val += "\n" + _fmt_ids(cfg["roles"], "role")
        if r_mode == "include" and not cfg["roles"]:
            r_val += "\n⚠️ ما حددت أي رتبة، فالميزة ما بتشتغل لأي عضو."
    embed.add_field(name="👥 لمين تشتغل", value=r_val, inline=False)

    plats = " • ".join(f"{'✅' if cfg['platforms'].get(k, True) else '❌'} {name}" for k, name in LINK_PLATFORMS.items())
    embed.add_field(name="🌐 المنصات", value=plats, inline=False)
    embed.add_field(name="⏱️ أقصى مدة للفيديو", value=f"{cfg['max_duration']} ثانية", inline=False)
    return embed


async def refresh_link_panel(interaction: discord.Interaction):
    st = await db.get_guild_settings(interaction.guild_id)
    cfg = await db.get_link_config(interaction.guild_id)
    enabled = st.get('link_embed_enabled')
    enabled = 1 if enabled is None else enabled
    await edit_reply(interaction, embed=build_link_embed(enabled, cfg), view=LinkEmbedView())


async def _link_update(interaction: discord.Interaction, **changes):
    cfg = await db.get_link_config(interaction.guild_id)
    cfg.update(changes)
    await db.set_link_config(interaction.guild_id, cfg)
    await refresh_link_panel(interaction)


class _LinkBaseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await reply(interaction, "❌ هذه اللوحة للإداريين فقط!", ephemeral=True)
            return False
        return True


class LinkDurationModal(discord.ui.Modal, title="أقصى مدة للفيديو"):
    seconds = discord.ui.TextInput(label="بالثواني (من 10 إلى 300)", placeholder="180", required=True, max_length=3)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.seconds.value.strip())
        except ValueError:
            await reply(interaction, "❌ اكتب رقم صحيح بالثواني!", ephemeral=True)
            return
        await _link_update(interaction, max_duration=max(10, min(300, val)))


class LinkChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self, guild, cfg):
        defaults = []
        for cid in cfg.get("channels", [])[:25]:
            if guild and guild.get_channel(cid):
                defaults.append(discord.SelectDefaultValue(id=cid, type=discord.SelectDefaultValueType.channel))
        kwargs = dict(
            placeholder="📺 اختر القنوات أو الكاتيجوريات (حتى 25)...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news, discord.ChannelType.voice,
                           discord.ChannelType.forum, discord.ChannelType.category],
            min_values=0, max_values=25,
        )
        try:
            super().__init__(default_values=defaults, **kwargs)
        except TypeError:  # نسخة discord.py قديمة ما تدعم default_values
            super().__init__(**kwargs)

    async def callback(self, interaction: discord.Interaction):
        await _link_update(interaction, channels=[c.id for c in self.values])


class LinkRolesSelect(discord.ui.RoleSelect):
    def __init__(self, guild, cfg):
        defaults = []
        for rid in cfg.get("roles", [])[:25]:
            if guild and guild.get_role(rid):
                defaults.append(discord.SelectDefaultValue(id=rid, type=discord.SelectDefaultValueType.role))
        kwargs = dict(placeholder="👥 اختر الرتب (حتى 25)...", min_values=0, max_values=25)
        try:
            super().__init__(default_values=defaults, **kwargs)
        except TypeError:
            super().__init__(**kwargs)

    async def callback(self, interaction: discord.Interaction):
        await _link_update(interaction, roles=[r.id for r in self.values])


class LinkPlatformsSelect(discord.ui.Select):
    def __init__(self, cfg):
        options = [
            discord.SelectOption(label=name, value=key, default=bool(cfg["platforms"].get(key, True)))
            for key, name in LINK_PLATFORMS.items()
        ]
        super().__init__(placeholder="🌐 اختر المنصات المفعلة...", min_values=0, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction):
        chosen = set(self.values)
        await _link_update(interaction, platforms={k: (k in chosen) for k in LINK_PLATFORMS})


class LinkPickerView(_LinkBaseView):
    def __init__(self, select):
        super().__init__()
        self.add_item(select)

    @discord.ui.button(label="رجوع", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await refresh_link_panel(interaction)


class LinkEmbedView(_LinkBaseView):
    @discord.ui.button(label="تفعيل / تعطيل", style=discord.ButtonStyle.success, row=0)
    async def toggle_enabled(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        cur = st.get('link_embed_enabled')
        cur = 1 if cur is None else cur
        await db.update_guild_setting(interaction.guild_id, "link_embed_enabled", 0 if cur else 1)
        await refresh_link_panel(interaction)

    @discord.ui.button(label="🔁 وضع رسالة الرابط", style=discord.ButtonStyle.primary, row=0)
    async def cycle_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_link_config(interaction.guild_id)
        await _link_update(interaction, mode=_next_in(LINK_MODE_ORDER, cfg["mode"]))

    @discord.ui.button(label="🔁 نطاق القنوات", style=discord.ButtonStyle.secondary, row=1)
    async def cycle_channel_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_link_config(interaction.guild_id)
        await _link_update(interaction, channel_mode=_next_in(LINK_FILTER_ORDER, cfg["channel_mode"]))

    @discord.ui.button(label="🔁 نطاق الأعضاء", style=discord.ButtonStyle.secondary, row=1)
    async def cycle_role_mode(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_link_config(interaction.guild_id)
        await _link_update(interaction, role_mode=_next_in(LINK_FILTER_ORDER, cfg["role_mode"]))

    @discord.ui.button(label="📺 اختيار القنوات", style=discord.ButtonStyle.secondary, row=2)
    async def pick_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_link_config(interaction.guild_id)
        embed = discord.Embed(title="📺 اختيار القنوات", description="اختر القنوات أو الكاتيجوريات (الكاتيجوري يشمل كل رومات داخلها). اترك الاختيار فاضي لمسح القائمة.", color=discord.Color.blurple())
        await edit_reply(interaction, embed=embed, view=LinkPickerView(LinkChannelsSelect(interaction.guild, cfg)))

    @discord.ui.button(label="👥 اختيار الرتب", style=discord.ButtonStyle.secondary, row=2)
    async def pick_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_link_config(interaction.guild_id)
        embed = discord.Embed(title="👥 اختيار الرتب", description="اختر الرتب اللي تنطبق عليها الميزة (أو تُستثنى منها حسب نطاق الأعضاء). اترك الاختيار فاضي لمسح القائمة.", color=discord.Color.blurple())
        await edit_reply(interaction, embed=embed, view=LinkPickerView(LinkRolesSelect(interaction.guild, cfg)))

    @discord.ui.button(label="🌐 المنصات", style=discord.ButtonStyle.secondary, row=2)
    async def pick_platforms(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await db.get_link_config(interaction.guild_id)
        embed = discord.Embed(title="🌐 المنصات", description="اختر المنصات اللي تبيها تتحول لفيديو.", color=discord.Color.blurple())
        await edit_reply(interaction, embed=embed, view=LinkPickerView(LinkPlatformsSelect(cfg)))

    @discord.ui.button(label="⏱️ أقصى مدة", style=discord.ButtonStyle.secondary, row=3)
    async def set_duration(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LinkDurationModal())

    @discord.ui.button(label="الرجوع", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        await edit_reply(interaction, embed=build_automod_embed(st), view=AutoModSettingsView())


class AutoModSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await reply(interaction, "❌ هذه اللوحة للإداريين فقط!", ephemeral=True)
            return False
        return True

    async def _flip(self, interaction: discord.Interaction, key: str):
        st = await db.get_guild_settings(interaction.guild_id)
        await db.update_guild_setting(interaction.guild_id, key, 0 if st.get(key) else 1)
        st = await db.get_guild_settings(interaction.guild_id)
        await edit_reply(interaction, content=None, embed=build_automod_embed(st), view=AutoModSettingsView())

    @discord.ui.button(label="تبديل الحماية العامة", style=discord.ButtonStyle.danger, row=0)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, "automod_enabled")

    @discord.ui.button(label="منع الروابط", style=discord.ButtonStyle.primary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, "anti_links")

    @discord.ui.button(label="منع دعوات الديسكورد", style=discord.ButtonStyle.primary, row=0)
    async def toggle_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._flip(interaction, "anti_invites")

    @discord.ui.button(label="🎬 تحويل روابط السوشل", style=discord.ButtonStyle.success, row=1)
    async def open_link_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await refresh_link_panel(interaction)

    @discord.ui.button(label="الكلمات الممنوعة", style=discord.ButtonStyle.secondary, row=1)
    async def edit_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditBadwordsModal())

    @discord.ui.button(label="رسائل التنبيه", style=discord.ButtonStyle.secondary, row=1, emoji="💬")
    async def edit_alerts(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_messages(interaction, show_main)

    @discord.ui.button(label="رجوع للوحة", style=discord.ButtonStyle.secondary, row=2, emoji="⬅️")
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await show_main(interaction)


SECTIONS = [
    ("👋 الترحيب والمغادرة", "رسائل حسب الرتبة، نادرة، مناسبات", "👋", "welcome"),
    ("⭐ اللفل والخبرة", "معدلات، تنبيهات، رتب التفاعل، شكل /rank", "⭐", "levels"),
    ("⚡ الاختصارات", "ردود تلقائية: إضافة وتعديل وحذف", "⚡", "shortcuts"),
    ("💬 الرسائل التلقائية", "تنبيهات الحماية والتحذيرات والعقوبات", "💬", "messages"),
    ("🛡️ الحماية والتعديل الآلي", "الروابط والدعوات والكلمات وتحويل السوشل", "🛡️", "automod"),
    ("🧰 عام", "قناة السجلات والرتبة التلقائية", "🧰", "general"),
]


class DashboardSelectMenu(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=l, description=d, emoji=e, value=v) for l, d, e, v in SECTIONS]
        super().__init__(placeholder="اختر القسم المراد التحكم به...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        sel = self.values[0]
        if sel == "welcome":
            await open_welcome(interaction, show_main)
        elif sel == "levels":
            await open_levels(interaction, show_main)
        elif sel == "shortcuts":
            await open_shortcuts(interaction, show_main)
        elif sel == "messages":
            await open_messages(interaction, show_main)
        elif sel == "automod":
            st = await db.get_guild_settings(interaction.guild_id)
            await edit_reply(interaction, content=None, embed=build_automod_embed(st), view=AutoModSettingsView())
        elif sel == "general":
            await show_general(interaction)


class MainDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=900)
        self.add_item(DashboardSelectMenu())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await reply(interaction, "❌ هذه اللوحة للإداريين فقط!", ephemeral=True)
            return False
        return True


class Dashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="dashboard", description="فتح لوحة تحكم السيرفر الشاملة")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction):
        await reply(interaction, embed=main_embed(), view=MainDashboardView(), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
