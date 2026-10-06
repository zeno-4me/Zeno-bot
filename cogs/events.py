import discord
from discord.ext import commands
import time
from database import db, check_and_grant_level_roles

class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_times = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        g_id = message.guild.id
        u_id = message.author.id
        settings = await db.get_guild_settings(g_id)

        # 1. نظام الحماية والأوتومود (Automod)
        if settings['automod_enabled']:
            content_lower = message.content.lower()
            badwords = [w.strip().lower() for w in settings['automod_badwords'].split(',') if w.strip()]
            
            # فحص الكلمات المحظورة
            if any(word in content_lower for word in badwords):
                try:
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention} تم حذف رسالتك لاحتوائها على كلمات محظورة.", delete_after=5)
                    return
                except Exception:
                    pass

            # فحص الروابط
            if settings['anti_links'] and ("http://" in content_lower or "https://" in content_lower):
                try:
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention} يمنع إرسال الروابط هنا.", delete_after=5)
                    return
                except Exception:
                    pass

            # فحص دعوات السيرفرات
            if settings['anti_invites'] and ("discord.gg/" in content_lower or "discord.com/invite/" in content_lower):
                try:
                    await message.delete()
                    await message.channel.send(f"⚠️ {message.author.mention} يمنع إرسال دعوات السيرفرات.", delete_after=5)
                    return
                except Exception:
                    pass

        # 2. الردود التلقائية (Auto Responses)
        auto_resps = await db.get_auto_responses(g_id)
        for row in auto_resps:
            if row['trigger_text'].lower() == message.content.strip().lower():
                await message.channel.send(row['response_text'])
                break

        # 3. اختصارات الأوامر (Custom Aliases)
        content = message.content.strip()
        words = content.split(" ")
        if words:
            first_word = words[0]
            mapped_cmd = await db.get_command_for_alias(g_id, first_word)
            if mapped_cmd:
                await message.channel.send(f"💡 هذا اختصار للأمر: `/{mapped_cmd}`")

        # 4. نظام الخبرة واللفلات للرسائل (Text XP)
        if settings['text_xp_enabled']:
            user_data = await db.get_user_data(g_id, u_id)
            now = time.time()
            # كولد داون دقيقة بين كل احتساب خبرة
            if now - user_data['last_msg_timestamp'] >= 60:
                xp_rate = settings['text_xp_rate'] or 15
                leveled_up, new_lvl = await db.add_text_xp(g_id, u_id, xp_rate)
                await db.log_activity(g_id, u_id, "text_xp", xp_rate)

                if leveled_up:
                    await check_and_grant_level_roles(message.guild, message.author, new_lvl)
                    lvl_channel_id = settings['level_up_channel_id']
                    target_channel = message.guild.get_channel(lvl_channel_id) or message.channel
                    try:
                        await target_channel.send(f"مبروك {message.author.mention}! ارتفع مستواك للفل **{new_lvl}**")
                    except Exception:
                        pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot or not member.guild:
            return

        g_id = member.guild.id
        u_id = member.id
        key = (g_id, u_id)
        settings = await db.get_guild_settings(g_id)

        if not settings['voice_xp_enabled']:
            return

        # دخول روم صوتي
        if before.channel is None and after.channel is not None:
            self.voice_times[key] = time.time()

        # خروج من روم صوتي
        elif before.channel is not None and after.channel is None:
            start_time = self.voice_times.pop(key, None)
            if start_time:
                duration = int(time.time() - start_time)
                minutes = duration // 60
                if minutes > 0:
                    xp_rate = settings['voice_xp_rate'] or 10
                    total_xp = minutes * xp_rate
                    leveled_up, new_lvl = await db.add_voice_xp(g_id, u_id, total_xp, duration)
                    await db.log_activity(g_id, u_id, "voice_xp", total_xp)

                    if leveled_up:
                        await check_and_grant_level_roles(member.guild, member, new_lvl)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        g_id = member.guild.id
        settings = await db.get_guild_settings(g_id)

        # إعطاء الرتبة التلقائية
        if settings['auto_role_id']:
            role = member.guild.get_role(settings['auto_role_id'])
            if role:
                try:
                    await member.add_roles(role, reason="Auto Role")
                except Exception:
                    pass

        # إرسال رسالة الترحب
        if settings['welcome_channel_id']:
            channel = member.guild.get_channel(settings['welcome_channel_id'])
            if channel:
                msg = settings['welcome_msg'].replace("{user}", member.mention).replace("{server}", member.guild.name)
                try:
                    await channel.send(msg)
                except Exception:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        g_id = member.guild.id
        settings = await db.get_guild_settings(g_id)

        # إرسال رسالة المغادرة
        if settings['leave_channel_id']:
            channel = member.guild.get_channel(settings['leave_channel_id'])
            if channel:
                msg = settings['leave_msg'].replace("{user}", member.name).replace("{server}", member.guild.name)
                try:
                    await channel.send(msg)
                except Exception:
                    pass

async def setup(bot):
    await bot.add_cog(Events(bot))
