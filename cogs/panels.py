"""
نظام اللوحات المتكامل (إمبد / تذاكر / أزرار رتب)
ضع الملف داخل مجلد cogs  —  يتطلب discord.py >= 2.4
الأمر: /panels
"""
import asyncio
import copy
import io
import re
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from database import db

# ─────────────────────────── ثوابت ───────────────────────────
PANEL_TYPES = {
    "embed": ("📌", "إمبد عادي"),
    "ticket": ("🎫", "لوحة تذاكر"),
    "roles": ("🎭", "أزرار رتب"),
}
STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}
STYLE_AR = {"primary": "أزرق", "secondary": "رمادي", "success": "أخضر", "danger": "أحمر"}
MODE_AR = {"toggle": "تبديل (إضافة/إزالة)", "add": "إضافة فقط", "remove": "إزالة فقط"}

DEFAULT_EMBEDS = {
    "embed": {"title": "📌 عنوان الإمبد", "description": "اكتب وصف الإمبد هنا.", "color": 0x5865F2},
    "ticket": {"title": "🎫 الدعم الفني", "description": "اضغط الزر بالأسفل لفتح تذكرة وسيقوم فريق الدعم بمساعدتك.", "color": 0x57F287},
    "roles": {"title": "🎭 اختيار الرتب", "description": "اضغط على الأزرار للحصول على الرتب أو إزالتها.", "color": 0x9B59B6},
}


def default_config(ptype: str) -> dict:
    base = {"content": "", "show_timestamp": False}
    if ptype == "ticket":
        base.update({
            "button": {"label": "فتح تذكرة", "emoji": "🎫", "style": "success"},
            "category_id": 0,
            "log_channel_id": 0,
            "support_role_ids": [],
            "max_open": 1,
            "name_format": "ticket-{number}",
            "ask_reason": True,
            "claim_enabled": True,
            "mention_support": True,
            "welcome_title": "🎫 تذكرة رقم {number}",
            "welcome_desc": "أهلاً {user} 👋\nتم فتح تذكرتك، اشرح مشكلتك وسيرد عليك فريق الدعم قريباً.\n\n**السبب:** {reason}",
            "welcome_color": "#57F287",
        })
    elif ptype == "roles":
        base.update({"buttons": [], "next_uid": 1, "exclusive": False})
    return base


# ─────────────────────────── أدوات مساعدة ───────────────────────────
def parse_color(text: str) -> Optional[int]:
    t = (text or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", t):
        return int(t, 16)
    return None


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://"))


def safe_emoji(text: Optional[str]) -> Optional[discord.PartialEmoji]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        p = discord.PartialEmoji.from_str(text)
    except Exception:
        return None
    if p.id is None and text.isascii():
        return None
    return p


def fmt(text: str, **kw) -> str:
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def make_button(btn: dict, custom_id: str, default_label: str, row: Optional[int] = None) -> discord.ui.Button:
    label = (btn.get("label") or "").strip() or None
    emoji = safe_emoji(btn.get("emoji"))
    if not label and not emoji:
        label = default_label
    return discord.ui.Button(
        label=label,
        emoji=emoji,
        style=STYLE_MAP.get(btn.get("style"), discord.ButtonStyle.secondary),
        custom_id=custom_id,
        row=row,
    )


async def load_panel(panel_id: int, guild_id: int) -> Optional[dict]:
    panel = await db.get_panel(panel_id)
    if not panel or panel["guild_id"] != guild_id:
        return None
    panel["config"] = {**default_config(panel["ptype"]), **panel["config"]}
    return panel


def build_embed(panel: dict) -> discord.Embed:
    e = discord.Embed.from_dict(copy.deepcopy(panel["embed"]))
    if e.color is None:
        e.color = discord.Color.blurple()
    if panel["config"].get("show_timestamp"):
        e.timestamp = discord.utils.utcnow()
    if not (e.title or e.description or e.fields):
        e.description = "لم يتم تعيين محتوى بعد."
    return e


def build_public_view(panel: dict) -> Optional[discord.ui.View]:
    cfg = panel["config"]
    view = discord.ui.View(timeout=None)
    if panel["ptype"] == "ticket":
        view.add_item(TicketOpenButton(panel["id"], cfg.get("button")))
    elif panel["ptype"] == "roles":
        for i, b in enumerate(cfg.get("buttons", [])[:25]):
            view.add_item(RoleButton(panel["id"], b["uid"], b, row=i // 5))
    return view if view.children else None


async def get_support_role_ids(guild_id: int, cfg: dict) -> list:
    ids = list(cfg.get("support_role_ids") or [])
    if not ids:
        st = await db.get_guild_settings(guild_id)
        ids = list(st.get("ticket_support_role_ids") or [])
        if not ids and st.get("ticket_support_role_id"):
            ids = [st["ticket_support_role_id"]]
    return ids


async def respond(interaction: discord.Interaction, text: str, **kw):
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True, **kw)
    else:
        await interaction.response.send_message(text, ephemeral=True, **kw)


# ─────────────────────────── أزرار ديناميكية دائمة ───────────────────────────
class TicketOpenButton(discord.ui.DynamicItem[discord.ui.Button], template=r"panel:tk:open:(?P<id>\d+)"):
    def __init__(self, panel_id: int, btn: Optional[dict] = None):
        super().__init__(make_button(btn or {}, f"panel:tk:open:{panel_id}", "فتح تذكرة"))
        self.panel_id = panel_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match, /):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction):
        await handle_ticket_open(interaction, self.panel_id)


class TicketCloseButton(discord.ui.DynamicItem[discord.ui.Button], template=r"panel:tk:close"):
    def __init__(self):
        super().__init__(discord.ui.Button(label="إغلاق التذكرة", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="panel:tk:close"))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket = await db.get_ticket(interaction.channel_id)
        if not ticket or ticket["status"] != "open":
            return await respond(interaction, "❌ هذه ليست تذكرة مفتوحة.")
        if not await can_manage_ticket(interaction, ticket, allow_owner=True):
            return await respond(interaction, "❌ لا تملك صلاحية إغلاق هذه التذكرة.")
        await interaction.followup.send(
            "⚠️ هل أنت متأكد من إغلاق التذكرة؟ سيتم حفظ سجل المحادثة ثم حذف القناة.",
            view=ConfirmCloseView(interaction.user.id, ticket), ephemeral=True
        )


class TicketClaimButton(discord.ui.DynamicItem[discord.ui.Button], template=r"panel:tk:claim"):
    def __init__(self, disabled: bool = False, label: str = "استلام التذكرة"):
        super().__init__(discord.ui.Button(label=label[:80], emoji="🙋", style=discord.ButtonStyle.primary,
                                           custom_id="panel:tk:claim", disabled=disabled))

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket = await db.get_ticket(interaction.channel_id)
        if not ticket or ticket["status"] != "open":
            return await respond(interaction, "❌ هذه ليست تذكرة مفتوحة.")
        if not await can_manage_ticket(interaction, ticket, allow_owner=False):
            return await respond(interaction, "❌ استلام التذاكر لفريق الدعم فقط.")
        if ticket.get("claimed_by"):
            return await respond(interaction, "❌ التذكرة مستلمة بالفعل.")
        await db.set_ticket_claim(interaction.channel_id, interaction.user.id)
        try:
            await interaction.message.edit(view=build_ticket_controls(True, True, interaction.user.display_name))
        except Exception:
            pass
        await interaction.followup.send(f"✅ استلم {interaction.user.mention} هذه التذكرة.", ephemeral=True)


class RoleButton(discord.ui.DynamicItem[discord.ui.Button], template=r"panel:rr:(?P<pid>\d+):(?P<uid>\d+)"):
    def __init__(self, panel_id: int, uid: int, btn: Optional[dict] = None, row: Optional[int] = None):
        super().__init__(make_button(btn or {}, f"panel:rr:{panel_id}:{uid}", "رتبة", row=row))
        self.panel_id, self.uid = panel_id, uid

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(int(match["pid"]), int(match["uid"]))

    async def callback(self, interaction: discord.Interaction):
        await handle_role_click(interaction, self.panel_id, self.uid)


# ─────────────────────────── منطق الرتب ───────────────────────────
async def handle_role_click(interaction: discord.Interaction, panel_id: int, uid: int):
    await interaction.response.defer(ephemeral=True)
    panel = await load_panel(panel_id, interaction.guild_id)
    if not panel or panel["ptype"] != "roles":
        return await respond(interaction, "❌ هذه اللوحة لم تعد موجودة.")
    cfg = panel["config"]
    btns = cfg.get("buttons", [])
    b = next((x for x in btns if x["uid"] == uid), None)
    if not b:
        return await respond(interaction, "❌ هذا الزر لم يعد مفعلاً.")
    guild, member = interaction.guild, interaction.user
    role = guild.get_role(b["role_id"])
    if not role:
        return await respond(interaction, "❌ الرتبة المرتبطة بالزر محذوفة.")
    me = guild.me
    if role.managed or role >= me.top_role:
        return await respond(interaction, "❌ لا أستطيع التحكم بهذه الرتبة (رتبتي أقل منها أو أنها رتبة بوت).")

    mode = b.get("mode", "toggle")
    has = role in member.roles
    try:
        if mode == "remove" or (mode == "toggle" and has):
            if not has:
                return await interaction.followup.send(f"ℹ️ ليست لديك الرتبة {role.mention}.", ephemeral=True)
            await member.remove_roles(role, reason="لوحة رتب")
            return await interaction.followup.send(f"➖ تمت إزالة الرتبة {role.mention}.", ephemeral=True)

        if has:
            return await interaction.followup.send(f"ℹ️ لديك الرتبة {role.mention} بالفعل.", ephemeral=True)
        if cfg.get("exclusive"):
            others = [guild.get_role(x["role_id"]) for x in btns if x["role_id"] != role.id]
            others = [r for r in others if r and r in member.roles and not r.managed and r < me.top_role]
            if others:
                await member.remove_roles(*others, reason="لوحة رتب (وضع حصري)")
        await member.add_roles(role, reason="لوحة رتب")
        await interaction.followup.send(f"➕ تمت إضافة الرتبة {role.mention}.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ ليست لدي صلاحية Manage Roles أو رتبتي أقل من الرتبة.", ephemeral=True)


# ─────────────────────────── منطق التذاكر ───────────────────────────
def build_ticket_controls(claim_enabled: bool, claimed: bool = False, claimer: str = "") -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(TicketCloseButton())
    if claim_enabled:
        view.add_item(TicketClaimButton(disabled=claimed, label=f"استلمها {claimer}" if claimed else "استلام التذكرة"))
    return view


async def can_manage_ticket(interaction: discord.Interaction, ticket: dict, allow_owner: bool) -> bool:
    user = interaction.user
    if user.guild_permissions.administrator or user.guild_permissions.manage_channels:
        return True
    if allow_owner and user.id == ticket["owner_id"]:
        return True
    panel = await load_panel(ticket["panel_id"], interaction.guild_id)
    cfg = panel["config"] if panel else {}
    role_ids = set(await get_support_role_ids(interaction.guild_id, cfg))
    return any(r.id in role_ids for r in user.roles)


async def handle_ticket_open(interaction: discord.Interaction, panel_id: int):
    panel = await load_panel(panel_id, interaction.guild_id)
    if not panel or panel["ptype"] != "ticket":
        return await respond(interaction, "❌ هذه اللوحة لم تعد موجودة.")
    cfg = panel["config"]

    rows = await db.get_open_tickets(interaction.guild_id, panel_id, interaction.user.id)
    alive = []
    for r in rows:
        if interaction.guild.get_channel(r["channel_id"]):
            alive.append(r)
        else:
            await db.close_ticket(r["channel_id"])
    if len(alive) >= max(1, int(cfg.get("max_open", 1))):
        ch = interaction.guild.get_channel(alive[0]["channel_id"])
        return await respond(interaction, f"❌ لديك تذكرة مفتوحة بالفعل: {ch.mention}")

    if cfg.get("ask_reason", True):
        await interaction.response.send_modal(TicketReasonModal(panel_id))
    else:
        await interaction.response.defer(ephemeral=True)
        await create_ticket_channel(interaction, panel, "—")


class TicketReasonModal(discord.ui.Modal, title="فتح تذكرة"):
    reason = discord.ui.TextInput(label="سبب فتح التذكرة", style=discord.TextStyle.paragraph,
                                  placeholder="اشرح مشكلتك باختصار...", required=True, max_length=800)

    def __init__(self, panel_id: int):
        super().__init__()
        self.panel_id = panel_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        if not panel:
            return await interaction.followup.send("❌ هذه اللوحة لم تعد موجودة.", ephemeral=True)
        await create_ticket_channel(interaction, panel, self.reason.value)


async def create_ticket_channel(interaction: discord.Interaction, panel: dict, reason: str):
    guild, user, cfg = interaction.guild, interaction.user, panel["config"]
    st = await db.get_guild_settings(guild.id)

    cat_id = cfg.get("category_id") or st.get("ticket_category_id") or 0
    category = guild.get_channel(cat_id) if cat_id else None
    if not isinstance(category, discord.CategoryChannel):
        category = None

    support_roles = [r for r in (guild.get_role(i) for i in await get_support_role_ids(guild.id, cfg)) if r]
    member_perms = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                               attach_files=True, embed_links=True)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: member_perms,
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True,
                                              manage_messages=True, embed_links=True, read_message_history=True,
                                              attach_files=True),
    }
    for r in support_roles:
        overwrites[r] = member_perms

    number = await db.next_ticket_number(guild.id)
    name = fmt(cfg.get("name_format") or "ticket-{number}", number=f"{number:04d}", user=user.name)
    name = re.sub(r"\s+", "-", name.lower())[:90] or f"ticket-{number:04d}"

    try:
        channel = await guild.create_text_channel(name, category=category, overwrites=overwrites,
                                                  reason=f"تذكرة جديدة من {user}")
    except discord.Forbidden:
        return await interaction.followup.send("❌ لا أملك صلاحية Manage Channels لإنشاء التذكرة.", ephemeral=True)
    except discord.HTTPException as e:
        return await interaction.followup.send(f"❌ تعذر إنشاء القناة: {e}", ephemeral=True)

    await db.create_ticket(channel.id, guild.id, panel["id"], user.id, number)

    color = parse_color(cfg.get("welcome_color", "")) or 0x57F287
    emb = discord.Embed(
        title=fmt(cfg.get("welcome_title", ""), number=f"{number:04d}", user=user.display_name, reason=reason, server=guild.name),
        description=fmt(cfg.get("welcome_desc", ""), number=f"{number:04d}", user=user.mention, reason=reason, server=guild.name),
        color=color,
    )
    emb.set_footer(text=f"صاحب التذكرة: {user}")
    mentions = user.mention
    if cfg.get("mention_support", True) and support_roles:
        mentions += " " + " ".join(r.mention for r in support_roles)
    await channel.send(content=mentions, embed=emb,
                       view=build_ticket_controls(cfg.get("claim_enabled", True)),
                       allowed_mentions=discord.AllowedMentions(users=True, roles=True))

    await send_ticket_log(guild, cfg, st, discord.Embed(
        title="🎫 تذكرة جديدة", color=discord.Color.green(),
        description=f"**القناة:** {channel.mention}\n**المالك:** {user.mention}\n**السبب:** {reason[:500]}"))
    await interaction.followup.send(f"✅ تم فتح تذكرتك: {channel.mention}", ephemeral=True)


async def send_ticket_log(guild: discord.Guild, cfg: dict, st: dict, embed: discord.Embed, file: discord.File = None):
    log_id = cfg.get("log_channel_id") or st.get("ticket_log_channel_id") or 0
    ch = guild.get_channel(log_id) if log_id else None
    if isinstance(ch, discord.TextChannel):
        try:
            await ch.send(embed=embed, file=file) if file else await ch.send(embed=embed)
        except discord.HTTPException:
            pass


async def build_transcript(channel: discord.TextChannel) -> io.BytesIO:
    lines = []
    async for m in channel.history(limit=1000, oldest_first=True):
        text = m.clean_content or ""
        if m.embeds:
            text += " [embed]"
        for a in m.attachments:
            text += f" [{a.url}]"
        lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {text}")
    return io.BytesIO("\n".join(lines).encode("utf-8"))


class ConfirmCloseView(discord.ui.View):
    def __init__(self, user_id: int, ticket: dict):
        super().__init__(timeout=60)
        self.user_id, self.ticket = user_id, ticket

    @discord.ui.button(label="تأكيد الإغلاق", style=discord.ButtonStyle.danger, emoji="🔒")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.user_id:
            return await respond(interaction, "❌ هذا الزر ليس لك.")
        await interaction.edit_original_response(content="⏳ جاري إغلاق التذكرة...", view=None)
        channel = interaction.channel
        guild = interaction.guild
        await db.close_ticket(channel.id)
        panel = await load_panel(self.ticket["panel_id"], guild.id)
        cfg = panel["config"] if panel else {}
        st = await db.get_guild_settings(guild.id)
        try:
            transcript = await build_transcript(channel)
            owner = guild.get_member(self.ticket["owner_id"])
            claimed = self.ticket.get("claimed_by")
            emb = discord.Embed(title="🔒 تذكرة مغلقة", color=discord.Color.red())
            emb.add_field(name="التذكرة", value=f"`{channel.name}`", inline=True)
            emb.add_field(name="المالك", value=owner.mention if owner else f"<@{self.ticket['owner_id']}>", inline=True)
            emb.add_field(name="أغلقها", value=interaction.user.mention, inline=True)
            if claimed:
                emb.add_field(name="استلمها", value=f"<@{claimed}>", inline=True)
            await send_ticket_log(guild, cfg, st, emb, discord.File(transcript, filename=f"{channel.name}.txt"))
        except Exception as e:
            print(f"تعذر حفظ سجل التذكرة: {e}")
        try:
            await channel.send("🔒 سيتم حذف هذه القناة بعد 5 ثوانٍ...")
            await asyncio.sleep(5)
            await channel.delete(reason=f"إغلاق تذكرة بواسطة {interaction.user}")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="إلغاء", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.edit_original_response(content="تم الإلغاء.", view=None)


# ─────────────────────────── واجهة الإدارة: أساسيات ───────────────────────────
class OwnedView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 900):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("❌ هذه القائمة ليست لك!", ephemeral=True)
            return False
        return True


class ChoiceSelect(discord.ui.Select):
    def __init__(self, choices: dict, current, placeholder: str, handler, row: Optional[int] = None):
        opts = [discord.SelectOption(label=lbl, value=k, default=(k == current)) for k, lbl in choices.items()]
        super().__init__(placeholder=placeholder, options=opts, min_values=1, max_values=1, row=row)
        self.handler = handler

    async def callback(self, interaction: discord.Interaction):
        await self.handler(interaction, self.values[0])


# ---------- الصفحة الرئيسية ----------
async def show_home(interaction: discord.Interaction, new: bool = False):
    panels = await db.get_panels(interaction.guild_id)
    if panels:
        lines = [f"{PANEL_TYPES.get(p['ptype'], ('📌',''))[0]} **{p['name']}** — {PANEL_TYPES.get(p['ptype'], ('', 'إمبد'))[1]}"
                 for p in panels[:25]]
        desc = "\n".join(lines)
        if len(panels) > 25:
            desc += "\n… (يعرض أول 25 لوحة)"
    else:
        desc = "لا توجد لوحات بعد. أنشئ أول لوحة بالزر بالأسفل."
    emb = discord.Embed(title="🧩 نظام اللوحات المتكامل", description=desc, color=discord.Color.blurple())
    emb.set_footer(text="إمبد عادي • لوحة تذاكر • أزرار رتب")
    view = HomeView(interaction.user.id, panels)
    if new:
        if interaction.response.is_done():
            await interaction.followup.send(embed=emb, view=view, ephemeral=True)
        else:
            await interaction.response.send_message(embed=emb, view=view, ephemeral=True)
    else:
        await interaction.response.edit_message(content=None, embeds=[emb], view=view)


async def open_panels_home(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await respond(interaction, "❌ هذا القسم للإدارة فقط.")
    await interaction.response.defer(ephemeral=True)
    await show_home(interaction, new=True)


class PanelPickSelect(discord.ui.Select):
    def __init__(self, panels: list):
        opts = [discord.SelectOption(label=p["name"][:100], value=str(p["id"]),
                                     description=PANEL_TYPES.get(p["ptype"], ("", "إمبد"))[1],
                                     emoji=PANEL_TYPES.get(p["ptype"], ("📌", ""))[0]) for p in panels[:25]]
        super().__init__(placeholder="اختر لوحة لتعديلها...", options=opts, min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await show_editor(interaction, int(self.values[0]))


class HomeView(OwnedView):
    def __init__(self, owner_id: int, panels: list):
        super().__init__(owner_id)
        if panels:
            self.add_item(PanelPickSelect(panels))

    @discord.ui.button(label="➕ إنشاء لوحة جديدة", style=discord.ButtonStyle.success, row=1)
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        emb = discord.Embed(title="➕ إنشاء لوحة", description="اختر نوع اللوحة:", color=discord.Color.green())
        await interaction.edit_original_response(embeds=[emb], view=CreateTypeView(interaction.user.id))


class CreateTypeView(OwnedView):
    def __init__(self, owner_id: int):
        super().__init__(owner_id)
        choices = {k: f"{v[0]} {v[1]}" for k, v in PANEL_TYPES.items()}
        self.add_item(ChoiceSelect(choices, None, "اختر نوع اللوحة...", self.on_choose, row=0))

    async def on_choose(self, interaction: discord.Interaction, ptype: str):
        await interaction.response.send_modal(NamePanelModal(ptype))

    @discord.ui.button(label="◀ رجوع", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_home(interaction)


class NamePanelModal(discord.ui.Modal, title="اسم اللوحة"):
    name = discord.ui.TextInput(label="اسم اللوحة (للإدارة فقط)", placeholder="مثال: rules أو support", max_length=50)

    def __init__(self, ptype: str):
        super().__init__()
        self.ptype = ptype

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        name = self.name.value.strip()
        if not name:
            return await interaction.followup.send("❌ الاسم مطلوب.", ephemeral=True)
        if await db.get_panel_by_name(interaction.guild_id, name):
            return await interaction.followup.send("❌ يوجد لوحة بنفس الاسم، اختر اسماً آخر.", ephemeral=True)
        pid = await db.create_panel(interaction.guild_id, name, self.ptype,
                                    copy.deepcopy(DEFAULT_EMBEDS[self.ptype]), default_config(self.ptype))
        panel = await load_panel(pid, interaction.guild_id)
        payload = await editor_payload(interaction.guild, panel, interaction.user.id)
        await interaction.edit_original_response(**payload)


# ---------- المحرر ----------
def describe_panel(guild: discord.Guild, panel: dict) -> str:
    cfg, lines = panel["config"], []
    if cfg.get("content"):
        lines.append(f"📝 **نص فوق الإمبد:** {cfg['content'][:100]}")
    lines.append(f"🕒 **التوقيت:** {'مفعل' if cfg.get('show_timestamp') else 'معطل'}")
    if panel["ptype"] == "ticket":
        b = cfg["button"]
        cat = guild.get_channel(cfg.get("category_id", 0))
        lg = guild.get_channel(cfg.get("log_channel_id", 0))
        roles = [f"<@&{i}>" for i in cfg.get("support_role_ids", [])]
        lines += [
            f"🔘 **الزر:** {b.get('emoji', '')} {b.get('label', '')} ({STYLE_AR.get(b.get('style'), '—')})",
            f"📁 **الكاتيجوري:** {cat.name if cat else 'غير محددة / من إعدادات السيرفر'}",
            f"📜 **سجل التذاكر:** {lg.mention if lg else 'غير محددة / من إعدادات السيرفر'}",
            f"🛡️ **رتب الدعم:** {' '.join(roles) if roles else 'غير محددة / من إعدادات السيرفر'}",
        ]
    elif panel["ptype"] == "roles":
        btns = cfg.get("buttons", [])
        lines.append(f"🔘 **عدد الأزرار:** {len(btns)}  |  🔒 **حصري:** {'نعم' if cfg.get('exclusive') else 'لا'}")
        for b in btns[:10]:
            lines.append(f"• {b.get('emoji', '')} {b.get('label', '')} ➜ <@&{b['role_id']}>")
    return "\n".join(lines)


async def editor_payload(guild: discord.Guild, panel: dict, owner_id: int) -> dict:
    icon, label = PANEL_TYPES.get(panel["ptype"], ("📌", "إمبد"))
    info = discord.Embed(title=f"{icon} لوحة: {panel['name']}  ({label})", color=discord.Color.dark_grey())
    pub = "❌ غير منشورة"
    if panel["message_id"] and panel["channel_id"]:
        pub = f"https://discord.com/channels/{guild.id}/{panel['channel_id']}/{panel['message_id']}"
    info.description = describe_panel(guild, panel) + f"\n📤 **النشر:** {pub}"
    info.set_footer(text="الأعلى: معاينة الإمبد • عدّل ثم اضغط نشر/تحديث")
    return {"content": None, "embeds": [build_embed(panel), info], "view": PanelEditorView(owner_id, panel)}


async def show_editor(interaction: discord.Interaction, panel_id: int, new: bool = False):
    panel = await load_panel(panel_id, interaction.guild_id)
    if not panel:
        return await respond(interaction, "❌ اللوحة غير موجودة.")
    payload = await editor_payload(interaction.guild, panel, interaction.user.id)
    if new:
        if interaction.response.is_done():
            await interaction.followup.send(**payload, ephemeral=True)
        else:
            await interaction.response.send_message(**payload, ephemeral=True)
    else:
        await interaction.edit_original_response(**payload)


class PanelEditorView(OwnedView):
    def __init__(self, owner_id: int, panel: dict):
        super().__init__(owner_id)
        self.panel_id = panel["id"]
        self.toggle_ts.label = f"🕒 التوقيت: {'✅' if panel['config'].get('show_timestamp') else '❌'}"
        if panel["ptype"] == "ticket":
            b = discord.ui.Button(label="🎫 إعدادات التذكرة", style=discord.ButtonStyle.primary, row=1)
            b.callback = self.open_ticket_settings
            self.add_item(b)
        elif panel["ptype"] == "roles":
            b = discord.ui.Button(label="🎭 أزرار الرتب", style=discord.ButtonStyle.primary, row=1)
            b.callback = self.open_roles
            self.add_item(b)

    @discord.ui.button(label="📝 الأساسيات", style=discord.ButtonStyle.primary, row=0)
    async def basics(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(BasicsModal(panel))

    @discord.ui.button(label="👤 المؤلف والفوتر", style=discord.ButtonStyle.secondary, row=0)
    async def author_footer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(AuthorFooterModal(panel))

    @discord.ui.button(label="🖼️ الصور", style=discord.ButtonStyle.secondary, row=0)
    async def images(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(ImagesModal(panel))

    @discord.ui.button(label="🧾 الحقول", style=discord.ButtonStyle.secondary, row=0)
    async def fields(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_fields(interaction, self.panel_id)

    @discord.ui.button(label="🕒 التوقيت", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_ts(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"]["show_timestamp"] = not panel["config"].get("show_timestamp")
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_editor(interaction, self.panel_id)

    async def open_ticket_settings(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await show_ticket_settings(interaction, self.panel_id)

    async def open_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await show_roles_manager(interaction, self.panel_id)

    @discord.ui.button(label="📤 نشر في قناة", style=discord.ButtonStyle.success, row=2)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        emb = discord.Embed(title="📤 اختر القناة المراد النشر فيها", color=discord.Color.green())
        await interaction.edit_original_response(embeds=[emb], view=PublishView(interaction.user.id, self.panel_id))

    @discord.ui.button(label="🔄 تحديث المنشورة", style=discord.ButtonStyle.success, row=2)
    async def update_published(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        if not panel["message_id"]:
            return await interaction.followup.send("❌ هذه اللوحة غير منشورة بعد، استخدم «نشر في قناة».", ephemeral=True)
        ch = interaction.guild.get_channel(panel["channel_id"])
        try:
            msg = await ch.fetch_message(panel["message_id"])
            await msg.edit(content=panel["config"].get("content") or None, embed=build_embed(panel),
                           view=build_public_view(panel))
        except (discord.NotFound, AttributeError):
            return await interaction.followup.send("❌ الرسالة المنشورة محذوفة، انشرها من جديد.", ephemeral=True)
        except discord.HTTPException as e:
            return await interaction.followup.send(f"❌ تعذر التحديث: {e}", ephemeral=True)
        await interaction.followup.send(f"✅ تم تحديث الرسالة المنشورة: {msg.jump_url}", ephemeral=True)

    @discord.ui.button(label="🗑️ حذف", style=discord.ButtonStyle.danger, row=2)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        emb = discord.Embed(title="⚠️ تأكيد الحذف",
                            description="سيتم حذف اللوحة نهائياً **ومعها الرسالة المنشورة** (إن وُجدت).",
                            color=discord.Color.red())
        await interaction.edit_original_response(embeds=[emb], view=DeleteConfirmView(interaction.user.id, self.panel_id))

    @discord.ui.button(label="◀ القائمة", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_home(interaction)


class BackToEditorView(OwnedView):
    def __init__(self, owner_id: int, panel_id: int):
        super().__init__(owner_id)
        self.panel_id = panel_id

    @discord.ui.button(label="◀ رجوع للمحرر", style=discord.ButtonStyle.secondary)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_editor(interaction, self.panel_id)


class DeleteConfirmView(BackToEditorView):
    @discord.ui.button(label="تأكيد الحذف", style=discord.ButtonStyle.danger, row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        if panel and panel["message_id"]:
            ch = interaction.guild.get_channel(panel["channel_id"])
            try:
                msg = await ch.fetch_message(panel["message_id"])
                await msg.delete()
            except Exception:
                pass
        await db.delete_panel(self.panel_id)
        await show_home(interaction)


class PublishView(BackToEditorView):
    def __init__(self, owner_id: int, panel_id: int):
        super().__init__(owner_id, panel_id)
        sel = discord.ui.ChannelSelect(placeholder="📢 اختر القناة...", channel_types=[discord.ChannelType.text],
                                       min_values=1, max_values=1, row=0)
        sel.callback = self.on_select
        self.sel = sel
        self.add_item(sel)

    async def on_select(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ch = interaction.guild.get_channel(self.sel.values[0].id)
        perms = ch.permissions_for(interaction.guild.me)
        if not (perms.view_channel and perms.send_messages and perms.embed_links):
            return await interaction.followup.send("❌ لا أملك صلاحية الإرسال/الإمبد في هذه القناة.", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        try:
            msg = await ch.send(content=panel["config"].get("content") or None, embed=build_embed(panel),
                                view=build_public_view(panel))
        except discord.HTTPException as e:
            return await interaction.followup.send(f"❌ تعذر النشر: {e}", ephemeral=True)
        await db.update_panel(self.panel_id, channel_id=ch.id, message_id=msg.id)
        await interaction.edit_original_response(content=f"✅ تم النشر: {msg.jump_url}", embeds=[],
                                                view=BackToEditorView(interaction.user.id, self.panel_id))


# ---------- مودالات الإمبد ----------
class BasicsModal(discord.ui.Modal, title="الأساسيات"):
    m_title = discord.ui.TextInput(label="العنوان", required=False, max_length=256)
    m_desc = discord.ui.TextInput(label="الوصف", style=discord.TextStyle.paragraph, required=False, max_length=4000)
    m_color = discord.ui.TextInput(label="اللون HEX (مثل #5865F2)", required=False, max_length=7)
    m_url = discord.ui.TextInput(label="رابط العنوان (اختياري)", required=False, max_length=300)
    m_content = discord.ui.TextInput(label="نص فوق الإمبد (اختياري)", required=False, max_length=500)

    def __init__(self, panel: dict):
        super().__init__()
        self.panel_id = panel["id"]
        e = panel["embed"]
        self.m_title.default = e.get("title")
        self.m_desc.default = e.get("description")
        if e.get("color") is not None:
            self.m_color.default = f"#{e['color']:06X}"
        self.m_url.default = e.get("url")
        self.m_content.default = panel["config"].get("content") or None

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        e, cfg = panel["embed"], panel["config"]

        def put(key, val):
            val = (val or "").strip()
            if val:
                e[key] = val
            else:
                e.pop(key, None)

        put("title", self.m_title.value)
        put("description", self.m_desc.value)
        if self.m_color.value.strip():
            c = parse_color(self.m_color.value)
            if c is None:
                return await interaction.followup.send("❌ اللون غير صالح، استخدم صيغة مثل #5865F2", ephemeral=True)
            e["color"] = c
        else:
            e.pop("color", None)
        url = self.m_url.value.strip()
        if url and not is_url(url):
            return await interaction.followup.send("❌ رابط العنوان يجب أن يبدأ بـ http:// أو https://", ephemeral=True)
        put("url", url)
        cfg["content"] = self.m_content.value.strip()
        await db.update_panel(self.panel_id, embed=e, config=cfg)
        await show_editor(interaction, self.panel_id)


class AuthorFooterModal(discord.ui.Modal, title="المؤلف والفوتر"):
    a_name = discord.ui.TextInput(label="اسم المؤلف", required=False, max_length=256)
    a_icon = discord.ui.TextInput(label="رابط أيقونة المؤلف", required=False, max_length=300)
    a_url = discord.ui.TextInput(label="رابط المؤلف", required=False, max_length=300)
    f_text = discord.ui.TextInput(label="نص الفوتر", required=False, max_length=2000)
    f_icon = discord.ui.TextInput(label="رابط أيقونة الفوتر", required=False, max_length=300)

    def __init__(self, panel: dict):
        super().__init__()
        self.panel_id = panel["id"]
        a, f = panel["embed"].get("author", {}), panel["embed"].get("footer", {})
        self.a_name.default, self.a_icon.default, self.a_url.default = a.get("name"), a.get("icon_url"), a.get("url")
        self.f_text.default, self.f_icon.default = f.get("text"), f.get("icon_url")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        for v in (self.a_icon.value, self.a_url.value, self.f_icon.value):
            if v.strip() and not is_url(v.strip()):
                return await interaction.followup.send("❌ كل الروابط يجب أن تبدأ بـ http:// أو https://", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        e = panel["embed"]
        if self.a_name.value.strip():
            a = {"name": self.a_name.value.strip()}
            if self.a_icon.value.strip():
                a["icon_url"] = self.a_icon.value.strip()
            if self.a_url.value.strip():
                a["url"] = self.a_url.value.strip()
            e["author"] = a
        else:
            e.pop("author", None)
        if self.f_text.value.strip():
            f = {"text": self.f_text.value.strip()}
            if self.f_icon.value.strip():
                f["icon_url"] = self.f_icon.value.strip()
            e["footer"] = f
        else:
            e.pop("footer", None)
        await db.update_panel(self.panel_id, embed=e)
        await show_editor(interaction, self.panel_id)


class ImagesModal(discord.ui.Modal, title="الصور"):
    img = discord.ui.TextInput(label="رابط الصورة الكبيرة", required=False, max_length=500)
    thumb = discord.ui.TextInput(label="رابط الصورة المصغرة", required=False, max_length=500)

    def __init__(self, panel: dict):
        super().__init__()
        self.panel_id = panel["id"]
        self.img.default = panel["embed"].get("image", {}).get("url")
        self.thumb.default = panel["embed"].get("thumbnail", {}).get("url")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        for v in (self.img.value, self.thumb.value):
            if v.strip() and not is_url(v.strip()):
                return await interaction.followup.send("❌ الروابط يجب أن تبدأ بـ http:// أو https://", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        e = panel["embed"]
        for key, val in (("image", self.img.value), ("thumbnail", self.thumb.value)):
            if val.strip():
                e[key] = {"url": val.strip()}
            else:
                e.pop(key, None)
        await db.update_panel(self.panel_id, embed=e)
        await show_editor(interaction, self.panel_id)


# ---------- الحقول ----------
async def show_fields(interaction: discord.Interaction, panel_id: int):
    panel = await load_panel(panel_id, interaction.guild_id)
    fields = panel["embed"].get("fields", [])
    lines = [f"`{i + 1}.` **{f['name']}** {'(بجانب)' if f.get('inline') else ''}" for i, f in enumerate(fields)]
    emb = discord.Embed(title="🧾 حقول الإمبد", description="\n".join(lines) or "لا توجد حقول.",
                        color=discord.Color.blurple())
    emb.set_footer(text="اختر حقلاً لتعديله أو حذفه • الحد الأقصى 25")
    view = FieldsView(interaction.user.id, panel)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embeds=[emb], view=view)
    else:
        await interaction.response.edit_message(content=None, embeds=[emb], view=view)


class FieldsView(BackToEditorView):
    def __init__(self, owner_id: int, panel: dict):
        super().__init__(owner_id, panel["id"])
        fields = panel["embed"].get("fields", [])
        if fields:
            choices = {str(i): f"{i + 1}. {f['name']}"[:100] for i, f in enumerate(fields)}
            self.add_item(ChoiceSelect(choices, None, "اختر حقلاً للتعديل/الحذف...", self.on_pick, row=0))
        self.n = len(fields)

    async def on_pick(self, interaction: discord.Interaction, idx: str):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(FieldModal(panel, int(idx)))

    @discord.ui.button(label="➕ إضافة حقل", style=discord.ButtonStyle.success, row=1)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if self.n >= 25:
            return await interaction.followup.send("❌ وصلت للحد الأقصى (25 حقل).", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(FieldModal(panel, None))


class FieldModal(discord.ui.Modal, title="حقل الإمبد"):
    f_name = discord.ui.TextInput(label="اسم الحقل", max_length=256)
    f_value = discord.ui.TextInput(label="قيمة الحقل", style=discord.TextStyle.paragraph, max_length=1024)
    f_inline = discord.ui.TextInput(label="بجانب غيره؟ (نعم / لا)", required=False, max_length=3, default="لا")
    f_delete = discord.ui.TextInput(label="اكتب «حذف» لحذف هذا الحقل", required=False, max_length=4)

    def __init__(self, panel: dict, index: Optional[int]):
        super().__init__()
        self.panel_id, self.index = panel["id"], index
        if index is None:
            self.remove_item(self.f_delete)
        else:
            f = panel["embed"]["fields"][index]
            self.f_name.default, self.f_value.default = f["name"], f["value"]
            self.f_inline.default = "نعم" if f.get("inline") else "لا"

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        fields = panel["embed"].setdefault("fields", [])
        if self.index is not None and self.f_delete.value.strip() == "حذف":
            if self.index < len(fields):
                fields.pop(self.index)
        else:
            item = {"name": self.f_name.value.strip(), "value": self.f_value.value.strip(),
                    "inline": self.f_inline.value.strip().lower() in ("نعم", "yes", "y", "true", "1")}
            if self.index is None:
                fields.append(item)
            elif self.index < len(fields):
                fields[self.index] = item
        if not fields:
            panel["embed"].pop("fields", None)
        await db.update_panel(self.panel_id, embed=panel["embed"])
        await show_fields(interaction, self.panel_id)


# ─────────────────────────── إعدادات التذاكر ───────────────────────────
async def show_ticket_settings(interaction: discord.Interaction, panel_id: int):
    panel = await load_panel(panel_id, interaction.guild_id)
    emb = discord.Embed(title="🎫 إعدادات لوحة التذاكر", description=describe_panel(interaction.guild, panel),
                        color=discord.Color.green())
    emb.add_field(name="خيارات", inline=False, value=(
        f"سؤال السبب: {'✅' if panel['config']['ask_reason'] else '❌'}  |  "
        f"زر الاستلام: {'✅' if panel['config']['claim_enabled'] else '❌'}  |  "
        f"منشن الدعم: {'✅' if panel['config']['mention_support'] else '❌'}\n"
        f"أقصى تذاكر للعضو: `{panel['config']['max_open']}`  |  صيغة الاسم: `{panel['config']['name_format']}`"))
    emb.set_footer(text="إن تركت الكاتيجوري/السجل/الرتب فارغة تُستخدم إعدادات السيرفر القديمة إن وُجدت")
    view = TicketSettingsView(interaction.user.id, panel)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embeds=[emb], view=view)
    else:
        await interaction.response.edit_message(content=None, embeds=[emb], view=view)


class CfgChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, panel_id: int, key: str, placeholder: str, types: list, row: int):
        super().__init__(placeholder=placeholder, channel_types=types, min_values=1, max_values=1, row=row)
        self.panel_id, self.key = panel_id, key

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"][self.key] = self.values[0].id
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_ticket_settings(interaction, self.panel_id)


class SupportRolesSelect(discord.ui.RoleSelect):
    def __init__(self, panel_id: int):
        super().__init__(placeholder="🛡️ اختر رتب الدعم (يمكن اختيار عدة رتب)", min_values=0, max_values=10, row=2)
        self.panel_id = panel_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"]["support_role_ids"] = [r.id for r in self.values]
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_ticket_settings(interaction, self.panel_id)


class TicketSettingsView(OwnedView):
    def __init__(self, owner_id: int, panel: dict):
        super().__init__(owner_id)
        self.panel_id = pid = panel["id"]
        self.add_item(CfgChannelSelect(pid, "category_id", "📁 كاتيجوري التذاكر", [discord.ChannelType.category], 0))
        self.add_item(CfgChannelSelect(pid, "log_channel_id", "📜 قناة سجل التذاكر", [discord.ChannelType.text], 1))
        self.add_item(SupportRolesSelect(pid))
        self.add_item(ChoiceSelect({k: f"لون الزر: {v}" for k, v in STYLE_AR.items()},
                                   panel["config"]["button"].get("style"), "🎨 لون زر الفتح", self.on_style, row=3))

    async def on_style(self, interaction: discord.Interaction, style: str):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"]["button"]["style"] = style
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_ticket_settings(interaction, self.panel_id)

    @discord.ui.button(label="🔘 نص/إيموجي الزر", style=discord.ButtonStyle.primary, row=4)
    async def btn_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(TicketButtonModal(panel))

    @discord.ui.button(label="💬 رسالة الترحيب", style=discord.ButtonStyle.primary, row=4)
    async def welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(TicketWelcomeModal(panel))

    @discord.ui.button(label="⚙️ خيارات", style=discord.ButtonStyle.secondary, row=4)
    async def options(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_ticket_options(interaction, self.panel_id)

    @discord.ui.button(label="◀ رجوع", style=discord.ButtonStyle.secondary, row=4)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_editor(interaction, self.panel_id)


class TicketButtonModal(discord.ui.Modal, title="زر فتح التذكرة"):
    label = discord.ui.TextInput(label="نص الزر", required=False, max_length=80)
    emoji = discord.ui.TextInput(label="إيموجي الزر", required=False, max_length=60)

    def __init__(self, panel: dict):
        super().__init__()
        self.panel_id = panel["id"]
        b = panel["config"]["button"]
        self.label.default, self.emoji.default = b.get("label"), b.get("emoji")

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self.emoji.value.strip() and not safe_emoji(self.emoji.value):
            return await interaction.followup.send("❌ الإيموجي غير صالح. استخدم إيموجي عادي أو مخصص بصيغة <:name:id>", ephemeral=True)
        if not self.label.value.strip() and not self.emoji.value.strip():
            return await interaction.followup.send("❌ يجب وضع نص أو إيموجي للزر.", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"]["button"]["label"] = self.label.value.strip()
        panel["config"]["button"]["emoji"] = self.emoji.value.strip()
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_ticket_settings(interaction, self.panel_id)


class TicketWelcomeModal(discord.ui.Modal, title="رسالة الترحيب داخل التذكرة"):
    w_title = discord.ui.TextInput(label="العنوان", max_length=256)
    w_desc = discord.ui.TextInput(label="الوصف ({user} {number} {reason} {server})",
                                  style=discord.TextStyle.paragraph, max_length=2000)
    w_color = discord.ui.TextInput(label="اللون HEX", required=False, max_length=7)

    def __init__(self, panel: dict):
        super().__init__()
        self.panel_id = panel["id"]
        c = panel["config"]
        self.w_title.default, self.w_desc.default, self.w_color.default = c["welcome_title"], c["welcome_desc"], c["welcome_color"]

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        color = self.w_color.value.strip() or "#57F287"
        if parse_color(color) is None:
            return await interaction.followup.send("❌ اللون غير صالح، مثال: #57F287", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"].update(welcome_title=self.w_title.value, welcome_desc=self.w_desc.value, welcome_color=color)
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_ticket_settings(interaction, self.panel_id)


async def show_ticket_options(interaction: discord.Interaction, panel_id: int):
    panel = await load_panel(panel_id, interaction.guild_id)
    emb = discord.Embed(title="⚙️ خيارات التذاكر", color=discord.Color.dark_grey(),
                        description=f"أقصى تذاكر للعضو: `{panel['config']['max_open']}`\nصيغة الاسم: `{panel['config']['name_format']}`\n"
                                    "المتغيرات: `{number}` `{user}`")
    view = TicketOptionsView(interaction.user.id, panel)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embeds=[emb], view=view)
    else:
        await interaction.response.edit_message(content=None, embeds=[emb], view=view)


class ToggleButton(discord.ui.Button):
    def __init__(self, panel_id: int, key: str, label: str, value: bool, row: int = 0):
        super().__init__(label=f"{'✅' if value else '❌'} {label}", row=row,
                         style=discord.ButtonStyle.success if value else discord.ButtonStyle.secondary)
        self.panel_id, self.key = panel_id, key

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"][self.key] = not panel["config"].get(self.key)
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_ticket_options(interaction, self.panel_id)


class TicketOptionsView(OwnedView):
    def __init__(self, owner_id: int, panel: dict):
        super().__init__(owner_id)
        self.panel_id, c = panel["id"], panel["config"]
        self.add_item(ToggleButton(self.panel_id, "ask_reason", "سؤال السبب", c["ask_reason"]))
        self.add_item(ToggleButton(self.panel_id, "claim_enabled", "زر الاستلام", c["claim_enabled"]))
        self.add_item(ToggleButton(self.panel_id, "mention_support", "منشن الدعم", c["mention_support"]))

    @discord.ui.button(label="🔢 الحد وصيغة الاسم", style=discord.ButtonStyle.primary, row=1)
    async def limits(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        await interaction.followup.send_modal(TicketLimitsModal(panel))

    @discord.ui.button(label="◀ رجوع", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_ticket_settings(interaction, self.panel_id)


class TicketLimitsModal(discord.ui.Modal, title="الحد وصيغة الاسم"):
    max_open = discord.ui.TextInput(label="أقصى عدد تذاكر مفتوحة للعضو (1-10)", max_length=2)
    name_format = discord.ui.TextInput(label="صيغة اسم القناة ({number} {user})", max_length=50)

    def __init__(self, panel: dict):
        super().__init__()
        self.panel_id = panel["id"]
        self.max_open.default = str(panel["config"]["max_open"])
        self.name_format.default = panel["config"]["name_format"]

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not self.max_open.value.strip().isdigit() or not 1 <= int(self.max_open.value) <= 10:
            return await interaction.followup.send("❌ الحد يجب أن يكون رقماً من 1 إلى 10.", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"]["max_open"] = int(self.max_open.value)
        panel["config"]["name_format"] = self.name_format.value.strip() or "ticket-{number}"
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_ticket_options(interaction, self.panel_id)


# ─────────────────────────── أزرار الرتب ───────────────────────────
async def show_roles_manager(interaction: discord.Interaction, panel_id: int):
    panel = await load_panel(panel_id, interaction.guild_id)
    btns = panel["config"]["buttons"]
    lines = [f"`{i + 1}.` {b.get('emoji', '')} **{b.get('label', '')}** ➜ <@&{b['role_id']}> "
             f"• {STYLE_AR.get(b.get('style'), '')} • {MODE_AR.get(b.get('mode'), '')}" for i, b in enumerate(btns)]
    emb = discord.Embed(title="🎭 أزرار الرتب", description="\n".join(lines) or "لا توجد أزرار بعد.",
                        color=discord.Color.purple())
    emb.set_footer(text=f"{len(btns)}/25 زر • الوضع الحصري: {'مفعل' if panel['config']['exclusive'] else 'معطل'}")
    view = RoleManagerView(interaction.user.id, panel)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embeds=[emb], view=view)
    else:
        await interaction.response.edit_message(content=None, embeds=[emb], view=view)


class RoleManagerView(BackToEditorView):
    def __init__(self, owner_id: int, panel: dict):
        super().__init__(owner_id, panel["id"])
        btns = panel["config"]["buttons"]
        self.count = len(btns)
        if btns:
            choices = {str(b["uid"]): f"{i + 1}. {b.get('label') or b.get('emoji') or 'زر'}"[:100] for i, b in enumerate(btns)}
            self.add_item(ChoiceSelect(choices, None, "اختر زراً لتعديله أو حذفه...", self.on_pick, row=0))
        self.toggle_exclusive.label = f"🔒 وضع حصري: {'✅' if panel['config']['exclusive'] else '❌'}"

    async def on_pick(self, interaction: discord.Interaction, uid: str):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        b = next((x for x in panel["config"]["buttons"] if x["uid"] == int(uid)), None)
        if not b:
            return await respond(interaction, "❌ الزر غير موجود.")
        await show_draft(interaction, self.panel_id, dict(b))

    @discord.ui.button(label="➕ إضافة زر", style=discord.ButtonStyle.success, row=1)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if self.count >= 25:
            return await interaction.followup.send("❌ وصلت للحد الأقصى (25 زر).", ephemeral=True)
        await show_draft(interaction, self.panel_id,
                         {"uid": None, "label": "", "emoji": "", "style": "primary", "mode": "toggle", "role_id": 0})

    @discord.ui.button(label="🔒 وضع حصري", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_exclusive(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"]["exclusive"] = not panel["config"]["exclusive"]
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_roles_manager(interaction, self.panel_id)

    @discord.ui.button(label="◀ رجوع للمحرر", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_editor(interaction, self.panel_id)


async def show_draft(interaction: discord.Interaction, panel_id: int, draft: dict):
    role = f"<@&{draft['role_id']}>" if draft["role_id"] else "❌ لم تُحدد"
    emb = discord.Embed(title="🛠️ تخصيص الزر" + (" (تعديل)" if draft["uid"] else " (جديد)"), color=discord.Color.purple(),
                        description=(f"**الرتبة:** {role}\n**اللون:** {STYLE_AR[draft['style']]}\n"
                                     f"**النمط:** {MODE_AR[draft['mode']]}\n"
                                     f"**النص/الإيموجي:** {draft['emoji']} {draft['label']}".strip()))
    emb.set_footer(text="اختر الرتبة واللون والنمط ثم اضغط «الاسم والإيموجي وحفظ»")
    view = RoleDraftView(interaction.user.id, panel_id, draft)
    if interaction.response.is_done():
        await interaction.edit_original_response(content=None, embeds=[emb], view=view)
    else:
        await interaction.response.edit_message(content=None, embeds=[emb], view=view)


class DraftRoleSelect(discord.ui.RoleSelect):
    def __init__(self, panel_id: int, draft: dict):
        defaults = [discord.SelectDefaultValue(id=draft["role_id"], type=discord.SelectDefaultValueType.role)] if draft["role_id"] else []
        super().__init__(placeholder="🎖️ اختر الرتبة", min_values=1, max_values=1, default_values=defaults, row=0)
        self.panel_id, self.draft = panel_id, draft

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        self.draft["role_id"] = self.values[0].id
        await show_draft(interaction, self.panel_id, self.draft)


class RoleDraftView(OwnedView):
    def __init__(self, owner_id: int, panel_id: int, draft: dict):
        super().__init__(owner_id)
        self.panel_id, self.draft = panel_id, draft
        self.add_item(DraftRoleSelect(panel_id, draft))
        self.add_item(ChoiceSelect({k: f"لون الزر: {v}" for k, v in STYLE_AR.items()}, draft["style"], "🎨 لون الزر", self.on_style, row=1))
        self.add_item(ChoiceSelect(MODE_AR, draft["mode"], "⚙️ نمط الزر", self.on_mode, row=2))
        if not draft["uid"]:
            self.remove_item(self.delete)

    async def on_style(self, interaction: discord.Interaction, v: str):
        await interaction.response.defer(ephemeral=True)
        self.draft["style"] = v
        await show_draft(interaction, self.panel_id, self.draft)

    async def on_mode(self, interaction: discord.Interaction, v: str):
        await interaction.response.defer(ephemeral=True)
        self.draft["mode"] = v
        await show_draft(interaction, self.panel_id, self.draft)

    @discord.ui.button(label="💾 الاسم والإيموجي وحفظ", style=discord.ButtonStyle.success, row=3)
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if not self.draft["role_id"]:
            return await interaction.followup.send("❌ اختر الرتبة أولاً.", ephemeral=True)
        await interaction.followup.send_modal(RoleButtonModal(self.panel_id, self.draft))

    @discord.ui.button(label="🗑️ حذف الزر", style=discord.ButtonStyle.danger, row=3)
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        panel["config"]["buttons"] = [b for b in panel["config"]["buttons"] if b["uid"] != self.draft["uid"]]
        await db.update_panel(self.panel_id, config=panel["config"])
        await show_roles_manager(interaction, self.panel_id)

    @discord.ui.button(label="◀ رجوع", style=discord.ButtonStyle.secondary, row=3)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await show_roles_manager(interaction, self.panel_id)


class RoleButtonModal(discord.ui.Modal, title="نص وإيموجي الزر"):
    r_label = discord.ui.TextInput(label="نص الزر", required=False, max_length=80)
    r_emoji = discord.ui.TextInput(label="إيموجي الزر", required=False, max_length=60)

    def __init__(self, panel_id: int, draft: dict):
        super().__init__()
        self.panel_id, self.draft = panel_id, draft
        self.r_label.default, self.r_emoji.default = draft["label"] or None, draft["emoji"] or None

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        label, emoji = self.r_label.value.strip(), self.r_emoji.value.strip()
        if not label and not emoji:
            return await interaction.followup.send("❌ يجب وضع نص أو إيموجي للزر.", ephemeral=True)
        if emoji and not safe_emoji(emoji):
            return await interaction.followup.send("❌ الإيموجي غير صالح. استخدم إيموجي عادي أو مخصص بصيغة <:name:id>", ephemeral=True)
        panel = await load_panel(self.panel_id, interaction.guild_id)
        cfg = panel["config"]
        d = {**self.draft, "label": label, "emoji": emoji}
        if d["uid"]:
            cfg["buttons"] = [d if b["uid"] == d["uid"] else b for b in cfg["buttons"]]
        else:
            d["uid"] = cfg["next_uid"]
            cfg["next_uid"] += 1
            cfg["buttons"].append(d)
        await db.update_panel(self.panel_id, config=cfg)
        await show_roles_manager(interaction, self.panel_id)


# ─────────────────────────── الكوج ───────────────────────────
class Panels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_dynamic_items(TicketOpenButton, TicketCloseButton, TicketClaimButton, RoleButton)

    async def cog_unload(self):
        self.bot.remove_dynamic_items(TicketOpenButton, TicketCloseButton, TicketClaimButton, RoleButton)

    @app_commands.command(name="panels", description="نظام اللوحات المتكامل: إمبدز، تذاكر، وأزرار رتب")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def panels(self, interaction: discord.Interaction):
        await show_home(interaction, new=True)


async def setup(bot):
    await bot.add_cog(Panels(bot))
