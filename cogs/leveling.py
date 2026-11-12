import random
import time
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from database import (db, reply, edit_reply, build_message, level_from_xp, xp_for_level, level_progress,
                      create_progress_bar, check_and_grant_level_roles, parse_hex)

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


# ═══════════════════════════ أدوات مشتركة ═══════════════════════════
def is_ignored(channel, member: discord.Member, cfg: dict) -> bool:
    """هل القناة/العضو مستثنى من الخبرة؟"""
    ids = set(cfg.get("ignored_channels") or [])
    if ids and channel is not None:
        if (channel.id in ids or getattr(channel, "category_id", None) in ids
                or getattr(channel, "parent_id", None) in ids):
            return True
    roles = set(cfg.get("ignored_roles") or [])
    return bool(roles and any(r.id in roles for r in member.roles))


def role_multiplier(member: discord.Member, cfg: dict) -> float:
    have = {r.id for r in member.roles}
    return max([float(m["mult"]) for m in cfg.get("multipliers", []) if m["role_id"] in have], default=1.0)


def fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    if h >= 24:
        return f"{h // 24} يوم {h % 24} ساعة"
    return f"{h} ساعة {m} دقيقة" if h else f"{m} دقيقة"


async def build_rank_embed(guild: discord.Guild, member: discord.Member) -> discord.Embed:
    cfg = await db.get_level_cfg(guild.id)
    data = await db.get_user_data(guild.id, member.id)
    base = cfg["base_xp"]
    text_xp, voice_xp = data["text_xp"], data["voice_xp"]
    total = text_xp + voice_xp
    lvl, into, need = level_progress(total, base)
    rank, rank_total = await db.get_user_rank(guild.id, member.id)
    pct = int(into / need * 100) if need else 100
    bar = create_progress_bar(into, need, 14, cfg["bar"])

    embed = discord.Embed(color=parse_hex(cfg["rank_color"]) or 0xF1C40F)
    embed.set_author(name=f"{member.display_name} • بطاقة المستوى", icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.description = (
        f"{MEDALS.get(rank, '🏅')} **المركز #{rank}** من أصل `{rank_total}`\n"
        f"⭐ **اللفل الأساسي: {lvl}**\n\n"
        f"{bar} **{pct}%**\n"
        f"`{into:,} / {need:,}` XP للوصول للمستوى **{lvl + 1}**"
    )
    embed.add_field(name="💬 اللفل الكتابي", value=f"المستوى `{level_from_xp(text_xp, base)}`\n`{text_xp:,}` XP", inline=True)
    embed.add_field(name="🎤 اللفل الصوتي",
                    value=f"المستوى `{level_from_xp(voice_xp, base)}`\n`{voice_xp:,}` XP\n⏱️ {fmt_duration(data['voice_time_seconds'])}",
                    inline=True)
    embed.add_field(name="✨ إجمالي الخبرة", value=f"`{total:,}` XP", inline=True)

    rewards = [r for r in await db.get_level_rewards(guild.id) if r["level"] > lvl]
    if rewards:
        nxt = rewards[0]
        role = guild.get_role(nxt["role_id"])
        left = max(0, xp_for_level(nxt["level"], base) - total)
        embed.add_field(name="🎖️ رتبة التفاعل القادمة",
                        value=f"{role.mention if role else 'رتبة'} عند المستوى `{nxt['level']}` (باقي `{left:,}` XP)", inline=False)
    embed.set_footer(text=f"{guild.name} • اللفل الأساسي = الكتابي + الصوتي")
    return embed


# ═══════════════════════════ واجهة /rank ═══════════════════════════
class RankTimeframeSelect(discord.ui.Select):
    def __init__(self, target: discord.Member):
        self.target = target
        options = [
            discord.SelectOption(label="اليوم", value="today", emoji="📅"),
            discord.SelectOption(label="هذا الأسبوع", value="week", emoji="📆"),
            discord.SelectOption(label="هذا الشهر", value="month", emoji="🗓️"),
            discord.SelectOption(label="هذه السنة", value="year", emoji="🌎"),
            discord.SelectOption(label="الكلي (كل الأوقات)", value="all", emoji="♾️"),
        ]
        super().__init__(placeholder="اختر الفترة الزمنية لعرض التفاصيل...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        timeframe = self.values[0]
        cfg = await db.get_level_cfg(interaction.guild_id)
        base = cfg["base_xp"]
        stats = await db.get_timeframe_stats(interaction.guild_id, self.target.id, timeframe)
        if timeframe == "all":
            data = await db.get_user_data(interaction.guild_id, self.target.id)
            stats["text_xp"], stats["voice_xp"] = data["text_xp"], data["voice_xp"]
        text_xp, voice_xp = stats["text_xp"], stats["voice_xp"]
        total = text_xp + voice_xp
        names = {"today": "اليوم", "week": "هذا الأسبوع", "month": "هذا الشهر", "year": "هذه السنة", "all": "الكلي"}

        embed = discord.Embed(title=f"📊 إحصائيات {self.target.display_name} — {names[timeframe]}",
                              color=parse_hex(cfg["rank_color"]) or 0x3498DB)
        embed.set_thumbnail(url=self.target.display_avatar.url)
        embed.add_field(name="⭐ اللفل الأساسي", value=f"المستوى `{level_from_xp(total, base)}`\n`{total:,}` XP", inline=False)
        embed.add_field(name="💬 الكتابي", value=f"المستوى `{level_from_xp(text_xp, base)}`\n`{text_xp:,}` XP", inline=True)
        embed.add_field(name="🎤 الصوتي", value=f"المستوى `{level_from_xp(voice_xp, base)}`\n`{voice_xp:,}` XP", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        embed.add_field(name="💬 الرسائل", value=f"`{stats.get('message_count', 0):,}`", inline=True)
        embed.add_field(name="🖼️ الصور", value=f"`{stats.get('image_count', 0):,}`", inline=True)
        embed.add_field(name="🎥 الفيديوهات", value=f"`{stats.get('video_count', 0):,}`", inline=True)
        await edit_reply(interaction, content=None, embed=embed, view=RankInfoView(self.target, interaction.user.id))


class RankInfoView(discord.ui.View):
    def __init__(self, target: discord.Member, author_id: int):
        super().__init__(timeout=180)
        self.target, self.author_id = target, author_id
        self.add_item(RankTimeframeSelect(target))

    @discord.ui.button(label="رجوع للبطاقة", style=discord.ButtonStyle.secondary, emoji="⬅️", row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await build_rank_embed(interaction.guild, self.target)
        await edit_reply(interaction, content=None, embed=embed, view=RankMainView(self.target, self.author_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply(interaction, "❌ هذه القائمة ليست لك!", ephemeral=True)
            return False
        return True


class RankMainView(discord.ui.View):
    def __init__(self, target: discord.Member, author_id: int):
        super().__init__(timeout=180)
        self.target, self.author_id = target, author_id

    @discord.ui.button(label="المعلومات التفصيلية", style=discord.ButtonStyle.secondary, emoji="📊")
    async def show_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await edit_reply(interaction, view=RankInfoView(self.target, self.author_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply(interaction, "❌ أنت لست صاحب الطلب!", ephemeral=True)
            return False
        return True


# ═══════════════════════════ واجهة /top ═══════════════════════════
TOP_CATS = {"main": "⭐ اللفل الأساسي", "text": "💬 الكتابي", "voice": "🎤 الصوتي", "credits": "💳 الكريدت"}
PAGE_SIZE = 10


async def build_top_embed(guild: discord.Guild, cat: str, page: int):
    cfg = await db.get_level_cfg(guild.id)
    base = cfg["base_xp"]
    total = await db.count_top_credits(guild.id) if cat == "credits" else await db.count_top_levels(guild.id, cat)
    pages = max(1, -(-total // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    offset = page * PAGE_SIZE

    lines = []
    if cat == "credits":
        rows = await db.get_top_credits(guild.id, PAGE_SIZE, offset)
        for n, r in enumerate(rows, offset + 1):
            lines.append(f"{MEDALS.get(n, f'`#{n}`')} <@{r['user_id']}> — **${r['credits']:,}**")
    else:
        rows = await db.get_top_levels(guild.id, PAGE_SIZE, offset, cat)
        for n, r in enumerate(rows, offset + 1):
            xp = {"main": r["text_xp"] + r["voice_xp"], "text": r["text_xp"], "voice": r["voice_xp"]}[cat]
            lines.append(f"{MEDALS.get(n, f'`#{n}`')} <@{r['user_id']}> — مستوى `{level_from_xp(xp, base)}` • `{xp:,}` XP")

    embed = discord.Embed(title=f"🏆 المتصدرين — {TOP_CATS[cat]}", description="\n".join(lines) or "لا توجد بيانات بعد.",
                          color=parse_hex(cfg["rank_color"]) or 0xF1C40F)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"صفحة {page + 1} / {pages} • {guild.name}")
    return embed, page, pages


class TopView(discord.ui.View):
    def __init__(self, guild: discord.Guild, author_id: int, cat: str, page: int, pages: int):
        super().__init__(timeout=180)
        self.guild, self.author_id, self.cat, self.page, self.pages = guild, author_id, cat, page, pages

        sel = discord.ui.Select(placeholder="اختر التصنيف...", row=0,
                                options=[discord.SelectOption(label=v, value=k, default=(k == cat)) for k, v in TOP_CATS.items()])

        async def on_cat(i: discord.Interaction):
            await self.render(i, sel.values[0], 0)
        sel.callback = on_cat
        self.add_item(sel)

        prev_b = discord.ui.Button(label="السابق", emoji="◀️", style=discord.ButtonStyle.secondary, row=1, disabled=page <= 0)
        next_b = discord.ui.Button(label="التالي", emoji="▶️", style=discord.ButtonStyle.secondary, row=1, disabled=page >= pages - 1)

        async def on_prev(i: discord.Interaction):
            await self.render(i, self.cat, self.page - 1)

        async def on_next(i: discord.Interaction):
            await self.render(i, self.cat, self.page + 1)
        prev_b.callback, next_b.callback = on_prev, on_next
        self.add_item(prev_b)
        self.add_item(next_b)

    async def render(self, interaction: discord.Interaction, cat: str, page: int):
        embed, page, pages = await build_top_embed(self.guild, cat, page)
        await edit_reply(interaction, content=None, embed=embed, view=TopView(self.guild, self.author_id, cat, page, pages))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await reply(interaction, "❌ هذه القائمة ليست لك! اكتب /top لفتح قائمتك.", ephemeral=True)
            return False
        return True


# ═══════════════════════════ الكوج ═══════════════════════════
class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._xp_last = {}
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    # ───────────── تنبيه ارتفاع اللفل (اللفل الأساسي فقط) ─────────────
    async def on_level_up(self, guild: discord.Guild, member: discord.Member, new_lvl: int, old_lvl: int,
                          hint_channel, st: dict, cfg: dict):
        added = await check_and_grant_level_roles(guild, member, new_lvl)
        ann = cfg["announce"]
        if not ann["enabled"]:
            return
        data = await db.get_user_data(guild.id, member.id)
        variables = {
            "user": member.mention, "name": member.display_name, "level": new_lvl, "old_level": old_lvl,
            "xp": f"{data['text_xp'] + data['voice_xp']:,}", "server": guild.name,
            "reward": "، ".join(r.name for r in added) if added else "—",
        }
        msg = ann["msg"]
        prefix = member.mention if (ann["ping"] and msg.get("as_embed")) else None
        kw = build_message(msg, variables, member=member, guild=guild, content_prefix=prefix)
        if ann["delete_after"] and ann["delete_after"] > 0:
            kw["delete_after"] = int(ann["delete_after"])
        allowed = discord.AllowedMentions(users=bool(ann["ping"]), roles=False, everyone=False)

        if ann["dest"] == "dm":
            try:
                await member.send(**kw)
            except (discord.Forbidden, discord.HTTPException):
                pass
            return

        lvl_ch = guild.get_channel(st["level_up_channel_id"]) if st["level_up_channel_id"] else None
        target = (hint_channel or lvl_ch) if ann["dest"] == "current" else (lvl_ch or hint_channel)
        if target is None or not target.permissions_for(guild.me).send_messages:
            return
        try:
            await target.send(allowed_mentions=allowed, **kw)
        except discord.HTTPException:
            pass

    # ───────────── خبرة الكتابة ─────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        gid, uid = message.guild.id, message.author.id
        st = await db.get_guild_settings(gid)
        if not st["text_xp_enabled"]:
            return
        cfg = await db.get_level_cfg(gid)
        if is_ignored(message.channel, message.author, cfg):
            return

        now = time.time()
        key = (gid, uid)
        if len(self._xp_last) > 20000:
            self._xp_last = {k: v for k, v in self._xp_last.items() if now - v < 3600}
        if now - self._xp_last.get(key, 0) < cfg["cooldown"]:
            return

        lo = st["text_xp_rate"] if st["text_xp_rate"] is not None else 15
        hi = cfg["text_xp_max"]
        amount = random.randint(lo, hi) if hi > lo else lo
        amount = int(round(amount * role_multiplier(message.author, cfg)))
        if amount <= 0:
            return
        self._xp_last[key] = now

        leveled, new_lvl, old_lvl = await db.add_text_xp(gid, uid, amount, cfg["base_xp"])
        await db.log_activity(gid, uid, "text_xp", amount)
        if leveled:
            await self.on_level_up(message.guild, message.author, new_lvl, old_lvl, message.channel, st, cfg)

    # ───────────── خبرة الصوت ─────────────
    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        for guild in self.bot.guilds:
            try:
                st = await db.get_guild_settings(guild.id)
                if not st or not st["voice_xp_enabled"]:
                    continue
                v_rate = st["voice_xp_rate"] if st["voice_xp_rate"] is not None else 10
                if v_rate <= 0:
                    continue
                cfg = await db.get_level_cfg(guild.id)
                for channel in guild.voice_channels:
                    if channel == guild.afk_channel:
                        continue
                    humans = [m for m in channel.members if not m.bot]
                    if cfg["voice_require_others"] and len(humans) < 2:
                        continue
                    for member in humans:
                        vs = member.voice
                        if not vs or vs.self_deaf or vs.deaf:
                            continue
                        if (vs.self_mute or vs.mute) and not cfg["voice_count_muted"]:
                            continue
                        if is_ignored(channel, member, cfg):
                            continue
                        try:
                            amount = int(round(v_rate * role_multiplier(member, cfg)))
                            if amount <= 0:
                                continue
                            leveled, new_lvl, old_lvl = await db.add_voice_xp(guild.id, member.id, amount, 60, cfg["base_xp"])
                            await db.log_activity(guild.id, member.id, "voice_xp", amount)
                            if leveled:
                                await self.on_level_up(guild, member, new_lvl, old_lvl, None, st, cfg)
                        except Exception as e:
                            print(f"⚠️ خطأ في خبرة الصوت للعضو {member.id}: {e}")
            except Exception as e:
                print(f"⚠️ خطأ في حلقة الخبرة الصوتية للسيرفر {guild.id}: {e}")

    @voice_xp_loop.before_loop
    async def _before_voice_xp_loop(self):
        await self.bot.wait_until_ready()

    # ───────────── الأوامر ─────────────
    @app_commands.command(name="rank", description="بطاقة مستواك: اللفل الأساسي والكتابي والصوتي والمركز")
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        if target.bot:
            return await reply(interaction, "❌ البوتات ما عندها مستوى!", ephemeral=True)
        embed = await build_rank_embed(interaction.guild, target)
        await reply(interaction, embed=embed, view=RankMainView(target, interaction.user.id))

    @app_commands.command(name="top", description="قائمة المتصدرين (اللفل الأساسي / الكتابي / الصوتي / الكريدت)")
    @app_commands.guild_only()
    async def top(self, interaction: discord.Interaction,
                  category: Literal["اللفل الأساسي", "الكتابي", "الصوتي", "الكريدت"] = "اللفل الأساسي"):
        cat = {"اللفل الأساسي": "main", "الكتابي": "text", "الصوتي": "voice", "الكريدت": "credits"}[category]
        embed, page, pages = await build_top_embed(interaction.guild, cat, 0)
        await reply(interaction, embed=embed, view=TopView(interaction.guild, interaction.user.id, cat, page, pages))

    # ───────────── إدارة الخبرة (للإداريين) ─────────────
    xp_group = app_commands.Group(name="xp", description="إدارة خبرة الأعضاء (للإدارة)", guild_only=True,
                                  default_permissions=discord.Permissions(administrator=True))

    async def _apply(self, interaction, member, kind, amount, mode):
        cfg = await db.get_level_cfg(interaction.guild_id)
        base = cfg["base_xp"]
        if mode == "set":
            new = await db.set_user_xp(interaction.guild_id, member.id,
                                       text_xp=amount if kind == "كتابي" else None,
                                       voice_xp=amount if kind == "صوتي" else None, base=base)
        else:
            delta = amount if mode == "add" else -amount
            if kind == "كتابي":
                _, new, _ = await db.add_text_xp(interaction.guild_id, member.id, delta, base)
            else:
                _, new, _ = await db.add_voice_xp(interaction.guild_id, member.id, delta, 0, base)
        await check_and_grant_level_roles(interaction.guild, member, new)
        return new

    @xp_group.command(name="add", description="إضافة خبرة لعضو")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_add(self, interaction: discord.Interaction, member: discord.Member,
                     amount: app_commands.Range[int, 1, 10_000_000], kind: Literal["كتابي", "صوتي"] = "كتابي"):
        new = await self._apply(interaction, member, kind, amount, "add")
        await reply(interaction, f"✅ أضفت `{amount:,}` XP ({kind}) لـ {member.mention} — لفله الأساسي الحين **{new}**")

    @xp_group.command(name="remove", description="سحب خبرة من عضو")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_remove(self, interaction: discord.Interaction, member: discord.Member,
                        amount: app_commands.Range[int, 1, 10_000_000], kind: Literal["كتابي", "صوتي"] = "كتابي"):
        new = await self._apply(interaction, member, kind, amount, "remove")
        await reply(interaction, f"✅ سحبت `{amount:,}` XP ({kind}) من {member.mention} — لفله الأساسي الحين **{new}**")

    @xp_group.command(name="set", description="تحديد خبرة عضو بقيمة معينة")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_set(self, interaction: discord.Interaction, member: discord.Member,
                     amount: app_commands.Range[int, 0, 100_000_000], kind: Literal["كتابي", "صوتي"] = "كتابي"):
        new = await self._apply(interaction, member, kind, amount, "set")
        await reply(interaction, f"✅ خبرة {member.mention} ({kind}) صارت `{amount:,}` XP — لفله الأساسي **{new}**")

    @xp_group.command(name="reset", description="تصفير كل خبرة ولفل عضو")
    @app_commands.checks.has_permissions(administrator=True)
    async def xp_reset(self, interaction: discord.Interaction, member: discord.Member):
        await db.set_user_xp(interaction.guild_id, member.id, text_xp=0, voice_xp=0)
        await reply(interaction, f"🧹 تم تصفير مستوى {member.mention}.")


async def setup(bot):
    await bot.add_cog(Leveling(bot))
