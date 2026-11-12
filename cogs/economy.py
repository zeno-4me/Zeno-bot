import time
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from database import db, reply, level_progress, create_progress_bar, parse_hex

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="credits", description="عرض رصيدك أو تحويل كريدت لعضو آخر")
    async def credits(self, interaction: discord.Interaction, member: Optional[discord.Member] = None, amount: Optional[int] = None):
        if member and amount is not None:
            if member.id == interaction.user.id:
                await reply(interaction, "❌ لا يمكنك تحويل الكريدت لنفسك!", ephemeral=True)
                return
            if member.bot:
                await reply(interaction, "❌ لا يمكنك تحويل الكريدت للبوتات!", ephemeral=True)
                return
            if amount <= 0:
                await reply(interaction, "❌ يرجى إدخال مبلغ صحيح للتحويل!", ephemeral=True)
                return

            if amount > 2_000_000_000:
                await reply(interaction, "❌ المبلغ كبير جداً!", ephemeral=True)
                return

            ok, _ = await db.transfer_credits(interaction.guild_id, interaction.user.id, member.id, amount)
            if not ok:
                await reply(interaction, "❌ رصيدك الحالي لا يكفي لإجراء هذا التحويل!", ephemeral=True)
                return

            await reply(interaction, f"💸 قام {interaction.user.mention} بتحويل **${amount:,}** كريدت إلى {member.mention}!")
        else:
            target = member or interaction.user
            data = await db.get_economy_data(interaction.guild_id, target.id)
            user_credits = data['credits'] if data else 0
            await reply(interaction, f"💳 رصيد {target.mention} الحالي هو: **${user_credits:,}** كريدت.")

    @app_commands.command(name="daily", description="استلام المكافأة اليومية المجانية من الكريدت")
    async def daily(self, interaction: discord.Interaction):
        reward = 300
        ok, remaining = await db.claim_daily(interaction.guild_id, interaction.user.id, reward, 86400)
        if not ok:
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            kw = await db.auto_kwargs(interaction.guild_id, "daily_wait", user=interaction.user.mention,
                                      name=interaction.user.display_name, server=interaction.guild.name,
                                      time=f"{hours}h {minutes}m {seconds}s")
            await reply(interaction, ephemeral=True, **(kw or {"content": "⏳ ارجع لاحقاً."}))
            return

        kw = await db.auto_kwargs(interaction.guild_id, "daily_ok", user=interaction.user.mention,
                                  name=interaction.user.display_name, server=interaction.guild.name,
                                  amount=f"{reward:,}")
        await reply(interaction, **(kw or {"content": "✅ تم استلام المكافأة.", "ephemeral": True}))

    @app_commands.command(name="profile", description="بطاقة بروفايلك الشاملة (الرصيد، اللقب، السمعة، اللفل والمركز)")
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        if not interaction.response.is_done():
            await interaction.response.defer()
        gid = interaction.guild_id
        cfg = await db.get_level_cfg(gid)
        eco = await db.get_economy_data(gid, target.id)
        lvl_data = await db.get_user_data(gid, target.id)
        rank, rank_total = await db.get_user_rank(gid, target.id)
        stats = await db.get_timeframe_stats(gid, target.id, "all")

        credits_val = eco['credits'] if eco else 0
        rep_val = eco['rep'] if eco else 0
        title_val = eco['title'] if eco and eco['title'] else "بدون لقب"
        total = lvl_data['text_xp'] + lvl_data['voice_xp']
        lvl, into, need = level_progress(total, cfg['base_xp'])
        pct = int(into / need * 100) if need else 100
        bar = create_progress_bar(into, need, 12, cfg['bar'])

        embed = discord.Embed(color=parse_hex(cfg['rank_color']) or 0xF1C40F)
        embed.set_author(name=f"{target.display_name} • البروفايل", icon_url=target.display_avatar.url)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.description = (f"❝ **{title_val}** ❞\n\n"
                             f"⭐ **المستوى {lvl}** • 🏅 المركز **#{rank}** / {rank_total}\n"
                             f"{bar} **{pct}%**\n`{into:,} / {need:,}` XP")
        embed.add_field(name="💳 الكريدت", value=f"**${credits_val:,}**", inline=True)
        embed.add_field(name="🌟 السمعة", value=f"**+{rep_val}**", inline=True)
        embed.add_field(name="✨ الخبرة", value=f"**{total:,}** XP", inline=True)
        embed.add_field(name="💬 الكتابي", value=f"`{lvl_data['text_xp']:,}` XP • `{stats.get('message_count', 0):,}` رسالة", inline=True)
        embed.add_field(name="🎤 الصوتي", value=f"`{lvl_data['voice_xp']:,}` XP • {lvl_data['voice_time_seconds'] // 3600} ساعة", inline=True)
        if getattr(target, "joined_at", None):
            embed.add_field(name="📅 انضم للسيرفر", value=f"<t:{int(target.joined_at.timestamp())}:D>", inline=True)
        embed.add_field(name="🕰️ عمر الحساب", value=f"<t:{int(target.created_at.timestamp())}:R>", inline=True)
        if target.top_role and not target.top_role.is_default():
            embed.add_field(name="🎭 أعلى رتبة", value=target.top_role.mention, inline=True)
        try:
            user = await interaction.client.fetch_user(target.id)
            if user.banner:
                embed.set_image(url=user.banner.url)
        except Exception:
            pass
        embed.set_footer(text=interaction.guild.name)
        await reply(interaction, embed=embed)

    @app_commands.command(name="rep", description="إعطاء نقطة سمعة لشخص آخر (تتاح كل 12 ساعة)")
    async def rep(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            await reply(interaction, "❌ لا يمكنك إعطاء نقطة سمعة لنفسك!", ephemeral=True)
            return
        if member.bot:
            await reply(interaction, "❌ لا يمكنك إعطاء نقاط سمعة للبوتات!", ephemeral=True)
            return

        ok, remaining = await db.claim_rep(interaction.guild_id, interaction.user.id, member.id, 43200)
        if not ok:
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            await reply(interaction, 
                f"⏳ يمكنك إعطاء نقطة سمعة مجدداً بعد `{hours}h {minutes}m {seconds}s`.",
                ephemeral=True
            )
            return

        kw = await db.auto_kwargs(interaction.guild_id, "rep_ok", user=interaction.user.mention,
                                  name=interaction.user.display_name, target=member.mention,
                                  target_name=member.display_name, server=interaction.guild.name)
        await reply(interaction, **(kw or {"content": "✅ تم.", "ephemeral": True}))

    @app_commands.command(name="title", description="كتابة وتغيير اللقب الذي يظهر في بروفايلك")
    async def title(self, interaction: discord.Interaction, text: str):
        if len(text) > 30:
            await reply(interaction, "❌ اللقب يتجاوز الحد المسموح (30 حرف)!", ephemeral=True)
            return
        await db.set_title(interaction.guild_id, interaction.user.id, text)
        await reply(interaction, f"✅ تم تحديث لقبك الشخصي إلى: **{text}**")

async def setup(bot):
    await bot.add_cog(Economy(bot))
