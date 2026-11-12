import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from datetime import timedelta
from database import db, reply

def hierarchy_error(interaction: discord.Interaction, member: discord.Member):
    """يرجع رسالة خطأ إذا ما يحق للمنفّذ تطبيق الإجراء على العضو، وإلا None."""
    guild = interaction.guild
    if member.id == guild.owner_id:
        return "❌ لا يمكنك تنفيذ هذا الإجراء على مالك السيرفر!"
    if member.id == interaction.client.user.id:
        return "❌ لا يمكنك تنفيذ هذا الإجراء على البوت!"
    if interaction.user.id != guild.owner_id and member.top_role >= interaction.user.top_role:
        return "❌ لا يمكنك تنفيذ هذا الإجراء على عضو رتبته مساوية أو أعلى من رتبتك!"
    return None


async def set_everyone_send(channel, role, value):
    """يعدّل send_messages فقط ويحافظ على باقي صلاحيات الروم."""
    ow = channel.overwrites_for(role)
    ow.send_messages = value
    await channel.set_permissions(role, overwrite=None if ow.is_empty() else ow)


async def send_dm(guild_id: int, member: discord.Member, key: str, **variables):
    """يرسل رسالة خاصة للعضو حسب تخصيص الإدارة (معطلة افتراضياً). يرجع الرسالة أو None."""
    kw = await db.auto_kwargs(guild_id, key, name=member.display_name, server=member.guild.name, **variables)
    if not kw:
        return None
    try:
        return await member.send(**kw)
    except (discord.Forbidden, discord.HTTPException):
        return None


async def public_reply(interaction: discord.Interaction, key: str, **variables):
    """رد الأمر العام حسب تخصيص الإدارة (لو معطل يرد تأكيد بسيط للمنفذ فقط)."""
    kw = await db.auto_kwargs(interaction.guild_id, key, server=interaction.guild.name,
                              moderator=interaction.user.mention, **variables)
    if kw:
        await reply(interaction, **kw)
    else:
        await reply(interaction, "✅ تم تنفيذ الإجراء.", ephemeral=True)


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
                    await reply(interaction, "❌ هذا النوع من الرومات لا يدعم خاصية التقييد العمري.", ephemeral=True)
                    return
                    
                await target_channel.edit(nsfw=restricted)
                state_text = "مقيدة عمرياً 🔞 (Age-Restricted)" if restricted else "عادية 🟢"
                await reply(interaction, f"✅ تم تغيير إعدادات الروم {target_channel.mention} لتصبح {state_text}!")
                
        except discord.Forbidden:
            msg = "❌ البوت لا يمتلك صلاحيات كافية لتعديل إعدادات هذه القناة!"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await reply(interaction, msg, ephemeral=True)
        except Exception as e:
            msg = f"❌ حدث خطأ غير متوقع: {e}"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await reply(interaction, msg, ephemeral=True)

    @app_commands.command(name="ban", description="حظر عضو من السيرفر")
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
        if member.id == interaction.user.id:
            await reply(interaction, "❌ لا يمكنك حظر نفسك!", ephemeral=True)
            return
        err = hierarchy_error(interaction, member)
        if err:
            await reply(interaction, err, ephemeral=True)
            return
        dm_msg = await send_dm(interaction.guild_id, member, "ban_dm", moderator=interaction.user.mention, reason=reason)
        try:
            await member.ban(reason=reason)
            await public_reply(interaction, "ban_public", user=member.mention, name=member.display_name, reason=reason)
        except discord.Forbidden:
            if dm_msg:
                try:
                    await dm_msg.delete()
                except discord.HTTPException:
                    pass
            await reply(interaction, "❌ لا أملك صلاحيات كافية لحظر هذا العضو (قد تكون رتبته أعلى مني).", ephemeral=True)

    @app_commands.command(name="unban", description="فك الحظر عن عضو باستخدام ID")
    @app_commands.checks.has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user)
            await reply(interaction, f"✅ تم فك الحظر عن العضو **{user.name}** (`{user.id}`)")
        except ValueError:
            await reply(interaction, "❌ يرجى إدخال ID صحيح (أرقام فقط)!", ephemeral=True)
        except discord.NotFound:
            await reply(interaction, "❌ هذا العضو غير موجود أو غير محظور في السيرفر!", ephemeral=True)
        except Exception as e:
            await reply(interaction, f"❌ تعذر فك الحظر: {e}", ephemeral=True)

    @app_commands.command(name="kick", description="طرد عضو خارج السيرفر")
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
        if member.id == interaction.user.id:
            await reply(interaction, "❌ لا يمكنك طرد نفسك!", ephemeral=True)
            return
        err = hierarchy_error(interaction, member)
        if err:
            await reply(interaction, err, ephemeral=True)
            return
        dm_msg = await send_dm(interaction.guild_id, member, "kick_dm", moderator=interaction.user.mention, reason=reason)
        try:
            await member.kick(reason=reason)
            await public_reply(interaction, "kick_public", user=member.mention, name=member.display_name, reason=reason)
        except discord.Forbidden:
            if dm_msg:
                try:
                    await dm_msg.delete()
                except discord.HTTPException:
                    pass
            await reply(interaction, "❌ لا أملك صلاحيات كافية لطرد هذا العضو.", ephemeral=True)

    @app_commands.command(name="timeout", description="كتم عضو لمنعه من الكتابة والتفاعل لفترة محددة")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, member: discord.Member, minutes: int, reason: Optional[str] = "لا يوجد سبب"):
        if member.id == interaction.user.id:
            await reply(interaction, "❌ لا يمكنك كتم نفسك!", ephemeral=True)
            return
        err = hierarchy_error(interaction, member)
        if err:
            await reply(interaction, err, ephemeral=True)
            return
        try:
            duration = timedelta(minutes=minutes)
            await member.timeout(duration, reason=reason)
            await send_dm(interaction.guild_id, member, "timeout_dm", moderator=interaction.user.mention,
                          reason=reason, minutes=minutes)
            await public_reply(interaction, "timeout_public", user=member.mention, name=member.display_name,
                               reason=reason, minutes=minutes)
        except discord.Forbidden:
            await reply(interaction, "❌ لا أملك صلاحيات كافية لكتم هذا العضو.", ephemeral=True)

    @app_commands.command(name="unmute", description="فك الكتم عن عضو")
    @app_commands.checks.has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member):
        err = hierarchy_error(interaction, member)
        if err:
            await reply(interaction, err, ephemeral=True)
            return
        try:
            await member.timeout(None)
            await public_reply(interaction, "unmute_public", user=member.mention, name=member.display_name)
        except discord.Forbidden:
            await reply(interaction, "❌ لا أملك صلاحيات كافية لفك الكتم عن هذا العضو.", ephemeral=True)

    @app_commands.command(name="clear", description="مسح عدد محدد من الرسائل في الروم الحالي")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear(self, interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
        await interaction.response.defer(ephemeral=True)
        try:
            if member:
                def check(m):
                    return m.author == member
                deleted = await interaction.channel.purge(limit=amount, check=check)
            else:
                deleted = await interaction.channel.purge(limit=amount)
            await interaction.followup.send(f"🧹 تم مسح `{len(deleted)}` رسالة بنجاح!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ لا أملك صلاحية إدارة الرسائل في هذه القناة!", ephemeral=True)

    @app_commands.command(name="lock", description="قفل الروم ومنع الأعضاء من الكتابة")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def lock(self, interaction: discord.Interaction):
        try:
            await set_everyone_send(interaction.channel, interaction.guild.default_role, False)
            await reply(interaction, "🔒 تم قفل هذه القناة ومنع الكتابة بها!")
        except discord.Forbidden:
            await reply(interaction, "❌ لا أملك صلاحية تعديل صلاحيات القناة!", ephemeral=True)

    @app_commands.command(name="unlock", description="فتح الروم وإعادة السماح بالكتابة")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def unlock(self, interaction: discord.Interaction):
        try:
            await set_everyone_send(interaction.channel, interaction.guild.default_role, None)
            await reply(interaction, "🔓 تم فتح القناة والسماح بالكتابة مجدداً!")
        except discord.Forbidden:
            await reply(interaction, "❌ لا أملك صلاحية تعديل صلاحيات القناة!", ephemeral=True)

    @app_commands.command(name="slowmode", description="تفعيل الوضع البطئ للقناة (ضع 0 لإلغائه)")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def slowmode(self, interaction: discord.Interaction, seconds: int):
        try:
            await interaction.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await reply(interaction, "⚡ تم إلغاء الوضع البطئ!")
            else:
                await reply(interaction, f"⏱️ تم ضبط الوضع البطئ إلى `{seconds}` ثانية!")
        except discord.Forbidden:
            await reply(interaction, "❌ لا أملك صلاحية تعديل هذه القناة!", ephemeral=True)

    @app_commands.command(name="warn", description="إعطاء تحذير رسمي لعضو")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        if member.bot:
            await reply(interaction, "❌ لا يمكنك تحذير البوتات!", ephemeral=True)
            return
        await db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        count = len(await db.get_warnings(interaction.guild_id, member.id))
        await send_dm(interaction.guild_id, member, "warn_dm", moderator=interaction.user.mention,
                      reason=reason, count=count)
        await public_reply(interaction, "warn_public", user=member.mention, name=member.display_name,
                           reason=reason, count=count)

    @app_commands.command(name="warnings", description="عرض سجل تحذيرات عضو")
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = await db.get_warnings(interaction.guild_id, member.id)
        if not warns:
            await reply(interaction, f"✅ العضو {member.mention} ليس لديه أي تحذيرات سابقة.")
            return
        embed = discord.Embed(title=f"⚠️️ تحذيرات العضو {member.display_name}", color=discord.Color.orange())
        for row in warns:
            w_id = row['id']
            mod_id = row['moderator_id']
            reason = row['reason']
            ts = row['timestamp']
            mod = interaction.guild.get_member(mod_id)
            embed.add_field(name=f"تحذير #{w_id} ({ts})", value=f"**السبب:** {reason}\n**بواسطة:** {mod.mention if mod else 'إداري'}", inline=False)
        await reply(interaction, embed=embed)

    @app_commands.command(name="clear-warns", description="مسح جميع التحذيرات عن عضو معين")
    @app_commands.checks.has_permissions(administrator=True)
    async def clear_warns(self, interaction: discord.Interaction, member: discord.Member):
        await db.clear_warnings(interaction.guild_id, member.id)
        await reply(interaction, f"🧹 تم مسح جميع تحذيرات العضو {member.mention} بنجاح!")

    @app_commands.command(name="move", description="نقل عضو إلى الروم الصوتي الموجود فيه أنت")
    @app_commands.checks.has_permissions(move_members=True)
    async def move(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.user.voice or not interaction.user.voice.channel:
            await reply(interaction, "❌ يجب أن تكون في روم صوتي أولاً!", ephemeral=True)
            return
        if not member.voice or not member.voice.channel:
            await reply(interaction, "❌ العضو المراد نقله ليس متواجد في أي روم صوتي حالياً!", ephemeral=True)
            return
        try:
            await member.move_to(interaction.user.voice.channel)
            await reply(interaction, f"🚚 تم نقل {member.mention} إلى الروم **{interaction.user.voice.channel.name}**")
        except discord.Forbidden:
            await reply(interaction, "❌ لا أملك صلاحية نقل الأعضاء بين الرومات الصوتية!", ephemeral=True)

    @app_commands.command(name="vkick", description="طرد عضو من الروم الصوتي")
    @app_commands.checks.has_permissions(move_members=True)
    async def vkick(self, interaction: discord.Interaction, member: discord.Member):
        if not member.voice or not member.voice.channel:
            await reply(interaction, "❌ العضو غير متواجد في روم صوتي حالياً!", ephemeral=True)
            return
        err = hierarchy_error(interaction, member)
        if err:
            await reply(interaction, err, ephemeral=True)
            return
        try:
            await member.move_to(None)
            await reply(interaction, f"👢 تم طرد {member.mention} من الروم الصوتي!")
        except discord.Forbidden:
            await reply(interaction, "❌ لا أملك صلاحية فصل العضو عن الروم الصوتي!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
