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
        st = db.get_guild_settings(member.guild.id)
        if st[6]:
            role = member.guild.get_role(st[6])
            if role:
                try:
                    await member.add_roles(role)
                except Exception:
                    pass
        if st[2]:
            chan = member.guild.get_channel(st[2])
            if chan:
                msg = st[3].replace("{user}", member.mention).replace("{server}", member.guild.name)
                embed = discord.Embed(title="👋 عضو جديد ينضم إلينا!", description=msg, color=discord.Color.green())
                embed.set_thumbnail(url=member.display_avatar.url)
                await chan.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        st = db.get_guild_settings(member.guild.id)
        if st[4]:
            chan = member.guild.get_channel(st[4])
            if chan:
                msg = st[5].replace("{user}", member.display_name).replace("{server}", member.guild.name)
                embed = discord.Embed(title="🚪 عضو غادر السيرفر", description=msg, color=discord.Color.red())
                await chan.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        g_id = message.guild.id
        st = db.get_guild_settings(g_id)

        content = message.content.strip()
        words = content.split(" ")
        if words:
            first_word = words[0]
            mapped_cmd = db.get_command_for_alias(g_id, first_word)
            if mapped_cmd:
                args = " ".join(words[1:])
                message.content = f"{self.bot.command_prefix}{mapped_cmd} {args}".strip()
                await self.bot.process_commands(message)
                return

        if st[17] and re.search(r"http[s]?://", message.content):
            if not message.author.guild_permissions.administrator:
                await message.delete()
                await message.channel.send(f"⚠️ {message.author.mention} يمنع نشر الروابط الخارجية هنا!", delete_after=5)
                return

        if st[18] and re.search(r"(discord\.gg|discord\.com/invite)", message.content):
            if not message.author.guild_permissions.administrator:
                await message.delete()
                await message.channel.send(f"⚠️ {message.author.mention} يمنع نشر روابط سيرفرات الديسكورد!", delete_after=5)
                return

        if st[15] and st[16]:
            bad_words = [w.strip().lower() for w in st[16].split(",") if w.strip()]
            if any(word in message.content.lower() for word in bad_words):
                await message.delete()
                await message.channel.send(f"⚠️ {message.author.mention} تم حذف رسالتك لاحتوائها على كلمات ممنوعة!", delete_after=5)
                return

        responses = db.get_auto_responses(g_id)
        for trig, resp in responses:
            if trig in message.content.lower():
                await message.channel.send(resp)
                break

        if st[10]:
            u_data = db.get_user_data(g_id, message.author.id)
            
            for attachment in message.attachments:
                if attachment.content_type:
                    if attachment.content_type.startswith('image/'):
                        db.log_activity(g_id, message.author.id, 'image_count', 1)
                    elif attachment.content_type.startswith('video/'):
                        db.log_activity(g_id, message.author.id, 'video_count', 1)
                        db.log_activity(g_id, message.author.id, 'video_duration', 1)

            if time.time() - u_data[7] >= 60:
                t_rate = st[12]
                leveled_up, new_lvl = db.add_text_xp(g_id, message.author.id, t_rate)
                db.log_activity(g_id, message.author.id, 'text_xp', t_rate)
                
                if leveled_up:
                    await check_and_grant_level_roles(message.guild, message.author, new_lvl)
                    lvl_c_id = st[14]
                    target_c = message.guild.get_channel(lvl_c_id) or message.channel
                    await target_c.send(f"🎉 مبروك {message.author.mention}! ارتفع مستواك الكتابي إلى **المستوى {new_lvl}** 💬!")

        await self.bot.process_commands(message)

async def setup(bot):
    await bot.add_cog(Events(bot))
