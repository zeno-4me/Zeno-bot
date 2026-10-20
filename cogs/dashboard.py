import asyncio
from datetime import datetime
import random
import re
import discord
from discord import app_commands
from discord.ext import commands
from database import db

# دالة مساعدة لاستخراج آيدي القناة وآيدي الرسالة من رابط الرسالة (Message URL)
def parse_discord_message_url(url: str):
    pattern = r"https://(?:ptb\.|canary\.)?discord\.com/channels/(\d+)/(\d+)/(\d+)"
    match = re.search(pattern, url.strip())
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    return None, None, None

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
        responses_list = [r.strip() for r in self.response.value.split("|") if r.strip()]
        formatted_resp = " | ".join(responses_list)
        await db.add_auto_response(interaction.guild_id, self.trigger.value, formatted_resp)
        await interaction.response.send_message(f"✅ تمت إضافة الردود التلقائية للكلمة `{self.trigger.value}` بعدد `{len(responses_list)}` ردود عشوائية!", ephemeral=True)

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
    embed_name_input = discord.ui.TextInput(label="اسم الإمبد (مطلوبة للحفظ)", placeholder="مثال: rules_embed", required=True)

    def __init__(self, view):
        super().__init__()
        self.builder_view = view
        if self.builder_view.embed_name and self.builder_view.embed_name != "custom":
            self.embed_name_input.default = self.builder_view.embed_name

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        name = self.embed_name_input.value.strip()
        if not name:
            await interaction.followup.send("❌ يجب إدخال اسم صحيح للإمبد لكي يتم حفظه!", ephemeral=True)
            return

        self.builder_view.embed_name = name
        sent_msg = await interaction.channel.send(embed=self.builder_view.current_embed)
        
        data = {
            "embed": self.builder_view.current_embed.to_dict(),
            "message_url": sent_msg.jump_url
        }
        await db.save_custom_embed(interaction.guild_id, name, data)
        await interaction.followup.send(f"✅ تم حفظ الإمبد باسم `{name}` وإرساله بنجاح!", ephemeral=True)

class ApplyEmbedEditModal(discord.ui.Modal, title="تعديل الإمبد المرسل"):
    url_input = discord.ui.TextInput(label="رابط الرسالة الأصلية (Message URL)", placeholder="https://discord.com/channels/...", required=False)

    def __init__(self, builder_view):
        super().__init__()
        self.builder_view = builder_view
        if builder_view.saved_message_url:
            self.url_input.default = builder_view.saved_message_url

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        target_url = self.url_input.value.strip() or self.builder_view.saved_message_url
        
        if not target_url:
            await interaction.followup.send("❌ يرجى توفير رابط الرسالة المراد تعديلها، أو إرسال الإمبد كرسالة جديدة أولاً!", ephemeral=True)
            return

        guild_id, channel_id, message_id = parse_discord_message_url(target_url)
        if not channel_id or not message_id:
            await interaction.followup.send("❌ صيغة رابط الرسالة غير صحيحة!", ephemeral=True)
            return

        channel = interaction.guild.get_channel(channel_id)
        if not channel:
            await interaction.followup.send("❌ لم يتم العثور على القناة في السيرفر!", ephemeral=True)
            return

        try:
            target_msg = await channel.fetch_message(message_id)
            await target_msg.edit(embed=self.builder_view.current_embed)
            
            data = {
                "embed": self.builder_view.current_embed.to_dict(),
                "message_url": target_url
            }
            await db.save_custom_embed(interaction.guild_id, self.builder_view.embed_name, data)
            
            await interaction.followup.send(f"🔄 تم تحديث وتعديل الرسالة المرسلة بنجاح!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ متعذر تعديل الرسالة، قد تكون محذوفة أو يفتقد البوت لصلاحية التعديل عليها: {e}", ephemeral=True)

class AdvancedEmbedBuilderView(discord.ui.View):
    def __init__(self, author: discord.Member, embed_name: str = "custom", default_embed: discord.Embed = None, saved_message_url: str = None):
        super().__init__(timeout=300)
        self.author = author
        self.embed_name = embed_name
        self.saved_message_url = saved_message_url
        self.current_embed = default_embed or discord.Embed(
            title="📌 صانع الإمبدز",
            description="مرحباً بك في صانع الإمبدز! عدل الأساسيات، الصور، ثم احفظه أو عدل رسالة مرسلة.", 
            color=discord.Color.blurple()
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("❌ هذه القائمة ليست لك!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="تعديل الأساسيات والفوتر", style=discord.ButtonStyle.primary, row=0)
    async def edit_basics(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedBasicsAndFooterModal(self.current_embed, self))

    @discord.ui.button(label="تعديل الصور", style=discord.ButtonStyle.secondary, row=0)
    async def edit_images(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedImagesModal(self.current_embed, self))

    @discord.ui.button(label="التعديل على ايمبد مرسل", style=discord.ButtonStyle.primary, row=1)
    async def apply_edit_to_original(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ApplyEmbedEditModal(self))

    @discord.ui.button(label="ارسال الايمبد", style=discord.ButtonStyle.success, row=1)
    async def prompt_send_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EmbedNameModal(self))

# UI Select Helpers
class ChannelSelectMenu(discord.ui.ChannelSelect):
    def __init__(self, setting_key: str, placeholder_text: str, channel_types=None):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, channel_types=channel_types or [discord.ChannelType.text], min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await db.update_guild_setting(interaction.guild_id, self.setting_key, channel.id)
        await interaction.response.send_message(f"✅ تم تحديد القناة: {channel.mention}", ephemeral=True)

class RoleSelectMenu(discord.ui.RoleSelect):
    def __init__(self, setting_key: str, placeholder_text: str):
        self.setting_key = setting_key
        super().__init__(placeholder=placeholder_text, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        role = self.values[0]
        await db.update_guild_setting(interaction.guild_id, self.setting_key, role.id)
        await interaction.response.send_message(f"✅ تم تحديد الرتبة: {role.mention}", ephemeral=True)

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

    @discord.ui.button(label="الرجوع للصفحة الرئيسية", style=discord.ButtonStyle.secondary, row=4)
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

    @discord.ui.button(label="صانع الإمبدز (الرئيسي)", style=discord.ButtonStyle.primary, row=0)
    async def open_embed_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        saved_data = await db.get_custom_embed(interaction.guild_id, "main_embed")
        if saved_data:
            default_emb = discord.Embed.from_dict(saved_data.get("embed", {}))
            saved_url = saved_data.get("message_url", None)
        else:
            default_emb = discord.Embed(
                title="📌 صانع الإمبدز", 
                description="صمم إمبدك الخاص بكل إتقان.", 
                color=discord.Color.green()
            )
            saved_url = None

        view = AdvancedEmbedBuilderView(
            author=interaction.user, 
            embed_name="main_embed", 
            default_embed=default_emb,
            saved_message_url=saved_url
        )
        await interaction.response.send_message(embed=view.current_embed, view=view, ephemeral=True)

    @discord.ui.button(label="تعديل الإمبدز المحفوظة", style=discord.ButtonStyle.success, row=0)
    async def edit_old_embeds(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_embeds = await db.get_all_custom_embeds(interaction.guild_id)
        view = OldEmbedsView(all_embeds)
        await interaction.response.send_message("📁 اختر الإمبد المحفوظ الذي تريد تعديله:", view=view, ephemeral=True)

    @discord.ui.button(label="🗑️ حذف إمبد محفوظ", style=discord.ButtonStyle.danger, row=1)
    async def delete_old_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        all_embeds = await db.get_all_custom_embeds(interaction.guild_id)
        if not all_embeds:
            await interaction.response.send_message("❌ لا توجد أي إمبدز محفوظة حالياً للحذف!", ephemeral=True)
            return
        view = DeleteEmbedsView(all_embeds)
        await interaction.response.send_message("🗑️ اختر الإمبد المحفوظ الذي تريد حذفه نهائياً:", view=view, ephemeral=True)

    @discord.ui.button(label="الرجوع للصفحة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
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
            
        super().__init__(placeholder="اختر الإمبد المحفوظ للتعديل...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("❌ لا توجد إمبدز محفوظة حالياً!", ephemeral=True)
            return

        selected_name = self.values[0]
        all_embeds = await db.get_all_custom_embeds(interaction.guild_id)
        embed_data = all_embeds.get(selected_name, {})
        
        # التصحيح الأكيد هنا: التعامل سواء كانت الداتا مخزنة كمباشر أو داخل مفتاح "embed"
        if isinstance(embed_data, dict) and "embed" in embed_data:
            raw_embed_dict = embed_data.get("embed")
            saved_url = embed_data.get("message_url", None)
        else:
            raw_embed_dict = embed_data
            saved_url = None

        if raw_embed_dict:
            default_emb = discord.Embed.from_dict(raw_embed_dict)
        else:
            default_emb = discord.Embed(title=selected_name, description="محتوى الإمبد...")

        view = AdvancedEmbedBuilderView(
            author=interaction.user, 
            embed_name=selected_name, 
            default_embed=default_emb,
            saved_message_url=saved_url
        )
        
        # تعديل الرسالة الحالية التابعة للقائمة المنسدلة وعرض الإمبد الحقيقي بدلاً من إرسال رسالة جديدة فارغة
        await interaction.response.edit_message(content=f"📁 تم تحميل الإمبد: `{selected_name}`", embed=view.current_embed, view=view)

class OldEmbedsView(discord.ui.View):
    def __init__(self, embeds_dict: dict):
        super().__init__(timeout=None)
        self.add_item(OldEmbedSelect(embeds_dict))

class DeleteEmbedSelect(discord.ui.Select):
    def __init__(self, embeds_dict: dict):
        options = []
        for name in embeds_dict.keys():
            options.append(discord.SelectOption(label=name, description=f"حذف الإمبد المحفوظ: {name}", emoji="🗑️"))
        
        super().__init__(placeholder="اختر الإمبد المراد حذفه...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_name = self.values[0]
        
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT custom_embeds FROM guild_settings WHERE guild_id = $1", interaction.guild_id)
            if row and row['custom_embeds']:
                import json
                embeds = json.loads(row['custom_embeds'])
                if selected_name in embeds:
                    del embeds[selected_name]
                    await conn.execute("UPDATE guild_settings SET custom_embeds = $1 WHERE guild_id = $2", json.dumps(embeds), interaction.guild_id)

        await interaction.response.send_message(f"✅ تم حذف الإمبد المحفوظ باسم `{selected_name}` بنجاح!", ephemeral=True)

class DeleteEmbedsView(discord.ui.View):
    def __init__(self, embeds_dict: dict):
        super().__init__(timeout=None)
        self.add_item(DeleteEmbedSelect(embeds_dict))

class DashboardSelectMenu(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="📌 قسم الإيمبدز", description="إدارة وصنع الإمبدز الاحترافية وتعديلها", emoji="📌", value="embeds"),
            discord.SelectOption(label="👋 الترحيب والمغادرة والسجلات", description="إعداد رومات الترحيب والمغادرة والرتب التلقائية", emoji="👋", value="general"),
            discord.SelectOption(label="🛡️ الحماية والتعديل الآلي", description="منع الروابط والدعوات والكلمات الممنوعة", emoji="🛡️", value="automod"),
            discord.SelectOption(label="⭐ نظام اللفل والخبرة والمكافآت", description="معدلات XP والفلل الصوتي والكتابي", emoji="⭐", value="xp"),
            discord.SelectOption(label="🤖 الردود التلقائية", description="إدارة الردود الآلية المتعددة والعشوائية", emoji="🤖", value="auto_responses"),
        ]
        super().__init__(placeholder="اختر القسم المراد التحكم به بالكامل...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        sel = self.values[0]
        st = await db.get_guild_settings(interaction.guild_id)

        if sel == "embeds":
            embed = discord.Embed(
                title="📌 قسم الإيمبدز",
                description="إدارة وصنع الإمبدز بكل احترافية وحذفها أو تعديلها.",
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
            embed = discord.Embed(title="🤖 الردود التلقائية", color=discord.Color.purple())
            responses = await db.get_auto_responses(interaction.guild_id)
            
            resp_str = "\n".join([f"• `{r['trigger_text']}` ➔ {r['response_text']}" for r in responses[:10]]) if responses else "لا توجد ردود تلقائية مضافة"

            embed.add_field(name="💬 الردود التلقائية الحالية (متعددة/عشوائية)", value=resp_str, inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoResponseView())

        elif sel.lower() == "xp":
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

    @app_commands.command(name="dashboard", description="فتح لوحة تحكم السيرفر الشاملة لأغلب ضروريات البوت")
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ لوحة تحكم السيرفر الشاملة",
            description="اختر القسم الذي تريد تعديله من القائمة المستطيلة للتحكم الكامل بسيرفرك!",
            color=discord.Color.blurple()
        )
        view = MainDashboardView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Dashboard(bot))
