import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import db

# ==================== المودلز (Modals) ====================

class EditWelcomeModal(discord.ui.Modal, title="تعديل رسالة الترحيب"):
    welcome_msg = discord.ui.TextInput(label="رسالة الترحيب", style=discord.TextStyle.paragraph, placeholder="مرحباً بك {user} في سيرفر {server}!", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "welcome_msg", self.welcome_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة الترحيب بنجاح!", ephemeral=True)

class EditLeaveModal(discord.ui.Modal, title="تعديل رسالة المغادرة"):
    leave_msg = discord.ui.TextInput(label="رسالة المغادرة", style=discord.TextStyle.paragraph, placeholder="وداعاً {user}، نراك على خير!", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "leave_msg", self.leave_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة المغادرة بنجاح!", ephemeral=True)

class EditBadwordsModal(discord.ui.Modal, title="إدارة الكلمات الممنوعة"):
    bad_words = discord.ui.TextInput(label="الكلمات الممنوعة (افصل بفاصلة)", style=discord.TextStyle.paragraph, placeholder="كلمة1, كلمة2, رابط", required=False)
    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "automod_badwords", self.bad_words.value)
        await interaction.response.send_message("✅ تم حفظ قائمة الكلمات الممنوعة!", ephemeral=True)

class AddAutoResponseModal(discord.ui.Modal, title="إضافة رد تلقائي"):
    trigger = discord.ui.TextInput(label="جملة المستخدم", placeholder="مثال: السلام عليكم", required=True)
    response = discord.ui.TextInput(label="رد البوت التلقائي", style=discord.TextStyle.paragraph, placeholder="وعليكم السلام", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await db.add_auto_response(interaction.guild_id, self.trigger.value, self.response.value)
        await interaction.response.send_message(f"✅ تم إضافة الرد للكلمة: `{self.trigger.value}`", ephemeral=True)

class AddCustomAliasModal(discord.ui.Modal, title="إضافة اختصار لـ أمر"):
    alias_input = discord.ui.TextInput(label="الاختصار", placeholder="طرد", required=True)
    command_input = discord.ui.TextInput(label="اسم الأمر الأصلي", placeholder="kick", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await db.add_custom_alias(interaction.guild_id, self.alias_input.value, self.command_input.value)
        await interaction.response.send_message(f"✅ تم ربط الاختصار `{self.alias_input.value}` بالأمر `/{self.command_input.value}`!", ephemeral=True)

class AddButtonRoleModal(discord.ui.Modal, title="إضافة رتبة زر تفاعلي"):
    label = discord.ui.TextInput(label="اسم الزر", placeholder="VIP", required=True)
    role_id_input = discord.ui.TextInput(label="آيدي الرتبة (Role ID)", placeholder="123456789...", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            r_id = int(self.role_id_input.value)
            role = interaction.guild.get_role(r_id)
            if not role:
                await interaction.response.send_message("❌ الرتبة غير موجودة بهذا الآيدي!", ephemeral=True)
                return
            await db.add_button_role(interaction.guild_id, self.label.value, r_id)
            await interaction.response.send_message(f"✅ تم ربط الزر `{self.label.value}` بالرتبة {role.mention}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى إدخال آيدي صحيح!", ephemeral=True)

class ChangeXPRatesModal(discord.ui.Modal, title="تعديل معدل الـ XP"):
    text_rate = discord.ui.TextInput(label="خبرة الكتابة", default="15", max_length=4)
    voice_rate = discord.ui.TextInput(label="خبرة الصوت", default="10", max_length=4)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            t_rate = int(self.text_rate.value)
            v_rate = int(self.voice_rate.value)
            await db.update_guild_setting(interaction.guild_id, "text_xp_rate", t_rate)
            await db.update_guild_setting(interaction.guild_id, "voice_xp_rate", v_rate)
            await interaction.response.send_message(f"✅ تم تحديث معدل الخبرة بنجاح!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى كتابة أرقام صحيحة!", ephemeral=True)


# ==================== الـ Views والأزرار ====================

class GeneralSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تعديل رسالة الترحيب", style=discord.ButtonStyle.primary, row=0)
    async def edit_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditWelcomeModal())

    @discord.ui.button(label="تعديل رسالة المغادرة", style=discord.ButtonStyle.primary, row=0)
    async def edit_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditLeaveModal())

    @discord.ui.button(label="🔙 القائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


class AutoModSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تبديل الحماية العامة", style=discord.ButtonStyle.danger, row=0)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['automod_enabled'] else 1
        await db.update_guild_setting(interaction.guild_id, "automod_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} الحماية العامة!", ephemeral=True)

    @discord.ui.button(label="منع الروابط", style=discord.ButtonStyle.primary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['anti_links'] else 1
        await db.update_guild_setting(interaction.guild_id, "anti_links", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} مانع الروابط!", ephemeral=True)

    @discord.ui.button(label="منع الدعوات", style=discord.ButtonStyle.primary, row=0)
    async def toggle_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['anti_invites'] else 1
        await db.update_guild_setting(interaction.guild_id, "anti_invites", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} مانع الدعوات!", ephemeral=True)

    @discord.ui.button(label="تعديل الكلمات الممنوعة", style=discord.ButtonStyle.secondary, row=1)
    async def edit_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditBadwordsModal())

    @discord.ui.button(label="🔙 القائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
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

    @discord.ui.button(label="➕ إضافة زر رتبة", style=discord.ButtonStyle.secondary, row=1)
    async def add_btn_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddButtonRoleModal())

    @discord.ui.button(label="🔙 القائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


class XPSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تعديل معدل الـ XP", style=discord.ButtonStyle.primary, row=0)
    async def edit_rates(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeXPRatesModal())

    @discord.ui.button(label="🔙 القائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


class TicketSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="إرسال بنل التذاكر هنا", style=discord.ButtonStyle.success, row=0)
    async def deploy_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        from dashboard import OpenTicketView
        embed = discord.Embed(title="🎟️ قسم الدعم الفني", description="اضغط الزر أدناه لفتح تذكرة.", color=discord.Color.green())
        await interaction.channel.send(embed=embed, view=OpenTicketView())
        await interaction.response.send_message("✅ تم نشر بنل التذاكر!", ephemeral=True)

    @discord.ui.button(label="🔙 القائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


# ==================== التذاكر (Persistent Views) ====================

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 فتح تذكرة جديدة", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn_pro")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        st = await db.get_guild_settings(guild.id)
        cat_id = st['ticket_category_id']
        support_role_id = st['ticket_support_role_id']
        
        category = guild.get_channel(cat_id) if cat_id else None
        support_role = guild.get_role(support_role_id) if support_role_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel = await guild.create_text_channel(name=f"ticket-{interaction.user.name}", category=category, overwrites=overwrites)
        embed = discord.Embed(title=f"🎟️ تذكرة الدعم - {interaction.user.display_name}", description="أهلاً بك! يرجى توضيح مشكلتك.", color=discord.Color.blue())
        await channel.send(content=f"{interaction.user.mention} {support_role.mention if support_role else ''}", embed=embed, view=CloseTicketView())
        await interaction.followup.send(f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True)


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn_pro")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 سيتم إغلاق التذكرة خلال 5 ثوانٍ...")
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except:
            pass


# ==================== القائمة الرئيسية (Select Menu) ====================

class DashboardSelectMenu(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👋 الترحيب والمغادرة", description="إعداد رسائل الترحيب والمغادرة", emoji="👋", value="general"),
            discord.SelectOption(label="🛡️ الحماية والتعديل الآلي", description="إدارة الحماية ومنع الروابط", emoji="🛡️", value="automod"),
            discord.SelectOption(label="⭐ نظام اللفل والخبرة", description="تعديل معدلات الـ XP", emoji="⭐", value="xp"),
            discord.SelectOption(label="🎟️ نظام التذاكر", description="نشر بنل التذاكر", emoji="🎟️", value="tickets"),
            discord.SelectOption(label="🤖 الردود التلقائية والأزرار", description="إدارة الردود والاختصارات", emoji="🤖", value="auto_responses"),
        ]
        super().__init__(placeholder="📂 اختر القسم للتحكم به...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        sel = self.values[0]
        st = await db.get_guild_settings(interaction.guild_id)

        if sel == "general":
            embed = discord.Embed(title="👋 إعدادات الترحيب والمغادرة", color=discord.Color.green())
            embed.add_field(name="رسالة الترحيب الحالية", value=f"`{st['welcome_msg']}`", inline=False)
            embed.add_field(name="رسالة المغادرة الحالية", value=f"`{st['leave_msg']}`", inline=False)
            await interaction.response.edit_message(embed=embed, view=GeneralSettingsView())

        elif sel == "automod":
            embed = discord.Embed(title="🛡️ إعدادات الحماية", color=discord.Color.red())
            embed.add_field(name="الحماية العامة", value="✅ مفعلة" if st['automod_enabled'] else "❌ معطلة", inline=True)
            embed.add_field(name="منع الروابط", value="✅ مفعل" if st['anti_links'] else "❌ معطل", inline=True)
            embed.add_field(name="منع الدعوات", value="✅ مفعل" if st['anti_invites'] else "❌ معطل", inline=True)
            await interaction.response.edit_message(embed=embed, view=AutoModSettingsView())

        elif sel == "xp":
            embed = discord.Embed(title="⭐ إعدادات نظام اللفل", color=discord.Color.gold())
            embed.add_field(name="معدل الكتابة", value=f"`{st['text_xp_rate']}` XP", inline=True)
            embed.add_field(name="معدل الصوت", value=f"`{st['voice_xp_rate']}` XP", inline=True)
            await interaction.response.edit_message(embed=embed, view=XPSettingsView())

        elif sel == "tickets":
            embed = discord.Embed(title="🎟️ إعدادات التذاكر", color=discord.Color.blue())
            embed.description = "اضغط على الزر أدناه لنشر بنل التذاكر في هذه القناة."
            await interaction.response.edit_message(embed=embed, view=TicketSettingsView())

        elif sel == "auto_responses":
            embed = discord.Embed(title="🤖 الردود التلقائية والأزرار", color=discord.Color.purple())
            responses = await db.get_auto_responses(interaction.guild_id)
            resp_str = "\n".join([f"• `{r['trigger_text']}`" for r in responses[:10]]) if responses else "لا توجد ردود"
            embed.add_field(name="💬 الردود الحالية", value=resp_str, inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoResponseView())


class MainDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DashboardSelectMenu())


class Dashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="dashboard", description="فتح لوحة تحكم السيرفر الشاملة")
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ لوحة تحكم السيرفر الشاملة",
            description="مرحباً بك في لوحة التحكم الداخلية!\nاختر القسم الذي تريد التحكم به من القائمة أدناه:",
            color=discord.Color.blurple()
        )
        view = MainDashboardView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
