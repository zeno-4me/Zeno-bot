"""
منطق الترحيب والمغادرة والرتبة التلقائية.
الأولوية: ✨ رسالة نادرة ← 📅 مناسبة نشطة ← 🎭 رسالة الرتبة ← 📝 الافتراضية
"""
import asyncio
import random

import discord
from discord.ext import commands

from database import db, build_message, fmt_vars, event_is_active

try:
    from cogs.dash_welcome import welcome_vars
except ImportError:
    from dash_welcome import welcome_vars

NO_PINGS = discord.AllowedMentions(users=True, roles=False, everyone=False)


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._tasks = set()

    # ───────────── اختيار الرسالة المناسبة ─────────────
    def pick_message(self, cfg: dict, member: discord.Member, gained_ids=None):
        """يرجع (قاموس الرسالة, النوع, متغيرات إضافية)."""
        rare = cfg["rare"]
        if rare["enabled"] and rare["messages"] and rare["chance"] > 0:
            if random.random() * 100 < float(rare["chance"]):
                return random.choice(rare["messages"]), "rare", {}

        for ev in cfg["events"]:
            if event_is_active(ev, cfg["tz_offset"]):
                return ev["msg"], "event", {"event": ev["name"]}

        have = set(gained_ids) if gained_ids else {r.id for r in member.roles}
        for entry in cfg["roles"]:
            if entry["role_id"] in have:
                role = member.guild.get_role(entry["role_id"])
                return entry["msg"], "role", {"role": role.name if role else ""}

        return cfg["default"], "default", {}

    async def send_welcome(self, member: discord.Member, gained_ids=None):
        guild = member.guild
        st = await db.get_guild_settings(guild.id)
        cfg = await db.get_welcome_cfg(guild.id)
        if not cfg["enabled"]:
            return
        channel = guild.get_channel(st['welcome_channel_id']) if st['welcome_channel_id'] else None
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        perms = channel.permissions_for(guild.me)
        if not perms.send_messages:
            return

        msg, _kind, extra = self.pick_message(cfg, member, gained_ids)
        variables = welcome_vars(member, extra)
        prefix = member.mention if (cfg["mention"] and msg.get("as_embed")) else None
        kw = build_message(msg, variables, member=member, guild=guild, content_prefix=prefix)
        if cfg["delete_after"] and cfg["delete_after"] > 0:
            kw["delete_after"] = int(cfg["delete_after"])
        try:
            await channel.send(allowed_mentions=NO_PINGS, **kw)
        except discord.HTTPException as e:
            print(f"⚠️ تعذر إرسال الترحيب في {guild.name}: {e}")

    async def _send_dm(self, member: discord.Member, cfg: dict):
        if not cfg["dm_enabled"] or not cfg["dm_text"]:
            return
        try:
            await member.send(fmt_vars(cfg["dm_text"], welcome_vars(member))[:2000])
        except (discord.Forbidden, discord.HTTPException):
            pass

    async def _fallback(self, member: discord.Member, minutes: int):
        try:
            await asyncio.sleep(minutes * 60)
            guild = member.guild
            if guild.get_member(member.id) is None:
                return
            if await db.mark_welcomed(guild.id, member.id):
                await self.send_welcome(guild.get_member(member.id))
        except Exception as e:
            print(f"⚠️ خطأ في الترحيب الاحتياطي: {e}")

    # ───────────── الأحداث ─────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        st = await db.get_guild_settings(guild.id)

        if st['auto_role_id']:
            role = guild.get_role(st['auto_role_id'])
            if role:
                try:
                    await member.add_roles(role, reason="Auto Role")
                except Exception:
                    pass

        cfg = await db.get_welcome_cfg(guild.id)
        if not cfg["enabled"]:
            return
        await self._send_dm(member, cfg)

        if cfg["trigger"] == "join":
            await self.send_welcome(member)
        else:
            # وضع الرتبة: نرحب لما ياخذ رتبة. لو ما أخذ بعد المدة المحددة نرسل الافتراضية.
            if cfg["fallback_minutes"] > 0:
                t = asyncio.create_task(self._fallback(member, cfg["fallback_minutes"]))
                self._tasks.add(t)
                t.add_done_callback(self._tasks.discard)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot or before.roles == after.roles:
            return
        gained = {r.id for r in after.roles} - {r.id for r in before.roles}
        if not gained:
            return
        cfg = await db.get_welcome_cfg(after.guild.id)
        if not cfg["enabled"] or cfg["trigger"] != "role":
            return
        wanted = {e["role_id"] for e in cfg["roles"]}
        if not (gained & wanted):
            return
        if await db.mark_welcomed(after.guild.id, after.id):
            await self.send_welcome(after, gained_ids=gained & wanted)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        guild = member.guild
        await db.unmark_welcomed(guild.id, member.id)
        st = await db.get_guild_settings(guild.id)
        cfg = await db.get_welcome_cfg(guild.id)
        if not cfg["leave"]["enabled"] or not st['leave_channel_id']:
            return
        channel = guild.get_channel(st['leave_channel_id'])
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        variables = welcome_vars(member, {"user": member.display_name})
        kw = build_message(cfg["leave"]["msg"], variables, member=member, guild=guild)
        try:
            await channel.send(allowed_mentions=discord.AllowedMentions.none(), **kw)
        except discord.HTTPException:
            pass


async def setup(bot):
    await bot.add_cog(Welcome(bot))
