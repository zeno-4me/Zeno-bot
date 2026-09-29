import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from datetime import timedelta
from database import db

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    channel_group = app_commands.Group(name="channel", description="أوامر إدارة القنوات والفئات (Categories)")

    @channel_group.command(name="age", description="تغيير إعدادات الروم أو الكاتيجوري إلى مقيدة عمرياً (Age-Restricted)")
    @app_commands.describe(
        target="الروم أو الكاتيجوري المراد تعديله (اتركه فارغاً لتعديل الروم الحالي)",
        restricted="اختر True لجعلها مقيدة عمرياً (NSFW) أو False لجعلها عادية"
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def channel_age(self, interaction: discord.Interaction, target: Optional[discord.abc.GuildChannel] = None, restricted: bool = True):
        target_channel = target or interaction.channel
        
        try:
            if isinstance(target_channel, discord.CategoryChannel):
                await interaction.response.defer()
                count = 0
                for ch in target_channel.channels:
                    if hasattr(ch, 'edit') and hasattr(ch, 'nsfw'):
                        await ch.edit(nsfw=restricted)
                        count += 1
                
                state_text = "مقيدة عمرياً 🔞 (Age-Restricted)" if restricted else "عادية 🟢"
                await interaction.followup.send(f"✅ تم بنجاح تغيير إعدادات `{count}` رومات داخل الكاتيجوري **{target_channel.name}** لتصبح {state_text}!")
            
            else:
                if not hasattr(target_channel, 'nsfw'):
                    await interaction.response.send_message("❌ هذا النوع من الرومات لا يدعم خاصية التقييد العمري.", ephemeral=True)
                    return
                    
                await target_channel.edit(nsfw=restricted)
                state_text = "مقيدة عمرياً 🔞 (Age-Restricted)" if restricted else "عادية 🟢"
                await interaction.response.send_message(f"✅ تم تغيير إعدادات الروم {target_channel.mention} لتصبح {state_text}!")
                
        except discord.Forbidden:
            msg = "❌ البوت لا يمتلك صلاحيات كافية لتعديل إعدادات هذه القناة!"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            msg = f"❌ حدث خطأ غير متوقع: {e}"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="ban", description="حظر عضو من السيرفر")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
        await member.ban(reason=reason)
        await interaction.response.send_message(f"⛔ تم حظر {member.mention} | السبب: {reason}")

    @app_commands.command(name="unban", description="فك الحظر عن عضو باستخدام ID")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user)
            await interaction.response.send_message(f"✅ تم فك الحظر عن العضو **{user.name}** (`{user.id}`)")
        except Exception as e:
            await interaction.response.send_message(f"❌ تعذر فك الحظر: {e}", ephemeral=True)

    @app_commands.command(name="kick", description="طرد عضو خارج السيرفر")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
        await member.kick(reason=reason)
        await interaction.response.send_message(f"🚨 تم طرد {member.mention} | السبب: {reason}")

    @app_commands.command(name="timeout", description="كتم عضو لمنعه من الكتابة والتفاعل لفترة محددة")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: Optional[str] = "لا يوجد سبب"):
        duration = timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await interaction.response.send_message(f"🤐 تم كتم {member.mention} لمدة `{minutes}` دقيقة | السبب: {reason}")

    @app_commands.command(name="unmute", description="فك الكتم عن عضو")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        await member.timeout(None)
        await interaction.response.send_message(f"🔊 تم فك الكتم عن {member.mention}")

    @app_commands.command(name="clear", description="مسح عدد محدد من الرسائل في الروم الحالي")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        if member:
            def check(m):
                return m.author == member
            deleted = await interaction.channel.purge(limit=amount, check=check)
        else:
            deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 تم مسح `{len(deleted)}` رسالة بنجاح!", ephemeral=True)

    @app_commands.command(name="lock", description="قفل الروم ومنع الأعضاء من الكتابة")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
        await interaction.response.send_message("🔒 تم قفل هذه القناة ومنع الكتابة بها!")

    @app_commands.command(name="unlock", description="فتح الروم وإعادة السماح بالكتابة")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
        await interaction.response.send_message("🔓 تم فتح القناة والسماح بالكتابة مجدداً!")

    @app_commands.command(name="slowmode", description="تفعيل الوضع البطئ للقناة (ضع 0 لإلغائه)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int):
        await interaction.channel.edit(slowmode_delay=seconds)
        if seconds == 0:
            await interaction.response.send_message("⚡ تم إلغاء الوضع البطئ!")
        else:
            await interaction.response.send_message(f"⏱️ تم ضبط الوضع البطئ إلى `{seconds}` ثانية!")

    @app_commands.command(name="warn", description="إعطاء تحذير رسمي لعضو")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        await interaction.response.send_message(f"⚠️ تم تحذير {member.mention} | السبب: **{reason}**")

    @app_commands.command(name="warnings", description="عرض سجل تحذيرات عضو")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = db.get_warnings(interaction.guild_id, member.id)
        if not warns:
            await interaction.response.send_message(f"✅ العضو {member.mention} ليس لديه أي تحذيرات سابقة.")
            return
        embed = discord.Embed(title=f"⚠️ تحذيرات العضو {member.display_name}", color=discord.Color.orange())
        for w_id, mod_id, reason, ts in warns:
            mod = interaction.guild.get_member(mod_id)
            embed.add_field(name=f"تحذير #{w_id} ({ts})", value=f"**السبب:** {reason}\n**بواسطة:** {mod.mention if mod else 'إداري'}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="clear-warns", description="مسح جميع التحذيرات عن عضو معين")
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_warns(self, interaction: discord.Interaction, member: discord.Member):
        db.clear_warnings(interaction.guild_id, member.id)
        await interaction.response.send_message(f"🧹 تم مسح جميع تحذيرات العضو {member.mention} بنجاح!")

    @app_commands.command(name="move", description="نقل عضو إلى الروم الصوتي الموجود فيه أنت")
    @app_commands.checks.has_permissions(move_members=True)
    async def move(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ يجب أن تكون في روم صوتي أولاً!", ephemeral=True)
            return
        if not member.voice or not member.voice.channel:
            await interaction.response.send_message("❌ العضو المراد نقله ليس متواجد في أي روم صوتي حالياً!", ephemeral=True)
            return
        await member.move_to(interaction.user.voice.channel)
        await interaction.response.send_message(f"🚚 تم نقل {member.mention} إلى الروم **{interaction.user.voice.channel.name}**")

    @app_commands.command(name="vkick", description="طرد عضو من الروم الصوتي")
    @app_commands.checks.has_permissions(move_members=True)
    async def vkick(self, interaction: discord.Interaction, member: discord.Member):
        if not member.voice or not member.voice.channel:
            await interaction.response.send_message("❌ العضو غير متواجد في روم صوتي حالياً!", ephemeral=True)
            return
        await member.move_to(None)
        await interaction.response.send_message(f"👢 تم طرد {member.mention} من الروم الصوتي!")

async def setup(bot):
    cog = Moderation(bot)
    await bot.add_cog(cog)
