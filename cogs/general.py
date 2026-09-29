import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='أمر_تجريبي')
    async def test_cmd(self, ctx):
        await ctx.send("أهلين! الكوج شغال زي الحلاوة 🚀")

async def setup(bot):
    await bot.add_cog(General(bot))
