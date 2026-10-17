import asyncio
from datetime import datetime
import random
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

class AddAutoResponseModal(discord.ui.Modal, title="إضافة رد تلقائي متعدد (عشوائي)"):
    trigger = discord.ui.TextInput(label="جملة المستخدم (الكلمة المفتاحية)", placeholder="مثال: السلام عليكم", required=True)
    response = discord.ui.TextInput(label="الردود التلقائية (افصل بينها بعلامة | )", style=discord.TextStyle.paragraph, placeholder="وعليكم السلام | هلا والله | أهلاً وسهلاً بك!", required=True)
    async def on_submit(self, interaction: discord.Interaction):
        # حفظ الردود مفصولة بعلامة | لدعم الاختيار العشوائي
        responses_list = [r.strip() for r in self.response.value.split("|") if r.strip()]
        formatted_resp = " | ".join(responses_list)
        await db.add_auto_response(interaction.guild_id, self.trigger.value, formatted_resp)
        await interaction.response.send_message(f"✅ تمت إضافة الردود التلقائية للكلمة `{self.trigger.value}` بعدد `{len(responses_list)}` ردود عشوائية!", ephemeral=True)

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

# Embed Builder Modals
class EmbedBasicsAndFooterModal(discord.ui.Modal, title="تعديل الأساسيات والفوتر والمؤلف"):
    e_title = discord.ui.TextInput(label="العنوان", required=False, placeholder="عنوان الإمبد...")
    e_desc = discord.ui.TextInput(label="الوصف", style=discord.TextStyle.paragraph, required=True, placeholder="اكتب محتوى الإمبد هنا...")
    e_color = discord.ui.TextInput(label="اللون (Hex Code)", required=False, placeholder="#3498db أو اترك فارغاً")
    e_author = discord.ui.TextInput(label="اسم المؤلف (Author)", required=False, placeholder="اسم المؤلف...")
    e_footer = discord.ui.TextInput(label="نص التذييل (Footer)", required=False, placeholder="نص الفوتر أسفل الرسالة...")

    def __init__(self, embed: discord.Embed, view: discord.ui.View):
        super().__init__()
        self.embed = embed
        self.embed_view = view
        if embed.title: self.e_title.default = embed.title
        if embed.description: self.e_desc.default = embed.description
        if embed.author and embed.author.name: self.e_author.default = embed.author.name
        if embed.footer and embed.footer.text: self.e_footer.default = embed.footer.text

    async def on_submit(self, interaction: discord.Interaction):
        self.embed.title = self.e_title.value
        self.embed.description = self.e_desc.value
        if self.e_color.value:
            try:
                self.embed.color = discord.Color(int(self.e_color.value.replace("#", ""), 16))
            except: pass
        
        if self.e_author.value: self.embed.set_author(name=self.e_author.value)
        else: self.embed.remove_author()

        if self.e_footer.value: self.embed.set_footer(text=self.e_footer.value)
        else: self.embed.remove_footer()

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

class EmbedNameModal(discord.ui.Modal, title="تسمية وإرسال الإمبد"):
    embed_name_input = discord.ui.TextInput(label="اسم الإمبد (مطلوبة للحفظ)", placeholder="مثال: main_ticket", required=True)

    def __init__(self, view):
        super().__init__()
        self.builder_view = view

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        name = self.embed_name_input.value.strip()
        if not name:
            await interaction.followup.send("❌ يجب إدخال اسم صحيح للإمبد لكي يتم حفظ الإرسال!", ephemeral=True)
            return

        self.builder_view.embed_name = name
        data = {
            "embed": self.builder_view.current_embed.to_dict(),
            "has_ticket": self.builder_view.has_ticket_button,
            "ticket_mode": self.builder_view.ticket_mode,
            "ticket_options": self.builder_view.ticket_options
        }
        await db.save_custom_embed(interaction.guild_id, name, data)

        view = TicketDeployView(data) if self.builder_view.has_ticket_button else None
        await interaction.channel.send(embed=self.builder_view.current_embed, view=view)
        await interaction.followup.send(f"✅ تم حفظ الإمبد باسم `{name}` وإرساله بنجاح إلى القناة!", ephemeral=True)

class TicketOptionSettingsModal(discord.ui.Modal, title="إعدادات زر/خيار التذكرة"):
    btn_label = discord.ui.TextInput(label="نص الزر / اسم الخيار", placeholder="مثال: 🎟️ تذكرة المساعدة", required=True)
    
    def __init__(self, option_key: str, builder_view):
        super().__init__()
        self.option_key = option_key
        self.builder_view = builder_view
        current_opt = builder_view.ticket_options.get(option_key, {})
        if current_opt.get("label"):
            self.btn_label.default = current_opt.get("label")

    async def on_submit(self, interaction: discord.Interaction):
        lbl = self.btn_label.value.strip()
        if self.option_key not in self.builder_view.ticket_options:
            self.builder_view.ticket_options[self.option_key] = {"label": lbl, "category_id": 0, "log_channel_id": 0, "support_roles": [], "embed": {}}
        else:
            self.builder_view.ticket_options[self.option_key]["label"] = lbl
            
        await interaction.response.send_message(f"✅ تم تحديث اسم الزر/الخيار إلى: `{lbl}`.", ephemeral=True)

class AdvancedEmbedBuilderView(discord.ui.View):
    def __init__(self, author: discord.Member, embed_name: str = "custom", default_embed: discord.Embed = None, has_ticket: bool = False, ticket_mode: str = "button", ticket_options: dict = None, is_internal_ticket: bool = False):
        super().__init__(timeout=300)
        self.author = author
        self.embed_name = embed_name
        self.has_ticket_button = has_ticket
        self.ticket_mode = ticket_mode
        self.ticket_options = ticket_options or {"default": {"label": "فتح تذكرة جديدة 📩", "category_id": 0, "log_channel_id": 0, "support_roles": [], "embed": {}}}
        self.is_internal_ticket = is_internal_ticket
        self.current_embed = default_embed or discord.Embed(
            title="📌 صانع الإمبدز",
            description="مرحباً بك في قسم الإمبدز! تعديل الأساسيات يشمل العنوان، الوصف، اللون والفوتر.", 
            color=discord.Color.blurple()
        )
        
        if self.is_internal_ticket:
            self.clear_items()
            self.add_item(discord.ui.Button(label="تعديل الأساسيات والفوتر", style=discord.ButtonStyle.primary, row=0, custom_id="int_basics"))
            self.add_item(discord.ui.Button(label="تعديل الصور", style=discord.ButtonStyle.secondary, row=0, custom_id="int_images"))
            self.add_item(discord.ui.Button(label="💾 حفظ تعديل التذكرة", style=discord.ButtonStyle.success, row=1, custom_id="int_save"))
            
            for child in self.children:
                if child.custom_id == "int_basics":
                    child.callback = self.edit_basics_callback
                elif child.custom_id == "int_images":
                    child.callback = self.edit_images_callback
                elif child.custom_id == "int_save":
                    child.callback = self.save_internal_ticket_callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("❌ هذه القائمة ليست لك!", ephemeral=True)
            return False
        return True

    async def edit_basics_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EmbedBasicsAndFooterModal(self.current_embed, self))

    async def edit_images_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EmbedImagesModal(self.current_embed, self))

    async def save_internal_ticket_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = {
            "embed": self.current_embed.to_dict(),
            "has_ticket": False
        }
        await db.save_custom_embed(interaction.guild_id, self.embed_name, data)
        await interaction.followup.send(f"✅ تم حفظ تعديل الإمبد الداخلي ({self.embed_name}) بنجاح!", ephemeral=True)

    @discord.ui.button(label="تعديل الأساسيات والفوتر", style=discord.ButtonStyle.primary, row=0)
    async def edit_basics(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedBasicsAndFooterModal(self.current_embed, self))

    @discord.ui.button(label="تعديل الصور", style=discord.ButtonStyle.secondary, row=0)
    async def edit_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedImagesModal(self.current_embed, self))

    @discord.ui.button(label="🎟️ تفعيل/إعداد التذاكر", style=discord.ButtonStyle.success, row=1)
    async def configure_tickets(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.has_ticket_button = True
        embed = discord.Embed(
            title="🎟️ إعدادات نظام التذاكر المتقدم",
            description=f"الوضع الحالي: **{'قائمة منسدلة (Select Menu)' if self.ticket_mode == 'select' else 'زر منفرد عادٍ (Button)'}**\nاختر من الأزرار أدناه للتبديل أو تخصيص كل زر وتذكرة على حدة:",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, view=TicketConfigControlView(self), ephemeral=True)

    @discord.ui.button(label="🎭", style=discord.ButtonStyle.secondary, row=1)
    async def role_button_placeholder(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🚧 نظام رتب الأزرار قيد التجهيز وسيتم تفعيله قريباً!", ephemeral=True)

    @discord.ui.button(label="إرسال الإمبد", style=discord.ButtonStyle.danger, row=1)
    async def prompt_send_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedNameModal(self))

class TicketConfigControlView(discord.ui.View):
    def __init__(self, builder_view: AdvancedEmbedBuilderView):
        super().__init__(timeout=300)
        self.builder_view = builder_view
        
        mode_label = "🔀 تحويل إلى: قائمة منسدلة" if self.builder_view.ticket_mode == "button" else "🔀 تحويل إلى: زر منفرد"
        self.mode_btn = discord.ui.Button(label=mode_label, style=discord.ButtonStyle.secondary, row=0)
        self.mode_btn.callback = self.toggle_mode
        self.add_item(self.mode_btn)

        if self.builder_view.ticket_mode == "select":
            add_opt_btn = discord.ui.Button(label="➕ إضافة خيار جديد للقائمة", style=discord.ButtonStyle.success, row=0)
            add_opt_btn.callback = self.add_select_option
            self.add_item(add_opt_btn)

    async def toggle_mode(self, interaction: discord.Interaction):
        if self.builder_view.ticket_mode == "button":
            self.builder_view.ticket_mode = "select"
            if "default" in self.builder_view.ticket_options:
                d_opt = self.builder_view.ticket_options.pop("default")
                self.builder_view.ticket_options["ticket_help"] = d_opt
                self.builder_view.ticket_options["ticket_shop"] = {"label": "🛍️ تذكرة المتجر", "category_id": 0, "log_channel_id": 0, "support_roles": [], "embed": {}}
        else:
            self.builder_view.ticket_mode = "button"
            self.builder_view.ticket_options = {"default": {"label": "فتح تذكرة جديدة 📩", "category_id": 0, "log_channel_id": 0, "support_roles": [], "embed": {}}}

        await interaction.response.edit_message(content="✅ تم تغيير وضع التذاكر بنجاح!", view=TicketConfigControlView(self.builder_view))

    async def add_select_option(self, interaction: discord.Interaction):
        new_key = f"ticket_opt_{len(self.builder_view.ticket_options) + 1}"
        self.builder_view.ticket_options[new_key] = {"label": "تذكرة جديدة", "category_id": 0, "log_channel_id": 0, "support_roles": [], "embed": {}}
        await interaction.response.edit_message(content="✅ تم إضافة خيار جديد للقائمة!", view=TicketConfigControlView(self.builder_view))

    @discord.ui.button(label="⚙️ تخصيص إعدادات كل تذكرة على حدة", style=discord.ButtonStyle.primary, row=1)
    async def configure_each(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = TicketOptionsListView(self.builder_view)
        await interaction.response.send_message("📁 اختر الزر أو الخيار المراد تعديل سيستمه الخاص:", view=view, ephemeral=True)

class TicketOptionsListView(discord.ui.View):
    def __init__(self, builder_view: AdvancedEmbedBuilderView):
        super().__init__(timeout=300)
        self.builder_view = builder_view
        
        for key, opt_data in self.builder_view.ticket_options.items():
            btn = discord.ui.Button(label=opt_data.get("label", key), style=discord.ButtonStyle.secondary)
            btn.callback = lambda i, k=key: self.select_option_to_edit(i, k)
            self.add_item(btn)

    async def select_option_to_edit(self, interaction: discord.Interaction, key: str):
        view = SingleTicketOptionSettingsView(key, self.builder_view)
        opt_info = self.builder_view.ticket_options[key]
        emb = discord.Embed(
            title=f"⚙️ إعدادات سيستم: {opt_info.get('label')}",
            description="قم بتعديل اسم الزر، الكاتيجوري، قناة اللوق، ورتب الدعم الخاصة بهذا الخيار:",
            color=discord.Color.purple()
        )
        await interaction.response.send_message(embed=emb, view=view, ephemeral=True)

class SingleTicketOptionSettingsView(discord.ui.View):
    def __init__(self, option_key: str, builder_view: AdvancedEmbedBuilderView):
        super().__init__(timeout=300)
        self.option_key = option_key
        self.builder_view = builder_view
        
        self.add_item(CategorySelectMenu(f"opt_cat_{option_key}", "📂 فئة فتح تذاكر هذا الزر..."))
        self.add_item(ChannelSelectMenu(f"opt_log_{option_key}", "📜 قناة لوق تذاكر هذا الزر..."))
        self.add_item(MultiRoleSelectMenu(f"🛡️ رتب الدعم الخاصة بهذا الزر..."))

    @discord.ui.button(label="✏️ تعديل اسم الزر / النص", style=discord.ButtonStyle.primary, row=3)
    async def edit_label(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketOptionSettingsModal(self.option_key, self.builder_view))

    @discord.ui.button(label="✏️ تعديل الإمبد الداخلي الخاص بهذا الزر", style=discord.ButtonStyle.success, row=3)
    async def edit_internal_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        opt_data = self.builder_view.ticket_options[self.option_key]
        if not opt_data.get("embed"):
            opt_data["embed"] = discord.Embed(title=f"🎟️ تذكرة {opt_data.get('label')}", description="مرحباً بك! اكتب استفسارك هنا.", color=discord.Color.blue()).to_dict()
        
        def_emb = discord.Embed.from_dict(opt_data["embed"])
        view = AdvancedEmbedBuilderView(author=interaction.user, embed_name=f"internal_{self.option_key}", default_embed=def_emb, is_internal_ticket=True)
        await interaction.response.send_message(embed=view.current_embed, view=view, ephemeral=True)

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

class MultiRoleSelectMenu(discord.ui.RoleSelect):
    def __init__(self, placeholder_text: str):
        super().__init__(placeholder=placeholder_text, min_values=1, max_values=10)

    async def callback(self, interaction: discord.Interaction):
        role_ids = [r.id for r in self.values]
        await db.update_guild_setting(interaction.guild_id, "ticket_support_role_ids", role_ids)
        roles_mentions = ", ".join([r.mention for r in self.values])
        await interaction.response.send_message(f"✅ تم تحديث رتب الدعم الفني لتشمل: {roles_mentions}", ephemeral=True)

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
        new_val = 0 if st.get('automod_enabled') else 1
        await db.update_guild_setting(interaction.guild_id, "automod_enabled", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} نظام الحماية العام!", ephemeral=True)

    @discord.ui.button(label="منع الروابط (Anti-Links)", style=discord.ButtonStyle.primary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st.get('anti_links') else 1
        await db.update_guild_setting(interaction.guild_id, "anti_links", new_val)
        await interaction.response.send_message(f"تم {'تفعيل' if new_val else 'تعطيل'} مانع الروابط الخارجية!", ephemeral=True)

    @discord.ui.button(label="منع دعوات الديسكورد (Anti-Invites)", style=discord.ButtonStyle.primary, row=0)
    async def toggle_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st.get('anti_invites') else 1
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

    @discord.ui.button(label="➕ إضافة رد تلقائي متعدد (عشوائي)", style=discord.ButtonStyle.success, row=0)
    async def add_response(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddAutoResponseModal())

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

class EmbedsSectionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CategorySelectMenu("ticket_category_id", "📂 فئة فتح التذاكر العامة (Category)..."))
        self.add_item(ChannelSelectMenu("ticket_log_channel_id", "📜 قناة لوق التذاكر العامة (Ticket Logs)..."))
        self.add_item(MultiRoleSelectMenu("🛡️ تحديد رتب المساعدة العامة (الدعم الفني)..."))

    @discord.ui.button(label="صانع الإمبدز (الرئيسي)", style=discord.ButtonStyle.primary, row=3)
    async def open_embed_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        saved_data = await db.get_custom_embed(interaction.guild_id, "main_embed")
        if saved_data:
            default_emb = discord.Embed.from_dict(saved_data.get("embed", {}))
            has_btn = saved_data.get("has_ticket", False)
            t_mode = saved_data.get("ticket_mode", "button")
            t_opts = saved_data.get("ticket_options", None)
        else:
            default_emb = discord.Embed(
                title="📌 صانع الإمبدز", 
                description="صمم إمبدك الخاص مع إمكانية إضافة أزرار التذاكر أو القوائم المستقلة بالكامل.", 
                color=discord.Color.green()
            )
            has_btn = False
            t_mode = "button"
            t_opts = None

        view = AdvancedEmbedBuilderView(author=interaction.user, embed_name="main_embed", default_embed=default_emb, has_ticket=has_btn, ticket_mode=t_mode, ticket_options=t_opts, is_internal_ticket=False)
        await interaction.response.send_message(embed=view.current_embed, view=view, ephemeral=True)

    @discord.ui.button(label="تعديل الإمبدز القديمة والمحفوظة", style=discord.ButtonStyle.success, row=3)
    async def edit_old_embeds(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_embeds = await db.get_all_custom_embeds(interaction.guild_id)
        view = OldEmbedsView(all_embeds)
        await interaction.response.send_message("📁 اختر الإمبد المحفوظ الذي تريد تعديله:", view=view, ephemeral=True)

    @discord.ui.button(label="الرجوع للصفحة الرئيسية", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم المراد التحكم به او تعديله!", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())

class OldEmbedSelect(discord.ui.Select):
    def __init__(self, embeds_dict: dict):
        options = []
        for name in embeds_dict.keys():
            options.append(discord.SelectOption(label=name, description=f"تعديل الإمبد المحفوظ: {name}", emoji="📁"))
        
        if not options:
            options.append(discord.SelectOption(label="لا توجد إمبدز محفوظة", description="قم بحفظ إمبد جديد أولاً", emoji="❌", value="none"))
            
        super().__init__(placeholder="اختر الإمبد القديم للتعديل...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("❌ لا توجد إمبدز محفوظة حالياً!", ephemeral=True)
            return

        selected_name = self.values[0]
        all_embeds = await db.get_all_custom_embeds(interaction.guild_id)
        embed_data = all_embeds.get(selected_name, {})
        
        default_emb = discord.Embed.from_dict(embed_data.get("embed", {})) if embed_data.get("embed") else discord.Embed(title=selected_name, description="محتوى الإمبد...")
        has_btn = embed_data.get("has_ticket", False)
        t_mode = embed_data.get("ticket_mode", "button")
        t_opts = embed_data.get("ticket_options", None)

        view = AdvancedEmbedBuilderView(author=interaction.user, embed_name=selected_name, default_embed=default_emb, has_ticket=has_btn, ticket_mode=t_mode, ticket_options=t_opts)
        await interaction.response.send_message(embed=view.current_embed, view=view, ephemeral=True)

class OldEmbedsView(discord.ui.View):
    def __init__(self, embeds_dict: dict):
        super().__init__(timeout=None)
        self.add_item(OldEmbedSelect(embeds_dict))

class TicketDeployView(discord.ui.View):
    def __init__(self, embed_data: dict):
        super().__init__(timeout=None)
        self.embed_data = embed_data
        t_mode = embed_data.get("ticket_mode", "button")
        t_opts = embed_data.get("ticket_options", {})

        if t_mode == "select":
            options = []
            for key, opt in t_opts.items():
                options.append(discord.SelectOption(label=opt.get("label", "تذكرة"), value=key, emoji="🎟️"))
            self.add_item(TicketSelectMenu(options, t_opts))
        else:
            opt_key = list(t_opts.keys())[0] if t_opts else "default"
            opt_data = t_opts.get(opt_key, {"label": "فتح تذكرة جديدة 📩"})
            btn = discord.ui.Button(label=opt_data.get("label", "فتح تذكرة جديدة 📩"), style=discord.ButtonStyle.primary, custom_id=f"ticket_btn_{opt_key}")
            btn.callback = lambda i: create_ticket_channel(i, opt_key, opt_data)
            self.add_item(btn)

class TicketSelectMenu(discord.ui.Select):
    def __init__(self, options: list, ticket_options: dict):
        self.ticket_options = ticket_options
        super().__init__(placeholder="اختر نوع التذكرة المطلوبة...", min_values=1, max_values=1, options=options, custom_id="ticket_select_menu_pro")

    async def callback(self, interaction: discord.Interaction):
        selected_key = self.values[0]
        opt_data = self.ticket_options.get(selected_key, {})
        await create_ticket_channel(interaction, selected_key, opt_data)

async def create_ticket_channel(interaction: discord.Interaction, opt_key: str, opt_data: dict):
    guild = interaction.guild
    st = await db.get_guild_settings(guild.id)
    
    cat_id = opt_data.get("category_id") or st.get('ticket_category_id')
    log_id = opt_data.get("log_channel_id") or st.get('ticket_log_channel_id')
    support_roles = opt_data.get("support_roles") or st.get('ticket_support_role_ids', [])
    
    category = guild.get_channel(cat_id) if cat_id else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
    }
    
    support_mentions = []
    for r_id in support_roles:
        role = guild.get_role(r_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            support_mentions.append(role.mention)

    channel = await guild.create_text_channel(name=f"ticket-{interaction.user.name}", category=category, overwrites=overwrites)
    
    internal_emb_data = opt_data.get("embed")
    if internal_emb_data and internal_emb_data.get("title"):
        embed = discord.Embed.from_dict(internal_emb_data)
    else:
        embed = discord.Embed(
            title=f"🎟️ تذكرة {opt_data.get('label', 'الدعم')} - {interaction.user.display_name}", 
            description="مرحباً بك! تفضل بكتابة استفسارك وسيتم الرد عليك باسرع وقت ممكن.", 
            color=discord.Color.blue()
        )

    mentions_str = " ".join(support_mentions)
    await channel.send(content=f"{mentions_str}" if mentions_str else None, embed=embed, view=CloseTicketView(log_id))
    await interaction.response.send_message(f"✅ تم إنشاء تذكرتك بنجاح: {channel.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self, log_channel_id: int):
        super().__init__(timeout=None)
        self.log_channel_id = log_channel_id

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn_pro")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("سيتم إغلاق وحذف التذكرة خلال 5 ثوانٍ...")

        if self.log_channel_id:
            log_chan = interaction.guild.get_channel(self.log_channel_id)
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
            discord.SelectOption(label="📌 قسم الإيمبودز والتذاكر", description="إدارة الإمبدز وأزرار التذاكر المتقدمة", emoji="📌", value="embeds"),
            discord.SelectOption(label="👋 الترحيب والمغادرة والسجلات", description="إعداد رومات الترحيب والمغادرة والرتب التلقائية", emoji="👋", value="general"),
            discord.SelectOption(label="🛡️ الحماية والتعديل الآلي", description="منع الروابط والدعوات والكلمات الممنوعة", emoji="🛡️", value="automod"),
            discord.SelectOption(label="⭐ نظام اللفل والخبرة والمكافآت", description="معدلات XP واللفل الصوتي والكتابي", emoji="⭐", value="xp"),
            discord.SelectOption(label="🤖 الردود التلقائية ورتب الأزرار", description="إدارة الردود الآلية وأزرار إعطاء الرتب", emoji="🤖", value="auto_responses"),
        ]
        super().__init__(placeholder="اختر القسم المراد التحكم به بالكامل...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        sel = self.values[0]
        st = await db.get_guild_settings(interaction.guild_id)

        if sel == "embeds":
            embed = discord.Embed(
                title="📌 قسم الإيمبدز والتذاكر المتقدمة",
                description="إدارة وصنع الإمبدز مع خيارات تفعيل أزرار التذاكر الفردية أو القوائم المنسدلة بكل استقلالية.",
                color=discord.Color.blurple()
            )
            await interaction.response.edit_message(embed=embed, view=EmbedsSectionView())

        elif sel == "general":
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
            embed = discord.Embed(title="🤖 الردود التلقائية ورتب الأزرار", color=discord.Color.purple())
            responses = await db.get_auto_responses(interaction.guild_id)
            
            resp_str = "\n".join([f"• `{r['trigger_text']}` ➔ {r['response_text']}" for r in responses[:10]]) if responses else "لا توجد ردود تلقائية مضافة"

            embed.add_field(name="💬 الردود التلقائية الحالية (متعددة/عشوائية)", value=resp_str, inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoResponseView())

        elif sel == "xp":
            embed = discord.Embed(title="⭐ إعدادات نظام اللفل والخبرة", color=discord.Color.gold())
            lvl_chan = interaction.guild.get_channel(st['level_up_channel_id'])
            embed.add_field(name="قناة تنبيهات اللفل", value=lvl_chan.mention if lvl_chan else "لم تحدد (تلقائي في الشات)", inline=False)
            embed.add_field(name="معدل الكتابة", value=f"`{st['text_xp_rate']}` XP", inline=True)
            embed.add_field(name="معدل الصوت", value=f"`{st['voice_xp_rate']}` XP", inline=True)
            await interaction.response.edit_message(embed=embed, view=XPSettingsView())

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
