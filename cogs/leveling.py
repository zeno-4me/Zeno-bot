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
        
        stats = await db.get_timeframe_stats(interaction.guild_id, self.target_member.id, timeframe)
        
        text_xp = stats.get('text_xp', 0)
        voice_xp = stats.get('voice_xp', 0)
        total_xp = text_xp + voice_xp
        
        temp_text_lvl = int(math.sqrt(text_xp / 100)) + 1
        temp_voice_lvl = int(math.sqrt(voice_xp / 100)) + 1
        temp_main_lvl = int(math.sqrt(total_xp / 100)) + 1
        
        timeframe_names = {"today": "اليوم", "week": "هذا الأسبوع", "month": "هذا الشهر", "year": "هذه السنة", "all": "الكلي"}
        
        embed = discord.Embed(
            title=f"📊 إحصائيات {self.target_member.display_name} - ({timeframe_names[timeframe]})",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=self.target_member.display_avatar.url)
        
        embed.add_field(name="⭐ اللفل الأساسي (Total XP)", value=f"Level: `{temp_main_lvl}`\nXP: `{total_xp:,}`", inline=False)
        embed.add_field(name="💬 اللفل الكتابي (Text XP)", value=f"Level: `{temp_text_lvl}`\nXP: `{text_xp:,}`", inline=True)
        embed.add_field(name="🎤 اللفل الصوتي (Voice XP)", value=f"Level: `{temp_voice_lvl}`\nXP: `{voice_xp:,}`", inline=True)
        
        embed.add_field(name="💬 إجمالي الرسائل", value=f"`{stats.get('message_count', 0):,}` رسالة", inline=False)
        embed.add_field(name="🖼️ الصور المرسلة", value=f"`{stats.get('image_count', 0):,}` صورة", inline=True)
        embed.add_field(name="🎥 الفيديوهات المرسلة", value=f"`{stats.get('video_count', 0):,}` فيديو", inline=True)
        
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

    @discord.ui.button(label="المعلومات التفصيلية", style=discord.ButtonStyle.secondary, emoji="ℹ️")
    async def show_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ أنت لست صاحب الطلب!", ephemeral=True)
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
            st = await db.get_guild_settings(guild.id)
            if not st or not st['voice_xp_enabled']:
                continue
            v_rate = st['voice_xp_rate'] if st['voice_xp_rate'] is not None else 10
            for channel in guild.voice_channels:
                if channel == guild.afk_channel:
                    continue
                for member in channel.members:
                    if member.bot or member.voice.self_deaf or member.voice.self_mute:
                        continue
                    
                    leveled_up, new_main_lvl = await db.add_voice_xp(guild.id, member.id, v_rate, time_add=60)
                    await db.log_activity(guild.id, member.id, 'voice_xp', v_rate)
                    
                    if leveled_up:
                        await check_and_grant_level_roles(guild, member, new_main_lvl)
                        lvl_c_id = st['level_up_channel_id']
                        target_c = guild.get_channel(lvl_c_id) if lvl_c_id else None
                        if target_c:
                            await target_c.send(f"🎉 مبروك {member.mention}! ارتفع مستواك الأساسي إلى **المستوى {new_main_lvl}**!")

    @app_commands.command(name="rank", description="عرض المستوى الأساسي والتفصيلي لحسابك")
    async def rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        data = await db.get_user_data(interaction.guild_id, target.id)

        text_xp = data['text_xp'] if data else 0
        text_lvl = data['text_level'] if data else 1
        voice_xp = data['voice_xp'] if data else 0
        voice_lvl = data['voice_level'] if data else 1
        
        total_xp = text_xp + voice_xp
        main_level = int(math.sqrt(total_xp / 100)) + 1
        
        next_level_xp = calculate_next_level_xp(main_level)
        progress_bar = create_progress_bar(total_xp, next_level_xp, length=15)

        embed = discord.Embed(title=f"🏆 البروفايل والرتبة - {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="✨ اللفل الأساسي (Main Level)", value=f"**Level {main_level}**", inline=False)
        embed.add_field(name="⭐ الخبرة الكلية (Total XP)", value=f"`{total_xp:,} / {next_level_xp:,}`\n`[{progress_bar}]`", inline=False)
        embed.add_field(name="💬 اللفل الكتابي (Text XP)", value=f"Level `{text_lvl}` ({text_xp:,} XP)", inline=True)
        embed.add_field(name="🎤 اللفل الصوتي (Voice XP)", value=f"Level `{voice_lvl}` ({voice_xp:,} XP)", inline=True)
        
        view = RankMainView(target_member=target, author_id=interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="top", description="عرض قائمة المتصدرين بالسيرفر باللفل أو الكريدت")
    async def top(self, interaction: discord.Interaction, category: Literal["المستويات (XP)", "الكريدت (Credits)"]):
        embed = discord.Embed(title=f"🏆 قائمة المتصدرين - {category}", color=discord.Color.gold())
        
        if "XP" in category:
            rows = await db.get_top_levels(interaction.guild_id, limit=10)
            desc = ""
            for idx, r in enumerate(rows, 1):
                m = interaction.guild.get_member(r['user_id'])
                total_user_xp = r['text_xp'] + r['voice_xp']  # text_xp + voice_xp
                main_lvl = int(math.sqrt(total_user_xp / 100)) + 1
                desc += f"**#{idx}** | {m.mention if m else 'عضو'} - Level `{main_lvl}` (`{total_user_xp:,}` XP)\n"
            embed.description = desc if desc else "لا توجد بيانات متاحة."
        else:
            rows = await db.get_top_credits(interaction.guild_id, limit=10)
            desc = ""
            for idx, r in enumerate(rows, 1):
                m = interaction.guild.get_member(r['user_id'])
                desc += f"**#{idx}** | {m.mention if m else 'عضو'} - **${r['credits']:,}** كريدت\n"
            embed.description = desc if desc else "لا توجد بيانات متاحة."

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Leveling(bot))
