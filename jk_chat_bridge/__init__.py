from redbot.core.utils import get_end_user_data_statement

from .JKChatBridge import JKChatBridge  # Adjust to match your cog's class name

__red_end_user_data_statement__ = get_end_user_data_statement(__file__)

async def setup(bot):
    cog = JKChatBridge(bot)
    await bot.add_cog(cog)