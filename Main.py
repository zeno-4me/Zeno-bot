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

        # تسجيل الـ Persistent Views عشان أزرار التذاكر ما تعطّل بعد ريستارت البوت
        try:
            from dashboard import OpenTicketView, CloseTicketView
            self.add_view(OpenTicketView())
            self.add_view(CloseTicketView())
        except Exception as e:
            print(f"تعذر تسجيل Views التذاكر: {e}")

        # تحميل كل الـ cogs
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
    try:
        synced = await bot.tree.sync()
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
