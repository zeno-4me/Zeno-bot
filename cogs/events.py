import random
import time

import discord
from discord.ext import commands

from database import db, build_message, fmt_vars

NO_PINGS = discord.AllowedMentions.none()


def shortcut_matches(sc: dict, content: str) -> bool:
    trig = (sc.get("trigger") or "").strip().lower()
    if not trig:
        return False
    text = content.strip().lower()
    mode = sc.get("match", "contains")
    if mode == "exact":
        return text == trig
    if mode == "starts":
        return text == trig or text.startswith(trig + " ")
    if mode == "word":
        return trig in text.replace("\n", " ").split()
    return trig in text


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._sc_cd = {}

    async def _automod_hit(self, message: discord.Message, settings: dict, key: str, reason: str):
        """يحذف الرسالة + يرسل تنبيه (حسب تخصيص الإدارة) + يسجل بقناة اللوق."""
        try:
            await message.delete()
        except Exception:
            return False
        kw = await db.auto_kwargs(message.guild.id, key, user=message.author.mention, name=message.author.display_name,
                                  server=message.guild.name, channel=message.channel.mention)
        if kw:
            try:
                await message.channel.send(allowed_mentions=discord.AllowedMentions(users=True), **kw)
            except discord.HTTPException:
                pass
        log_id = settings.get('log_channel_id')
        log_ch = message.guild.get_channel(log_id) if log_id else None
        if log_ch:
            emb = discord.Embed(title="🛡️ إجراء حماية تلقائي", color=discord.Color.orange(),
                                description=f"**العضو:** {message.author.mention}\n**القناة:** {message.channel.mention}\n**السبب:** {reason}")
            emb.add_field(name="الرسالة", value=(message.content or "—")[:900], inline=False)
            try:
                await log_ch.send(embed=emb)
            except discord.HTTPException:
                pass
        return True

    async def _run_shortcuts(self, message: discord.Message):
        g_id = message.guild.id
        for sc in await db.get_shortcuts(g_id):
            if not sc["enabled"] or not sc["responses"] or not shortcut_matches(sc, message.content):
                continue
            ch_ids = set(sc["channels"])
            if sc["channel_mode"] == "include" and ch_ids and message.channel.id not in ch_ids \
                    and getattr(message.channel, "category_id", None) not in ch_ids:
                continue
            if sc["channel_mode"] == "exclude" and (message.channel.id in ch_ids
                                                    or getattr(message.channel, "category_id", None) in ch_ids):
                continue
            role_ids = {r.id for r in message.author.roles}
            if sc["role_mode"] == "include" and sc["roles"] and not (role_ids & set(sc["roles"])):
                continue
            if sc["role_mode"] == "exclude" and (role_ids & set(sc["roles"])):
                continue
            now = time.time()
            if sc["cooldown"] and now - self._sc_cd.get(sc["id"], 0) < sc["cooldown"]:
                continue
            self._sc_cd[sc["id"]] = now

            text = fmt_vars(random.choice(sc["responses"]), {
                "user": message.author.mention, "name": message.author.display_name,
                "server": message.guild.name, "channel": message.channel.mention,
                "count": message.guild.member_count})
            msg = {"as_embed": sc["style"] == "embed", "title": sc["title"], "desc": text,
                   "color": sc["color"], "image": sc["image"], "thumb": "none"}
            kw = build_message(msg, {}, member=message.author, guild=message.guild)
            if sc["delete_after"]:
                kw["delete_after"] = int(sc["delete_after"])
            try:
                if sc["react"]:
                    try:
                        await message.add_reaction(sc["react"])
                    except discord.HTTPException:
                        pass
                if sc["delete_trigger"]:
                    try:
                        await message.delete()
                    except discord.HTTPException:
                        pass
                if sc["reply"] and not sc["delete_trigger"]:
                    await message.reply(mention_author=bool(sc["mention_author"]), allowed_mentions=NO_PINGS, **kw)
                else:
                    await message.channel.send(allowed_mentions=NO_PINGS, **kw)
            except discord.HTTPException:
                pass
            break

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        g_id, u_id = message.guild.id, message.author.id
        settings = await db.get_guild_settings(g_id)

        # 1. الحماية (Automod)
        if settings['automod_enabled'] and not message.author.guild_permissions.manage_messages:
            content_lower = message.content.lower()
            badwords = [w.strip().lower() for w in settings['automod_badwords'].split(',') if w.strip()]
            if any(word in content_lower for word in badwords):
                if await self._automod_hit(message, settings, "automod_badword", "كلمة محظورة"):
                    return
            if settings['anti_links'] and ("http://" in content_lower or "https://" in content_lower):
                if await self._automod_hit(message, settings, "automod_link", "رابط ممنوع"):
                    return
            if settings['anti_invites'] and ("discord.gg/" in content_lower or "discord.com/invite/" in content_lower):
                if await self._automod_hit(message, settings, "automod_invite", "دعوة سيرفر"):
                    return

        # 2. الاختصارات (ردود تلقائية / اختصارات)
        if message.content:
            await self._run_shortcuts(message)

        # 3. إحصائيات النشاط (الخبرة واللفل في leveling.py)
        await db.log_activity(g_id, u_id, "message_count", 1)
        for attachment in message.attachments:
            name = attachment.filename.lower()
            if any(ext in name for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                await db.log_activity(g_id, u_id, "image_count", 1)
            elif any(ext in name for ext in ['.mp4', '.mov', '.mkv', '.avi']):
                await db.log_activity(g_id, u_id, "video_count", 1)


async def setup(bot):
    await bot.add_cog(Events(bot))
