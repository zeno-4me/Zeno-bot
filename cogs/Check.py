import discord
from discord.ext import commands

class General(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='انت شغال؟')
    async def test_cmd(self, ctx):
        await ctx.send("ب-بابا؟؟ ا-انا شغال تمام @_@ ب-ب-بس لا تعدل على اكوادي اليوم بليز احس اني صرت دبة T-T")

async def setup(bot):
    await bot.add_cog(General(bot))
