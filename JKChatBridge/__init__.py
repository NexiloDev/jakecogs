import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
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
        # Create ALL attributes FIRST
        self.monitoring = False
        self.monitor_task = None
        self.random_chat_task = None
        self.is_restarting = False
        self.restart_map = None
        self.last_welcome_time = 0
        self.random_chat_lines = []
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Now safe to call setup from mixins
        self.setup_cog(bot)
        self.start_monitoring()
        self.bot.loop.create_task(self._start_random_chat_when_ready())
        self.bot.loop.create_task(self.auto_reload_monitor())

    async def _start_random_chat_when_ready(self):
        await self.bot.wait_until_ready()
        await self.start_random_chat_task()

    async def cog_load(self):
        await self.load_random_chat_lines()

    async def cog_unload(self):
        self.monitoring = False
        for t in (self.monitor_task, self.random_chat_task):
            if t and not t.done():
                t.cancel()
        self.executor.shutdown(wait=True)
        logger.info("JKChatBridge unloaded cleanly.")

async def setup(bot):
    await bot.add_cog(JKChatBridge(bot))