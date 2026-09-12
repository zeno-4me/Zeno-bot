import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import asyncio
import time
import math
import os
import re
from datetime import datetime, timezone
from typing import Optional, List

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

class Database:
    """Enhanced Database Manager for Guild Settings, AutoMod, Tickets, Logs, and Leveling."""
    def __init__(self, db_name="bot_data.db"):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        """Creates SQLite tables and migrates schemas if required."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Comprehensive Guild Settings Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER DEFAULT 0,
                    welcome_channel_id INTEGER DEFAULT 0,
                    welcome_msg TEXT DEFAULT 'مرحباً بك {user} في سيرفر {server}!',
                    leave_channel_id INTEGER DEFAULT 0,
                    leave_msg TEXT DEFAULT 'وداعاً {user}، نتمنى لك التوفيق!',
                    auto_role_id INTEGER DEFAULT 0,
                    ticket_category_id INTEGER DEFAULT 0,
                    ticket_log_channel_id INTEGER DEFAULT 0,
                    ticket_support_role_id INTEGER DEFAULT 0,
                    text_xp_enabled INTEGER DEFAULT 1,
                    voice_xp_enabled INTEGER DEFAULT 1,
                    text_xp_rate INTEGER DEFAULT 15,
                    voice_xp_rate INTEGER DEFAULT 10,
                    level_up_channel_id INTEGER DEFAULT 0,
                    automod_enabled INTEGER DEFAULT 1,
                    automod_badwords TEXT DEFAULT '',
                    anti_links INTEGER DEFAULT 0,
                    anti_invites INTEGER DEFAULT 0,
                    anti_spam INTEGER DEFAULT 0
                )
            """)

            # Level Rewards Table (Role given when reaching a specific level)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS level_rewards (
                    guild_id INTEGER,
                    level INTEGER,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, level)
                )
            """)

            # User Leveling Data Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_levels (
                    guild_id INTEGER,
                    user_id INTEGER,
                    text_xp INTEGER DEFAULT 0,
                    text_level INTEGER DEFAULT 1,
                    voice_xp INTEGER DEFAULT 0,
                    voice_level INTEGER DEFAULT 1,
                    voice_time_seconds INTEGER DEFAULT 0,
                    last_msg_timestamp REAL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            """)
            conn.commit()

    def get_guild_settings(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
                conn.commit()
                return self.get_guild_settings(guild_id)
            return row

    def update_guild_setting(self, guild_id: int, column: str, value):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE guild_settings SET {column} = ? WHERE guild_id = ?", (value, guild_id))
            conn.commit()

    def add_level_reward(self, guild_id: int, level: int, role_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)", (guild_id, level, role_id))
            conn.commit()

    def get_level_rewards(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT level, role_id FROM level_rewards WHERE guild_id = ? ORDER BY level ASC", (guild_id,))
            return cursor.fetchall()

    def delete_level_reward(self, guild_id: int, level: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM level_rewards WHERE guild_id = ? AND level = ?", (guild_id, level))
            conn.commit()

    def get_user_data(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO user_levels (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
                conn.commit()
                return self.get_user_data(guild_id, user_id)
            return row

    def set_user_xp_level(self, guild_id: int, user_id: int, text_xp: int, text_lvl: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_levels SET text_xp = ?, text_level = ? WHERE guild_id = ? AND user_id = ?
            """, (text_xp, text_lvl, guild_id, user_id))
            conn.commit()

    def add_text_xp(self, guild_id: int, user_id: int, xp_amount: int):
        data = self.get_user_data(guild_id, user_id)
        current_xp = data[2] + xp_amount
        current_lvl = data[3]
        
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_levels 
                SET text_xp = ?, text_level = ?, last_msg_timestamp = ?
                WHERE guild_id = ? AND user_id = ?
            """, (current_xp, new_lvl, time.time(), guild_id, user_id))
            conn.commit()

        return leveled_up, new_lvl

    def add_voice_xp(self, guild_id: int, user_id: int, xp_amount: int, time_add: int):
        data = self.get_user_data(guild_id, user_id)
        current_xp = data[4] + xp_amount
        current_lvl = data[5]
        total_time = data[6] + time_add
        
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_levels 
                SET voice_xp = ?, voice_level = ?, voice_time_seconds = ?
                WHERE guild_id = ? AND user_id = ?
            """, (current_xp, new_lvl, total_time, guild_id, user_id))
            conn.commit()

        return leveled_up, new_lvl

db = Database()

def create_progress_bar(current: int, total: int, length: int = 12) -> str:
    """Generates visual progress bar."""
    if total <= 0:
        total = 1
    percent = min(max(current / total, 0.0), 1.0)
    filled = int(length * percent)
    return "█" * filled + "░" * (length - filled)

def calculate_next_level_xp(level: int) -> int:
    return (level ** 2) * 100

async def check_and_grant_level_roles(guild: discord.Guild, member: discord.Member, level: int):
    """Grant level reward roles if matched."""
    rewards = db.get_level_rewards(guild.id)
    for req_level, role_id in rewards:
        if level >= req_level:
            role = guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason="رتبة مكافأة اللفل")
                except Exception:
                    pass

class EditWelcomeModal(discord.ui.Modal, title="تعديل رسالة الترحيب"):
    welcome_msg = discord.ui.TextInput(
        label="رسالة الترحيب",
        style=discord.TextStyle.paragraph,
        placeholder="مثال: مرحباً بك {user} في سيرفر {server}!",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "welcome_msg", self.welcome_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة الترحيب بنجاح!", ephemeral=True)

class EditLeaveModal(discord.ui.Modal, title="تعديل رسالة المغادرة"):
    leave_msg = discord.ui.TextInput(
        label="رسالة المغادرة",
        style=discord.TextStyle.paragraph,
        placeholder="مثال: وداعاً {user}، نراك على خير!",
        required=True,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "leave_msg", self.leave_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة المغادرة بنجاح!", ephemeral=True)

class EditBadwordsModal(discord.ui.Modal, title="إدارة الكلمات الممنوعة"):
    bad_words = discord.ui.TextInput(
        label="الكلمات الممنوعة (افصل بين الكلمات بفاصلة)",
        style=discord.TextStyle.paragraph,
        placeholder="كلمة1, كلمة2, رابط_ممنوع",
        required=False,
        max_length=1000
    )

    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "automod_badwords", self.bad_words.value)
        await interaction.response.send_message("✅ تم حفظ قائمة الكلمات الممنوعة!", ephemeral=True)

class ChangeXPRatesModal(discord.ui.Modal, title="تعديل معدل الـ XP"):
    text_rate = discord.ui.TextInput(label="خبرة الكتابة (لكل رسالة)", default="15", max_length=4)
    voice_rate = discord.ui.TextInput(label="خبرة الصوت (لكل دقيقة)", default="10", max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            t_rate = int(self.text_rate.value)
            v_rate = int(self.voice_rate.value)
            db.update_guild_setting(interaction.guild_id, "text_xp_rate", t_rate)
            db.update_guild_setting(interaction.guild_id, "voice_xp_rate", v_rate)
            await interaction.response.send_message(f"✅ تم تحديث معدل الخبرة: الكتابة `{t_rate}` XP | الصوت `{v_rate}` XP", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى كتابة أرقام صحيحة فقط!", ephemeral=True)

class AddLevelRewardModal(discord.ui.Modal, title="إضافة رتيبة مكافأة لفل"):
    level_req = discord.ui.TextInput(label="المستوى المطلوب (Level)", placeholder="مثال: 5", max_length=3)
    role_id = discord.ui.TextInput(label="آيدي الرتبة (Role ID)", placeholder="أدخل ID الرتبة هنا", max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            lvl = int(self.level_req.value)
            r_id = int(self.role_id.value)
            role = interaction.guild.get_role(r_id)
            if not role:
                await interaction.response.send_message("❌ الرتبة غير موجودة بهذا الآيدي!", ephemeral=True)
                return
            db.add_level_reward(interaction.guild_id, lvl, r_id)
            await interaction.response.send_message(f"✅ تم ربط المستوى `{lvl}` بالرتبة {role.mention}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى إدخال أرقام صحيحة!", ephemeral=True)

class ManageUserXPModal(discord.ui.Modal, title="تعديل لفل عضو مباشرة"):
    user_id = discord.ui.TextInput(label="آيدي العضو (User ID)", placeholder="أدخل آيدي العضو", max_length=20)
    new_level = discord.ui.TextInput(label="المستوى الجديد (Level)", placeholder="مثال: 10", max_length=4)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            u_id = int(self.user_id.value)
            lvl = int(self.new_level.value)
            xp_needed = calculate_next_level_xp(lvl - 1) if lvl > 1 else 0
            db.set_user_xp_level(interaction.guild_id, u_id, xp_needed, lvl)
            await interaction.response.send_message(f"✅ تم تعديل مستوى العضو `{u_id}` إلى المستوى `{lvl}`!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى إدخال أرقام صحيحة!", ephemeral=True)

class EmbedBuilderModal(discord.ui.Modal, title="منشئ الرسائل والمطبوعات (Embed Creator)"):
    title_input = discord.ui.TextInput(label="عنوان الإمبد", placeholder="اكتب العنوان هنا...", required=True)
    description_input = discord.ui.TextInput(label="محتوى الرسالة", style=discord.TextStyle.paragraph, placeholder="اكتب النص هنا...", required=True)
    color_input = discord.ui.TextInput(label="رمز اللون (Hex Code)", placeholder="#3498db أو اتركه فارغاً", required=False)
    image_input = discord.ui.TextInput(label="رابط صورة كبيرة (URL)", placeholder="https://...", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        color_val = discord.Color.blue()
        if self.color_input.value.startswith("#"):
            try:
                color_val = discord.Color(int(self.color_input.value.replace("#", ""), 16))
            except Exception:
                pass

        embed = discord.Embed(title=self.title_input.value, description=self.description_input.value, color=color_val)
        if self.image_input.value and self.image_input.value.startswith("http"):
            embed.set_image(url=self.image_input.value)

        embed.set_footer(text=f"تم الإرسال بواسطة: {interaction.user.display_name}")
        
        await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ تم إنشاء وإرسال الإمبد في هذه القناة بنجاح!", ephemeral=True)

class ChannelSelectMenu(discord.ui.ChannelSelect):
    """Universal Channel Selector Component."""
    def __init__(self, setting_key: str, placeholder_text: str, channel_types=None):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, channel_types=channel_types or [discord.ChannelType.text], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        db.update_guild_setting(interaction.guild_id, self.setting_key, channel.id)
        await interaction.response.send_message(f"✅ تم حفظ القناة المحدد: {channel.mention}", ephemeral=True)

class RoleSelectMenu(discord.ui.RoleSelect):
    """Universal Role Selector Component."""
    def __init__(self, setting_key: str, placeholder_text: str):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        db.update_guild_setting(interaction.guild_id, self.setting_key, role.id)
        await interaction.response.send_message(f"✅ تم حفظ الرتبة المحددة: {role.mention}", ephemeral=True)

class CategorySelectMenu(discord.ui.ChannelSelect):
    """Category Selector for Tickets."""
    def __init__(self):
        super().__init__(placeholder="اختر فئة التذاكر (Category)...", channel_types=[discord.ChannelType.category], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        cat = self.values[0]
        db.update_guild_setting(interaction.guild_id, "ticket_category_id", cat.id)
        await interaction.response.send_message(f"✅ تم تحديد فئة التذاكر: **{cat.name}**", ephemeral=True)

class GeneralSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ChannelSelectMenu("welcome_channel_id", "👋 اختر قناة الترحيب..."))
        self.add_item(ChannelSelectMenu("leave_channel_id", "🚪 اختر قناة المغادرة..."))
        self.add_item(ChannelSelectMenu("log_channel_id", "📜 اختر قناة السجلات (Logs)..."))
        self.add_item(RoleSelectMenu("auto_role_id", "🎖️ اختر الرتبة التلقائية للأعضاء الجدد..."))

    @discord.ui.button(label="تعديل نص الترحيب", style=discord.ButtonStyle.primary, row=4)
    async def edit_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditWelcomeModal())

    @discord.ui.button(label="تعديل نص المغادرة", style=discord.ButtonStyle.primary, row=4)
    async def edit_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditLeaveModal())

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به بالكامل دون استخدام أي موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class AutoModSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تبديل الحماية العامة", style=discord.ButtonStyle.danger, row=0)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st[15] else 1
        db.update_guild_setting(interaction.guild_id, "automod_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} نظام الحماية العام!", ephemeral=True)

    @discord.ui.button(label="منع الروابط (Anti-Links)", style=discord.ButtonStyle.primary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st[17] else 1
        db.update_guild_setting(interaction.guild_id, "anti_links", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} مانع الروابط الخارجية!", ephemeral=True)

    @discord.ui.button(label="منع دعوات الديسكورد (Anti-Invites)", style=discord.ButtonStyle.primary, row=0)
    async def toggle_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st[18] else 1
        db.update_guild_setting(interaction.guild_id, "anti_invites", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} مانع دعوات السيرفرات!", ephemeral=True)

    @discord.ui.button(label="تعديل الكلمات الممنوعة", style=discord.ButtonStyle.secondary, row=1)
    async def edit_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditBadwordsModal())

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به بالكامل دون استخدام أي موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class XPSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ChannelSelectMenu("level_up_channel_id", "📢 اختر قناة إشعارات ارتفاع اللفل (أو اتركها للروم الحالي)..."))

    @discord.ui.button(label="تبديل اللفل الكتابي", style=discord.ButtonStyle.primary, row=1)
    async def toggle_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st[10] else 1
        db.update_guild_setting(interaction.guild_id, "text_xp_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} اللفل الكتابي!", ephemeral=True)

    @discord.ui.button(label="تبديل اللفل الصوتي", style=discord.ButtonStyle.primary, row=1)
    async def toggle_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st[11] else 1
        db.update_guild_setting(interaction.guild_id, "voice_xp_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} اللفل الصوتي!", ephemeral=True)

    @discord.ui.button(label="تعديل سرعة الـ XP", style=discord.ButtonStyle.secondary, row=1)
    async def rates(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeXPRatesModal())

    @discord.ui.button(label="إضافة رتبة مكافأة لفل", style=discord.ButtonStyle.success, row=2)
    async def add_reward(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddLevelRewardModal())

    @discord.ui.button(label="تعديل لفل عضو يدوي", style=discord.ButtonStyle.danger, row=2)
    async def edit_user_xp(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserXPModal())

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به بالكامل دون استخدام أي موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class TicketSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelectMenu())
        self.add_item(ChannelSelectMenu("ticket_log_channel_id", "📜 اختر قناة سجل التذاكر (Ticket Logs)..."))
        self.add_item(RoleSelectMenu("ticket_support_role_id", "🛡️ اختر رتبة الدعم الفني المسؤول عن التذاكر..."))

    @discord.ui.button(label="إرسال بنل التذاكر في هذه القناة", style=discord.ButtonStyle.success, row=3)
    async def deploy_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎟️ قسم الدعم الفني والمساعدة",
            description="اضغط على الزر أدناه لفتح تذكرة خاصة والتواصل مباشرة مع فريق الإدارة والدعم الفني.",
            color=discord.Color.green()
        )
        await interaction.channel.send(embed=embed, view=OpenTicketView())
        await interaction.response.send_message("✅ تم نشر بنل التذاكر بنجاح!", ephemeral=True)

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به بالكامل دون استخدام أي موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 فتح تذكرة جديدة", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn_pro")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        st = db.get_guild_settings(guild.id)
        cat_id = st[7]
        support_role_id = st[9]
        
        category = guild.get_channel(cat_id) if cat_id else None
        support_role = guild.get_role(support_role_id) if support_role_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}",
            category=category,
            overwrites=overwrites
        )

        embed = discord.Embed(
            title=f"🎟️ تذكرة الدعم - {interaction.user.display_name}",
            description="مرحباً بك! تفضل بكتابة مشكلتك أو استفسارك وسيتم الرد عليك في أقرب وقت.",
            color=discord.Color.blue()
        )
        await channel.send(content=f"{interaction.user.mention} {support_role.mention if support_role else ''}", embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ تم إنشاء تذكرتك بنجاح: {channel.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn_pro")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = db.get_guild_settings(interaction.guild_id)
        log_chan_id = st[8]

        await interaction.response.send_message("سيتم إغلاق وحذف التذكرة خلال 5 ثوانٍ...")

        if log_chan_id:
            log_chan = interaction.guild.get_channel(log_chan_id)
            if log_chan:
                embed = discord.Embed(title="🔒 تم إغلاق تذكرة", color=discord.Color.red())
                embed.add_field(name="القناة", value=interaction.channel.name)
                embed.add_field(name="بواسطة", value=interaction.user.mention)
                embed.set_footer(text=f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                await log_chan.send(embed=embed)

        await asyncio.sleep(5)
        await interaction.channel.delete()

class DashboardSelectMenu(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👋 الترحيب والمغادرة والسجلات", description="إعداد رومات الترحيب، المغادرة، السجلات والرتب التلقائية", emoji="👋", value="general"),
            discord.SelectOption(label="🛡️ الحماية والتعديل الآلي", description="منع الروابط والدعوات والكلمات الممنوعة", emoji="🛡️", value="automod"),
            discord.SelectOption(label="⭐ نظام اللفل والخبرة والمكافآت", description="معدلات XP، اللفل الكتابي والصوتي، ورتب المستويات", emoji="⭐", value="xp"),
            discord.SelectOption(label="🎟️ نظام التذاكر المتقدم", description="فئات التذاكر، رتبة الدعم وسجلات التذاكر", emoji="🎟️", value="tickets"),
            discord.SelectOption(label="📢 منشئ الرسائل والإعلانات (Embed Builder)", description="تصميم وإرسال إمبد باحترافية لأي قناة", emoji="📢", value="embed"),
        ]
        super().__init__(placeholder="اختر القسم المراد التحكم به بالكامل...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        sel = self.values[0]
        st = db.get_guild_settings(interaction.guild_id)

        if sel == "general":
            embed = discord.Embed(title="👋 إعدادات الترحيب والمغادرة والسجلات", color=discord.Color.green())
            w_c = interaction.guild.get_channel(st[2])
            l_c = interaction.guild.get_channel(st[4])
            lg_c = interaction.guild.get_channel(st[1])
            a_r = interaction.guild.get_role(st[6])

            embed.add_field(name="قناة الترحيب", value=w_c.mention if w_c else "غير محددة", inline=True)
            embed.add_field(name="قناة المغادرة", value=l_c.mention if l_c else "غير محددة", inline=True)
            embed.add_field(name="قناة السجلات", value=lg_c.mention if lg_c else "غير محددة", inline=True)
            embed.add_field(name="الرتبة التلقائية", value=a_r.mention if a_r else "غير محددة", inline=True)
            embed.add_field(name="نص الترحيب الحالي", value=f"`{st[3]}`", inline=False)
            embed.add_field(name="نص المغادرة الحالي", value=f"`{st[5]}`", inline=False)

            await interaction.response.edit_message(embed=embed, view=GeneralSettingsView())

        elif sel == "automod":
            embed = discord.Embed(title="🛡️ إعدادات الحماية والتعديل الآلي", color=discord.Color.red())
            embed.add_field(name="الحماية العامة", value="✅ مفعلة" if st[15] else "❌ معطلة", inline=True)
            embed.add_field(name="منع الروابط", value="✅ مفعل" if st[17] else "❌ معطل", inline=True)
            embed.add_field(name="منع الدعوات", value="✅ مفعل" if st[18] else "❌ معطل", inline=True)
            embed.add_field(name="الكلمات الممنوعة", value=st[16] if st[16] else "لا توجد كلمات ممنوعة", inline=False)

            await interaction.response.edit_message(embed=embed, view=AutoModSettingsView())

        elif sel == "xp":
            embed = discord.Embed(title="⭐ إعدادات اللفل والـ XP والمكافآت", color=discord.Color.gold())
            lvl_c = interaction.guild.get_channel(st[14])
            embed.add_field(name="اللفل الكتابي", value="✅ مفعل" if st[10] else "❌ معطل", inline=True)
            embed.add_field(name="اللفل الصوتي", value="✅ مفعل" if st[11] else "❌ معطل", inline=True)
            embed.add_field(name="معدل خبرة الكتابة", value=f"`{st[12]}` XP", inline=True)
            embed.add_field(name="معدل خبرة الصوت", value=f"`{st[13]}` XP", inline=True)
            embed.add_field(name="قناة الإشعارات", value=lvl_c.mention if lvl_c else "الروم الحالي", inline=True)

            rewards = db.get_level_rewards(interaction.guild_id)
            rew_text = "\n".join([f"• Level `{r[0]}` ➔ <@&{r[1]}>" for r in rewards]) if rewards else "لا توجد رتب مكافأة مضافة"
            embed.add_field(name="🏆 رتب المكافآت الحالية", value=rew_text, inline=False)

            await interaction.response.edit_message(embed=embed, view=XPSettingsView())

        elif sel == "tickets":
            embed = discord.Embed(title="🎟️ إعدادات نظام التذاكر", color=discord.Color.blue())
            cat = interaction.guild.get_channel(st[7])
            t_log = interaction.guild.get_channel(st[8])
            s_role = interaction.guild.get_role(st[9])

            embed.add_field(name="فئة التذاكر (Category)", value=cat.mention if cat else "غير محددة", inline=True)
            embed.add_field(name="سجل التذاكر", value=t_log.mention if t_log else "غير محددة", inline=True)
            embed.add_field(name="رتبة الدعم الفني", value=s_role.mention if s_role else "غير محددة", inline=True)

            await interaction.response.edit_message(embed=embed, view=TicketSettingsView())

        elif sel == "embed":
            await interaction.response.send_modal(EmbedBuilderModal())

class MainDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DashboardSelectMenu())

@tasks.loop(minutes=1)
async def voice_xp_loop():
    """Background task awarding Voice XP."""
    for guild in bot.guilds:
        st = db.get_guild_settings(guild.id)
        if not st[11]: # Voice XP disabled
            continue

        v_rate = st[13]

        for channel in guild.voice_channels:
            if channel == guild.afk_channel:
                continue

            for member in channel.members:
                if member.bot or member.voice.self_deaf or member.voice.self_mute:
                    continue

                leveled_up, new_lvl = db.add_voice_xp(guild.id, member.id, v_rate, time_add=60)
                if leveled_up:
                    await check_and_grant_level_roles(guild, member, new_lvl)
                    lvl_c_id = st[14] or st[1]
                    target_c = guild.get_channel(lvl_c_id) or channel
                    try:
                        await target_c.send(f"🎉 مبروك {member.mention}! ارتفع مستواك الصوتي إلى **المستوى {new_lvl}** 🎤!")
                    except Exception:
                        pass

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("---------------------------------------------")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} Slash Commands successfully!")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")

    if not voice_xp_loop.is_running():
        voice_xp_loop.start()

@bot.event
async def on_member_join(member: discord.Member):
    st = db.get_guild_settings(member.guild.id)
    
    # Auto Role
    if st[6]:
        role = member.guild.get_role(st[6])
        if role:
            try:
                await member.add_roles(role)
            except Exception:
                pass

    # Welcome Message
    if st[2]:
        chan = member.guild.get_channel(st[2])
        if chan:
            msg = st[3].replace("{user}", member.mention).replace("{server}", member.guild.name)
            embed = discord.Embed(title="👋 عضو جديد ينضم إلينا!", description=msg, color=discord.Color.green())
            embed.set_thumbnail(url=member.display_avatar.url)
            await chan.send(embed=embed)

@bot.event
async def on_member_remove(member: discord.Member):
    st = db.get_guild_settings(member.guild.id)
    if st[4]: # Leave channel
        chan = member.guild.get_channel(st[4])
        if chan:
            msg = st[5].replace("{user}", member.display_name).replace("{server}", member.guild.name)
            embed = discord.Embed(title="🚪 عضو غادر السيرفر", description=msg, color=discord.Color.red())
            await chan.send(embed=embed)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    g_id = message.guild.id
    st = db.get_guild_settings(g_id)

    # Anti Links Check
    if st[17] and re.search(r"http[s]?://", message.content):
        if not message.author.guild_permissions.administrator:
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention} يمنع نشر الروابط الخارجية هنا!", delete_after=5)
            return

    # Anti Invites Check
    if st[18] and re.search(r"(discord\.gg|discord\.com/invite)", message.content):
        if not message.author.guild_permissions.administrator:
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention} يمنع نشر روابط سيرفرات الديسكورد!", delete_after=5)
            return

    # Bad Words Check
    if st[15] and st[16]:
        bad_words = [w.strip().lower() for w in st[16].split(",") if w.strip()]
        if any(word in message.content.lower() for word in bad_words):
            await message.delete()
            await message.channel.send(f"⚠️ {message.author.mention} تم حذف رسالتك لاحتوائها على كلمات ممنوعة!", delete_after=5)
            return

    # Text XP Check
    if st[10]: # Text XP enabled
        u_data = db.get_user_data(g_id, message.author.id)
        if time.time() - u_data[7] >= 60: # 60 sec cooldown
            t_rate = st[12]
            leveled_up, new_lvl = db.add_text_xp(g_id, message.author.id, t_rate)
            if leveled_up:
                await check_and_grant_level_roles(message.guild, message.author, new_lvl)
                lvl_c_id = st[14]
                target_c = message.guild.get_channel(lvl_c_id) or message.channel
                await target_c.send(f"🎉 مبروك {message.author.mention}! ارتفع مستواك الكتابي إلى **المستوى {new_lvl}** 💬!")

    await bot.process_commands(message)

@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    st = db.get_guild_settings(message.guild.id)
    if st[1]: # Log channel
        chan = message.guild.get_channel(st[1])
        if chan:
            embed = discord.Embed(title="🗑️ تم حذف رسالة", color=discord.Color.red())
            embed.add_field(name="الكاتب", value=message.author.mention)
            embed.add_field(name="القناة", value=message.channel.mention)
            embed.add_field(name="المحتوى", value=message.content or "محتوى غير نصي/صورة", inline=False)
            embed.set_footer(text=f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            await chan.send(embed=embed)

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    st = db.get_guild_settings(before.guild.id)
    if st[1]: # Log channel
        chan = before.guild.get_channel(st[1])
        if chan:
            embed = discord.Embed(title="✏️ تم تعديل رسالة", color=discord.Color.orange())
            embed.add_field(name="الكاتب", value=before.author.mention)
            embed.add_field(name="القناة", value=before.channel.mention)
            embed.add_field(name="قبل", value=before.content or "فارغ", inline=False)
            embed.add_field(name="بعد", value=after.content or "فارغ", inline=False)
            await chan.send(embed=embed)

@bot.tree.command(name="dashboard", description="فتح لوحة تحكم السيرفر الشاملة والتفاعلية (ProBot Style)")
@app_commands.checks.has_permissions(administrator=True)
async def dashboard(interaction: discord.Interaction):
    embed = discord.Embed(
        title="⚙️ لوحة تحكم السيرفر الشاملة (ProBot Dashboard)",
        description="اختر القسم الذي تريد تعديله من القائمة المنسدلة أدناه للتحكم الكامل بسيرفرك بدون موقع!",
        color=discord.Color.blurple()
    )
    view = MainDashboardView()
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="rank", description="عرض بطاقة المستوى والمستوى الكتابي والصوتي")
async def rank(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    target = user or interaction.user
    data = db.get_user_data(interaction.guild_id, target.id)

    text_xp, text_lvl = data[2], data[3]
    voice_xp, voice_lvl = data[4], data[5]
    v_hours = round(data[6] / 3600, 1)

    next_text_xp = calculate_next_level_xp(text_lvl)
    next_voice_xp = calculate_next_level_xp(voice_lvl)

    text_bar = create_progress_bar(text_xp, next_text_xp)
    voice_bar = create_progress_bar(voice_xp, next_voice_xp)

    embed = discord.Embed(title=f"📊 بطاقة المستوى - {target.display_name}", color=discord.Color.blue())
    embed.set_thumbnail(url=target.display_avatar.url)

    embed.add_field(
        name="💬 المستوى الكتابي (Text)",
        value=f"**Level:** `{text_lvl}` | **XP:** `{text_xp}/{next_text_xp}`\n`[{text_bar}]`",
        inline=False
    )
    embed.add_field(
        name="🎤 المستوى الصوتي (Voice)",
        value=f"**Level:** `{voice_lvl}` | **XP:** `{voice_xp}/{next_voice_xp}`\n**الساعات الصوتية:** `{v_hours}` ساعة\n`[{voice_bar}]`",
        inline=False
    )

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="عرض قائمة المتصدرين في تفاعل السيرفر")
async def leaderboard(interaction: discord.Interaction):
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, text_level, text_xp FROM user_levels WHERE guild_id = ? ORDER BY text_xp DESC LIMIT 5", (interaction.guild_id,))
        top_text = cursor.fetchall()

        cursor.execute("SELECT user_id, voice_level, voice_xp FROM user_levels WHERE guild_id = ? ORDER BY voice_xp DESC LIMIT 5", (interaction.guild_id,))
        top_voice = cursor.fetchall()

    embed = discord.Embed(title="🏆 قائمة المتصدرين (Leaderboard)", color=discord.Color.gold())

    t_desc = ""
    for idx, row in enumerate(top_text, 1):
        mem = interaction.guild.get_member(row[0])
        t_desc += f"**#{idx}** | {mem.mention if mem else 'مستخدم'} - Lvl `{row[1]}` (`{row[2]}` XP)\n"

    v_desc = ""
    for idx, row in enumerate(top_voice, 1):
        mem = interaction.guild.get_member(row[0])
        v_desc += f"**#{idx}** | {mem.mention if mem else 'مستخدم'} - Lvl `{row[1]}` (`{row[2]}` XP)\n"

    embed.add_field(name="💬 المتصدرون كتابياً", value=t_desc if t_desc else "لا يوجد بيانات", inline=False)
    embed.add_field(name="🎤 المتصدرون صوتياً", value=v_desc if v_desc else "لا يوجد بيانات", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear", description="مسح عدد محدد من الرسائل")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 تم مسح `{len(deleted)}` رسالة بنجاح!", ephemeral=True)

@bot.tree.command(name="kick", description="طرد عضو من السيرفر")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"🚨 تم طرد {member.mention} | السبب: {reason}")

@bot.tree.command(name="ban", description="حظر عضو من السيرفر")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"⛔ تم حظر {member.mention} | السبب: {reason}")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️ يرجى استبدال YOUR_BOT_TOKEN_HERE بتوكن البوت الخاص بك في نهاية الملف!")
    else:
        bot.run(TOKEN)
