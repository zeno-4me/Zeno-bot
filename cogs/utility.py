import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

class Utility(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="user", description="عرض معلومات الحساب وتاريخ انضمامه للديسكورد والسيرفر")
    async def user(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        embed = discord.Embed(title=f"👤 معلومات الحساب - {target.display_name}", color=target.color)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="الاسم الكامل", value=str(target), inline=True)
        embed.add_field(name="الآيدي (ID)", value=f"`{target.id}`", inline=True)
        embed.add_field(name="تاريخ إنشاء الحساب", value=target.created_at.strftime("%Y-%m-%d"), inline=False)
        embed.add_field(name="تاريخ الانضمام للسيرفر", value=target.joined_at.strftime("%Y-%m-%d") if target.joined_at else "غير معروف", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="server", description="تفاصيل وإحصائيات السيرفر الشاملة")
    async def server(self, interaction: discord.Interaction):
        g = interaction.guild
        embed = discord.Embed(title=f"🏰 إحصائيات سيرفر - {g.name}", color=discord.Color.blurple())
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="المالك (Owner)", value=g.owner.mention if g.owner else "غير معروف", inline=True)
        embed.add_field(name="عدد الأعضاء", value=f"`{g.member_count}` عضو", inline=True)
        embed.add_field(name="عدد الرومات", value=f"`{len(g.channels)}` قناة", inline=True)
        embed.add_field(name="مستوى البوستات", value=f"Level `{g.premium_tier}` ({g.premium_subscription_count} Boosts)", inline=True)
        embed.add_field(name="تاريخ إنشاء السيرفر", value=g.created_at.strftime("%Y-%m-%d"), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="إظهار صورة البروفايل لأي شخص")
    async def avatar(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        embed = discord.Embed(title=f"🖼️ صورة حساب - {target.display_name}", color=discord.Color.blue())
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="banner", description="عرض صورة البانر الخلفية للحساب")
    async def banner(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        fetched_user = await self.bot.fetch_user(target.id)
        if not fetched_user.banner:
            await interaction.response.send_message("❌ هذا الحساب ليس لديه صورة بانر!", ephemeral=True)
            return
        embed = discord.Embed(title=f"🎨 صورة البانر - {target.display_name}", color=discord.Color.purple())
        embed.set_image(url=fetched_user.banner.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roles", description="عرض قائمة رتب السيرفر")
    async def roles(self, interaction: discord.Interaction):
        roles_list = [r.mention for r in reversed(interaction.guild.roles) if r != interaction.guild.default_role]
        roles_str = ", ".join(roles_list[:30])
        embed = discord.Embed(title=f"🎭 رتب السيرفر ({len(roles_list)})", description=roles_str if roles_str else "لا توجد رتب", color=discord.Color.dark_teal())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ping", description="فحص سرعة استجابة البوت (Latency)")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! سرعة استجابة البوت: `{latency}ms`")

    @app_commands.command(name="bot", description="عرض معلومات وإحصائيات البوت")
    async def bot_info(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🤖 معلومات البوت الخاص بك", description="بوت متكامل ومخصص بأسلوب راقي مع لوحة تحكم داخلية كاملة.", color=discord.Color.gold())
        embed.add_field(name="السيرفرات المتصلة", value=f"`{len(self.bot.guilds)}`", inline=True)
        embed.add_field(name="مكتبة التشغيل", value="ما اتوقع انك مهتم", inline=True)
        embed.add_field(name="نظام التلفيل", value="كتابي + صوتي مفعل", inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="poll", description="إنشاء استبيان تصويت سريع للأعضاء")
    async def poll(self, interaction: discord.Interaction, question: str):
        embed = discord.Embed(title="📊 استبيان وتصويت جديد", description=question, color=discord.Color.green())
        embed.set_footer(text=f"تم إنشاؤه بواسطة: {interaction.user.display_name}")
        await interaction.response.send_message("✅ تم إنشاء التصويت!", ephemeral=True)
        msg = await interaction.channel.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

async def setup(bot):
    await bot.add_cog(Utility(bot))
