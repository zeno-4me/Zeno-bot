import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='انت_شغال؟')
    async def test_cmd(self, ctx):
        await ctx.send("ب-بابا ل-ل-لسانك قذر بابا•~•")

async def setup(bot):
    await bot.add_cog(General(bot))
