from .RepoMonitor import RepoMonitor

async def setup(bot):
    cog = RepoMonitor(bot)
    await bot.add_cog(cog)