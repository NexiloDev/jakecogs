import aiofiles
import os
import re
import time
import logging
import asyncio
import aiohttp

logger = logging.getLogger("JKChatBridge")

class MonitorHandler:
    def setup_attributes(self):
        self.monitoring = False
        self.monitor_task = None
        self.is_restarting = False
        self.restart_map = None
        self.last_welcome_time = 0

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

                        # === VPN Detection: Fixed index ===
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

                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message:
                                message = self.replace_text_emotes_with_emojis(message)
                                await channel.send(f"**{player_name}**: {message}")

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