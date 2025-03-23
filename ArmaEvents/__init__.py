from .ArmaEvents import ArmaEvents

async def setup(bot):
    cog = ArmaEvents(bot)
    await bot.add_cog(cog)