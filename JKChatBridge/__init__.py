import asyncio
import logging
from redbot.core import commands
from .config import ConfigHandler
from .chat import ChatHandler
from .core import CoreHandler

logger = logging.getLogger("JKChatBridge")

class JKChatBridge(commands.Cog, ConfigHandler, ChatHandler, CoreHandler):
    def __init__(self, bot):
        self.bot = bot
        self.setup_attributes()
        self.setup_config(bot)  # From ConfigHandler
        self.start_monitoring()  # From CoreHandler
        self.bot.loop.create_task(self._start_random_chat_when_ready())
        self.bot.loop.create_task(self.auto_reload_monitor())

    def setup_attributes(self):
        self.monitoring = False
        self.monitor_task = None
        self.random_chat_task = None
        self.is_restarting = False
        self.restart_map = None
        self.last_welcome_time = 0
        self.random_chat_lines = []

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
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.executor.shutdown(wait=True)
        logger.info("JKChatBridge unloaded cleanly.")

async def setup(bot):
    await bot.add_cog(JKChatBridge(bot))