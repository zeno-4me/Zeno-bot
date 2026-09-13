import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import asyncio
import time
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Literal
from flask import Flask
from threading import Thread

# إعداد خادم الويب (Flask) لإبقاء البوت متصلاً
app = Flask('')

@app.route('/')
def home():
    return "البوت شغال!"

def run():
    # ريندر يحدد المنفذ تلقائياً
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Initialize Discord Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

class Database:
    """Comprehensive Database Manager for ProBot features."""
    def __init__(self, db_name="bot_data.db"):
        self.db_name = db_name
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_name)

    def init_db(self):
        """Initializes database tables for all features."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Guild Settings Table
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

            # Level Rewards Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS level_rewards (
                    guild_id INTEGER,
                    level INTEGER,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, level)
                )
            """)

            # User Levels Table
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

            # Warnings Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    moderator_id INTEGER,
                    reason TEXT,
                    timestamp TEXT
                )
            """)

            # Economy & Profile Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS economy (
                    guild_id INTEGER,
                    user_id INTEGER,
                    credits INTEGER DEFAULT 100,
                    last_daily REAL DEFAULT 0,
                    rep INTEGER DEFAULT 0,
                    last_rep REAL DEFAULT 0,
                    title TEXT DEFAULT 'عضو مميز',
                    PRIMARY KEY (guild_id, user_id)
                )
            """)

            # Auto Responses Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS auto_responses (
                    guild_id INTEGER,
                    trigger_text TEXT,
                    response_text TEXT,
                    PRIMARY KEY (guild_id, trigger_text)
                )
            """)

            # Custom Aliases / Shortcuts Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS custom_aliases (
                    guild_id INTEGER,
                    alias TEXT,
                    command_name TEXT,
                    PRIMARY KEY (guild_id, alias)
                )
            """)

            # Reaction / Button Roles Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS button_roles (
                    guild_id INTEGER,
                    button_label TEXT,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, button_label)
                )
            """)

            conn.commit()

    # Guild Settings Operations
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

    # Leveling Operations
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
            cursor.execute("UPDATE user_levels SET text_xp = ?, text_level = ? WHERE guild_id = ? AND user_id = ?", (text_xp, text_lvl, guild_id, user_id))
            conn.commit()

    def add_text_xp(self, guild_id: int, user_id: int, xp_amount: int):
        data = self.get_user_data(guild_id, user_id)
        current_xp = data[2] + xp_amount
        current_lvl = data[3]
        new_lvl = int(math.sqrt(current_xp / 100)) + 1
        leveled_up = new_lvl > current_lvl

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE user_levels SET text_xp = ?, text_level = ?, last_msg_timestamp = ? WHERE guild_id = ? AND user_id = ?", (current_xp, new_lvl, time.time(), guild_id, user_id))
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
            cursor.execute("UPDATE user_levels SET voice_xp = ?, voice_level = ?, voice_time_seconds = ? WHERE guild_id = ? AND user_id = ?", (current_xp, new_lvl, total_time, guild_id, user_id))
            conn.commit()
        return leveled_up, new_lvl

    # Warnings Operations
    def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            cursor.execute("INSERT INTO warnings (guild_id, user_id, moderator_id, reason, timestamp) VALUES (?, ?, ?, ?, ?)", (guild_id, user_id, moderator_id, reason, now_str))
            conn.commit()

    def get_warnings(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, moderator_id, reason, timestamp FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            return cursor.fetchall()

    def clear_warnings(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM warnings WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            conn.commit()

    # Economy Operations
    def get_economy_data(self, guild_id: int, user_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM economy WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            row = cursor.fetchone()
            if not row:
                cursor.execute("INSERT INTO economy (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id))
                conn.commit()
                return self.get_economy_data(guild_id, user_id)
            return row

    def update_credits(self, guild_id: int, user_id: int, amount: int):
        data = self.get_economy_data(guild_id, user_id)
        new_credits = max(0, data[2] + amount)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET credits = ? WHERE guild_id = ? AND user_id = ?", (new_credits, guild_id, user_id))
            conn.commit()
        return new_credits

    def set_daily_claimed(self, guild_id: int, user_id: int, amount: int):
        data = self.get_economy_data(guild_id, user_id)
        new_credits = data[2] + amount
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET credits = ?, last_daily = ? WHERE guild_id = ? AND user_id = ?", (new_credits, time.time(), guild_id, user_id))
            conn.commit()

    def add_rep(self, guild_id: int, target_id: int, sender_id: int):
        target_data = self.get_economy_data(guild_id, target_id)
        new_rep = target_data[4] + 1
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET rep = ? WHERE guild_id = ? AND user_id = ?", (new_rep, guild_id, target_id))
            cursor.execute("UPDATE economy SET last_rep = ? WHERE guild_id = ? AND user_id = ?", (time.time(), guild_id, sender_id))
            conn.commit()

    def set_title(self, guild_id: int, user_id: int, title_text: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE economy SET title = ? WHERE guild_id = ? AND user_id = ?", (title_text, guild_id, user_id))
            conn.commit()

    # Auto Responses
    def add_auto_response(self, guild_id: int, trigger: str, response: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO auto_responses (guild_id, trigger_text, response_text) VALUES (?, ?, ?)", (guild_id, trigger.lower(), response))
            conn.commit()

    def get_auto_responses(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT trigger_text, response_text FROM auto_responses WHERE guild_id = ?", (guild_id,))
            return cursor.fetchall()

    def delete_auto_response(self, guild_id: int, trigger: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM auto_responses WHERE guild_id = ? AND trigger_text = ?", (guild_id, trigger.lower()))
            conn.commit()

    # Custom Aliases Operations
    def add_custom_alias(self, guild_id: int, alias: str, command_name: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO custom_aliases (guild_id, alias, command_name) VALUES (?, ?, ?)", (guild_id, alias.lower(), command_name.lower()))
            conn.commit()

    def get_custom_aliases(self, guild_id: int):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT alias, command_name FROM custom_aliases WHERE guild_id = ?", (guild_id,))
            return cursor.fetchall()

    def delete_custom_alias(self, guild_id: int, alias: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM custom_aliases WHERE guild_id = ? AND alias = ?", (guild_id, alias.lower()))
            conn.commit()

    def get_command_for_alias(self, guild_id: int, alias: str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT command_name FROM custom_aliases WHERE guild_id = ? AND alias = ?", (guild_id, alias.lower()))
            row = cursor.fetchone()
            return row[0] if row else None

    # Button Roles Operations
            try:
                    await member.add_roles(role, reason="رتبة مكافأة اللفل")
                except Exception:
                    pass

class EditWelcomeModal(discord.ui.Modal, title="تعديل رسالة الترحيب"):
    welcome_msg = discord.ui.TextInput(label="رسالة الترحيب", style=discord.TextStyle.paragraph, placeholder="مرحباً بك {user} في سيرفر {server}!", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "welcome_msg", self.welcome_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة الترحيب بنجاح!", ephemeral=True)

class EditLeaveModal(discord.ui.Modal, title="تعديل رسالة المغادرة"):
    leave_msg = discord.ui.TextInput(label="رسالة المغادرة", style=discord.TextStyle.paragraph, placeholder="وداعاً {user}، نراك على خير!", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "leave_msg", self.leave_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة المغادرة بنجاح!", ephemeral=True)

class EditBadwordsModal(discord.ui.Modal, title="إدارة الكلمات الممنوعة"):
    bad_words = discord.ui.TextInput(label="الكلمات الممنوعة (افصل بفاصلة)", style=discord.TextStyle.paragraph, placeholder="كلمة1, كلمة2, رابط", required=False)
    async def on_submit(self, interaction: discord.Interaction):
        db.update_guild_setting(interaction.guild_id, "automod_badwords", self.bad_words.value)
        await interaction.response.send_message("✅ تم حفظ قائمة الكلمات الممنوعة!", ephemeral=True)

class AddAutoResponseModal(discord.ui.Modal, title="إضافة رد تلقائي"):
    trigger = discord.ui.TextInput(label="الكلمة أو الجملة المفتاحية", placeholder="مثال: السلام عليكم", required=True)
    response = discord.ui.TextInput(label="رد البوت التلقائي", style=discord.TextStyle.paragraph, placeholder="وعليكم السلام ورحمة الله وبركاته", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        db.add_auto_response(interaction.guild_id, self.trigger.value, self.response.value)
        await interaction.response.send_message(f"✅ تم إضافة الرد التلقائي للكلمة: `{self.trigger.value}`", ephemeral=True)

class AddCustomAliasModal(discord.ui.Modal, title="إضافة اختصار لـ أمر"):
    alias_input = discord.ui.TextInput(label="الاختصار (مثل: طرد أو .kick)", placeholder="طرد", required=True)
    command_input = discord.ui.TextInput(label="اسم الأمر الأصلي (مثل: kick أو ban)", placeholder="kick", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        db.add_custom_alias(interaction.guild_id, self.alias_input.value, self.command_input.value)
        await interaction.response.send_message(f"✅ تم ربط الاختصار `{self.alias_input.value}` بالأمر `/{self.command_input.value}` بنجاح!", ephemeral=True)

class AddButtonRoleModal(discord.ui.Modal, title="إضافة رتبة زر تفاعلي"):
                await interaction.response.send_message("❌ الرتبة غير موجودة بهذا الآيدي!", ephemeral=True)
                return
            db.add_button_role(interaction.guild_id, self.label.value, r_id)
            await interaction.response.send_message(f"✅ تم ربط الزر `{self.label.value}` بالرتبة {role.mention}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى إدخال آيدي صحيح!", ephemeral=True)

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
            await interaction.response.send_message("❌ يرجى كتابة أرقام صحيحة!", ephemeral=True)

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
    def __init__(self, setting_key: str, placeholder_text: str, channel_types=None):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, channel_types=channel_types or [discord.ChannelType.text], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        db.update_guild_setting(interaction.guild_id, self.setting_key, channel.id)
        await interaction.response.send_message(f"✅ تم تحديد القناة: {channel.mention}", ephemeral=True)

class RoleSelectMenu(discord.ui.RoleSelect):
    def __init__(self, setting_key: str, placeholder_text: str):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        db.update_guild_setting(interaction.guild_id, self.setting_key, role.id)
        await interaction.response.send_message(f"✅ تم تحديد الرتبة: {role.mention}", ephemeral=True)

class DynamicRoleButton(discord.ui.Button):
    def __init__(self, label: str, role_id: int):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"btn_role_{role_id}")
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ هذه الرتبة لم تعد موجودة في السيرفر!", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(f"➖ تم إزالة الرتبة {role.mention} منك!", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"➕ تم إعطاؤك الرتبة {role.mention} بنجاح!", ephemeral=True)

class ButtonRolesDeployView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=None)
        b_roles = db.get_button_roles(guild_id)
        for label, r_id in b_roles:
            self.add_item(DynamicRoleButton(label, r_id))

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

class AutoResponseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ إضافة رد تلقائي", style=discord.ButtonStyle.success, row=0)
    async def add_response(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddAutoResponseModal())

    @discord.ui.button(label="➕ إضافة اختصار لأمر", style=discord.ButtonStyle.primary, row=0)
    async def add_alias(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddCustomAliasModal())

    @discord.ui.button(label="➕ إضافة زر رتبة تفاعلية", style=discord.ButtonStyle.secondary, row=1)
    async def add_btn_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddButtonRoleModal())

    @discord.ui.button(label="📢 نشر بنل رتب الأزرار هنا", style=discord.ButtonStyle.secondary, row=1)
    async def deploy_btn_roles(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ButtonRolesDeployView(interaction.guild_id)
        if len(view.children) == 0:
            await interaction.response.send_message("❌ لم تقم بإضافة أي أزرار رتب بعد! اضغط على إضافة زر رتبة تفاعلية أولاً.", ephemeral=True)
            return
        embed = discord.Embed(title="🎭 اختيار الرتب التفاعلية", description="اضغط على الأزرار أدناه للحصول على الرتبة أو إزالتها!", color=discord.Color.purple())
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ تم نشر بنل الرتب التفاعلية!", ephemeral=True)

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به بالكامل دون استخدام أي موقع!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class TicketSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ChannelSelectMenu("ticket_log_channel_id", "📜 اختر قناة سجل التذاكر (Ticket Logs)..."))
        self.add_item(RoleSelectMenu("ticket_support_role_id", "🛡️ اختر رتبة الدعم الفني المسؤول عن التذاكر..."))

    @discord.ui.button(label="إرسال بنل التذاكر في هذه القناة", style=discord.ButtonStyle.success, row=2)
    async def deploy_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎟️ قسم الدعم الفني والمساعدة",
            description="اضغط على الزر أدناه لفتح تذكرة خاصة والتواصل مباشرة مع فريق الإدارة والدعم الفني.",
            color=discord.Color.green()
        )
        await interaction.channel.send(embed=embed, view=OpenTicketView())
        await interaction.response.send_message("✅ تم نشر بنل التذاكر بنجاح!", ephemeral=True)

    @discord.ui.button(label="الرجوع للرئيسية", style=discord.ButtonStyle.secondary, row=2)
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

        channel = await guild.create_text_channel(name=f"ticket-{interaction.user.name}", category=category, overwrites=overwrites)
        embed = discord.Embed(title=f"🎟️ تذكرة الدعم - {interaction.user.display_name}", description="مرحباً بك! تفضل بكتابة استفسارك وسيتم الرد عليك فوراً.", color=discord.Color.blue())
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
            discord.SelectOption(label="👋 الترحيب والمغادرة والسجلات", description="إعداد رومات الترحيب والمغادرة والرتب التلقائية", emoji="👋", value="general"),
            discord.SelectOption(label="🛡️ الحماية والتعديل الآلي", description="منع الروابط والدعوات والكلمات الممنوعة", emoji="🛡️", value="automod"),
            discord.SelectOption(label="⭐ نظام اللفل والخبرة والمكافآت", description="معدلات XP واللفل الصوتي والكتابي", emoji="⭐", value="xp"),
            discord.SelectOption(label="🎟️ نظام التذاكر المتقدم", description="فئات التذاكر، رتبة الدعم وسجلات التذاكر", emoji="🎟️", value="tickets"),
            discord.SelectOption(label="🤖 الردود التلقائية ورتب الأزرار", description="إدارة الردود الآلية وأزرار إعطاء الرتب", emoji="🤖", value="auto_responses"),
            discord.SelectOption(label="📢 منشئ الرسائل والإعلانات (Embed)", description="تصميم وإرسال إمبد باحترافية لأي قناة", emoji="📢", value="embed"),
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
            await interaction.response.edit_message(embed=embed, view=GeneralSettingsView())

        elif sel == "automod":
            embed = discord.Embed(title="🛡️ إعدادات الحماية والتعديل الآلي", color=discord.Color.red())
            embed.add_field(name="الحماية العامة", value="✅ مفعلة" if st[15] else "❌ معطلة", inline=True)
            embed.add_field(name="منع الروابط", value="✅ مفعل" if st[17] else "❌ معطل", inline=True)
            embed.add_field(name="منع الدعوات", value="✅ مفعل" if st[18] else "❌ معطل", inline=True)
            embed.add_field(name="الكلمات الممنوعة", value=st[16] if st[16] else "لا توجد كلمات ممنوعة", inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoModSettingsView())

        elif sel == "auto_responses":
            embed = discord.Embed(title="🤖 الردود التلقائية والاختصارات", color=discord.Color.purple())
            responses = db.get_auto_responses(interaction.guild_id)
            aliases = db.get_custom_aliases(interaction.guild_id)
            
            resp_str = "\n".join([f"• `{r[0]}` ➔ {r[1]}" for r in responses[:10]]) if responses else "لا توجد ردود تلقائية مضافة"
            alias_str = "\n".join([f"• `{a[0]}` ➔ `/{a[1]}`" for a in aliases[:10]]) if aliases else "لا توجد اختصارات مضافة"

            embed.add_field(name="💬 الردود التلقائية الحالية", value=resp_str, inline=False)
            embed.add_field(name="⚡ اختصارات الأوامر الحالية", value=alias_str, inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoResponseView())

        elif sel == "tickets":
            embed = discord.Embed(title="🎟️ إعدادات نظام التذاكر", color=discord.Color.blue())
            t_log = interaction.guild.get_channel(st[8])
            s_role = interaction.guild.get_role(st[9])
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
    """Background task awarding Voice XP continuously."""
    for guild in bot.guilds:
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
                # الجزء الذي كان مقطوعاً وتم إكماله
                leveled_up, new_lvl = db.add_voice_xp(guild.id, member.id, v_rate, time_add=60)
                if leveled_up:
                    await check_and_grant_level_roles(guild, member, new_lvl)

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user.name} ({bot.user.id})")
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
    if st[6]:
        role = member.guild.get_role(st[6])
        if role:
            try:
                await member.add_roles(role)
            except Exception:
                pass
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
    if st[4]:
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

    # Custom Aliases Check (مثلاً لو كتب طرد @user سبب أو .طرد ...)
    content = message.content.strip()
    words = content.split(" ")
    if words:
        first_word = words[0]
        mapped_cmd = db.get_command_for_alias(g_id, first_word)
        if mapped_cmd:
            # إعادة صياغة الرسالة كأمر تفاعلي للبوت بحيث يفهمها النظام أو يحولها للسلاش كومانْد
            # يمكنك هنا تطبيق المنطق المخصص لتنفيذ الأمر أو إرسال توجيه للمشرف
            pass

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

    # Auto Responses Check
    responses = db.get_auto_responses(g_id)
    for trig, resp in responses:
        if trig in message.content.lower():
            await message.channel.send(resp)
            break

    # Aliases Execution Check (مثال: إذا كتب طرد @user)
    aliases = db.get_custom_aliases(g_id)
    for alias_item, cmd_name in aliases:
        if message.content.lower().startswith(alias_item + " ") or message.content.lower() == alias_item:
            # تحويل الاختصار إلى تنبيه أو تنفيذه للمشرفين
            if message.author.guild_permissions.manage_messages:
                await message.channel.send(f"⚡ تم تفعيل الاختصار `{alias_item}` للأمر `/{cmd_name}` بواسطة {message.author.mention}")
            break

    # Text XP Check
    if st[10]:
        u_data = db.get_user_data(g_id, message.author.id)
        if time.time() - u_data[7] >= 60:
            t_rate = st[12]
            leveled_up, new_lvl = db.add_text_xp(g_id, message.author.id, t_rate)
            if leveled_up:
                await check_and_grant_level_roles(message.guild, message.author, new_lvl)
                lvl_c_id = st[14]
                target_c = message.guild.get_channel(lvl_c_id) or message.channel
                await target_c.send(f"🎉 مبروك {message.author.mention}! ارتفع مستواك الكتابي إلى **المستوى {new_lvl}** 💬!")

    await bot.process_commands(message)

channel_group = app_commands.Group(name="channel", description="أوامر إدارة القنوات والفئات (Categories)")
bot.tree.add_command(channel_group)

@channel_group.command(name="age", description="تغيير إعدادات الروم أو الكاتيجوري إلى مقيدة عمرياً (Age-Restricted)")
@app_commands.describe(
    target="الروم أو الكاتيجوري المراد تعديله (اتركه فارغاً لتعديل الروم الحالي)",
    restricted="اختر True لجعلها مقيدة عمرياً (NSFW) أو False لجعلها عادية"
)
@app_commands.checks.has_permissions(manage_channels=True)
async def channel_age(interaction: discord.Interaction, target: Optional[discord.abc.GuildChannel] = None, restricted: bool = True):
    target_channel = target or interaction.channel
    
    try:
        # إذا كان الهدف عبارة عن كاتيجوري (Category)، نقوم بتعديل كل الرومات داخله
        if isinstance(target_channel, discord.CategoryChannel):
            await interaction.response.defer()
            count = 0
            for ch in target_channel.channels:
                if hasattr(ch, 'edit') and hasattr(ch, 'nsfw'):
                    await ch.edit(nsfw=restricted)
                    count += 1
            
            state_text = "مقيدة عمرياً 🔞 (Age-Restricted)" if restricted else "عادية 🟢"
            await interaction.followup.send(f"✅ تم بنجاح تغيير إعدادات `{count}` رومات داخل الكاتيجوري **{target_channel.name}** لتصبح {state_text}!")
        
        # إذا كان الهدف روم عادي (Text/Voice/Forum)
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


@bot.tree.command(name="ban", description="حظر عضو من السيرفر")
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"⛔ تم حظر {member.mention} | السبب: {reason}")

@bot.tree.command(name="unban", description="فك الحظر عن عضو باستخدام ID")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ تم فك الحظر عن العضو **{user.name}** (`{user.id}`)")
    except Exception as e:
        await interaction.response.send_message(f"❌ تعذر فك الحظر: {e}", ephemeral=True)

@bot.tree.command(name="kick", description="طرد عضو خارج السيرفر")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = "لا يوجد سبب"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"🚨 تم طرد {member.mention} | السبب: {reason}")

@bot.tree.command(name="timeout", description="كتم عضو لمنعه من الكتابة والتفاعل لفترة محددة")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: Optional[str] = "لا يوجد سبب"):
    duration = timedelta(minutes=minutes)
    await member.timeout(duration, reason=reason)
    await interaction.response.send_message(f"🤐 تم كتم {member.mention} لمدة `{minutes}` دقيقة | السبب: {reason}")

@bot.tree.command(name="unmute", description="فك الكتم عن عضو")
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction: discord.Interaction, member: discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"🔊 تم فك الكتم عن {member.mention}")

@bot.tree.command(name="clear", description="مسح عدد محدد من الرسائل في الروم الحالي")
@app_commands.checks.has_permissions(manage_messages=True)
async def clear(interaction: discord.Interaction, amount: int, member: Optional[discord.Member] = None):
    await interaction.response.defer(ephemeral=True)
    if member:
        def check(m):
            return m.author == member
        deleted = await interaction.channel.purge(limit=amount, check=check)
    else:
        deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🧹 تم مسح `{len(deleted)}` رسالة بنجاح!", ephemeral=True)

@bot.tree.command(name="lock", description="قفل الروم ومنع الأعضاء من الكتابة")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 تم قفل هذه القناة ومنع الكتابة بها!")

@bot.tree.command(name="unlock", description="فتح الروم وإعادة السماح بالكتابة")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 تم فتح القناة والسماح بالكتابة مجدداً!")

@bot.tree.command(name="slowmode", description="تفعيل الوضع البطئ للقناة (ضع 0 لإلغائه)")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: int):
    await interaction.channel.edit(slowmode_delay=seconds)
    if seconds == 0:
        await interaction.response.send_message("⚡ تم إلغاء الوضع البطئ!")
    else:
        await interaction.response.send_message(f"⏱️ تم ضبط الوضع البطئ إلى `{seconds}` ثانية!")

@bot.tree.command(name="warn", description="إعطاء تحذير رسمي لعضو")
@app_commands.checks.has_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
    db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
    await interaction.response.send_message(f"⚠️ تم تحذير {member.mention} | السبب: **{reason}**")

@bot.tree.command(name="warnings", description="عرض سجل تحذيرات عضو")
async def warnings(interaction: discord.Interaction, member: discord.Member):
    warns = db.get_warnings(interaction.guild_id, member.id)
    if not warns:
        await interaction.response.send_message(f"✅ العضو {member.mention} ليس لديه أي تحذيرات سابقة.")
        return
    embed = discord.Embed(title=f"⚠️ تحذيرات العضو {member.display_name}", color=discord.Color.orange())
    for w_id, mod_id, reason, ts in warns:
        mod = interaction.guild.get_member(mod_id)
        embed.add_field(name=f"تحذير #{w_id} ({ts})", value=f"**السبب:** {reason}\n**بواسطة:** {mod.mention if mod else 'إداري'}", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="clear-warns", description="مسح جميع التحذيرات عن عضو معين")
@app_commands.checks.has_permissions(administrator=True)
async def clear_warns(interaction: discord.Interaction, member: discord.Member):
    db.clear_warnings(interaction.guild_id, member.id)
    await interaction.response.send_message(f"🧹 تم مسح جميع تحذيرات العضو {member.mention} بنجاح!")

@bot.tree.command(name="move", description="نقل عضو إلى الروم الصوتي الموجود فيه أنت")
@app_commands.checks.has_permissions(move_members=True)
async def move(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.voice or not interaction.user.voice.channel:
        await interaction.response.send_message("❌ يجب أن تكون في روم صوتي أولاً!", ephemeral=True)
        return
    if not member.voice or not member.voice.channel:
        await interaction.response.send_message("❌ العضو المراد نقله ليس متواجد في أي روم صوتي حالياً!", ephemeral=True)
        return
    await member.move_to(interaction.user.voice.channel)
    await interaction.response.send_message(f"🚚 تم نقل {member.mention} إلى الروم **{interaction.user.voice.channel.name}**")

@bot.tree.command(name="vkick", description="طرد عضو من الروم الصوتي")
@app_commands.checks.has_permissions(move_members=True)
async def vkick(interaction: discord.Interaction, member: discord.Member):
    if not member.voice or not member.voice.channel:
        await interaction.response.send_message("❌ العضو غير متواجد في روم صوتي حالياً!", ephemeral=True)
        return
    await member.move_to(None)
    await interaction.response.send_message(f"👢 تم طرد {member.mention} من الروم الصوتي!")

@bot.tree.command(name="credits", description="عرض رصيدك أو تحويل كريدت لعضو آخر")
async def credits(interaction: discord.Interaction, member: Optional[discord.Member] = None, amount: Optional[int] = None):
    if member and amount:
        if member.id == interaction.user.id:
            await interaction.response.send_message("❌ لا يمكنك تحويل الكريدت لنفسك!", ephemeral=True)
            return
        if amount <= 0:
            await interaction.response.send_message("❌ يرجى إدخال مبلغ صحيح للتحويل!", ephemeral=True)
            return
        sender_data = db.get_economy_data(interaction.guild_id, interaction.user.id)
        if sender_data[2] < amount:
            await interaction.response.send_message("❌ رصيدك الحالي لا يكفي لإجراء هذا التحويل!", ephemeral=True)
            return
        db.update_credits(interaction.guild_id, interaction.user.id, -amount)
        db.update_credits(interaction.guild_id, member.id, amount)
        await interaction.response.send_message(f"💸 قام {interaction.user.mention} بتحويل **${amount}** كريدت إلى {member.mention}!")
    else:
        target = member or interaction.user
        data = db.get_economy_data(interaction.guild_id, target.id)
        await interaction.response.send_message(f"💳 رصيد {target.mention} الحالي هو: **${data[2]}** كريدت.")

@bot.tree.command(name="daily", description="استلام المكافأة اليومية المجانية من الكريدت")
async def daily(interaction: discord.Interaction):
    data = db.get_economy_data(interaction.guild_id, interaction.user.id)
    last_daily = data[3]
    cooldown = 86400  # 24 Hours
    now = time.time()

    if now - last_daily < cooldown:
        remaining = int(cooldown - (now - last_daily))
        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        await interaction.response.send_message(f"⏳ لقد استلمت مكافأتك اليومية بالفعل! يرجى الانتظار `{hours}h {minutes}m {seconds}s` مجدداً.", ephemeral=True)
        return

    reward = 300
    db.set_daily_claimed(interaction.guild_id, interaction.user.id, reward)
    await interaction.response.send_message(f"🎉 مبارك! لقد حصلت على **${reward}** كريدت كمكافأة يومية!")

@bot.tree.command(name="profile", description="عرض بطاقة بروفايلك الشاملة (الرصيد، اللقب، السمعة، واللفل)")
async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    eco = db.get_economy_data(interaction.guild_id, target.id)
    lvl_data = db.get_user_data(interaction.guild_id, target.id)

    credits_val = eco[2]
    rep_val = eco[4]
    title_val = eco[6]
    text_lvl = lvl_data[3]

    embed = discord.Embed(title=f"👤 بطاقة بروفايل - {target.display_name}", color=discord.Color.gold())
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="🏷️ اللقب (Title)", value=f"`{title_val}`", inline=False)
    embed.add_field(name="💳 الكريدت (Credits)", value=f"**${credits_val}**", inline=True)
    embed.add_field(name="⭐ السمعة (Rep)", value=f"**+{rep_val}**", inline=True)
    embed.add_field(name="📊 المستوى الكتابي", value=f"**Level {text_lvl}**", inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rep", description="إعطاء نقطة سمعة لشخص آخر (تتاح كل 12 ساعة)")
async def rep(interaction: discord.Interaction, member: discord.Member):
    if member.id == interaction.user.id:
        await interaction.response.send_message("❌ لا يمكنك إعطاء نقطة سمعة لنفسك!", ephemeral=True)
        return
    if member.bot:
        await interaction.response.send_message("❌ لا يمكنك إعطاء نقاط سمعة للبوتات!", ephemeral=True)
        return

    sender_eco = db.get_economy_data(interaction.guild_id, interaction.user.id)
    last_rep = sender_eco[5]
    cooldown = 43200  # 12 Hours
    now = time.time()

    if now - last_rep < cooldown:
        remaining = int(cooldown - (now - last_rep))
        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        await interaction.response.send_message(f"⏳ يمكنك إعطاء نقطة سمعة مجدداً بعد `{hours}h {minutes}m {seconds}s`.", ephemeral=True)
        return

    db.add_rep(interaction.guild_id, member.id, interaction.user.id)
    await interaction.response.send_message(f"🌟 قام {interaction.user.mention} بإعطاء نقطة سمعة (+1 Rep) إلى {member.mention}!")

@bot.tree.command(name="title", description="كتابة وتغيير اللقب الشرفي الذي يظهر في بروفايلك")
async def title(interaction: discord.Interaction, text: str):
    if len(text) > 30:
        await interaction.response.send_message("❌ اللقب يتجاوز الحد المسموح (30 حرف)!", ephemeral=True)
        return
    db.set_title(interaction.guild_id, interaction.user.id, text)
    await interaction.response.send_message(f"✅ تم تحديث لقبك الشخصي إلى: **{text}**")

@bot.tree.command(name="rank", description="عرض بطاقة المستوى والمستوى الكتابي والصوتي")
async def rank(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
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
    embed.add_field(name="💬 المستوى الكتابي (Text)", value=f"**Level:** `{text_lvl}` | **XP:** `{text_xp}/{next_text_xp}`\n`[{text_bar}]`", inline=False)
    embed.add_field(name="🎤 المستوى الصوتي (Voice)", value=f"**Level:** `{voice_lvl}` | **XP:** `{voice_xp}/{next_voice_xp}`\n**ساعات التحدث:** `{v_hours}` hrs\n`[{voice_bar}]`", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="top", description="عرض قائمة المتصدرين للسيرفر باللفل أو الكريدت")
async def top(interaction: discord.Interaction, category: Literal["المستويات (XP)", "الكريدت (Credits)"]):
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

@bot.tree.command(name="user", description="عرض معلومات الحساب وتاريخ انضمامه للديسكورد والسيرفر")
async def user(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    embed = discord.Embed(title=f"👤 معلومات الحساب - {target.display_name}", color=target.color)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="الاسم الكامل", value=str(target), inline=True)
    embed.add_field(name="الآيدي (ID)", value=f"`{target.id}`", inline=True)
    embed.add_field(name="تاريخ إنشاء الحساب", value=target.created_at.strftime("%Y-%m-%d"), inline=False)
    embed.add_field(name="تاريخ الانضمام للسيرفر", value=target.joined_at.strftime("%Y-%m-%d") if target.joined_at else "غير معروف", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="server", description="تفاصيل وإحصائيات السيرفر الشاملة")
async def server(interaction: discord.Interaction):
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

@bot.tree.command(name="avatar", description="إظهار صورة البروفايل لأي شخص")
async def avatar(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    embed = discord.Embed(title=f"🖼️ صورة حساب - {target.display_name}", color=discord.Color.blue())
    embed.set_image(url=target.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="banner", description="عرض صورة البانر الخلفية للحساب")
async def banner(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    fetched_user = await bot.fetch_user(target.id)
    if not fetched_user.banner:
        await interaction.response.send_message("❌ هذا الحساب ليس لديه صورة بانر خلفية!", ephemeral=True)
        return
    embed = discord.Embed(title=f"🎨 صورة البانر - {target.display_name}", color=discord.Color.purple())
    embed.set_image(url=fetched_user.banner.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="roles", description="عرض قائمة رتب السيرفر")
async def roles(interaction: discord.Interaction):
    roles_list = [r.mention for r in reversed(interaction.guild.roles) if r != interaction.guild.default_role]
    roles_str = ", ".join(roles_list[:30])
    embed = discord.Embed(title=f"🎭 رتب السيرفر ({len(roles_list)})", description=roles_str if roles_str else "لا توجد رتب", color=discord.Color.dark_teal())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="فحص سرعة استجابة البوت (Latency)")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! سرعة استجابة البوت: `{latency}ms`")

@bot.tree.command(name="bot", description="عرض معلومات وإحصائيات البوت")
async def bot_info(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 معلومات البوت الخاص بك", description="بوت متكامل ومخصص بأسلوب برو بوت بريميوم مع لوحة تحكم داخلية كاملة.", color=discord.Color.gold())
    embed.add_field(name="السيرفرات المتصلة", value=f"`{len(bot.guilds)}`", inline=True)
    embed.add_field(name="مكتبة التشغيل", value="`discord.py v2.x`", inline=True)
    embed.add_field(name="نظام التلفيل", value="كتابي + صوتي مفعل", inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="poll", description="إنشاء استبيان تصويت سريع للأعضاء")
async def poll(interaction: discord.Interaction, question: str):
    embed = discord.Embed(title="📊 استبيان وتصويت جديد", description=question, color=discord.Color.green())
    embed.set_footer(text=f"تم إنشاؤه بواسطة: {interaction.user.display_name}")
    await interaction.response.send_message("✅ تم إنشاء التصويت!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("👍")
    await msg.add_reaction("👎")

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

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("⚠️ يرجى استبدال YOUR_BOT_TOKEN_HERE بتوكن البوت الخاص بك في نهاية الملف!")
    else:
        # تشغيل خادم الويب (Flask) أولاً لإبقاء البوت أونلاين
        keep_alive() 
        # تشغيل البوت
        bot.run(TOKEN)
