"""
واجهة الاختصارات (الردود التلقائية) داخل /dashboard
إضافة • تعديل • حذف • تعطيل • مطابقة • قنوات/رتب • كولداون • تفاعل • إمبد
"""
import discord

from database import db, reply, build_message, fmt_vars, parse_hex, SHORTCUT_DEFAULT

try:
    from cogs.dash_common import (NavView, ModalBase, show, short, onoff, show_id_picker, fmt_ids)
except ImportError:
    from dash_common import (NavView, ModalBase, show, short, onoff, show_id_picker, fmt_ids)

PAGE = 25
MATCH_ORDER = ["contains", "exact", "starts", "word"]
MATCH_AR = {"contains": "تحتوي الرسالة على الكلمة", "exact": "الرسالة = الكلمة بالضبط",
            "starts": "الرسالة تبدأ بالكلمة", "word": "كلمة كاملة داخل الرسالة"}
MODE_ORDER = ["all", "include", "exclude"]
CH_MODE_AR = {"all": "كل القنوات", "include": "فقط القنوات المحددة", "exclude": "كل القنوات ما عدا المحددة"}
RO_MODE_AR = {"all": "كل الأعضاء", "include": "فقط أصحاب الرتب المحددة", "exclude": "الكل ما عدا أصحاب الرتب المحددة"}
VARS_HELP = "{user} منشن • {name} الاسم • {server} • {channel} • {count} عدد الأعضاء"


# ═══════════════════════════ القائمة ═══════════════════════════
async def open_shortcuts(interaction: discord.Interaction, back):
    await show_shortcuts_home(interaction, back, 0)


async def show_shortcuts_home(interaction: discord.Interaction, back, page: int = 0):
    items = await db.get_shortcuts(interaction.guild_id)
    pages = max(1, -(-len(items) // PAGE))
    page = max(0, min(page, pages - 1))
    chunk = items[page * PAGE:(page + 1) * PAGE]
    lines = []
    for s in chunk:
        mark = "🟢" if s["enabled"] else "⏸️"
        lines.append(f"{mark} `{short(s['trigger'], 25)}` ← {short(' | '.join(s['responses']), 45) or '—'}")
    emb = discord.Embed(
        title="⚡ الاختصارات والردود التلقائية", color=discord.Color.blurple(),
        description=("لما العضو يكتب كلمة معينة، البوت يرد تلقائياً. تقدر تضيف أكثر من رد (عشوائي)، تخصص المطابقة، "
                     "القنوات، الرتب، الكولداون، التفاعل، وتعدل أو تحذف أو تعطل أي اختصار.\n\n"
                     + ("\n".join(lines) if lines else "لا توجد اختصارات بعد. اضغط ➕ إضافة.")))
    emb.set_footer(text=f"الإجمالي: {len(items)} • صفحة {page + 1}/{pages} • اختر اختصاراً من القائمة لتعديله")
    await show(interaction, emb, ShortcutsHomeView(chunk, page, pages, back))


class AddShortcutModal(ModalBase, title="إضافة اختصار جديد"):
    def __init__(self, back):
        super().__init__()
        self.back = back
        self.trigger = discord.ui.TextInput(label="الكلمة / العبارة اللي تشغّل الرد", max_length=100, placeholder="مثال: السلام عليكم")
        self.resp = discord.ui.TextInput(label="الرد (افصل بين عدة ردود بعلامة | للاختيار العشوائي)",
                                         style=discord.TextStyle.paragraph, max_length=1500, placeholder="وعليكم السلام | هلا والله {user}")
        self.add_item(self.trigger)
        self.add_item(self.resp)

    async def on_submit(self, interaction: discord.Interaction):
        responses = [r.strip() for r in self.resp.value.split("|") if r.strip()]
        trig = self.trigger.value.strip()
        if not trig or not responses:
            return await reply(interaction, "❌ لازم تكتب الكلمة والرد.", ephemeral=True)
        existing = await db.get_shortcuts(interaction.guild_id)
        if len(existing) >= 200:
            return await reply(interaction, "❌ وصلت الحد الأقصى (200 اختصار).", ephemeral=True)
        data = {**SHORTCUT_DEFAULT, "trigger": trig, "responses": responses}
        sid = await db.add_shortcut(interaction.guild_id, data)
        await show_shortcut(interaction, sid, self.back)


class _PickShortcut(discord.ui.Select):
    def __init__(self, chunk, back):
        opts = [discord.SelectOption(label=short(s["trigger"], 90) or "—", value=str(s["id"]),
                                     description=short(" | ".join(s["responses"]), 90) or None,
                                     emoji="🟢" if s["enabled"] else "⏸️") for s in chunk]
        super().__init__(placeholder="✏️ اختر اختصاراً لتعديله أو حذفه...", options=opts, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await show_shortcut(interaction, int(self.values[0]), self.back)


class ShortcutsHomeView(NavView):
    def __init__(self, chunk, page, pages, back):
        super().__init__()
        if chunk:
            self.add_item(_PickShortcut(chunk, back))

        async def add(i): await i.response.send_modal(AddShortcutModal(back))
        async def prev(i): await show_shortcuts_home(i, back, page - 1)
        async def nxt(i): await show_shortcuts_home(i, back, page + 1)

        self.add_btn("إضافة اختصار", add, discord.ButtonStyle.success, row=1, emoji="➕")
        self.add_btn("السابق", prev, row=1, emoji="◀️", disabled=page <= 0)
        self.add_btn("التالي", nxt, row=1, emoji="▶️", disabled=page >= pages - 1)
        self.add_back(back, row=1, label="رجوع للوحة")


# ═══════════════════════════ محرر اختصار واحد ═══════════════════════════
async def show_shortcut(interaction: discord.Interaction, sid: int, back):
    gid = interaction.guild_id
    sc = await db.get_shortcut(gid, sid)

    async def to_list(i): await show_shortcuts_home(i, back, 0)
    if not sc:
        return await to_list(interaction)

    emb = discord.Embed(title=f"⚡ اختصار: {short(sc['trigger'], 60)}",
                        color=discord.Color.green() if sc["enabled"] else discord.Color.light_grey())
    emb.add_field(name="الحالة", value=onoff(sc["enabled"]), inline=True)
    emb.add_field(name="النمط", value="🖼️ إمبد" if sc["style"] == "embed" else "💬 نص", inline=True)
    emb.add_field(name="طريقة الإرسال", value="↩️ رد على رسالته" if sc["reply"] else "📤 رسالة جديدة", inline=True)
    emb.add_field(name="المطابقة", value=MATCH_AR[sc["match"]], inline=False)
    resp = "\n".join(f"`{n}.` {short(r, 120)}" for n, r in enumerate(sc["responses"][:8], 1)) or "—"
    emb.add_field(name="الردود", value=resp[:1000], inline=False)
    emb.add_field(name="📺 القنوات", value=f"{CH_MODE_AR[sc['channel_mode']]}\n{fmt_ids(sc['channels'], 'channel', 8) if sc['channel_mode'] != 'all' else ''}", inline=True)
    emb.add_field(name="👥 الرتب", value=f"{RO_MODE_AR[sc['role_mode']]}\n{fmt_ids(sc['roles'], 'role', 8) if sc['role_mode'] != 'all' else ''}", inline=True)
    opts = [f"كولداون: {sc['cooldown']}ث" if sc["cooldown"] else "بدون كولداون",
            f"حذف الرد بعد {sc['delete_after']}ث" if sc["delete_after"] else "الرد دائم",
            "🧹 يحذف رسالة العضو" if sc["delete_trigger"] else "يبقي رسالة العضو"]
    if sc["react"]:
        opts.append(f"تفاعل {sc['react']}")
    emb.add_field(name="⚙️ خيارات", value=" • ".join(opts), inline=False)
    emb.set_footer(text="المتغيرات: " + VARS_HELP)

    view = NavView()
    refresh = lambda i: show_shortcut(i, sid, back)

    async def save_and_refresh(i, **changes):
        cur = await db.get_shortcut(gid, sid)
        if cur:
            cur.update(changes)
            await db.update_shortcut(gid, sid, cur)
        await show_shortcut(i, sid, back)

    async def edit_content(i):
        cur = await db.get_shortcut(gid, sid)
        await i.response.send_modal(ContentModal(sid, cur, back))

    async def cycle_match(i):
        cur = await db.get_shortcut(gid, sid)
        await save_and_refresh(i, match=MATCH_ORDER[(MATCH_ORDER.index(cur["match"]) + 1) % len(MATCH_ORDER)])

    async def toggle_style(i):
        cur = await db.get_shortcut(gid, sid)
        await save_and_refresh(i, style="text" if cur["style"] == "embed" else "embed")

    async def look(i):
        cur = await db.get_shortcut(gid, sid)
        await i.response.send_modal(LookModal(sid, cur, back))

    async def options(i):
        cur = await db.get_shortcut(gid, sid)
        await i.response.send_modal(OptionsModal(sid, cur, back))

    async def tg_reply(i):
        cur = await db.get_shortcut(gid, sid); await save_and_refresh(i, reply=not cur["reply"])

    async def tg_del(i):
        cur = await db.get_shortcut(gid, sid); await save_and_refresh(i, delete_trigger=not cur["delete_trigger"])

    async def tg_enable(i):
        cur = await db.get_shortcut(gid, sid); await save_and_refresh(i, enabled=not cur["enabled"])

    async def pick_channels(i):
        cur = await db.get_shortcut(gid, sid)

        async def on_save(ii, ids):
            await save_and_refresh(ii, channels=ids)
        await show_id_picker(i, "channel", cur["channels"], on_save, refresh, "📺 قنوات الاختصار",
                             "اختر القنوات، وبعدها حدد الوضع (فقط هذي / كل شي ما عدا هذي) من زر وضع القنوات.")

    async def pick_roles(i):
        cur = await db.get_shortcut(gid, sid)

        async def on_save(ii, ids):
            await save_and_refresh(ii, roles=ids)
        await show_id_picker(i, "role", cur["roles"], on_save, refresh, "👥 رتب الاختصار",
                             "اختر الرتب، وبعدها حدد الوضع من زر وضع الرتب.")

    async def ch_mode(i):
        cur = await db.get_shortcut(gid, sid)
        await save_and_refresh(i, channel_mode=MODE_ORDER[(MODE_ORDER.index(cur["channel_mode"]) + 1) % 3])

    async def ro_mode(i):
        cur = await db.get_shortcut(gid, sid)
        await save_and_refresh(i, role_mode=MODE_ORDER[(MODE_ORDER.index(cur["role_mode"]) + 1) % 3])

    async def test(i):
        cur = await db.get_shortcut(gid, sid)
        if not cur or not cur["responses"]:
            return await reply(i, "❌ ما فيه ردود.", ephemeral=True)
        text = fmt_vars(cur["responses"][0], {"user": i.user.mention, "name": i.user.display_name, "server": i.guild.name,
                                              "channel": i.channel.mention, "count": i.guild.member_count})
        kw = build_message({"as_embed": cur["style"] == "embed", "title": cur["title"], "desc": text,
                            "color": cur["color"], "image": cur["image"]}, {}, member=i.user, guild=i.guild)
        await reply(i, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kw)

    async def ask_delete(i):
        await show_delete_confirm(i, sid, back)

    view.add_btn("المحتوى", edit_content, discord.ButtonStyle.primary, row=0, emoji="✏️")
    view.add_btn("المطابقة", cycle_match, discord.ButtonStyle.secondary, row=0, emoji="🎯")
    view.add_btn("نص / إمبد", toggle_style, discord.ButtonStyle.secondary, row=0, emoji="🎨")
    view.add_btn("مظهر الإمبد", look, discord.ButtonStyle.secondary, row=0, emoji="🖼️", disabled=sc["style"] != "embed")
    view.add_btn("خيارات", options, discord.ButtonStyle.secondary, row=0, emoji="⚙️")
    view.add_btn("رد / رسالة جديدة", tg_reply, discord.ButtonStyle.secondary, row=1, emoji="↩️")
    view.add_btn("حذف رسالة العضو", tg_del, discord.ButtonStyle.secondary, row=1, emoji="🧹")
    view.add_btn("تعطيل" if sc["enabled"] else "تفعيل", tg_enable,
                 discord.ButtonStyle.danger if sc["enabled"] else discord.ButtonStyle.success, row=1, emoji="🔘")
    view.add_btn("القنوات", pick_channels, discord.ButtonStyle.secondary, row=1, emoji="📺")
    view.add_btn("الرتب", pick_roles, discord.ButtonStyle.secondary, row=1, emoji="👥")
    view.add_btn("وضع القنوات", ch_mode, discord.ButtonStyle.secondary, row=2, emoji="🔁")
    view.add_btn("وضع الرتب", ro_mode, discord.ButtonStyle.secondary, row=2, emoji="🔁")
    view.add_btn("تجربة", test, discord.ButtonStyle.success, row=2, emoji="🧪")
    view.add_btn("حذف", ask_delete, discord.ButtonStyle.danger, row=2, emoji="🗑️")
    view.add_back(to_list, row=2)
    await show(interaction, emb, view)


async def show_delete_confirm(interaction: discord.Interaction, sid: int, back):
    sc = await db.get_shortcut(interaction.guild_id, sid)
    emb = discord.Embed(title="🗑️ تأكيد الحذف", color=discord.Color.red(),
                        description=f"متأكد تبي تحذف الاختصار `{short(sc['trigger'], 50) if sc else sid}` نهائياً؟")
    view = NavView()

    async def yes(i):
        await db.delete_shortcut(i.guild_id, sid)
        await show_shortcuts_home(i, back, 0)

    async def no(i):
        await show_shortcut(i, sid, back)
    view.add_btn("نعم، احذف", yes, discord.ButtonStyle.danger, emoji="🗑️")
    view.add_btn("إلغاء", no, discord.ButtonStyle.secondary, emoji="↩️")
    await show(interaction, emb, view)


# ═══════════════════════════ النوافذ ═══════════════════════════
class ContentModal(ModalBase, title="محتوى الاختصار"):
    def __init__(self, sid, sc, back):
        super().__init__()
        self.sid, self.back = sid, back
        self.trigger = discord.ui.TextInput(label="الكلمة / العبارة", max_length=100, default=sc["trigger"][:100] or None)
        self.resp = discord.ui.TextInput(label="الردود (افصل بينها بعلامة |)", style=discord.TextStyle.paragraph,
                                         max_length=1800, default=" | ".join(sc["responses"])[:1800] or None)
        self.add_item(self.trigger)
        self.add_item(self.resp)

    async def on_submit(self, interaction: discord.Interaction):
        responses = [r.strip() for r in self.resp.value.split("|") if r.strip()]
        if not self.trigger.value.strip() or not responses:
            return await reply(interaction, "❌ لازم تكتب الكلمة والرد.", ephemeral=True)
        sc = await db.get_shortcut(interaction.guild_id, self.sid)
        if sc:
            sc.update(trigger=self.trigger.value.strip(), responses=responses)
            await db.update_shortcut(interaction.guild_id, self.sid, sc)
        await show_shortcut(interaction, self.sid, self.back)


class LookModal(ModalBase, title="مظهر الإمبد"):
    def __init__(self, sid, sc, back):
        super().__init__()
        self.sid, self.back = sid, back
        self.t_title = discord.ui.TextInput(label="العنوان", required=False, max_length=256, default=sc["title"] or None)
        self.color = discord.ui.TextInput(label="اللون (Hex)", required=False, max_length=7, default=sc["color"] or None)
        self.image = discord.ui.TextInput(label="رابط صورة", required=False, max_length=500, default=sc["image"] or None)
        for it in (self.t_title, self.color, self.image):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        c = self.color.value.strip()
        if c and parse_hex(c) is None:
            return await reply(interaction, "❌ اللون لازم يكون Hex مثل `#5865F2`.", ephemeral=True)
        sc = await db.get_shortcut(interaction.guild_id, self.sid)
        if sc:
            sc.update(title=self.t_title.value.strip(), color=("#" + c.lstrip("#")) if c else "#5865F2",
                      image=self.image.value.strip())
            await db.update_shortcut(interaction.guild_id, self.sid, sc)
        await show_shortcut(interaction, self.sid, self.back)


class OptionsModal(ModalBase, title="خيارات الاختصار"):
    def __init__(self, sid, sc, back):
        super().__init__()
        self.sid, self.back = sid, back
        self.cd = discord.ui.TextInput(label="كولداون بالثواني (0 = بدون)", max_length=6, default=str(sc["cooldown"]))
        self.da = discord.ui.TextInput(label="حذف الرد تلقائياً بعد (ثواني، 0 = لا)", max_length=6, default=str(sc["delete_after"]))
        self.react = discord.ui.TextInput(label="إيموجي يتفاعل فيه البوت على رسالة العضو (اختياري)", required=False,
                                          max_length=60, default=sc["react"] or None)
        for it in (self.cd, self.da, self.react):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cd, da = int(self.cd.value.strip() or 0), int(self.da.value.strip() or 0)
        except ValueError:
            return await reply(interaction, "❌ اكتب أرقام صحيحة!", ephemeral=True)
        sc = await db.get_shortcut(interaction.guild_id, self.sid)
        if sc:
            sc.update(cooldown=max(0, min(86400, cd)), delete_after=max(0, min(86400, da)), react=self.react.value.strip())
            await db.update_shortcut(interaction.guild_id, self.sid, sc)
        await show_shortcut(interaction, self.sid, self.back)


async def setup(bot):
    """ملف واجهة فقط، لا يضيف أوامر."""
    pass
