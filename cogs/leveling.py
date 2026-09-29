import math
import discord
from discord import app_commands
from discord.ext import commands, tasks
from typing import Optional, Literal
from database import db, calculate_next_level_xp, create_progress_bar, check_and_grant_level_roles

class RankTimeframeSelect(discord.ui.Select):
    def __init__(self, target_member: discord.Member):
        self.target_member = target_member
        options = [
            discord.SelectOption(label="اليوم", value="today", emoji="📅"),
            discord.SelectOption(label="هذا الأسبوع", value="week", emoji="📆"),
            discord.SelectOption(label="هذا الشهر", value="month", emoji="🗓️"),
            discord.SelectOption(label="هذه السنة", value="year", emoji="🌎"),
            discord.SelectOption(label="الكلي (كل الأوقات)", value="all", emoji="♾️")
        ]
        super().__init__(placeholder="اختر الفترة الزمنية لعرض التفاصيل...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        timeframe = self.values[0]
        
        stats = db.get_timeframe_stats(interaction.guild_id, self.target_member.id, timeframe)
        temp_text_lvl = int(math.sqrt(stats['text_xp'] / 100)) + 1
        temp_voice_lvl = int(math.sqrt(stats['voice_xp'] / 100)) + 1
        
        timeframe_names = {"today": "اليوم", "week": "هذا الأسبوع", "month": "هذا الشهر", "year": "هذه السنة", "all": "الكلي"}
        
        embed = discord.Embed(
            title=f"📊 إحصائيات {self.target_member.display_name} - ({timeframe_names[timeframe]})",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=self.target_member.display_avatar.url)
        
        embed.add_field(name="💬 اللفل الكتابي", value=f"Level: `{temp_text_lvl}`\nXP: `{stats['text_xp']}`", inline=True)
        embed.add_field(name="🎤 اللفل الصوتي", value=f"Level: `{temp_voice_lvl}`\nXP: `{stats['voice_xp']}`", inline=True)
        embed.add_field(name="🖼️ الصور المرسلة", value=f"`{stats['image_count']}` صور", inline=False)
        embed.add_field(name="🎥 الفيديوهات المرسلة", value=f"`{stats['video_count']}` فيديو", inline=True)
        embed.add_field(name="⏱️ دقائق الفيديوهات", value=f"`{stats['video_duration']}` دقيقة", inline=True)
        
        await interaction.edit_original_response(embed=embed)

class RankInfoView(discord.ui.View):
    def __init__(self, target_member: discord.Member, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.add_item(RankTimeframeSelect(target_member))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ هذه القائمة ليست لك!", ephemeral=True)
            return False
        return True

class RankMainView(discord.ui.View):
    def __init__(self, target_member: discord.Member, author_id: int):
        super().__init__(timeout=120)
        self.target_member = target_member
        self.author_id = author_id

    @discord.ui.button(label="المعلومات", style=discord.ButtonStyle.secondary, emoji="ℹ️")
    async def show_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ مو أنت اللي طلبت الأمر!", ephemeral=True)
            return
            
        view = RankInfoView(self.target_member, self.author_id)
        await interaction.response.edit_message(view=view)

class Leveling(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        for guild in self.bot.guilds:
            st = db.get_guild_settings(guild.id)
            if not st[11]:
                continue
            v_rate = st[13]
            for channel in guild.voice_channels:
                if channel == guild.afk_channel:
                    continue
                for member in channel.members:
                    if member.bot or member.voice.self_deaf or member.voice.self_mute:
                        continue
                    leveled_up, new_lvl = db.add_voice_xp(guild.id, member.id, v_rate, time_add=60)
                    db.log_activity(guild.id, member.id, 'voice_xp', v_rate)
                    
                    if leveled_up:
                        await check_and_grant_level_roles(guild, member, new_lvl)

    @app_commands.command(name="rank", description="عرض المستوى الكلي أو التفصيلي لحسابك")
    async def rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        data = db.get_user_data(interaction.guild_id, target.id)

        text_xp = data[2]
        text_lvl = data[3]
        voice_xp = data[4]
        voice_lvl = data[5]
        
        unified_level = text_lvl + voice_lvl
        total_xp = text_xp + voice_xp
        
        next_level_xp = calculate_next_level_xp(unified_level)
        progress_bar = create_progress_bar(total_xp, next_level_xp, length=15)

        embed = discord.Embed(title=f"🏆 المستوى الكلي - {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="اللفل الموحد (Unified Level)", value=f"**Level {unified_level}**", inline=False)
        embed.add_field(name="الخبرة الكلية (Total XP)", value=f"`{total_xp} / {next_level_xp}`\n`[{progress_bar}]`", inline=False)
        
        view = RankMainView(target_member=target, author_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="top", description="عرض قائمة المتصدرين للسيرفر باللفل أو الكريدت")
    async def top(self, interaction: discord.Interaction, category: Literal["المستويات (XP)", "الكريدت (Credits)"]):
        embed = discord.Embed(title=f"🏆 قائمة المتصدرين - {category}", color=discord.Color.gold())
        with db.get_connection() as conn:
            cursor = conn.cursor()

            if "XP" in category:
                cursor.execute("SELECT user_id, text_level, text_xp FROM user_levels WHERE guild_id = ? ORDER BY text_xp DESC LIMIT 10", (interaction.guild_id,))
                rows = cursor.fetchall()
                desc = ""
                for idx, r in enumerate(rows, 1):
                    m = interaction.guild.get_member(r[0])
                    desc += f"**#{idx}** | {m.mention if m else 'عضو'} - Level `{r[1]}` (`{r[2]}` XP)\n"
                embed.description = desc if desc else "لا توجد بيانات متاحة."
            else:
                cursor.execute("SELECT user_id, credits FROM economy WHERE guild_id = ? ORDER BY credits DESC LIMIT 10", (interaction.guild_id,))
                rows = cursor.fetchall()
                desc = ""
                for idx, r in enumerate(rows, 1):
                    m = interaction.guild.get_member(r[0])
                    desc += f"**#{idx}** | {m.mention if m else 'عضو'} - **${r[1]}** كريدت\n"
                embed.description = desc if desc else "لا توجد بيانات متاحة."

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Leveling(bot))
