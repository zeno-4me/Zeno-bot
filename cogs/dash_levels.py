"""
واجهة إعدادات نظام اللفل داخل /dashboard
(تفعيل • معدلات • تنبيهات • رتب التفاعل • استثناءات • مضاعفات • شكل /rank)
"""
import discord

from database import (db, reply, LEVEL_VARS, BAR_STYLES, parse_hex, build_message)

try:
    from cogs.dash_common import (NavView, ModalBase, MsgCtx, show, show_msg_editor, short, onoff,
                                  show_id_picker, fmt_ids, send_preview)
except ImportError:
    from dash_common import (NavView, ModalBase, MsgCtx, show, show_msg_editor, short, onoff,
                             show_id_picker, fmt_ids, send_preview)

DEST_AR = {"channel": "قناة التنبيهات (وإلا نفس الشات)", "current": "نفس الشات اللي كتب فيه العضو",
           "dm": "رسالة خاصة للعضو"}
DEST_ORDER = ["channel", "current", "dm"]


# ═══════════════════════════ الشاشة الرئيسية ═══════════════════════════
async def open_levels(interaction: discord.Interaction, back):
    await show_levels_home(interaction, back)


async def show_levels_home(interaction: discord.Interaction, back):
    gid = interaction.guild_id
    st = await db.get_guild_settings(gid)
    cfg = await db.get_level_cfg(gid)
    rewards = await db.get_level_rewards(gid)
    ch = interaction.guild.get_channel(st['level_up_channel_id']) if st['level_up_channel_id'] else None
    ann = cfg["announce"]

    emb = discord.Embed(title="⭐ نظام اللفل والخبرة", color=discord.Color.gold(),
                        description=("**اللفل الأساسي = الخبرة الكتابية + الخبرة الصوتية**\n"
                                     "اللفل الكتابي والصوتي للعرض فقط، والتنبيه والرتب يعتمدون على اللفل الأساسي."))
    emb.add_field(name="💬 الخبرة الكتابية", value=f"{onoff(st['text_xp_enabled'])}\n`{st['text_xp_rate']}"
                  + (f"–{cfg['text_xp_max']}" if cfg['text_xp_max'] > st['text_xp_rate'] else "") + f"` XP / رسالة", inline=True)
    emb.add_field(name="🎤 الخبرة الصوتية", value=f"{onoff(st['voice_xp_enabled'])}\n`{st['voice_xp_rate']}` XP / دقيقة", inline=True)
    emb.add_field(name="⏱️ كولداون الرسائل", value=f"`{cfg['cooldown']}` ثانية", inline=True)
    emb.add_field(name="📣 تنبيه اللفل", value=f"{onoff(ann['enabled'])}\n{DEST_AR[ann['dest']]}\n"
                  f"القناة: {ch.mention if ch else 'غير محددة'}", inline=True)
    emb.add_field(name="🎖️ رتب التفاعل", value=f"`{len(rewards)}` رتبة • {'تراكمي' if cfg['reward_mode'] == 'stack' else 'استبدال'}", inline=True)
    emb.add_field(name="🧮 الصعوبة", value=f"أساس `{cfg['base_xp']}` XP", inline=True)
    emb.add_field(name="🚫 الاستثناءات", value=f"`{len(cfg['ignored_channels'])}` قناة • `{len(cfg['ignored_roles'])}` رتبة", inline=True)
    emb.add_field(name="✖️ المضاعفات", value=f"`{len(cfg['multipliers'])}` رتبة", inline=True)
    emb.add_field(name="🎤 شروط الصوت", value=f"لازم أحد معك: {'نعم' if cfg['voice_require_others'] else 'لا'}\n"
                  f"احتساب المكتوم: {'نعم' if cfg['voice_count_muted'] else 'لا'}", inline=True)
    await show(interaction, emb, LevelsHomeView(back, st))


class _LevelChannel(discord.ui.ChannelSelect):
    def __init__(self, back):
        super().__init__(placeholder="🎉 اختر قناة تنبيهات اللفل...", channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                         min_values=1, max_values=1, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "level_up_channel_id", self.values[0].id)
        await show_levels_home(interaction, self.back)


class RatesModal(ModalBase, title="معدلات الخبرة والصعوبة"):
    def __init__(self, st, cfg, back):
        super().__init__()
        self.back = back
        self.t_min = discord.ui.TextInput(label="خبرة الرسالة (الحد الأدنى)", max_length=4, default=str(st['text_xp_rate']))
        self.t_max = discord.ui.TextInput(label="خبرة الرسالة (الحد الأقصى، اختياري = عشوائي)", max_length=4,
                                          default=str(cfg['text_xp_max'] or st['text_xp_rate']))
        self.v_rate = discord.ui.TextInput(label="خبرة الصوت لكل دقيقة", max_length=4, default=str(st['voice_xp_rate']))
        self.cd = discord.ui.TextInput(label="كولداون الرسائل (ثواني)", max_length=4, default=str(cfg['cooldown']))
        self.base = discord.ui.TextInput(label="الصعوبة (100 = عادي، أكبر = أصعب)", max_length=5, default=str(cfg['base_xp']))
        for it in (self.t_min, self.t_max, self.v_rate, self.cd, self.base):
            self.add_item(it)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            t_min, t_max = int(self.t_min.value), int(self.t_max.value)
            v, cd, base = int(self.v_rate.value), int(self.cd.value), int(self.base.value)
        except ValueError:
            return await reply(interaction, "❌ اكتب أرقام صحيحة في كل الخانات!", ephemeral=True)
        gid = interaction.guild_id
        t_min, v = max(0, min(1000, t_min)), max(0, min(1000, v))
        await db.update_guild_setting(gid, "text_xp_rate", t_min)
        await db.update_guild_setting(gid, "voice_xp_rate", v)
        cfg = await db.get_level_cfg(gid)
        cfg["text_xp_max"] = max(t_min, min(1000, t_max)) if t_max > t_min else 0
        cfg["cooldown"] = max(0, min(3600, cd))
        cfg["base_xp"] = max(10, min(100000, base))
        await db.set_level_cfg(gid, cfg)
        await show_levels_home(interaction, self.back)


class LevelsHomeView(NavView):
    def __init__(self, back, st):
        super().__init__()
        self.add_item(_LevelChannel(back))

        async def home(i): await show_levels_home(i, back)

        async def tg_text(i):
            s = await db.get_guild_settings(i.guild_id)
            await db.update_guild_setting(i.guild_id, "text_xp_enabled", 0 if s['text_xp_enabled'] else 1)
            await home(i)

        async def tg_voice(i):
            s = await db.get_guild_settings(i.guild_id)
            await db.update_guild_setting(i.guild_id, "voice_xp_enabled", 0 if s['voice_xp_enabled'] else 1)
            await home(i)

        async def rates(i):
            s = await db.get_guild_settings(i.guild_id)
            await i.response.send_modal(RatesModal(s, await db.get_level_cfg(i.guild_id), back))

        async def voice_opts(i): await show_voice_opts(i, back)
        async def announce(i): await show_announce(i, back)
        async def rewards(i): await show_rewards(i, back)
        async def ignore(i): await show_ignore(i, back)
        async def mults(i): await show_mults(i, back)
        async def rank_style(i): await show_rank_style(i, back)

        self.add_btn("الكتابي", tg_text, discord.ButtonStyle.success if st['text_xp_enabled'] else discord.ButtonStyle.danger, row=1, emoji="💬")
        self.add_btn("الصوتي", tg_voice, discord.ButtonStyle.success if st['voice_xp_enabled'] else discord.ButtonStyle.danger, row=1, emoji="🎤")
        self.add_btn("المعدلات والصعوبة", rates, discord.ButtonStyle.primary, row=1, emoji="⚡")
        self.add_btn("شروط الصوت", voice_opts, discord.ButtonStyle.secondary, row=1, emoji="🔊")
        self.add_btn("التنبيهات", announce, discord.ButtonStyle.primary, row=2, emoji="📣")
        self.add_btn("رتب التفاعل", rewards, discord.ButtonStyle.primary, row=2, emoji="🎖️")
        self.add_btn("الاستثناءات", ignore, discord.ButtonStyle.secondary, row=2, emoji="🚫")
        self.add_btn("المضاعفات", mults, discord.ButtonStyle.secondary, row=2, emoji="✖️")
        self.add_btn("شكل /rank", rank_style, discord.ButtonStyle.secondary, row=3, emoji="🎨")
        self.add_back(back, row=3, label="رجوع للوحة")


# ═══════════════════════════ شروط الصوت ═══════════════════════════
async def show_voice_opts(interaction: discord.Interaction, back):
    cfg = await db.get_level_cfg(interaction.guild_id)
    emb = discord.Embed(title="🔊 شروط احتساب الخبرة الصوتية", color=discord.Color.blurple(),
                        description=("• **لازم أحد معك:** ما تنحسب الخبرة لو العضو لحاله بالروم.\n"
                                     "• **احتساب المكتوم:** تنحسب الخبرة حتى لو العضو كاتم المايك (لكن مو الديفن).\n"
                                     "• رومات AFK ما تنحسب أبداً."))
    emb.add_field(name="لازم أحد معك", value=onoff(cfg["voice_require_others"]), inline=True)
    emb.add_field(name="احتساب المكتوم", value=onoff(cfg["voice_count_muted"]), inline=True)
    view = NavView()

    async def flip(i, key):
        c = await db.get_level_cfg(i.guild_id); c[key] = not c[key]
        await db.set_level_cfg(i.guild_id, c); await show_voice_opts(i, back)

    async def a(i): await flip(i, "voice_require_others")
    async def b(i): await flip(i, "voice_count_muted")
    async def home(i): await show_levels_home(i, back)
    view.add_btn("لازم أحد معك", a, discord.ButtonStyle.primary, row=0, emoji="👥")
    view.add_btn("احتساب المكتوم", b, discord.ButtonStyle.primary, row=0, emoji="🎙️")
    view.add_back(home, row=1)
    await show(interaction, emb, view)


# ═══════════════════════════ تنبيهات اللفل ═══════════════════════════
def level_preview_vars(i: discord.Interaction) -> dict:
    return {"user": i.user.mention, "name": i.user.display_name, "level": 10, "old_level": 9, "xp": 8100,
            "server": i.guild.name, "reward": "رتبة تجريبية"}


def announce_ctx(gid, back) -> MsgCtx:
    async def to_ann(i): await show_announce(i, back)

    async def load():
        return (await db.get_level_cfg(gid))["announce"]["msg"]

    async def save(m):
        c = await db.get_level_cfg(gid); c["announce"]["msg"] = m; await db.set_level_cfg(gid, c)
    return MsgCtx("رسالة ارتفاع اللفل", load, save, to_ann, LEVEL_VARS, level_preview_vars)


class DeleteAfterModal(ModalBase, title="حذف التنبيه تلقائياً"):
    def __init__(self, cur, back):
        super().__init__()
        self.back = back
        self.sec = discord.ui.TextInput(label="بعد كم ثانية يُحذف التنبيه؟ (0 = لا يُحذف)", max_length=5, default=str(cur))
        self.add_item(self.sec)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = int(self.sec.value.strip())
        except ValueError:
            return await reply(interaction, "❌ اكتب رقم صحيح!", ephemeral=True)
        c = await db.get_level_cfg(interaction.guild_id)
        c["announce"]["delete_after"] = max(0, min(86400, v))
        await db.set_level_cfg(interaction.guild_id, c)
        await show_announce(interaction, self.back)


async def show_announce(interaction: discord.Interaction, back):
    cfg = await db.get_level_cfg(interaction.guild_id)
    a = cfg["announce"]
    m = a["msg"]
    emb = discord.Embed(title="📣 تنبيهات ارتفاع اللفل", color=discord.Color.green() if a["enabled"] else discord.Color.red(),
                        description=("التنبيه يوصل **فقط** لما اللفل الأساسي يرتفع.\n"
                                     "ارتفاع الكتابي لحاله أو الصوتي لحاله ما يرسل تنبيه (هما للعرض فقط)."))
    emb.add_field(name="الحالة", value=onoff(a["enabled"]), inline=True)
    emb.add_field(name="النمط", value="🖼️ إمبد" if m.get("as_embed") else "💬 نص عادي", inline=True)
    emb.add_field(name="المنشن", value=onoff(a["ping"]), inline=True)
    emb.add_field(name="الوجهة", value=DEST_AR[a["dest"]], inline=False)
    emb.add_field(name="حذف تلقائي", value=f"{a['delete_after']} ثانية" if a["delete_after"] else "لا", inline=True)
    emb.add_field(name="الرسالة", value=f"```{short(m.get('desc'), 300).replace('```', chr(39) * 3)}```", inline=False)
    view = NavView()

    async def toggle(i):
        c = await db.get_level_cfg(i.guild_id); c["announce"]["enabled"] = not c["announce"]["enabled"]
        await db.set_level_cfg(i.guild_id, c); await show_announce(i, back)

    async def dest(i):
        c = await db.get_level_cfg(i.guild_id)
        cur = c["announce"]["dest"]
        c["announce"]["dest"] = DEST_ORDER[(DEST_ORDER.index(cur) + 1) % len(DEST_ORDER)] if cur in DEST_ORDER else "channel"
        await db.set_level_cfg(i.guild_id, c); await show_announce(i, back)

    async def ping(i):
        c = await db.get_level_cfg(i.guild_id); c["announce"]["ping"] = not c["announce"]["ping"]
        await db.set_level_cfg(i.guild_id, c); await show_announce(i, back)

    async def dele(i):
        c = await db.get_level_cfg(i.guild_id)
        await i.response.send_modal(DeleteAfterModal(c["announce"]["delete_after"], back))

    async def edit(i): await show_msg_editor(i, announce_ctx(i.guild_id, back))

    async def preview(i):
        c = await db.get_level_cfg(i.guild_id)
        await send_preview(i, c["announce"]["msg"], level_preview_vars(i))

    async def home(i): await show_levels_home(i, back)
    view.add_btn("تفعيل / تعطيل", toggle, discord.ButtonStyle.success, row=0, emoji="🔘")
    view.add_btn("الوجهة", dest, discord.ButtonStyle.primary, row=0, emoji="🔁")
    view.add_btn("المنشن", ping, discord.ButtonStyle.secondary, row=0, emoji="🔔")
    view.add_btn("حذف تلقائي", dele, discord.ButtonStyle.secondary, row=0, emoji="⏱️")
    view.add_btn("تعديل الرسالة (نص / إمبد)", edit, discord.ButtonStyle.primary, row=1, emoji="✏️")
    view.add_btn("معاينة", preview, discord.ButtonStyle.success, row=1, emoji="👁️")
    view.add_back(home, row=1)
    await show(interaction, emb, view)


# ═══════════════════════════ رتب التفاعل (مكافآت اللفل) ═══════════════════════════
async def show_rewards(interaction: discord.Interaction, back):
    gid = interaction.guild_id
    cfg = await db.get_level_cfg(gid)
    rewards = await db.get_level_rewards(gid)
    lines, me_top = [], interaction.guild.me.top_role
    for r in rewards:
        role = interaction.guild.get_role(r['role_id'])
        warn = " ⚠️ أعلى من رتبة البوت" if role and role >= me_top else ""
        lines.append(f"🎖️ المستوى `{r['level']}` ← {role.mention if role else '`رتبة محذوفة`'}{warn}")
    emb = discord.Embed(title="🎖️ رتب التفاعل (مكافآت اللفل)", color=discord.Color.gold(),
                        description=("رتب تنعطى تلقائياً لما العضو يوصل **اللفل الأساسي** المحدد.\n\n"
                                     + ("\n".join(lines) if lines else "لا توجد رتب بعد. اختر رتبة من القائمة تحت لإضافتها.")))
    emb.add_field(name="طريقة المنح", value=("📚 **تراكمي:** العضو يحتفظ بكل الرتب اللي وصلها." if cfg["reward_mode"] == "stack"
                                            else "🔄 **استبدال:** تبقى أعلى رتبة وصلها فقط وتُزال الأقل."), inline=False)
    emb.set_footer(text="لازم تكون رتبة البوت أعلى من الرتب المكافأة، وللبوت صلاحية Manage Roles")
    await show(interaction, emb, RewardsView(rewards, interaction.guild, back))


class RewardLevelModal(ModalBase, title="مستوى الرتبة"):
    def __init__(self, role: discord.Role, back):
        super().__init__()
        self.role, self.back = role, back
        self.lvl = discord.ui.TextInput(label=f"اللفل المطلوب للحصول على «{role.name[:40]}»", max_length=4, placeholder="5")
        self.add_item(self.lvl)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            lvl = int(self.lvl.value.strip())
            if not 1 <= lvl <= 1000:
                raise ValueError
        except ValueError:
            return await reply(interaction, "❌ اكتب رقم لفل من 1 إلى 1000.", ephemeral=True)
        await db.add_level_reward(interaction.guild_id, lvl, self.role.id)
        await show_rewards(interaction, self.back)


class _RewardRole(discord.ui.RoleSelect):
    def __init__(self, back):
        super().__init__(placeholder="➕ اختر رتبة لإضافتها كمكافأة...", min_values=1, max_values=1, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        if role.is_default() or role.managed:
            return await reply(interaction, "❌ هذي الرتبة ما ينفع تنعطى (رتبة النظام أو رتبة بوت).", ephemeral=True)
        await interaction.response.send_modal(RewardLevelModal(role, self.back))


class _RewardDelete(discord.ui.Select):
    def __init__(self, rewards, guild, back):
        opts = []
        for r in rewards[:25]:
            role = guild.get_role(r['role_id'])
            opts.append(discord.SelectOption(label=f"المستوى {r['level']} — {(role.name if role else 'محذوفة')[:60]}",
                                             value=str(r['level']), emoji="🗑️"))
        super().__init__(placeholder="🗑️ اختر مكافأة لحذفها...", options=opts, row=1)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await db.remove_level_reward(interaction.guild_id, int(self.values[0]))
        await show_rewards(interaction, self.back)


class RewardsView(NavView):
    def __init__(self, rewards, guild, back):
        super().__init__()
        self.add_item(_RewardRole(back))
        if rewards:
            self.add_item(_RewardDelete(rewards, guild, back))

        async def mode(i):
            c = await db.get_level_cfg(i.guild_id)
            c["reward_mode"] = "replace" if c["reward_mode"] == "stack" else "stack"
            await db.set_level_cfg(i.guild_id, c); await show_rewards(i, back)

        async def home(i): await show_levels_home(i, back)
        self.add_btn("تبديل: تراكمي / استبدال", mode, discord.ButtonStyle.primary, row=2, emoji="🔁")
        self.add_back(home, row=2)


# ═══════════════════════════ الاستثناءات ═══════════════════════════
async def show_ignore(interaction: discord.Interaction, back):
    cfg = await db.get_level_cfg(interaction.guild_id)
    emb = discord.Embed(title="🚫 استثناءات الخبرة", color=discord.Color.red(),
                        description="القنوات والرتب هنا **ما تكسب خبرة** (كتابي وصوتي).")
    emb.add_field(name="📺 القنوات المستثناة (الكاتيجوري يشمل اللي داخلها)", value=fmt_ids(cfg["ignored_channels"], "channel"), inline=False)
    emb.add_field(name="👥 الرتب المستثناة", value=fmt_ids(cfg["ignored_roles"], "role"), inline=False)
    view = NavView()

    async def save_channels(i, ids):
        c = await db.get_level_cfg(i.guild_id); c["ignored_channels"] = ids
        await db.set_level_cfg(i.guild_id, c); await show_ignore(i, back)

    async def save_roles(i, ids):
        c = await db.get_level_cfg(i.guild_id); c["ignored_roles"] = ids
        await db.set_level_cfg(i.guild_id, c); await show_ignore(i, back)

    async def back_here(i): await show_ignore(i, back)

    async def pick_ch(i):
        await show_id_picker(i, "channel", cfg["ignored_channels"], save_channels, back_here, "📺 القنوات المستثناة")

    async def pick_ro(i):
        await show_id_picker(i, "role", cfg["ignored_roles"], save_roles, back_here, "👥 الرتب المستثناة")

    async def home(i): await show_levels_home(i, back)
    view.add_btn("القنوات", pick_ch, discord.ButtonStyle.primary, row=0, emoji="📺")
    view.add_btn("الرتب", pick_ro, discord.ButtonStyle.primary, row=0, emoji="👥")
    view.add_back(home, row=1)
    await show(interaction, emb, view)


# ═══════════════════════════ المضاعفات ═══════════════════════════
async def show_mults(interaction: discord.Interaction, back):
    cfg = await db.get_level_cfg(interaction.guild_id)
    lines = []
    for m in cfg["multipliers"]:
        role = interaction.guild.get_role(m["role_id"])
        lines.append(f"✖️ {role.mention if role else '`محذوفة`'} ← **×{m['mult']:g}**")
    emb = discord.Embed(title="✖️ مضاعفات الخبرة", color=discord.Color.purple(),
                        description=("أصحاب هذي الرتب يكسبون خبرة أكثر (مثلاً البوستر ×1.5). "
                                     "لو العضو عنده أكثر من رتبة تنطبق أعلى مضاعف.\n\n"
                                     + ("\n".join(lines) if lines else "لا توجد مضاعفات.")))
    await show(interaction, emb, MultsView(cfg, interaction.guild, back))


class MultModal(ModalBase, title="مضاعف الخبرة"):
    def __init__(self, role: discord.Role, back):
        super().__init__()
        self.role, self.back = role, back
        self.mult = discord.ui.TextInput(label=f"المضاعف لـ «{role.name[:40]}» (مثال 1.5)", max_length=5, placeholder="1.5")
        self.add_item(self.mult)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            v = float(self.mult.value.strip().replace(",", "."))
            if not 0.1 <= v <= 10:
                raise ValueError
        except ValueError:
            return await reply(interaction, "❌ اكتب رقم بين 0.1 و 10.", ephemeral=True)
        c = await db.get_level_cfg(interaction.guild_id)
        c["multipliers"] = [m for m in c["multipliers"] if m["role_id"] != self.role.id][:24]
        c["multipliers"].append({"role_id": self.role.id, "mult": round(v, 2)})
        await db.set_level_cfg(interaction.guild_id, c)
        await show_mults(interaction, self.back)


class _MultRole(discord.ui.RoleSelect):
    def __init__(self, back):
        super().__init__(placeholder="➕ اختر رتبة لإضافة مضاعف لها...", min_values=1, max_values=1, row=0)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(MultModal(self.values[0], self.back))


class _MultDelete(discord.ui.Select):
    def __init__(self, cfg, guild, back):
        opts = []
        for m in cfg["multipliers"][:25]:
            role = guild.get_role(m["role_id"])
            opts.append(discord.SelectOption(label=f"{(role.name if role else 'محذوفة')[:70]} ×{m['mult']:g}",
                                             value=str(m["role_id"]), emoji="🗑️"))
        super().__init__(placeholder="🗑️ اختر مضاعف لحذفه...", options=opts, row=1)
        self.back = back

    async def callback(self, interaction: discord.Interaction):
        c = await db.get_level_cfg(interaction.guild_id)
        c["multipliers"] = [m for m in c["multipliers"] if str(m["role_id"]) != self.values[0]]
        await db.set_level_cfg(interaction.guild_id, c)
        await show_mults(interaction, self.back)


class MultsView(NavView):
    def __init__(self, cfg, guild, back):
        super().__init__()
        self.add_item(_MultRole(back))
        if cfg["multipliers"]:
            self.add_item(_MultDelete(cfg, guild, back))

        async def home(i): await show_levels_home(i, back)
        self.add_back(home, row=2)


# ═══════════════════════════ شكل /rank ═══════════════════════════
async def show_rank_style(interaction: discord.Interaction, back):
    cfg = await db.get_level_cfg(interaction.guild_id)
    emb = discord.Embed(title="🎨 شكل أمر /rank", color=parse_hex(cfg["rank_color"]) or 0xF1C40F,
                        description="غيّر لون وشكل شريط التقدم اللي يظهر للأعضاء في `/rank` و `/profile`.")
    emb.add_field(name="اللون", value=f"`{cfg['rank_color']}`", inline=True)
    emb.add_field(name="شكل الشريط", value=BAR_STYLES.get(cfg["bar"], BAR_STYLES["blocks"])[2], inline=True)
    view = NavView()

    class BarSelect(discord.ui.Select):
        def __init__(self):
            opts = [discord.SelectOption(label=v[2], value=k, default=(k == cfg["bar"])) for k, v in BAR_STYLES.items()]
            super().__init__(placeholder="📊 اختر شكل شريط التقدم...", options=opts, row=0)

        async def callback(self, i: discord.Interaction):
            c = await db.get_level_cfg(i.guild_id); c["bar"] = self.values[0]
            await db.set_level_cfg(i.guild_id, c); await show_rank_style(i, back)

    view.add_item(BarSelect())

    async def color(i):
        await i.response.send_modal(RankColorModal(cfg["rank_color"], back))

    async def preview(i):
        try:
            from cogs.leveling import build_rank_embed
        except ImportError:
            from leveling import build_rank_embed
        e = await build_rank_embed(i.guild, i.user)
        await reply(i, embed=e, ephemeral=True)

    async def home(i): await show_levels_home(i, back)
    view.add_btn("تغيير اللون", color, discord.ButtonStyle.primary, row=1, emoji="🎨")
    view.add_btn("معاينة /rank", preview, discord.ButtonStyle.success, row=1, emoji="👁️")
    view.add_back(home, row=1)
    await show(interaction, emb, view)


class RankColorModal(ModalBase, title="لون /rank"):
    def __init__(self, cur, back):
        super().__init__()
        self.back = back
        self.c = discord.ui.TextInput(label="اللون (Hex)", max_length=7, default=cur, placeholder="#F1C40F")
        self.add_item(self.c)

    async def on_submit(self, interaction: discord.Interaction):
        v = self.c.value.strip()
        if parse_hex(v) is None:
            return await reply(interaction, "❌ اللون لازم يكون Hex مثل `#F1C40F`.", ephemeral=True)
        c = await db.get_level_cfg(interaction.guild_id)
        c["rank_color"] = "#" + v.lstrip("#")
        await db.set_level_cfg(interaction.guild_id, c)
        await show_rank_style(interaction, self.back)


async def setup(bot):
    """ملف واجهة فقط، لا يضيف أوامر."""
    pass
