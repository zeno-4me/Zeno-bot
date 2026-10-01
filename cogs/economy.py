import time
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from database import db

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="credits", description="عرض رصيدك أو تحويل كريدت لعضو آخر")
    async def credits(self, interaction: discord.Interaction, member: Optional[discord.Member] = None, amount: Optional[int] = None):
        if member and amount is not None:
            if member.id == interaction.user.id:
                await interaction.response.send_message("❌ لا يمكنك تحويل الكريدت لنفسك!", ephemeral=True)
                return
            if member.bot:
                await interaction.response.send_message("❌ لا يمكنك تحويل الكريدت للبوتات!", ephemeral=True)
                return
            if amount <= 0:
                await interaction.response.send_message("❌ يرجى إدخال مبلغ صحيح للتحويل!", ephemeral=True)
                return

            sender_data = await db.get_economy_data(interaction.guild_id, interaction.user.id)
            current_credits = sender_data[2] if sender_data and len(sender_data) > 2 else 0

            if current_credits < amount:
                await interaction.response.send_message("❌ رصيدك الحالي لا يكفي لإجراء هذا التحويل!", ephemeral=True)
                return

            await db.update_credits(interaction.guild_id, interaction.user.id, -amount)
            await db.update_credits(interaction.guild_id, member.id, amount)
            await interaction.response.send_message(f"💸 قام {interaction.user.mention} بتحويل **${amount:,}** كريدت إلى {member.mention}!")
        else:
            target = member or interaction.user
            data = await db.get_economy_data(interaction.guild_id, target.id)
            user_credits = data[2] if data and len(data) > 2 else 0
            await interaction.response.send_message(f"💳 رصيد {target.mention} الحالي هو: **${user_credits:,}** كريدت.")

    @app_commands.command(name="daily", description="استلام المكافأة اليومية المجانية من الكريدت")
    async def daily(self, interaction: discord.Interaction):
        data = await db.get_economy_data(interaction.guild_id, interaction.user.id)
        last_daily = data[3] if data and len(data) > 3 else 0
        cooldown = 86400
        now = time.time()

        if now - last_daily < cooldown:
            remaining = int(cooldown - (now - last_daily))
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            await interaction.response.send_message(
                f"⏳ لقد استلمت مكافأتك اليومية بالفعل! يرجى الانتظار `{hours}h {minutes}m {seconds}s` مجدداً.",
                ephemeral=True
            )
            return

        reward = 300
        await db.set_daily_claimed(interaction.guild_id, interaction.user.id, reward)
        await interaction.response.send_message(f"🎉 مبارك! لقد حصلت على **${reward:,}** كريدت كمكافأة يومية!")

    @app_commands.command(name="profile", description="عرض بطاقة بروفايلك الشاملة (الرصيد، اللقب، السمعة، واللفل)")
    async def profile(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        eco = await db.get_economy_data(interaction.guild_id, target.id)
        lvl_data = await db.get_user_data(interaction.guild_id, target.id)

        credits_val = eco[2] if eco and len(eco) > 2 else 0
        rep_val = eco[4] if eco and len(eco) > 4 else 0
        title_val = eco[6] if eco and len(eco) > 6 and eco[6] else "لا يوجد لقب"
        
        text_lvl = lvl_data[3] if lvl_data and len(lvl_data) > 3 else 0
        voice_lvl = lvl_data[5] if lvl_data and len(lvl_data) > 5 else 0
        unified_level = text_lvl + voice_lvl

        embed = discord.Embed(title=f"👤 بطاقة بروفايل - {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🏷️ اللقب (Title)", value=f"`{title_val}`", inline=False)
        embed.add_field(name="💳 الكريدت (Credits)", value=f"**${credits_val:,}**", inline=True)
        embed.add_field(name="⭐ السمعة (Rep)", value=f"**+{rep_val}**", inline=True)
        embed.add_field(name="📊 المستوى الكلي", value=f"**Level {unified_level}**", inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rep", description="إعطاء نقطة سمعة لشخص آخر (تتاح كل 12 ساعة)")
    async def rep(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            await interaction.response.send_message("❌ لا يمكنك إعطاء نقطة سمعة لنفسك!", ephemeral=True)
            return
        if member.bot:
            await interaction.response.send_message("❌ لا يمكنك إعطاء نقاط سمعة للبوتات!", ephemeral=True)
            return

        sender_eco = await db.get_economy_data(interaction.guild_id, interaction.user.id)
        last_rep = sender_eco[5] if sender_eco and len(sender_eco) > 5 else 0
        cooldown = 43200
        now = time.time()

        if now - last_rep < cooldown:
            remaining = int(cooldown - (now - last_rep))
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            await interaction.response.send_message(
                f"⏳ يمكنك إعطاء نقطة سمعة مجدداً بعد `{hours}h {minutes}m {seconds}s`.",
                ephemeral=True
            )
            return

        await db.add_rep(interaction.guild_id, member.id, interaction.user.id)
        await interaction.response.send_message(f"🌟 قام {interaction.user.mention} بإعطاء نقطة سمعة (+1 Rep) إلى {member.mention}!")

    @app_commands.command(name="title", description="كتابة وتغيير اللقب الذي يظهر في بروفايلك")
    async def title(self, interaction: discord.Interaction, text: str):
        if len(text) > 30:
            await interaction.response.send_message("❌ اللقب يتجاوز الحد المسموح (30 حرف)!", ephemeral=True)
            return
        await db.set_title(interaction.guild_id, interaction.user.id, text)
        await interaction.response.send_message(f"✅ تم تحديث لقبك الشخصي إلى: **{text}**")

async def setup(bot):
    await bot.add_cog(Economy(bot))
