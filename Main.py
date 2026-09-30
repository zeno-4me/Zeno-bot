import os
import traceback
import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "البوت شغال!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run, daemon=True) # daemon عشان ما يعلق لو طفي البوت
    t.start()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
intents.guilds = True

class ZenoBot(commands.Bot):
    async def setup_hook(self):
        if os.path.exists('./cogs'):
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py'):
                    try:
                        await self.load_extension(f'cogs.{filename[:-3]}')
                        print(f"تم تحميل: {filename}")
                    except Exception as e:
                        print(f"فشل تحميل الكوج {filename}: {e}")

bot = ZenoBot(command_prefix="!", intents=intents)

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
