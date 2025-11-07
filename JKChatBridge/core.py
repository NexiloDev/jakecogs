import socket
import time
import logging
import asyncio
import os
import aiofiles
import random
import aiohttp
import re
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("JKChatBridge")

class CoreHandler:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=2)

    # RCON
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

    # Random Chat
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

    # Monitor
    async def monitor_log(self):
        self.monitoring = True
        log_file = os.path.join(await self.config.log_base_path(), "qconsole.log")

        while self.monitoring:
            try:
                channel_id = await self.config.discord_channel_id()
                if not all([await self.config.log_base_path(), channel_id]):
                    logger.warning("Missing configuration, pausing monitor.")
                    await asyncio.sleep(5)
                    continue

                channel = self.bot.get_channel(channel_id)
                if not channel:
                    logger.warning(f"Channel not found: {channel_id}")
                    await asyncio.sleep(5)
                    continue

                if not os.path.exists(log_file):
                    logger.error(f"Log file not found: {log_file}")
                    await asyncio.sleep(5)
                    continue

                async with aiofiles.open(log_file, mode='r', encoding='latin-1') as f:
                    await f.seek(0, 2)
                    while self.monitoring:
                        line = await f.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        line = line.strip()

                        # VPN
                        if "info: IP: " in line and await self.config.vpn_check_enabled():
                            parts = line.split()
                            if len(parts) >= 6:
                                ip = parts[4]
                                player_id_str = parts[-1]
                                if player_id_str.isdigit():
                                    player_id = int(player_id_str)
                                    logger.info(f"VPN check triggered for Player ID {player_id} | IP {ip}")
                                    self.bot.loop.create_task(self._handle_vpn_check(player_id, ip))
                            continue

                        # Game chat
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message:
                                message = self.replace_text_emotes_with_emojis(message)
                                await channel.send(f"**{player_name}**: {message}")

                        # Duel
                        elif "duel:" in line and "won a duel against" in line:
                            parts = line.split("duel:")[1].split("won a duel against")
                            if len(parts) == 2:
                                winner = parts[0].strip()
                                loser = parts[1].strip()
                                if await self.validate_rcon_settings():
                                    bot_name = await self.config.bot_name()
                                    if bot_name:
                                        msg = f"sayasbot {bot_name} {winner} ^7has defeated {loser} ^7in a duel^5! :crown:"
                                        await self.bot.loop.run_in_executor(
                                            self.executor, self.send_rcon_command,
                                            msg, await self.config.rcon_host(),
                                            await self.config.rcon_port(), await self.config.rcon_password()
                                        )

                        # Restart
                        elif "ShutdownGame:" in line and not self.is_restarting:
                            self.is_restarting = True
                            await channel.send("Standby: Server integration suspended while map changes or server restarts.")
                            self.bot.loop.create_task(self.reset_restart_flag(channel))

                        elif "------ Server Initialization ------" in line and not self.is_restarting:
                            self.is_restarting = True
                            await channel.send("Standby: Server integration suspended while map changes or server restarts.")
                            self.bot.loop.create_task(self.reset_restart_flag(channel))

                        elif "Server: " in line and self.is_restarting:
                            self.restart_map = line.split("Server: ")[1].strip()
                            await asyncio.sleep(10)
                            if self.restart_map:
                                await channel.send(f"Server Integration Resumed: Map {self.restart_map} loaded.")
                            self.is_restarting = False
                            self.restart_map = None

                        # Join
                        elif "Going from CS_PRIMED to CS_ACTIVE for" in line:
                            join_name = line.split("for ")[1].strip()
                            name_clean = self.remove_color_codes(join_name)
                            if not name_clean.endswith("-Bot") and not self.is_restarting and await self.config.join_disconnect_enabled():
                                await channel.send(f"<:jk_connect:1349009924306374756> **{name_clean}** has joined the game!")
                                bot_name = await self.config.bot_name()
                                if bot_name and await self.validate_rcon_settings():
                                    now = time.time()
                                    if now - self.last_welcome_time >= 5:
                                        self.last_welcome_time = now
                                        msg = f"sayasbot {bot_name} ^7Hey {join_name}^7, welcome to the server^5! :jackolantern:"
                                        self.bot.loop.create_task(self.send_welcome_message(msg))

                        # Disconnect
                        elif "disconnected" in line:
                            match = re.search(r"info:\s*(.+?)\s*disconnected\s*\((\d+)\)", line)
                            if match and await self.config.join_disconnect_enabled():
                                name_clean = self.remove_color_codes(match.group(1))
                                if not self.is_restarting and not name_clean.endswith("-Bot") and name_clean.strip():
                                    await channel.send(f"<:jk_disconnect:1349010016044187713> **{name_clean}** has disconnected.")

            except Exception as e:
                logger.error(f"Error in monitor_log: {e}")
                await asyncio.sleep(5)

    def start_monitoring(self):
        if self.monitor_task and not self.monitor_task.done():
            logger.debug("Monitor task already running.")
            return
        logger.info("Starting log monitor task.")
        self.monitor_task = self.bot.loop.create_task(self.monitor_log())

    async def reset_restart_flag(self, channel):
        await asyncio.sleep(30)
        if self.is_restarting:
            self.is_restarting = False
            self.restart_map = None
            await channel.send("Server Integration Resumed: Restart timed out, resuming normal operation.")

    async def _handle_vpn_check(self, player_id: int, ip: str):
        api_key = await self.config.vpn_api_key()
        if not api_key:
            return
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://vpnapi.io/api/{ip}?key={api_key}"
                async with session.get(url, timeout=5) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    if data.get("security", {}).get("vpn", False):
                        bot_name = await self.config.bot_name() or "Server"
                        msg = f"sayasbot {bot_name} VPN Detected ^3(^7IP: {ip} ^3| ^7Player ID: {player_id}^7) :eyes:"
                        await self.bot.loop.run_in_executor(
                            self.executor, self.send_rcon_command,
                            msg, await self.config.rcon_host(),
                            await self.config.rcon_port(), await self.config.rcon_password()
                        )
        except Exception:
            pass

    async def auto_reload_monitor(self):
        while True:
            try:
                await asyncio.sleep(300)
                await self.reload_monitor()
                logger.debug("Auto-reload triggered")
            except Exception as e:
                logger.error(f"Auto-reload error: {e}")
                await asyncio.sleep(300)

    def clean_for_latin1(self, text):
        return ''.join(c if ord(c) < 256 else '' for c in text)

    def remove_color_codes(self, text):
        return re.sub(r'\^\d', '', text or '')

    def parse_chat_line(self, line):
        say_idx = line.find("say: ")
        if say_idx == -1:
            return None, None
        chat = line[say_idx + 5:]
        colon_idx = chat.find(": ")
        if colon_idx == -1:
            return None, None
        name = self.remove_color_codes(chat[:colon_idx].strip())
        msg = self.remove_color_codes(chat[colon_idx + 2:].strip())
        return name, msg