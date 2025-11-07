import asyncio
import logging
from redbot.core import commands
from .config import ConfigHandler
from .monitor import MonitorHandler
from .chat import ChatHandler
from .rcon import RCONHandler
from .commands import CommandHandler

logger = logging.getLogger("JKChatBridge")

class JKChatBridge(
    commands.Cog,
    ConfigHandler,
    MonitorHandler,
    ChatHandler,
    RCONHandler,
    CommandHandler
):
    def __init__(self, bot):
        self.bot = bot
        self.setup_cog(bot)

    async def cog_load(self):
        await self.load_random_chat_lines()

    async def cog_unload(self):
        self.monitoring = False
        for task in [self.monitor_task, self.random_chat_task]:
            if task and not task.done():
                task.cancel()
        self.executor.shutdown(wait=True)
        logger.info("JKChatBridge unloaded cleanly.")

async def setup(bot):
    cog = JKChatBridge(bot)
    await bot.add_cog(cog)