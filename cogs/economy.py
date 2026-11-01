import time
from typing import Optional
import discord
from discord import app_commands
from discord.ext import commands
from database import db, reply

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
            await reply(interaction, 
                f"⏳ لقد استلمت مكافأتك اليومية بالفعل! يرجى الانتظار `{hours}h {minutes}m {seconds}s` مجدداً.",
                ephemeral=True
            )
            return

        await reply(interaction, f"🎉 مبارك! لقد حصلت على **${reward:,}** كريدت كمكافأة يومية!")

    @app_commands.command(name="profile", description="عرض بطاقة بروفايلك الشاملة (الرصيد، اللقب، السمعة، واللفل)")
    async def profile(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        eco = await db.get_economy_data(interaction.guild_id, target.id)
        lvl_data = await db.get_user_data(interaction.guild_id, target.id)

        credits_val = eco['credits'] if eco else 0
        rep_val = eco['rep'] if eco else 0
        title_val = eco['title'] if eco and eco['title'] else "لا يوجد لقب"
        
        text_lvl = lvl_data['text_level'] if lvl_data else 0
        voice_lvl = lvl_data['voice_level'] if lvl_data else 0
        unified_level = text_lvl + voice_lvl

        embed = discord.Embed(title=f"👤 بطاقة بروفايل - {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="🏷️ اللقب (Title)", value=f"`{title_val}`", inline=False)
        embed.add_field(name="💳 الكريدت (Credits)", value=f"**${credits_val:,}**", inline=True)
        embed.add_field(name="⭐ السمعة (Rep)", value=f"**+{rep_val}**", inline=True)
        embed.add_field(name="📊 المستوى الكلي", value=f"**Level {unified_level}**", inline=True)

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

        await reply(interaction, f"🌟 قام {interaction.user.mention} بإعطاء نقطة سمعة (+1 Rep) إلى {member.mention}!")

    @app_commands.command(name="title", description="كتابة وتغيير اللقب الذي يظهر في بروفايلك")
    async def title(self, interaction: discord.Interaction, text: str):
        if len(text) > 30:
            await reply(interaction, "❌ اللقب يتجاوز الحد المسموح (30 حرف)!", ephemeral=True)
            return
        await db.set_title(interaction.guild_id, interaction.user.id, text)
        await reply(interaction, f"✅ تم تحديث لقبك الشخصي إلى: **{text}**")

async def setup(bot):
    await bot.add_cog(Economy(bot))
