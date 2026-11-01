import os
import asyncio
import traceback
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
from threading import Thread
from database import db

app = Flask('')

@app.route('/')
def home():
    return "البوت شغال!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

class ZenoBot(commands.Bot):
    async def setup_hook(self):
        if hasattr(db, 'init_db'):
            try:
                if asyncio.iscoroutinefunction(db.init_db):
                    await db.init_db()
                else:
                    db.init_db()
                print("تمت تهيئة قاعدة البيانات بنجاح.")
            except Exception as e:
                print(f"خطأ أثناء تهيئة قاعدة البيانات: {e}")

        cogs_dir = './cogs' if os.path.exists('./cogs') else '.'
        ignored_files = ['main.py', 'database.py']
        
        for filename in os.listdir(cogs_dir):
            if filename.endswith('.py') and filename.lower() not in ignored_files and not filename.startswith('.'):
                cog_name = f'cogs.{filename[:-3]}' if cogs_dir == './cogs' else filename[:-3]
                try:
                    await self.load_extension(cog_name)
                    print(f"تم تحميل: {filename}")
                except Exception as e:
                    print(f"فشل تحميل الكوج {filename}: {e}")
                    traceback.print_exc()

bot = ZenoBot(command_prefix="!", intents=intents)

# ───── حارس الـ3 ثواني: إذا ما تم الرد خلال ثانيتين، يسوي defer تلقائياً (يعطيك 15 دقيقة) ─────
AUTO_DEFER_AFTER = 2.0
_bg_tasks = set()

async def _auto_defer(interaction: discord.Interaction):
    await asyncio.sleep(AUTO_DEFER_AFTER)
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer()
    except discord.HTTPException:
        pass

@bot.listen('on_interaction')
async def auto_defer_watchdog(interaction: discord.Interaction):
    if interaction.type in (discord.InteractionType.application_command,
                            discord.InteractionType.component,
                            discord.InteractionType.modal_submit):
        task = asyncio.create_task(_auto_defer(interaction))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"⚠️ حدث خطأ في الأمر ({interaction.command.name if interaction.command else 'مجهول'}): {error}")
    traceback.print_exception(type(error), error, error.__traceback__)
    
    msg = "❌ حدث خطأ أثناء تنفيذ هذا الأمر! يرجى مراجعة الكونسول."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

@bot.event
async def on_ready():
    print(f"تم تسجيل الدخول باسم: {bot.user.name}")
    if getattr(bot, "_commands_synced", False):
        return  # on_ready قد يتكرر مع كل إعادة اتصال، المزامنة تكفي مرة وحدة
    try:
        synced = await bot.tree.sync()
        bot._commands_synced = True
        print(f"تم مزامنة {len(synced)} أمر سلاش!")
    except Exception as e:
        print(f"فشل المزامنة: {e}")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    if not TOKEN:
        print("لم يتم العثور على التوكن في DISCORD_BOT_TOKEN!")
    else:
        keep_alive()
        try:
            bot.run(TOKEN)
        except Exception as e:
            print("سبب كراش البوت:")
            traceback.print_exc()
