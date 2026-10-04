import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import db

# Modals
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
    response = discord.ui.TextInput(label="رد البوت التلقائي", style=discord.TextStyle.paragraph, placeholder="وعليكم السلام ورحمة الله وبركاته", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await db.add_auto_response(interaction.guild_id, self.trigger.value, self.response.value)
        await interaction.response.send_message(f"✅ تم إضافة الرد التلقائي للكلمة: `{self.trigger.value}`", ephemeral=True)

class AddCustomAliasModal(discord.ui.Modal, title="إضافة اختصار لـ أمر"):
    alias_input = discord.ui.TextInput(label="الاختصار (مثل: طرد أو .kick)", placeholder="طرد", required=True)
    command_input = discord.ui.TextInput(label="اسم الأمر الأصلي (مثل: kick أو ban)", placeholder="kick", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        await db.add_custom_alias(interaction.guild_id, self.alias_input.value, self.command_input.value)
        await interaction.response.send_message(f"✅ تم ربط الاختصار `{self.alias_input.value}` بالأمر `/{self.command_input.value}` بنجاح!", ephemeral=True)

class AddButtonRoleModal(discord.ui.Modal, title="إضافة رتبة زر تفاعلي"):
    label = discord.ui.TextInput(label="اسم الزر", placeholder="مثال: VIP", required=True)
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
    text_rate = discord.ui.TextInput(label="خبرة الكتابة (لكل رسالة)", default="15", max_length=4)
    voice_rate = discord.ui.TextInput(label="خبرة الصوت (لكل دقيقة)", default="10", max_length=4)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            t_rate = int(self.text_rate.value)
            v_rate = int(self.voice_rate.value)
            await db.update_guild_setting(interaction.guild_id, "text_xp_rate", t_rate)
            await db.update_guild_setting(interaction.guild_id, "voice_xp_rate", v_rate)
            await interaction.response.send_message(f"✅ تم تحديث معدل الخبرة: الكتابة `{t_rate}` XP | الصوت `{v_rate}` XP", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى كتابة أرقام صحيحة!", ephemeral=True)

# Embed Builder Modals & Views
class EmbedBasicsModal(discord.ui.Modal, title="تعديل أساسيات الإمبد (النص واللون)"):
    e_title = discord.ui.TextInput(label="العنوان", required=False, placeholder="عنوان الإمبد...")
    e_desc = discord.ui.TextInput(label="الوصف", style=discord.TextStyle.paragraph, required=True, placeholder="اكتب محتوى الإمبد هنا...")
    e_color = discord.ui.TextInput(label="اللون (Hex Code)", required=False, placeholder="#3498db أو اترك فارغاً")

    def __init__(self, embed: discord.Embed, view: discord.ui.View):
        super().__init__()
        self.embed = embed
        self.embed_view = view
        if embed.title: self.e_title.default = embed.title
        if embed.description: self.e_desc.default = embed.description

    async def on_submit(self, interaction: discord.Interaction):
        self.embed.title = self.e_title.value
        self.embed.description = self.e_desc.value
        if self.e_color.value:
            try:
                self.embed.color = discord.Color(int(self.e_color.value.replace("#", ""), 16))
            except: pass
        await interaction.response.edit_message(embed=self.embed, view=self.embed_view)

class EmbedImagesModal(discord.ui.Modal, title="تعديل الصور والروابط"):
    e_img = discord.ui.TextInput(label="رابط الصورة الكبيرة (URL)", required=False, placeholder="https://...")
    e_thumb = discord.ui.TextInput(label="رابط الصورة المصغرة الجانبية (URL)", required=False, placeholder="https://...")

    def __init__(self, embed: discord.Embed, view: discord.ui.View):
        super().__init__()
        self.embed = embed
        self.embed_view = view

    async def on_submit(self, interaction: discord.Interaction):
        if self.e_img.value.startswith("http"): self.embed.set_image(url=self.e_img.value)
        else: self.embed.set_image(url=None)
        
        if self.e_thumb.value.startswith("http"): self.embed.set_thumbnail(url=self.e_thumb.value)
        else: self.embed.set_thumbnail(url=None)
        
        await interaction.response.edit_message(embed=self.embed, view=self.embed_view)

class EmbedFooterModal(discord.ui.Modal, title="تعديل الفوتر والمؤلف"):
    e_author = discord.ui.TextInput(label="اسم المؤلف (Author)", required=False, placeholder="اكتب الاسم هنا...")
    e_footer = discord.ui.TextInput(label="نص التذييل (Footer)", required=False, placeholder="نص صغير أسفل الرسالة...")

    def __init__(self, embed: discord.Embed, view: discord.ui.View):
        super().__init__()
        self.embed = embed
        self.embed_view = view

    async def on_submit(self, interaction: discord.Interaction):
        if self.e_author.value: self.embed.set_author(name=self.e_author.value)
        else: self.embed.remove_author()
        
        if self.e_footer.value: self.embed.set_footer(text=self.e_footer.value)
        else: self.embed.remove_footer()
        
        await interaction.response.edit_message(embed=self.embed, view=self.embed_view)

class AdvancedEmbedBuilderView(discord.ui.View):
    def __init__(self, author: discord.Member):
        super().__init__(timeout=300)
        self.author = author
        self.current_embed = discord.Embed(description="أهلاً بك في صانع الإمبد المتقدم!\nاضغط على الأزرار في الأسفل لتعديل أي جزء تفصيلي في هذه الرسالة.", color=discord.Color.blurple())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("❌ هذه القائمة ليست لك!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📝 تعديل الأساسيات", style=discord.ButtonStyle.primary, row=0)
    async def edit_basics(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedBasicsModal(self.current_embed, self))

    @discord.ui.button(label="🖼️ تعديل الصور", style=discord.ButtonStyle.secondary, row=0)
    async def edit_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedImagesModal(self.current_embed, self))

    @discord.ui.button(label="🏷️ تعديل الفوتر", style=discord.ButtonStyle.secondary, row=0)
    async def edit_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedFooterModal(self.current_embed, self))

    @discord.ui.button(label="✅ إرسال الإمبد الآن!", style=discord.ButtonStyle.success, row=1)
    async def send_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.send(embed=self.current_embed)
        await interaction.message.delete()

# UI Select Helpers & Dynamic Controls
class ChannelSelectMenu(discord.ui.ChannelSelect):
    def __init__(self, setting_key: str, placeholder_text: str, channel_types=None):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, channel_types=channel_types or [discord.ChannelType.text], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await db.update_guild_setting(interaction.guild_id, self.setting_key, channel.id)
        await interaction.response.send_message(f"✅ تم تحديد القناة: {channel.mention}", ephemeral=True)

class CategorySelectMenu(discord.ui.ChannelSelect):
    def __init__(self, setting_key: str, placeholder_text: str):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, channel_types=[discord.ChannelType.category], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        await db.update_guild_setting(interaction.guild_id, self.setting_key, category.id)
        await interaction.response.send_message(f"✅ تم تحديد الفئة (Category): **{category.name}**", ephemeral=True)

class RoleSelectMenu(discord.ui.RoleSelect):
    def __init__(self, setting_key: str, placeholder_text: str):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await db.update_guild_setting(interaction.guild_id, self.setting_key, role.id)
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
            await interaction.response.send_message(f"➖ تم إزالة الرتبة {role.mention} بنجاح!", ephemeral=True)
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"➕ تم إعطاؤك الرتبة {role.mention} بنجاح!", ephemeral=True)

class ButtonRolesDeployView(discord.ui.View):
    def __init__(self, b_roles: list):
        super().__init__(timeout=None)
        for label, r_id in b_roles:
            self.add_item(DynamicRoleButton(label, r_id))

class GeneralSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ChannelSelectMenu("welcome_channel_id", "👋 اختر قناة الترحيب..."))
        self.add_item(ChannelSelectMenu("leave_channel_id", "🚪 اختر قناة المغادرة..."))
        self.add_item(ChannelSelectMenu("log_channel_id", "📜 اختر قناة السجلات (Logs)..."))
        self.add_item(RoleSelectMenu("auto_role_id", "🎖️ اختر الرتبة التلقائية للأعضاء الجدد..."))

    @discord.ui.button(label="تعديل رسالة الترحيب", style=discord.ButtonStyle.primary, row=4)
    async def edit_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditWelcomeModal())

    @discord.ui.button(label="تعديل رسالة المغادرة", style=discord.ButtonStyle.primary, row=4)
    async def edit_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditLeaveModal())

    @discord.ui.button(label="الرجوع للصفحة للرئيسية", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به او تعديله!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class AutoModSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تبديل الحماية العامة", style=discord.ButtonStyle.danger, row=0)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['automod_enabled'] else 1
        await db.update_guild_setting(interaction.guild_id, "automod_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} نظام الحماية العام!", ephemeral=True)

    @discord.ui.button(label="منع الروابط (Anti-Links)", style=discord.ButtonStyle.primary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['anti_links'] else 1
        await db.update_guild_setting(interaction.guild_id, "anti_links", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} مانع الروابط الخارجية!", ephemeral=True)

    @discord.ui.button(label="منع دعوات الديسكورد (Anti-Invites)", style=discord.ButtonStyle.primary, row=0)
    async def toggle_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['anti_invites'] else 1
        await db.update_guild_setting(interaction.guild_id, "anti_invites", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} مانع دعوات السيرفرات!", ephemeral=True)

    @discord.ui.button(label="تعديل الكلمات الممنوعة", style=discord.ButtonStyle.secondary, row=1)
    async def edit_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditBadwordsModal())

    @discord.ui.button(label="الرجوع للصفحة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به او تعديله!", color=discord.Color.blurple())
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
        b_roles = await db.get_button_roles(interaction.guild_id)
        view = ButtonRolesDeployView(b_roles)
        if len(view.children) == 0:
            await interaction.response.send_message("❌ لم تقم بإضافة أي أزرار رتب بعد! اضغط على إضافة زر رتبة تفاعلية أولاً.", ephemeral=True)
            return
        embed = discord.Embed(title="🎭 اختيار الرتب التفاعلية", description="اضغط على الأزرار أدناه للحصول على الرتبة أو إزالتها!", color=discord.Color.purple())
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ تم نشر بنل الرتب التفاعلية!", ephemeral=True)

    @discord.ui.button(label="الرجوع للصفحة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به او تعديله!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class XPSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ChannelSelectMenu("level_up_channel_id", "🎉 اختر قناة إرسال تنبيهات اللفل..."))

    @discord.ui.button(label="تعديل معدل الـ XP", style=discord.ButtonStyle.primary, row=1)
    async def edit_rates(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeXPRatesModal())

    @discord.ui.button(label="الرجوع للصفحة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به او تعديله!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class TicketSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelectMenu("ticket_category_id", "📂 اختر فئة التذاكر (الكاتيجوري)..."))
        self.add_item(ChannelSelectMenu("ticket_log_channel_id", "📜 اختر قناة سجل التذاكر (Ticket Logs)..."))
        self.add_item(RoleSelectMenu("ticket_support_role_id", "🛡️ اختر رتبة الدعم الفني المسؤول عن التذاكر..."))

    @discord.ui.button(label="إرسال بنل التذاكر في هذه القناة", style=discord.ButtonStyle.success, row=2)
    async def deploy_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🎟️ قسم الدعم الفني والمساعدة",
            description="اضغط على الزر أدناه لفتح التذكرة.",
            color=discord.Color.green()
        )
        await interaction.channel.send(embed=embed, view=OpenTicketView())
        await interaction.response.send_message("✅ تم نشر بنل التذاكر بنجاح!", ephemeral=True)

    @discord.ui.button(label="الرجوع للصفحه الرئيسية", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به او تعديله!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📩 فتح تذكرة جديدة", style=discord.ButtonStyle.primary, custom_id="open_ticket_btn_pro")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        st = await db.get_guild_settings(guild.id)
        cat_id = st['ticket_category_id']
        support_role_id = st['ticket_support_role_id']
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
        embed = discord.Embed(title=f"🎟️ تذكرة الدعم - {interaction.user.display_name}", description="مرحباً بك! تفضل بكتابة استفسارك وسيتم الرد عليك باسرع وقت ممكن.", color=discord.Color.blue())
        await channel.send(content=f"{interaction.user.mention} {support_role.mention if support_role else ''}", embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ تم إنشاء تذكرتك بنجاح: {channel.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn_pro")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        log_chan_id = st['ticket_log_channel_id']
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
        st = await db.get_guild_settings(interaction.guild_id)

        if sel == "general":
            embed = discord.Embed(title="👋 إعدادات الترحيب والمغادرة والسجلات", color=discord.Color.green())
            w_c = interaction.guild.get_channel(st['welcome_channel_id'])
            l_c = interaction.guild.get_channel(st['leave_channel_id'])
            lg_c = interaction.guild.get_channel(st['log_channel_id'])
            a_r = interaction.guild.get_role(st['auto_role_id'])
            embed.add_field(name="قناة الترحيب", value=w_c.mention if w_c else "غير محددة", inline=True)
            embed.add_field(name="قناة المغادرة", value=l_c.mention if l_c else "غير محددة", inline=True)
            embed.add_field(name="قناة السجلات", value=lg_c.mention if lg_c else "غير محددة", inline=True)
            embed.add_field(name="الرتبة التلقائية", value=a_r.mention if a_r else "غير محددة", inline=True)
            await interaction.response.edit_message(embed=embed, view=GeneralSettingsView())

        elif sel == "automod":
            embed = discord.Embed(title="🛡️ إعدادات الحماية والتعديل الآلي", color=discord.Color.red())
            embed.add_field(name="الحماية العامة", value="✅ مفعلة" if st['automod_enabled'] else "❌ معطلة", inline=True)
            embed.add_field(name="منع الروابط", value="✅ مفعل" if st['anti_links'] else "❌ معطل", inline=True)
            embed.add_field(name="منع الدعوات", value="✅ مفعل" if st['anti_invites'] else "❌ معطل", inline=True)
            embed.add_field(name="الكلمات الممنوعة", value=st['automod_badwords'] if st['automod_badwords'] else "لا توجد كلمات ممنوعة", inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoModSettingsView())

        elif sel == "auto_responses":
            embed = discord.Embed(title="🤖 الردود التلقائية والاختصارات", color=discord.Color.purple())
            responses = await db.get_auto_responses(interaction.guild_id)
            aliases = await db.get_custom_aliases(interaction.guild_id)
            
            resp_str = "\n".join([f"• `{r['trigger_text']}` ➔ {r['response_text']}" for r in responses[:10]]) if responses else "لا توجد ردود تلقائية مضافة"
            alias_str = "\n".join([f"• `{a['alias']}` ➔ `/{a['command_name']}`" for a in aliases[:10]]) if aliases else "لا توجد اختصارات مضافة"

            embed.add_field(name="💬 الردود التلقائية الحالية", value=resp_str, inline=False)
            embed.add_field(name="⚡ اختصارات الأوامر الحالية", value=alias_str, inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoResponseView())

        elif sel == "xp":
            embed = discord.Embed(title="⭐ إعدادات نظام اللفل والخبرة", color=discord.Color.gold())
            lvl_chan = interaction.guild.get_channel(st['level_up_channel_id'])
            embed.add_field(name="قناة تنبيهات اللفل", value=lvl_chan.mention if lvl_chan else "لم تحدد (تلقائي في الشات)", inline=False)
            embed.add_field(name="معدل الكتابة", value=f"`{st['text_xp_rate']}` XP", inline=True)
            embed.add_field(name="معدل الصوت", value=f"`{st['voice_xp_rate']}` XP", inline=True)
            await interaction.response.edit_message(embed=embed, view=XPSettingsView())

        elif sel == "tickets":
            embed = discord.Embed(title="🎟️ إعدادات نظام التذاكر", color=discord.Color.blue())
            t_cat = interaction.guild.get_channel(st['ticket_category_id'])
            t_log = interaction.guild.get_channel(st['ticket_log_channel_id'])
            s_role = interaction.guild.get_role(st['ticket_support_role_id'])
            
            embed.add_field(name="فئة التذاكر (Category)", value=t_cat.name if t_cat else "غير محددة", inline=False)
            embed.add_field(name="سجل التذاكر", value=t_log.mention if t_log else "غير محددة", inline=True)
            embed.add_field(name="رتبة الدعم الفني", value=s_role.mention if s_role else "غير محددة", inline=True)
            await interaction.response.edit_message(embed=embed, view=TicketSettingsView())

        elif sel == "embed":
            view = AdvancedEmbedBuilderView(author=interaction.user)
            await interaction.response.send_message(embed=view.current_embed, view=view, ephemeral=True)

class MainDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DashboardSelectMenu())

class Dashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="dashboard", description="فتح لوحة تحكم السيرفر الشاملة لاغلب ضروريات البوت")
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ لوحة تحكم السيرفر الشاملة",
            description="اختر القسم الذي تريد تعديله من القائمة المستطيلة للتحكم الكامل بسيرفرك بدون مواقع خارجية!",
            color=discord.Color.blurple()
        )
        view = MainDashboardView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Dashboard(bot))
