import re
import time
import discord
from discord.ext import commands
from database import db, check_and_grant_level_roles

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        st = await db.get_guild_settings(member.guild.id)
        if not st:
            return

        # Auto Role
        auto_role_id = st['auto_role_id']
        if auto_role_id:
            role = member.guild.get_role(auto_role_id)
            if role:
                try:
                    await member.add_roles(role)
                except Exception:
                    pass

        # Welcome Message
        welcome_channel_id = st['welcome_channel_id']
        if welcome_channel_id:
            chan = member.guild.get_channel(welcome_channel_id)
            if chan:
                welcome_text = st['welcome_msg'] or "مرحباً بك {user} في سيرفر {server}!"
                msg = welcome_text.replace("{user}", member.mention).replace("{server}", member.guild.name)
                embed = discord.Embed(title="👋 عضو جديد ينضم إلينا!", description=msg, color=discord.Color.green())
                embed.set_thumbnail(url=member.display_avatar.url)
                await chan.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        st = await db.get_guild_settings(member.guild.id)
        if not st:
            return

        # Leave Message
        leave_channel_id = st['leave_channel_id']
        if leave_channel_id:
            chan = member.guild.get_channel(leave_channel_id)
            if chan:
                leave_text = st['leave_msg'] or "وداعاً {user}!"
                msg = leave_text.replace("{user}", member.display_name).replace("{server}", member.guild.name)
                embed = discord.Embed(title="🚪 عضو غادر السيرفر", description=msg, color=discord.Color.red())
                await chan.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        g_id = message.guild.id
        st = await db.get_guild_settings(g_id)
        if not st:
            return

        # Custom Command Aliases
        content = message.content.strip()
        words = content.split(" ")
        if words:
            first_word = words[0]
            mapped_cmd = await db.get_command_for_alias(g_id, first_word)
            if mapped_cmd:
                args = " ".join(words[1:])
                prefix = self.bot.command_prefix if isinstance(self.bot.command_prefix, str) else "!"
                message.content = f"{prefix}{mapped_cmd} {args}".strip()
                await self.bot.process_commands(message)
                return

        # Anti Links
        if st['anti_links'] and re.search(r"http[s]?://", message.content):
            if not message.author.guild_permissions.administrator:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await message.channel.send(f"⚠️ {message.author.mention} يمنع نشر الروابط الخارجية هنا!", delete_after=5)
                return

        # Anti Invites
        if st['anti_invites'] and re.search(r"(discord\.gg|discord\.com/invite)", message.content):
            if not message.author.guild_permissions.administrator:
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await message.channel.send(f"⚠️ {message.author.mention} يمنع نشر روابط سيرفرات الديسكورد!", delete_after=5)
                return

        # AutoMod Badwords
        if st['automod_enabled'] and st['automod_badwords']:
            bad_words = [w.strip().lower() for w in st['automod_badwords'].split(",") if w.strip()]
            if any(word in message.content.lower() for word in bad_words):
                try:
                    await message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass
                await message.channel.send(f"⚠️ {message.author.mention} تم حذف رسالتك لاحتوائها على كلمات ممنوعة!", delete_after=5)
                return

        # Auto Responses
        responses = await db.get_auto_responses(g_id)
        for row in responses:
            trig, resp = row['trigger_text'], row['response_text']
            if trig.lower() in message.content.lower():
                await message.channel.send(resp)
                break

        # XP and Leveling System
        if st['text_xp_enabled']:
            u_data = await db.get_user_data(g_id, message.author.id)

            for attachment in message.attachments:
                if attachment.content_type:
                    if attachment.content_type.startswith('image/'):
                        await db.log_activity(g_id, message.author.id, 'image_count', 1)
                    elif attachment.content_type.startswith('video/'):
                        await db.log_activity(g_id, message.author.id, 'video_count', 1)
                        await db.log_activity(g_id, message.author.id, 'video_duration', 1)

            last_xp_time = u_data['last_msg_timestamp'] if u_data else 0
            if time.time() - last_xp_time >= 60:
                t_rate = st['text_xp_rate'] or 15
                leveled_up, new_lvl = await db.add_text_xp(g_id, message.author.id, t_rate)
                await db.log_activity(g_id, message.author.id, 'text_xp', t_rate)

                if leveled_up:
                    await check_and_grant_level_roles(message.guild, message.author, new_lvl)
                    lvl_c_id = st['level_up_channel_id']
                    target_c = message.guild.get_channel(lvl_c_id) if lvl_c_id else message.channel
                    if target_c:
                        await target_c.send(f"🎉 مبروك {message.author.mention}! ارتفع مستواك الكتابي إلى **المستوى {new_lvl}**!")

async def setup(bot):
    await bot.add_cog(Events(bot))
