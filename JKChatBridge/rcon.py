import socket
import time
import logging
import asyncio
import os
import aiofiles
import random

logger = logging.getLogger("JKChatBridge")

class RCONHandler:
    def setup_attributes(self):
        self.random_chat_task = None  # Only this

    async def load_random_chat_lines(self):
        path = await self.config.random_chat_path()
        self.random_chat_lines = []
        if not path or not os.path.exists(path):
            return
        try:
            async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = await f.read()
            lines = [line.strip() for line in content.splitlines() if line.strip() and not line.strip().startswith('#')]
            self.random_chat_lines = lines
            logger.info(f"Loaded {len(lines)} random chat lines from {path}")
        except Exception as e:
            logger.error(f"Failed to load random chat lines: {e}")

    async def start_random_chat_task(self):
        if self.random_chat_task and not self.random_chat_task.done():
            self.random_chat_task.cancel()
            try:
                await self.random_chat_task
            except asyncio.CancelledError:
                pass
        self.random_chat_task = self.bot.loop.create_task(self.random_chat_loop())

    async def random_chat_loop(self):
        while True:
            try:
                await asyncio.sleep(300)
                if not await self.validate_rcon_settings():
                    continue
                bot_name = await self.config.bot_name()
                if not bot_name or not self.random_chat_lines:
                    continue
                if random.random() > 0.5:
                    continue
                line = random.choice(self.random_chat_lines)
                command = f"sayasbot {bot_name} {line}"
                await self.bot.loop.run_in_executor(
                    self.executor,
                    self.send_rcon_command,
                    command,
                    await self.config.rcon_host(),
                    await self.config.rcon_port(),
                    await self.config.rcon_password()
                )
            except Exception as e:
                logger.error(f"Error in random_chat_loop: {e}")
                await asyncio.sleep(60)

    def send_rcon_command(self, command, host, port, password):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        cmd = self.clean_for_latin1(command)
        pwd = self.clean_for_latin1(password)
        packet = b'\xff\xff\xff\xffrcon ' + pwd.encode('latin-1') + b' ' + cmd.encode('latin-1')
        try:
            sock.sendto(packet, (host, port))
            time.sleep(0.1)
            response = b""
            start = time.time()
            while time.time() - start < 5:
                try:
                    data, _ = sock.recvfrom(16384)
                    response += data
                except socket.timeout:
                    break
            if not response:
                raise Exception("No response")
            return response
        except Exception as e:
            raise Exception(f"RCON error: {e}")
        finally:
            sock.close()

    async def validate_rcon_settings(self):
        return all([await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()])

    async def send_welcome_message(self, message: str):
        await asyncio.sleep(5)
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command,
                message, await self.config.rcon_host(),
                await self.config.rcon_port(), await self.config.rcon_password()
            )
        except Exception as e:
            logger.error(f"Welcome message failed: {e}")

    async def auto_reload_monitor(self):
        while True:
            try:
                await asyncio.sleep(300)
                await self.reload_monitor()
                logger.debug("Auto-reload triggered")
            except Exception as e:
                logger.error(f"Auto-reload error: {e}")
                await asyncio.sleep(300)