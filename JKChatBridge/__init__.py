from .JKChatBridge import JKChatBridge

async def setup(bot):
    cog = JKChatBridge(bot)
    await bot.add_cog(cog)