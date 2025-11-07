import asyncio
import logging
from redbot.core import commands
from .config import ConfigCommands
from .monitor import MonitorHandler
from .chat import ChatHandler
from .rcon import RCONHandler

logger = logging.getLogger("JKChatBridge")

class JKChatBridge(commands.Cog, ConfigCommands, MonitorHandler, ChatHandler, RCONHandler):
    """Bridges public chat between Jedi Academy and Discord."""

    RANDOM_CHAT_INTERVAL = 300
    RANDOM_CHAT_CHANCE = 0.5

    def __init__(self, bot):
        self.bot = bot
        self.config = self.init_config(bot)
        self.setup_attributes()
        self.setup_config_commands()
        self.start_monitoring()
        self.bot.loop.create_task(self._start_random_chat_when_ready())
        self.bot.loop.create_task(self.auto_reload_monitor())

    async def _start_random_chat_when_ready(self):
        await self.bot.wait_until_ready()
        await self.start_random_chat_task()

    async def cog_load(self):
        logger.debug("Cog loaded.")
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