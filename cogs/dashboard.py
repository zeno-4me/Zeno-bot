import asyncio
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import commands
from database import db

# ==================== المودلز (Models / Inputs) ====================

class EditWelcomeModal(discord.ui.Modal, title="تعديل رسالة الترحيب"):
    welcome_msg = discord.ui.TextInput(
        label="رسالة الترحيب", 
        style=discord.TextStyle.paragraph, 
        placeholder="مرحباً بك {user} في سيرفر {server}!", 
        required=True
    )
    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "welcome_msg", self.welcome_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة الترحيب بنجاح!", ephemeral=True)

class EditLeaveModal(discord.ui.Modal, title="تعديل رسالة المغادرة"):
    leave_msg = discord.ui.TextInput(
        label="رسالة المغادرة", 
        style=discord.TextStyle.paragraph, 
        placeholder="وداعاً {user}، نراك على خير!", 
        required=True
    )
    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "leave_msg", self.leave_msg.value)
        await interaction.response.send_message("✅ تم تحديث رسالة المغادرة بنجاح!", ephemeral=True)

class EditBadwordsModal(discord.ui.Modal, title="إدارة الكلمات الممنوعة"):
    bad_words = discord.ui.TextInput(
        label="الكلمات الممنوعة (افصل بينها بفاصلة)", 
        style=discord.TextStyle.paragraph, 
        placeholder="كلمة1, كلمة2, رابط", 
        required=False
    )
    async def on_submit(self, interaction: discord.Interaction):
        await db.update_guild_setting(interaction.guild_id, "automod_badwords", self.bad_words.value)
        await interaction.response.send_message("✅ تم تحديث قائمة الكلمات الممنوعة بنجاح!", ephemeral=True)

class AddAutoResponseModal(discord.ui.Modal, title="إضافة رد تلقائي جديد"):
    trigger = discord.ui.TextInput(label="كلمة المفتاح (Trigger)", placeholder="مثال: السلام عليكم", required=True)
    response = discord.ui.TextInput(label="الرد التلقائي للبوت", style=discord.TextStyle.paragraph, placeholder="وعليكم السلام ورحمة الله وبركاته", required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        await db.add_auto_response(interaction.guild_id, self.trigger.value, self.response.value)
        await interaction.response.send_message(f"✅ تم إضافة الرد للكلمة: `{self.trigger.value}` بنجاح!", ephemeral=True)

class AddCustomAliasModal(discord.ui.Modal, title="إضافة اختصار لأمر"):
    alias_input = discord.ui.TextInput(label="الاختصار (مثل: طرد)", placeholder="طرد", required=True)
    command_input = discord.ui.TextInput(label="اسم الأمر الأصلي (مثل: kick)", placeholder="kick", required=True)
    
    async def on_submit(self, interaction: discord.Interaction):
        await db.add_custom_alias(interaction.guild_id, self.alias_input.value, self.command_input.value)
        await interaction.response.send_message(f"✅ تم ربط الاختصار `{self.alias_input.value}` بالأمر `/{self.command_input.value}`!", ephemeral=True)

class AddButtonRoleModal(discord.ui.Modal, title="إضافة رتبة زر تفاعلي"):
    label = discord.ui.TextInput(label="اسم الزر", placeholder="مثال: VIP", required=True)
    role_id_input = discord.ui.TextInput(label="آيدي الرتبة (Role ID)", placeholder="123456789...", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            r_id = int(self.role_id_input.value)
            role = interaction.guild.get_role(r_id)
            if not role:
                await interaction.response.send_message("❌ الرتبة غير موجودة بهذا الآيدي في السيرفر!", ephemeral=True)
                return
            await db.add_button_role(interaction.guild_id, self.label.value, r_id)
            await interaction.response.send_message(f"✅ تم ربط الزر `{self.label.value}` بالرتبة {role.mention}!", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى إدخال آيدي صحيح يتكون من أرقام فقط!", ephemeral=True)

class ChangeXPRatesModal(discord.ui.Modal, title="تعديل معدلات الخبرة (XP)"):
    text_rate = discord.ui.TextInput(label="خبرة الكتابة لكل رسالة", default="15", max_length=4)
    voice_rate = discord.ui.TextInput(label="خبرة الصوت لكل دقيقة", default="10", max_length=4)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            t_rate = int(self.text_rate.value)
            v_rate = int(self.voice_rate.value)
            await db.update_guild_setting(interaction.guild_id, "text_xp_rate", t_rate)
            await db.update_guild_setting(interaction.guild_id, "voice_xp_rate", v_rate)
            await interaction.response.send_message(f"✅ تم تحديث معدلات الخبرة بنجاح: كتابة `{t_rate}` | صوت `{v_rate}`", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("❌ يرجى إدخال أرقام صحيحة فقط!", ephemeral=True)


# ==================== قوائم اختيار القنوات والرتب (Select Menus) ====================

class GeneralDropdown(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # قائمة اختيار قناة الترحيب
        welcome_select = discord.ui.ChannelSelect(placeholder="👋 اختر قناة الترحيب...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=0)
        async def welcome_callback(interaction: discord.Interaction):
            ch = welcome_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "welcome_channel_id", ch.id)
            await interaction.response.send_message(f"✅ تم تحديد قناة الترحيب إلى: {ch.mention}", ephemeral=True)
        welcome_select.callback = welcome_callback
        self.add_item(welcome_select)

        # قائمة اختيار قناة المغادرة
        leave_select = discord.ui.ChannelSelect(placeholder="🚪 اختر قناة المغادرة...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=1)
        async def leave_callback(interaction: discord.Interaction):
            ch = leave_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "leave_channel_id", ch.id)
            await interaction.response.send_message(f"✅ تم تحديد قناة المغادرة إلى: {ch.mention}", ephemeral=True)
        leave_select.callback = leave_callback
        self.add_item(leave_select)

        # قائمة اختيار قناة السجلات (Logs)
        log_select = discord.ui.ChannelSelect(placeholder="📜 اختر قناة السجلات (Logs)...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=2)
        async def log_callback(interaction: discord.Interaction):
            ch = log_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "log_channel_id", ch.id)
            await interaction.response.send_message(f"✅ تم تحديد قناة السجلات إلى: {ch.mention}", ephemeral=True)
        log_select.callback = log_callback
        self.add_item(log_select)

        # قائمة اختيار الرتبة التلقائية للأعضاء الجدد
        role_select = discord.ui.RoleSelect(placeholder="🎖️ اختر الرتبة التلقائية للأعضاء الجدد...", min_values=1, max_values=1, row=3)
        async def role_callback(interaction: discord.Interaction):
            role = role_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "auto_role_id", role.id)
            await interaction.response.send_message(f"✅ تم تحديد الرتبة التلقائية إلى: {role.mention}", ephemeral=True)
        role_select.callback = role_callback
        self.add_item(role_select)

    @discord.ui.button(label="تعديل رسالة الترحيب", style=discord.ButtonStyle.primary, row=4)
    async def edit_welcome_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditWelcomeModal())

    @discord.ui.button(label="تعديل رسالة المغادرة", style=discord.ButtonStyle.primary, row=4)
    async def edit_leave_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditLeaveModal())

    @discord.ui.button(label="🔙 الرجوع للقائمة الرئيسية", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


class TicketDropdown(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        cat_select = discord.ui.ChannelSelect(placeholder="📂 اختر فئة (Category) التذاكر...", channel_types=[discord.ChannelType.category], min_values=1, max_values=1, row=0)
        async def cat_callback(interaction: discord.Interaction):
            cat = cat_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "ticket_category_id", cat.id)
            await interaction.response.send_message(f"✅ تم تحديد فئة التذاكر: **{cat.name}**", ephemeral=True)
        cat_select.callback = cat_callback
        self.add_item(cat_select)

        log_select = discord.ui.ChannelSelect(placeholder="📜 اختر قناة سجلات التذاكر المغلقة...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=1)
        async def log_callback(interaction: discord.Interaction):
            ch = log_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "ticket_log_channel_id", ch.id)
            await interaction.response.send_message(f"✅ تم تحديد قناة سجلات التذاكر: {ch.mention}", ephemeral=True)
        log_select.callback = log_callback
        self.add_item(log_select)

        role_select = discord.ui.RoleSelect(placeholder="🛡️ اختر رتبة الدعم الفني المسؤول...", min_values=1, max_values=1, row=2)
        async def role_callback(interaction: discord.Interaction):
            role = role_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "ticket_support_role_id", role.id)
            await interaction.response.send_message(f"✅ تم تحديد رتبة الدعم الفني: {role.mention}", ephemeral=True)
        role_select.callback = role_callback
        self.add_item(role_select)

    @discord.ui.button(label="📢 نشر بنل التذاكر في هذه القناة", style=discord.ButtonStyle.success, row=3)
    async def deploy_ticket_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        from dashboard import OpenTicketView # استيراد كلاس فتح التذكرة
        embed = discord.Embed(
            title="🎟️ قسم الدعم الفني والمساعدة",
            description="إذا كنت بحاجة إلى مساعدة أو استفسار، اضغط على الزر أدناه لفتح تذكرة خاصة بك.",
            color=discord.Color.green()
        )
        await interaction.channel.send(embed=embed, view=OpenTicketView())
        await interaction.response.send_message("✅ تم نشر بنل التذاكر في هذه القناة بنجاح!", ephemeral=True)

    @discord.ui.button(label="🔙 الرجوع للقائمة الرئيسية", style=discord.ButtonStyle.secondary, row=3)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


# ==================== الأقسام العادية (Views) ====================

class AutoModSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="تبديل الحماية العامة", style=discord.ButtonStyle.danger, row=0)
    async def toggle_automod(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['automod_enabled'] else 1
        await db.update_guild_setting(interaction.guild_id, "automod_enabled", new_val)
        await interaction.response.send_message(f"✅ تم {'تفعيل' if new_val else 'تعطيل'} نظام الحماية العام!", ephemeral=True)

    @discord.ui.button(label="منع الروابط", style=discord.ButtonStyle.primary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['anti_links'] else 1
        await db.update_guild_setting(interaction.guild_id, "anti_links", new_val)
        await interaction.response.send_message(f"✅ تم {'تفعيل' if new_val else 'تعطيل'} مانع الروابط الخارجية!", ephemeral=True)

    @discord.ui.button(label="منع الدعوات", style=discord.ButtonStyle.primary, row=0)
    async def toggle_invites(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        new_val = 0 if st['anti_invites'] else 1
        await db.update_guild_setting(interaction.guild_id, "anti_invites", new_val)
        await interaction.response.send_message(f"✅ تم {'تفعيل' if new_val else 'تعطيل'} مانع دعوات السيرفرات!", ephemeral=True)

    @discord.ui.button(label="تعديل الكلمات الممنوعة", style=discord.ButtonStyle.secondary, row=1)
    async def edit_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(EditBadwordsModal())

    @discord.ui.button(label="🔙 الرجوع للقائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
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

    @discord.ui.button(label="➕ إضافة رتبة زر تفاعلي", style=discord.ButtonStyle.secondary, row=1)
    async def add_btn_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AddButtonRoleModal())

    @discord.ui.button(label="🔙 الرجوع للقائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


class XPSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        # اختيار قناة التلفيل
        lvl_select = discord.ui.ChannelSelect(placeholder="🎉 اختر قناة إرسال تنبيهات اللفل...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1, row=0)
        async def lvl_callback(interaction: discord.Interaction):
            ch = lvl_select.values[0]
            await db.update_guild_setting(interaction.guild_id, "level_up_channel_id", ch.id)
            await interaction.response.send_message(f"✅ تم تحديد قناة تنبيهات اللفل إلى: {ch.mention}", ephemeral=True)
        lvl_select.callback = lvl_callback
        self.add_item(lvl_select)

    @discord.ui.button(label="تعديل معدلات الـ XP", style=discord.ButtonStyle.primary, row=1)
    async def edit_rates(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ChangeXPRatesModal())

    @discord.ui.button(label="🔙 الرجوع للقائمة الرئيسية", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(title="⚙️ لوحة تحكم السيرفر الشاملة", description="اختر القسم الذي تريد التحكم به من القائمة أدناه:", color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=MainDashboardView())


# ==================== الأزرار الثابتة للتذاكر (Persistent Views) ====================

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
        embed = discord.Embed(title=f"🎟️ تذكرة الدعم - {interaction.user.display_name}", description="أهلاً بك! يرجى توضيح مشكلتك وسيتم الرد عليك في أقرب وقت.", color=discord.Color.blue())
        
        await channel.send(content=f"{interaction.user.mention} {support_role.mention if support_role else ''}", embed=embed, view=CloseTicketView())
        await interaction.response.send_message(f"✅ تم فتح تذكرتك بنجاح: {channel.mention}", ephemeral=True)


class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 إغلاق التذكرة", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn_pro")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = await db.get_guild_settings(interaction.guild_id)
        log_chan_id = st['ticket_log_channel_id']
        
        await interaction.response.send_message("🔒 سيتم إغلاق وحذف التذكرة خلال 5 ثوانٍ...")

        if log_chan_id:
            log_chan = interaction.guild.get_channel(log_chan_id)
            if log_chan:
                embed = discord.Embed(title="🔒 سجل إغلاق تذكرة", color=discord.Color.red())
                embed.add_field(name="اسم القناة", value=interaction.channel.name)
                embed.add_field(name="بواسطة المشرف", value=interaction.user.mention)
                embed.set_footer(text=f"الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                await log_chan.send(embed=embed)

        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except:
            pass


# ==================== القائمة الرئيسية للداشبورد ====================

class DashboardSelectMenu(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="👋 الترحيب والمغادرة والسجلات", description="إعداد رومات الترحيب، المغادرة، السجلات، والرتبة التلقائية", emoji="👋", value="general"),
            discord.SelectOption(label="🛡️ الحماية والتعديل الآلي", description="إدارة نظام الحماية، منع الروابط والدعوات والكلمات", emoji="🛡️", value="automod"),
            discord.SelectOption(label="⭐ نظام اللفل والخبرة", description="تعديل معدلات الXP وقناة تنبيهات الللفل", emoji="⭐", value="xp"),
            discord.SelectOption(label="🎟️ نظام التذاكر المتقدم", description="ضبط كاتيجوري التذاكر، رتبة الدعم وسجلات الإغلاق", emoji="🎟️", value="tickets"),
            discord.SelectOption(label="🤖 الردود التلقائية ورتب الأزرار", description="إضافة ردود آلية، اختصارات الأوامر ورتب الأزرار", emoji="🤖", value="auto_responses"),
        ]
        super().__init__(placeholder="📂 اختر القسم الذي تريد التحكم به...", min_values=1, max_values=1, options=options)

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
            await interaction.response.edit_message(embed=embed, view=GeneralDropdown())

        elif sel == "automod":
            embed = discord.Embed(title="🛡️ إعدادات الحماية والتعديل الآلي", color=discord.Color.red())
            embed.add_field(name="الحماية العامة", value="✅ مفعلة" if st['automod_enabled'] else "❌ معطلة", inline=True)
            embed.add_field(name="منع الروابط", value="✅ مفعل" if st['anti_links'] else "❌ معطل", inline=True)
            embed.add_field(name="منع الدعوات", value="✅ مفعل" if st['anti_invites'] else "❌ معطل", inline=True)
            embed.add_field(name="الكلمات الممنوعة", value=st['automod_badwords'] if st['automod_badwords'] else "لا توجد كلمات", inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoModSettingsView())

        elif sel == "xp":
            embed = discord.Embed(title="⭐ إعدادات نظام اللفل والخبرة", color=discord.Color.gold())
            lvl_chan = interaction.guild.get_channel(st['level_up_channel_id'])
            embed.add_field(name="قناة تنبيهات اللفل", value=lvl_chan.mention if lvl_chan else "تلقائي في نفس الشات", inline=False)
            embed.add_field(name="معدل الكتابة", value=f"`{st['text_xp_rate']}` XP", inline=True)
            embed.add_field(name="معدل الصوت", value=f"`{st['voice_xp_rate']}` XP", inline=True)
            await interaction.response.edit_message(embed=embed, view=XPSettingsView())

        elif sel == "tickets":
            embed = discord.Embed(title="🎟️ إعدادات نظام التذاكر", color=discord.Color.blue())
            t_cat = interaction.guild.get_channel(st['ticket_category_id'])
            t_log = interaction.guild.get_channel(st['ticket_log_channel_id'])
            s_role = interaction.guild.get_role(st['ticket_support_role_id'])
            
            embed.add_field(name="فئة التذاكر (Category)", value=t_cat.name if t_cat else "غير محددة", inline=False)
            embed.add_field(name="قناة السجلات", value=t_log.mention if t_log else "غير محددة", inline=True)
            embed.add_field(name="رتبة الدعم الفني", value=s_role.mention if s_role else "غير محددة", inline=True)
            await interaction.response.edit_message(embed=embed, view=TicketDropdown())

        elif sel == "auto_responses":
            embed = discord.Embed(title="🤖 الردود التلقائية ورتب الأزرار", color=discord.Color.purple())
            responses = await db.get_auto_responses(interaction.guild_id)
            aliases = await db.get_custom_aliases(interaction.guild_id)
            
            resp_str = "\n".join([f"• `{r['trigger_text']}` ➔ {r['response_text']}" for r in responses[:10]]) if responses else "لا توجد ردود"
            alias_str = "\n".join([f"• `{a['alias']}` ➔ `/{a['command_name']}`" for a in aliases[:10]]) if aliases else "لا توجد اختصارات"

            embed.add_field(name="💬 الردود التلقائية الحالية", value=resp_str, inline=False)
            embed.add_field(name="⚡ اختصارات الأوامر", value=alias_str, inline=False)
            await interaction.response.edit_message(embed=embed, view=AutoResponseView())


class MainDashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DashboardSelectMenu())


class Dashboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="dashboard", description="فتح لوحة تحكم السيرفر الشاملة لإدارة كل إعدادات البوت")
    @app_commands.checks.has_permissions(administrator=True)
    async def dashboard(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ لوحة تحكم السيرفر الشاملة",
            description="مرحباً بك في لوحة التحكم الداخلية الخاصة بسيرفرك!\nاختر القسم الذي تريد تعديله من القائمة أدناه.",
            color=discord.Color.blurple()
        )
        view = MainDashboardView()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
