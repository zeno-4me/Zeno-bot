"""
واجهة إعدادات الترحيب والمغادرة داخل /dashboard
(رسالة افتراضية • رسائل حسب الرتبة • رسالة نادرة بنسبة • رسائل مناسبات • مغادرة)
"""
import copy
import discord

from database import (db, reply, deep_merge, DEFAULT_MSG, WELCOME_VARS, event_is_active, parse_event_date)

try:
    from cogs.dash_common import (NavView, ModalBase, MsgCtx, show, show_msg_editor, short, onoff, send_preview)
except ImportError:  # لو الكوجز في نفس مجلد المشروع
    from dash_common import (NavView, ModalBase, MsgCtx, show, show_msg_editor, short, onoff, send_preview)

TRIGGER_AR = {"join": "عند دخول العضو للسيرفر", "role": "عند أخذ العضو رتبة من (رسائل الرتب)"}

EVENT_PRESETS = {
    "halloween": {"name": "🎃 الهالوين", "calendar": "greg", "start": "10-25", "end": "10-31",
                  "msg": {"as_embed": True, "title": "🎃 هالوين سعيد!", "color": "#E67E22", "thumb": "avatar",
                          "desc": "👻 {user} دخل السيرفر في ليلة الرعب! أهلاً بك في **{server}**"}},
    "newyear": {"name": "🎆 رأس السنة", "calendar": "greg", "start": "12-29", "end": "01-02",
                "msg": {"as_embed": True, "title": "🎆 سنة سعيدة!", "color": "#F1C40F", "thumb": "avatar",
                        "desc": "🎉 {user} أهلاً بك معنا في أجواء رأس السنة في **{server}**"}},
    "ramadan": {"name": "🌙 رمضان", "calendar": "hijri", "start": "09-01", "end": "09-30",
                "msg": {"as_embed": True, "title": "🌙 رمضان كريم", "color": "#2ECC71", "thumb": "avatar",
                        "desc": "✨ {user} أهلاً بك في **{server}** وكل عام وأنت بخير 🌙"}},
    "fitr": {"name": "🕌 عيد الفطر", "calendar": "hijri", "start": "10-01", "end": "10-03",
             "msg": {"as_embed": True, "title": "🕌 عيدكم مبارك", "color": "#1ABC9C", "thumb": "avatar",
                     "desc": "🎊 {user} عيدك مبارك! أهلاً بك في **{server}**"}},
    "adha": {"name": "🐑 عيد الأضحى", "calendar": "hijri", "start": "12-10", "end": "12-13",
             "msg": {"as_embed": True, "title": "🐑 عيدكم مبارك", "color": "#16A085", "thumb": "avatar",
                     "desc": "🎊 {user} عيدك مبارك! أهلاً بك في **{server}**"}},
}


def preview_vars(i: discord.Interaction) -> dict:
    return welcome_vars(i.user, extra={"role": "رتبة تجريبية"})


def welcome_vars(member: discord.Member, extra: dict = None) -> dict:
    ts = int(member.joined_at.timestamp()) if getattr(member, "joined_at", None) else 0
    v = {
        "user": member.mention, "name": member.display_name, "username": member.name,
        "server": member.guild.name, "count": member.guild.member_count, "id": member.id,
        "date": f"<t:{ts}:D>" if ts else "الآن", "created": f"<t:{int(member.created_at.timestamp())}:R>",
        "role": "", "event": "",
    }
    v.update(extra or {})
    return v


# ═══════════════════════════ الشاشة الرئيسية ═══════════════════════════
async def open_welcome(interaction: discord.Interaction, back):
    await show_welcome_home(interaction, back)


async def show_welcome_home(interaction: discord.Interaction, back):
    gid = interaction.guild_id
    st = await db.get_guild_settings(gid)
    cfg = await db.get_welcome_cfg(gid)
    g = interaction.guild
    w_c, l_c = g.get_channel(st['welcome_channel_id']), g.get_channel(st['leave_channel_id'])

    active = [e["name"] for e in cfg["events"] if event_is_active(e, cfg["tz_offset"])]
    emb = discord.Embed(title="👋 نظام الترحيب والمغادرة", color=discord.Color.green() if cfg["enabled"] else discord.Color.red())
    emb.add_field(name="الحالة", value=onoff(cfg["enabled"]), inline=True)
    emb.add_field(name="قناة الترحيب", value=w_c.mention if w_c else "⚠️ غير محددة", inline=True)
    emb.add_field(name="قناة المغادرة", value=l_c.mention if l_c else "غير محددة", inline=True)
    emb.add_field(name="🔔 وقت إرسال الترحيب", value=TRIGGER_AR[cfg["trigger"]], inline=False)
    emb.add_field(name="🎭 رسائل الرتب", value=f"`{len(cfg['roles'])}` رسالة", inline=True)
    emb.add_field(name="✨ الرسالة النادرة",
                  value=f"{onoff(cfg['rare']['enabled'])}\nالنسبة `{cfg['rare']['chance']}%` • `{len(cfg['rare']['messages'])}` رسالة", inline=True)
    emb.add_field(name="📅 المناسبات",
                  value=f"`{len(cfg['events'])}` مناسبة\n" + (f"🟢 الآن: {'، '.join(active)}" if active else "لا يوجد نشط الآن"), inline=True)
    emb.add_field(name="📩 ترحيب بالخاص", value=onoff(cfg["dm_enabled"]), inline=True)
    emb.add_field(name="🚪 رسالة المغادرة", value=onoff(cfg["leave"]["enabled"]), inline=True)
    emb.set_footer(text="الأولوية عند الإرسال: ✨ النادرة ← 📅 المناسبة ← 🎭 رسالة الرتبة ← 📝 الافتراضية")
    await show(interaction, emb, WelcomeHomeView(back))


class _SettingChannel(discord.ui.ChannelSelect):
    def __init__(self, column: str, placeholder: str, row: int, back):
        super().__init__(placeholder=placeholder, channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                         min_values=1, max_values=1, row=row)
        self.column, self.back = column, back

    async def callback(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, self.column, self.values[0].id)
        await show_welcome_home(interaction, self.back)


class WelcomeOptionsModal(ModalBase, title="خيارات الترحيب"):
    def __init__(self, cfg: dict, back):
        super().__init__()
        self.back = back
        self.tz = discord.ui.TextInput(label="فرق التوقيت عن UTC (للمناسبات) مثال: 3", max_length=5, default=str(cfg["tz_offset"]))
        self.da = discord.ui.TextInput(label="حذف الترحيب تلقائياً بعد (ثواني، 0 = لا)", max_length=5, default=str(cfg["delete_after"]))
        self.fb = discord.ui.TextInput(label="ترحيب احتياطي لو ما اختار رتبة (دقائق)",
                                       placeholder="0 = بدون ترحيب احتياطي", max_length=5, default=str(cfg["fallback_minutes"]))
        self.dm = discord.ui.TextInput(label="رسالة الترحيب بالخاص", style=discord.TextStyle.paragraph,
                                       max_length=1000, default=cfg["dm_text"][:1000], required=False)
        for it in (self.tz, self.da, self.fb, self.dm):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            tz = float(self.tz.value.strip())
            da = int(self.da.value.strip())
            fb = int(self.fb.value.strip())
        except ValueError:
            return await reply(interaction, "❌ اكتب أرقام صحيحة في الخانات!", ephemeral=True)
        cfg = await db.get_welcome_cfg(interaction.guild_id)
        cfg["tz_offset"] = max(-12, min(14, tz))
        cfg["delete_after"] = max(0, min(86400, da))
        cfg["fallback_minutes"] = max(0, min(10080, fb))
        cfg["dm_text"] = self.dm.value or cfg["dm_text"]
        await db.set_welcome_cfg(interaction.guild_id, cfg)
        await show_welcome_home(interaction, self.back)


class WelcomeHomeView(NavView):
    def __init__(self, back):
        super().__init__()
        self.back = back
        self.add_item(_SettingChannel("welcome_channel_id", "👋 اختر قناة الترحيب...", 0, back))
        self.add_item(_SettingChannel("leave_channel_id", "🚪 اختر قناة المغادرة...", 1, back))

        async def toggle(i):
            cfg = await db.get_welcome_cfg(i.guild_id); cfg["enabled"] = not cfg["enabled"]
            await db.set_welcome_cfg(i.guild_id, cfg); await show_welcome_home(i, back)

        async def trigger(i):
            cfg = await db.get_welcome_cfg(i.guild_id)
            cfg["trigger"] = "role" if cfg["trigger"] == "join" else "join"
            await db.set_welcome_cfg(i.guild_id, cfg); await show_welcome_home(i, back)

        async def dm(i):
            cfg = await db.get_welcome_cfg(i.guild_id); cfg["dm_enabled"] = not cfg["dm_enabled"]
            await db.set_welcome_cfg(i.guild_id, cfg); await show_welcome_home(i, back)

        async def options(i):
            await i.response.send_modal(WelcomeOptionsModal(await db.get_welcome_cfg(i.guild_id), back))

        async def default_msg(i):
            await show_msg_editor(i, default_ctx(i.guild_id, back))

        async def roles(i): await show_roles_screen(i, back)
        async def rare(i): await show_rare_screen(i, back)
        async def events(i): await show_events_screen(i, back)
        async def leave(i): await show_msg_editor(i, leave_ctx(i.guild_id, back))

        async def preview(i):
            cfg = await db.get_welcome_cfg(i.guild_id)
            await send_preview(i, cfg["default"], preview_vars(i))

        self.add_btn("تفعيل / تعطيل", toggle, discord.ButtonStyle.success, row=2, emoji="🔘")
        self.add_btn("وقت الإرسال", trigger, discord.ButtonStyle.primary, row=2, emoji="🔁")
        self.add_btn("ترحيب بالخاص", dm, discord.ButtonStyle.secondary, row=2, emoji="📩")
        self.add_btn("خيارات", options, discord.ButtonStyle.secondary, row=2, emoji="⚙️")
        self.add_btn("الرسالة الافتراضية", default_msg, discord.ButtonStyle.primary, row=3, emoji="📝")
        self.add_btn("رسائل الرتب", roles, discord.ButtonStyle.primary, row=3, emoji="🎭")
        self.add_btn("النادرة", rare, discord.ButtonStyle.primary, row=3, emoji="✨")
        self.add_btn("المناسبات", events, discord.ButtonStyle.primary, row=3, emoji="📅")
        self.add_btn("المغادرة", leave, discord.ButtonStyle.secondary, row=4, emoji="🚪")
        self.add_btn("معاينة", preview, discord.ButtonStyle.success, row=4, emoji="👁️")
        self.add_back(back, row=4, label="رجوع للوحة")


# ═══════════════════════════ سياقات المحرر ═══════════════════════════
def default_ctx(gid, back) -> MsgCtx:
    async def home(i): await show_welcome_home(i, back)

    async def load():
        return (await db.get_welcome_cfg(gid))["default"]

    async def save(m):
        cfg = await db.get_welcome_cfg(gid); cfg["default"] = m; await db.set_welcome_cfg(gid, cfg)
    return MsgCtx("الرسالة الافتراضية للترحيب", load, save, home, WELCOME_VARS, preview_vars)


def leave_ctx(gid, back) -> MsgCtx:
    async def home(i): await show_welcome_home(i, back)

    async def load():
        return (await db.get_welcome_cfg(gid))["leave"]["msg"]

    async def save(m):
        cfg = await db.get_welcome_cfg(gid); cfg["leave"]["msg"] = m; await db.set_welcome_cfg(gid, cfg)

    async def toggle(i):
        cfg = await db.get_welcome_cfg(gid); cfg["leave"]["enabled"] = not cfg["leave"]["enabled"]
        await db.set_welcome_cfg(gid, cfg); await show_msg_editor(i, leave_ctx(gid, back))

    async def info():
        cfg = await db.get_welcome_cfg(gid)
        return f"الحالة: {onoff(cfg['leave']['enabled'])}  (في المغادرة `{{user}}` = الاسم بدون منشن)"
    return MsgCtx("رسالة المغادرة", load, save, home,
                  "{user} {name} الاسم • {server} • {count} • {id}",
                  lambda i: welcome_vars(i.user, {"user": i.user.display_name}),
                  extra=[("تفعيل / تعطيل", "🔘", discord.ButtonStyle.secondary, toggle)], extra_info=info)


# ═══════════════════════════ رسائل الرتب ═══════════════════════════
async def show_roles_screen(interaction: discord.Interaction, back):
    gid = interaction.guild_id
    cfg = await db.get_welcome_cfg(gid)
    lines = []
    for e in cfg["roles"]:
        role = interaction.guild.get_role(e["role_id"])
        lines.append(f"🎭 {role.mention if role else '`رتبة محذوفة`'} ← {short(e['msg'].get('desc'), 45) or '—'}")
    emb = discord.Embed(
        title="🎭 رسائل الترحيب حسب الرتبة",
        description=("كل رتبة تقدر تحط لها رسالة خاصة (مثلاً رتبة ولد ← رسالة للأولاد، رتبة بنت ← رسالة للبنات).\n"
                     "في وضع **عند أخذ رتبة** يتم الترحيب لما العضو ياخذ الرتبة اللي اختارها لدخول السيرفر.\n\n"
                     + ("\n".join(lines) if lines else "لا توجد رسائل رتب بعد.")),
        color=discord.Color.purple())
    emb.add_field(name="🔔 وقت الإرسال الحالي", value=TRIGGER_AR[cfg["trigger"]], inline=False)
    await show(interaction, emb, RolesView(cfg, interaction.guild, back))


def role_ctx(gid, role_id, back) -> MsgCtx:
    async def to_list(i): await show_roles_screen(i, back)

    async def load():
        for e in (await db.get_welcome_cfg(gid))["roles"]:
            if e["role_id"] == role_id:
                return e["msg"]
        return {}

    async def save(m):
        cfg = await db.get_welcome_cfg(gid)
        for e in cfg["roles"]:
            if e["role_id"] == role_id:
                e["msg"] = m
        await db.set_welcome_cfg(gid, cfg)

    async def delete(i):
        cfg = await db.get_welcome_cfg(gid)
        cfg["roles"] = [e for e in cfg["roles"] if e["role_id"] != role_id]
        await db.set_welcome_cfg(gid, cfg)
        await show_roles_screen(i, back)

    async def info():
        return f"الرتبة: <@&{role_id}>"
    return MsgCtx("رسالة ترحيب الرتبة", load, save, to_list, WELCOME_VARS, preview_vars,
                  extra=[("حذف هذه الرسالة", "🗑️", discord.ButtonStyle.danger, delete)], extra_info=info)


class _AddRoleSelect(discord.ui.RoleSelect):
    def __init__(self, back):
        super().__init__(placeholder="➕ اختر رتبة لإضافة رسالة ترحيب لها...", min_values=1, max_values=1, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        gid = interaction.guild_id
        cfg = await db.get_welcome_cfg(gid)
        if not any(e["role_id"] == role.id for e in cfg["roles"]):
            m = copy.deepcopy(cfg["default"])
            m["desc"] = f"أهلاً {{user}} 🎉 نورت **{{server}}** يا صاحب رتبة {role.name}!"
            cfg["roles"].append({"role_id": role.id, "msg": m})
            await db.set_welcome_cfg(gid, cfg)
        await show_msg_editor(interaction, role_ctx(gid, role.id, self.back))


class _PickRoleEntry(discord.ui.Select):
    def __init__(self, cfg, guild, back):
        opts = []
        for e in cfg["roles"][:25]:
            r = guild.get_role(e["role_id"])
            opts.append(discord.SelectOption(label=(r.name if r else "رتبة محذوفة")[:100], value=str(e["role_id"]),
                                             description=short(e["msg"].get("desc"), 90) or None, emoji="🎭"))
        super().__init__(placeholder="✏️ اختر رسالة رتبة لتعديلها أو حذفها...", options=opts, row=1)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await show_msg_editor(interaction, role_ctx(interaction.guild_id, int(self.values[0]), self.back))


class RolesView(NavView):
    def __init__(self, cfg, guild, back):
        super().__init__()
        self.add_item(_AddRoleSelect(back))
        if cfg["roles"]:
            self.add_item(_PickRoleEntry(cfg, guild, back))

        async def trigger(i):
            c = await db.get_welcome_cfg(i.guild_id)
            c["trigger"] = "role" if c["trigger"] == "join" else "join"
            await db.set_welcome_cfg(i.guild_id, c); await show_roles_screen(i, back)

        async def home(i): await show_welcome_home(i, back)
        self.add_btn("تبديل وقت الإرسال (دخول / رتبة)", trigger, discord.ButtonStyle.primary, row=2, emoji="🔁")
        self.add_back(home, row=2)


# ═══════════════════════════ الرسالة النادرة ═══════════════════════════
async def show_rare_screen(interaction: discord.Interaction, back):
    cfg = await db.get_welcome_cfg(interaction.guild_id)
    rare = cfg["rare"]
    lines = [f"`{n}` ← {short(m.get('desc') or m.get('title'), 60) or '—'}" for n, m in enumerate(rare["messages"], 1)]
    emb = discord.Embed(
        title="✨ الرسالة النادرة",
        description=("كل عضو يدخل عنده نسبة معينة يجيه ترحيب **مميز ونادر** (عشوائي، ما له علاقة بالجنس أو الرتبة).\n"
                     "تقدر تضيف أكثر من رسالة نادرة والبوت يختار وحدة منها عشوائياً.\n\n"
                     + ("\n".join(lines) if lines else "لا توجد رسائل نادرة بعد.")),
        color=discord.Color.gold())
    emb.add_field(name="الحالة", value=onoff(rare["enabled"]), inline=True)
    emb.add_field(name="🎲 النسبة", value=f"`{rare['chance']}%` (حوالي واحد من كل {int(100 / rare['chance']) if rare['chance'] else '∞'})", inline=True)
    await show(interaction, emb, RareView(cfg, back))


def rare_ctx(gid, idx, back) -> MsgCtx:
    async def to_list(i): await show_rare_screen(i, back)

    async def load():
        msgs = (await db.get_welcome_cfg(gid))["rare"]["messages"]
        return msgs[idx] if idx < len(msgs) else {}

    async def save(m):
        cfg = await db.get_welcome_cfg(gid)
        if idx < len(cfg["rare"]["messages"]):
            cfg["rare"]["messages"][idx] = m
            await db.set_welcome_cfg(gid, cfg)

    async def delete(i):
        cfg = await db.get_welcome_cfg(gid)
        if idx < len(cfg["rare"]["messages"]):
            cfg["rare"]["messages"].pop(idx)
            await db.set_welcome_cfg(gid, cfg)
        await show_rare_screen(i, back)
    return MsgCtx(f"الرسالة النادرة رقم {idx + 1}", load, save, to_list, WELCOME_VARS, preview_vars,
                  extra=[("حذف", "🗑️", discord.ButtonStyle.danger, delete)])


class RareChanceModal(ModalBase, title="نسبة الرسالة النادرة"):
    def __init__(self, current, back):
        super().__init__()
        self.back = back
        self.chance = discord.ui.TextInput(label="النسبة المئوية (من 0.1 إلى 100)", default=str(current), max_length=6)
        self.add_item(self.chance)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = float(self.chance.value.strip().replace("%", "").replace(",", "."))
        except ValueError:
            return await reply(interaction, "❌ اكتب رقم مثل `5` أو `0.5`", ephemeral=True)
        cfg = await db.get_welcome_cfg(interaction.guild_id)
        cfg["rare"]["chance"] = max(0.0, min(100.0, round(v, 2)))
        await db.set_welcome_cfg(interaction.guild_id, cfg)
        await show_rare_screen(interaction, self.back)


class _PickRare(discord.ui.Select):
    def __init__(self, cfg, back):
        opts = [discord.SelectOption(label=f"رسالة نادرة {n}", value=str(n - 1),
                                     description=short(m.get("desc") or m.get("title"), 90) or None, emoji="✨")
                for n, m in enumerate(cfg["rare"]["messages"][:25], 1)]
        super().__init__(placeholder="✏️ اختر رسالة نادرة لتعديلها أو حذفها...", options=opts, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await show_msg_editor(interaction, rare_ctx(interaction.guild_id, int(self.values[0]), self.back))


class RareView(NavView):
    def __init__(self, cfg, back):
        super().__init__()
        if cfg["rare"]["messages"]:
            self.add_item(_PickRare(cfg, back))

        async def toggle(i):
            c = await db.get_welcome_cfg(i.guild_id); c["rare"]["enabled"] = not c["rare"]["enabled"]
            await db.set_welcome_cfg(i.guild_id, c); await show_rare_screen(i, back)

        async def chance(i):
            c = await db.get_welcome_cfg(i.guild_id)
            await i.response.send_modal(RareChanceModal(c["rare"]["chance"], back))

        async def add(i):
            c = await db.get_welcome_cfg(i.guild_id)
            if len(c["rare"]["messages"]) >= 25:
                return await reply(i, "❌ الحد الأقصى 25 رسالة نادرة.", ephemeral=True)
            c["rare"]["messages"].append({**DEFAULT_MSG, "as_embed": True, "title": "✨ ترحيب نادر!", "color": "#F1C40F",
                                          "thumb": "avatar", "desc": "🌟 {user} أنت محظوظ! طلعت لك الرسالة النادرة، أهلاً بك في **{server}**"})
            await db.set_welcome_cfg(i.guild_id, c)
            await show_msg_editor(i, rare_ctx(i.guild_id, len(c["rare"]["messages"]) - 1, back))

        async def home(i): await show_welcome_home(i, back)
        self.add_btn("تفعيل / تعطيل", toggle, discord.ButtonStyle.success, row=1, emoji="🔘")
        self.add_btn("تحديد النسبة", chance, discord.ButtonStyle.primary, row=1, emoji="🎲")
        self.add_btn("إضافة رسالة نادرة", add, discord.ButtonStyle.primary, row=1, emoji="➕")
        self.add_back(home, row=1)


# ═══════════════════════════ المناسبات ═══════════════════════════
def _ev_dates(e) -> str:
    cal = "هجري" if e.get("calendar") == "hijri" else "ميلادي"
    return f"{e.get('start')} ← {e.get('end')} ({cal})"


async def show_events_screen(interaction: discord.Interaction, back):
    cfg = await db.get_welcome_cfg(interaction.guild_id)
    lines = []
    for n, e in enumerate(cfg["events"], 1):
        mark = "🟢" if event_is_active(e, cfg["tz_offset"]) else ("⏸️" if not e.get("enabled", True) else "⚪")
        lines.append(f"{mark} **{e['name']}** — `{_ev_dates(e)}`")
    emb = discord.Embed(
        title="📅 رسائل المناسبات",
        description=("رسالة ترحيب خاصة تشتغل تلقائياً **خلال فترة المناسبة** فقط (رمضان، الهالوين، الأعياد...).\n"
                     "التواريخ: `MM-DD` تتكرر كل سنة، أو `YYYY-MM-DD` لسنة محددة. التقويم الهجري حسابي تقريبي (قد يختلف يوم).\n\n"
                     + ("\n".join(lines) if lines else "لا توجد مناسبات بعد. أضف من القائمة الجاهزة أو يدوياً.")),
        color=discord.Color.orange())
    emb.add_field(name="🟢 نشطة / ⚪ خارج الفترة / ⏸️ معطلة", value=f"فرق التوقيت المستخدم: UTC{cfg['tz_offset']:+g}", inline=False)
    await show(interaction, emb, EventsView(cfg, back))


class EventModal(ModalBase, title="مناسبة"):
    def __init__(self, back, idx=None, ev=None):
        super().__init__()
        self.back, self.idx = back, idx
        ev = ev or {"name": "", "start": "", "end": "", "calendar": "greg"}
        self.name = discord.ui.TextInput(label="اسم المناسبة", max_length=40, default=ev["name"] or None)
        self.start = discord.ui.TextInput(label="بداية الفترة (MM-DD أو YYYY-MM-DD)", max_length=10, default=ev["start"] or None, placeholder="10-25")
        self.end = discord.ui.TextInput(label="نهاية الفترة (MM-DD أو YYYY-MM-DD)", max_length=10, default=ev["end"] or None, placeholder="10-31")
        self.cal = discord.ui.TextInput(label="التقويم: ميلادي أو هجري", max_length=10,
                                        default="هجري" if ev.get("calendar") == "hijri" else "ميلادي")
        for it in (self.name, self.start, self.end, self.cal):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        s, e = self.start.value.strip(), self.end.value.strip()
        if not parse_event_date(s) or not parse_event_date(e):
            return await reply(interaction, "❌ صيغة التاريخ خطأ. استخدم `10-25` أو `2027-02-08`.", ephemeral=True)
        cal = "hijri" if self.cal.value.strip() in ("هجري", "هجرى", "hijri", "ه") else "greg"
        cfg = await db.get_welcome_cfg(interaction.guild_id)
        if self.idx is None:
            cfg["events"].append({"name": self.name.value.strip(), "enabled": True, "calendar": cal, "start": s, "end": e,
                                  "msg": {**DEFAULT_MSG, "as_embed": True, "title": f"🎉 {self.name.value.strip()}",
                                          "thumb": "avatar", "desc": "أهلاً {user} في **{server}** وكل عام وأنت بخير!"}})
            idx = len(cfg["events"]) - 1
        else:
            idx = self.idx
            if idx >= len(cfg["events"]):
                return await show_events_screen(interaction, self.back)
            cfg["events"][idx].update(name=self.name.value.strip(), start=s, end=e, calendar=cal)
        await db.set_welcome_cfg(interaction.guild_id, cfg)
        await show_msg_editor(interaction, event_ctx(interaction.guild_id, idx, self.back))


def event_ctx(gid, idx, back) -> MsgCtx:
    async def to_list(i): await show_events_screen(i, back)

    async def load():
        evs = (await db.get_welcome_cfg(gid))["events"]
        return evs[idx]["msg"] if idx < len(evs) else {}

    async def save(m):
        cfg = await db.get_welcome_cfg(gid)
        if idx < len(cfg["events"]):
            cfg["events"][idx]["msg"] = m
            await db.set_welcome_cfg(gid, cfg)

    async def dates(i):
        evs = (await db.get_welcome_cfg(gid))["events"]
        if idx < len(evs):
            await i.response.send_modal(EventModal(back, idx, evs[idx]))

    async def toggle(i):
        cfg = await db.get_welcome_cfg(gid)
        if idx < len(cfg["events"]):
            cfg["events"][idx]["enabled"] = not cfg["events"][idx].get("enabled", True)
            await db.set_welcome_cfg(gid, cfg)
        await show_msg_editor(i, event_ctx(gid, idx, back))

    async def delete(i):
        cfg = await db.get_welcome_cfg(gid)
        if idx < len(cfg["events"]):
            cfg["events"].pop(idx)
            await db.set_welcome_cfg(gid, cfg)
        await show_events_screen(i, back)

    async def info():
        cfg = await db.get_welcome_cfg(gid)
        if idx >= len(cfg["events"]):
            return ""
        e = cfg["events"][idx]
        now = "🟢 نشطة الآن" if event_is_active(e, cfg["tz_offset"]) else "⚪ خارج الفترة"
        return f"**{e['name']}** — `{_ev_dates(e)}`\nالحالة: {onoff(e.get('enabled', True))} • {now}"

    return MsgCtx("رسالة المناسبة", load, save, to_list, WELCOME_VARS, preview_vars,
                  extra=[("الاسم والتواريخ", "📅", discord.ButtonStyle.primary, dates),
                         ("تفعيل / تعطيل", "🔘", discord.ButtonStyle.secondary, toggle),
                         ("حذف", "🗑️", discord.ButtonStyle.danger, delete)], extra_info=info)


class _PresetSelect(discord.ui.Select):
    def __init__(self, back):
        opts = [discord.SelectOption(label=p["name"], value=k, description=_ev_dates(p)) for k, p in EVENT_PRESETS.items()]
        super().__init__(placeholder="📦 إضافة مناسبة جاهزة...", options=opts, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        p = copy.deepcopy(EVENT_PRESETS[self.values[0]])
        cfg = await db.get_welcome_cfg(interaction.guild_id)
        if len(cfg["events"]) >= 24:
            return await reply(interaction, "❌ وصلت الحد الأقصى للمناسبات.", ephemeral=True)
        p["msg"] = {**DEFAULT_MSG, **p["msg"]}
        p["enabled"] = True
        cfg["events"].append(p)
        await db.set_welcome_cfg(interaction.guild_id, cfg)
        await show_msg_editor(interaction, event_ctx(interaction.guild_id, len(cfg["events"]) - 1, self.back))


class _PickEvent(discord.ui.Select):
    def __init__(self, cfg, back):
        opts = [discord.SelectOption(label=e["name"][:100], value=str(n), description=_ev_dates(e)[:100], emoji="📅")
                for n, e in enumerate(cfg["events"][:25])]
        super().__init__(placeholder="✏️ اختر مناسبة لتعديلها...", options=opts, row=1)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await show_msg_editor(interaction, event_ctx(interaction.guild_id, int(self.values[0]), self.back))


class EventsView(NavView):
    def __init__(self, cfg, back):
        super().__init__()
        self.add_item(_PresetSelect(back))
        if cfg["events"]:
            self.add_item(_PickEvent(cfg, back))

        async def add(i):
            await i.response.send_modal(EventModal(back))

        async def home(i): await show_welcome_home(i, back)
        self.add_btn("إضافة مناسبة يدوياً", add, discord.ButtonStyle.primary, row=2, emoji="➕")
        self.add_back(home, row=2)


async def setup(bot):
    """ملف واجهة فقط، لا يضيف أوامر."""
    pass
