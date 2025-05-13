from .MCChatBridge import MCChatBridge

async def setup(bot):
    cog = MCChatBridge(bot)
    await bot.add_cog(cog)