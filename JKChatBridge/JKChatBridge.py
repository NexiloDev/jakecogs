import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import os
import socket
from concurrent.futures import ThreadPoolExecutor
import re
import time
import logging
import aiohttp
from urllib.parse import quote
import random

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("JKChatBridge")

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord using RCON and log monitoring."""

    # === Adjustable Random Chat Settings ===
    RANDOM_CHAT_INTERVAL = 360   # 6 minutes
    RANDOM_CHAT_CHANCE = 0.4     # 40%

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_base_path=None,
            discord_channel_id=None,
            rcon_host=None,
            rcon_port=None,
            rcon_password=None,
            custom_emoji=None,
            join_disconnect_enabled=True,
            vpn_api_key=None,
            vpn_check_enabled=False,
            tracker_url=None,
            bot_name=None,
            random_chat_path=None,
            vpn_auto_kick=False
        )
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.monitoring = False
        self.monitor_task = None
        self.random_chat_task = None
        self.is_restarting = False
        self.restart_map = None
        self.last_welcome_time = 0
        self.random_chat_lines = []
        self.start_monitoring()
        self.bot.loop.create_task(self._start_random_chat_when_ready())
        self.bot.loop.create_task(self.auto_reload_monitor())

    async def cog_load(self) -> None:
        logger.debug("Cog loaded.")
        await self.load_random_chat_lines()

    async def _start_random_chat_when_ready(self):
        await self.bot.wait_until_ready()
        await self.start_random_chat_task()

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
                await asyncio.sleep(self.RANDOM_CHAT_INTERVAL)
                if not await self.validate_rcon_settings():
                    continue
                bot_name = await self.config.bot_name()
                if not bot_name or not self.random_chat_lines:
                    continue
                if random.random() > self.RANDOM_CHAT_CHANCE:
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

    async def auto_reload_monitor(self):
        """Silent reload every 5 min - no ctx needed"""
        while True:
            try:
                await asyncio.sleep(300)
                if self.monitor_task and not self.monitor_task.done():
                    self.monitoring = False
                    self.monitor_task.cancel()
                    try:
                        await self.monitor_task
                    except asyncio.CancelledError:
                        pass
                await asyncio.sleep(0.5)
                self.is_restarting = False
                self.restart_map = None
                self.start_monitoring()
                logger.debug("Auto-reload triggered")
            except Exception as e:
                logger.error(f"Auto-reload error: {e}")
                await asyncio.sleep(300)

    async def validate_rcon_settings(self) -> bool:
        return all([
            await self.config.rcon_host(),
            await self.config.rcon_port(),
            await self.config.rcon_password()
        ])

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
            return response
        except Exception as e:
            raise Exception(f"RCON error: {e}")
        finally:
            sock.close()

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

    def start_monitoring(self):
        if self.monitor_task and not self.monitor_task.done():
            logger.debug("Monitor task already running.")
            return
        logger.info("Starting log monitor task.")
        self.monitor_task = self.bot.loop.create_task(self.monitor_log())

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

                        # VPN Detection
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
                                        msg = f"sayasbot {bot_name} {winner} ^7has defeated {loser} ^7in a duel^5! :trophy:"
                                        await self.bot.loop.run_in_executor(
                                            self.executor, self.send_rcon_command,
                                            msg, await self.config.rcon_host(),
                                            await self.config.rcon_port(), await self.config.rcon_password()
                                        )

                        # Restart
                        elif "ShutdownGame:" in line and not self.is_restarting:
                            self.is_restarting = True
                            await channel.send("⚠️ **Standby**: Server integration suspended while map changes or server restarts.")
                            self.bot.loop.create_task(self.reset_restart_flag(channel))
                        elif "------ Server Initialization ------" in line and not self.is_restarting:
                            self.is_restarting = True
                            await channel.send("⚠️ **Standby**: Server integration suspended while map changes or server restarts.")
                            self.bot.loop.create_task(self.reset_restart_flag(channel))

                        elif "Server: " in line and self.is_restarting:
                            self.restart_map = line.split("Server: ")[1].strip()
                            await asyncio.sleep(10)
                            if self.restart_map:
                                await channel.send(f"✅ **Server Integration Resumed**: Map {self.restart_map} loaded.")
                            self.is_restarting = False
                            self.restart_map = None

                        # Join
                        elif "Going from CS_PRIMED to CS_ACTIVE for" in line:
                            join_name = line.split("Going from CS_PRIMED to CS_ACTIVE for ")[1].strip()
                            join_name_clean = self.remove_color_codes(join_name)
                            if not join_name_clean.endswith("-Bot") and not self.is_restarting:
                                if await self.config.join_disconnect_enabled():
                                    await channel.send(f"<:jk_connect:1349009924306374756> **{join_name_clean}** has joined the game!")
                                    # Schedule welcome message with cooldown
                                    bot_name = await self.config.bot_name()
                                    if bot_name and await self.validate_rcon_settings():
                                        current_time = time.time()
                                        if current_time - self.last_welcome_time >= 5:  # 5-second cooldown
                                            self.last_welcome_time = current_time
                                            welcome_message = f"sayasbot {bot_name} ^7Hey {join_name}^7, welcome to the server^5! :wave:"
                                            self.bot.loop.create_task(self.send_welcome_message(welcome_message))
                                        else:
                                            logger.debug(f"Skipped welcome message for {join_name_clean} due to cooldown")

                        # Disconnect
                        elif "disconnected" in line:
                            match = re.search(r"info:\s*(.+?)\s*disconnected\s*\((\d+)\)", line)
                            if match:
                                name = match.group(1)
                                name_clean = self.remove_color_codes(name)
                                if not self.is_restarting and not name_clean.endswith("-Bot") and name_clean.strip():
                                    if await self.config.join_disconnect_enabled():
                                        await channel.send(f"<:jk_disconnect:1349010016044187713> **{name_clean}** has disconnected.")

            except Exception as e:
                logger.error(f"Error in monitor_log: {e}")
                await asyncio.sleep(5)

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
                        msg = f"say_admins VPN Detected ^3(^7IP: {ip} ^3| ^7Player Slot: {player_id}^3) :eyes:"
                        await self.bot.loop.run_in_executor(
                            self.executor, self.send_rcon_command,
                            msg, await self.config.rcon_host(),
                            await self.config.rcon_port(), await self.config.rcon_password()
                        )
                        # Auto-kick if enabled
                        if await self.config.vpn_auto_kick():
                            kick_cmd = f"kick {player_id}"
                            await self.bot.loop.run_in_executor(
                                self.executor, self.send_rcon_command,
                                kick_cmd, await self.config.rcon_host(),
                                await self.config.rcon_port(), await self.config.rcon_password()
                            )
        except Exception:
            pass

    @commands.command(name="jkvpn")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def toggle_vpn_kick(self, ctx):
        """Toggle auto-kick on VPN detection."""
        current = await self.config.vpn_auto_kick()
        new_state = not current
        await self.config.vpn_auto_kick.set(new_state)
        if new_state:
            await ctx.send("**VPN Connections BLOCKED** :no_entry:")
        else:
            await ctx.send("**VPN Connections ALLOWED** :white_check_mark:")

    # === CONFIG GROUP ===
    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """JKChatBridge settings"""
        pass

    @jkbridge.command()
    async def setlogbasepath(self, ctx, path: str):
        await self.config.log_base_path.set(path)
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        self.start_monitoring()
        await ctx.send(f"Log base path set to: {path}. Monitoring restarted.")

    @jkbridge.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        await self.config.discord_channel_id.set(channel.id)
        await ctx.send(f"Discord channel set to: {channel.name} (ID: {channel.id})")

    @jkbridge.command()
    async def setrconhost(self, ctx, host: str):
        await self.config.rcon_host.set(host)
        await ctx.send(f"RCON host set to: {host}")

    @jkbridge.command()
    async def setrconport(self, ctx, port: int):
        await self.config.rcon_port.set(port)
        await ctx.send(f"RCON port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx, password: str):
        await self.config.rcon_password.set(password)
        await ctx.send("RCON password set.")

    @jkbridge.command()
    async def setcustomemoji(self, ctx, emoji: str):
        await ctx.send("Custom emoji feature has been removed and is no longer used.")

    @jkbridge.command()
    async def settrackerurl(self, ctx, url: str):
        await self.config.tracker_url.set(url)
        await ctx.send(f"Tracker URL set to: {url}")

    @jkbridge.command()
    async def setbotname(self, ctx, name: str):
        await self.config.bot_name.set(name)
        await ctx.send(f"Bot name set to: {name}")

    @jkbridge.command()
    async def setvpnkey(self, ctx, key: str):
        await self.config.vpn_api_key.set(key)
        await ctx.send("VPN API key set.")

    @jkbridge.command()
    async def togglevpncheck(self, ctx):
        new = not await self.config.vpn_check_enabled()
        await self.config.vpn_check_enabled.set(new)
        await ctx.send(f"VPN detection {'enabled' if new else 'disabled'}.")

    @jkbridge.command()
    async def setchatpath(self, ctx, path: str):
        await self.config.random_chat_path.set(path)
        await self.load_random_chat_lines()
        count = len(self.random_chat_lines)
        await ctx.send(f"Random chat file set to: `{path}`\nLoaded **{count}** lines. Use `[p]reload JKChatBridge` after editing.")

    @jkbridge.command()
    async def showsettings(self, ctx):
        channel = self.bot.get_channel(await self.config.discord_channel_id()) if await self.config.discord_channel_id() else None
        chat_path = await self.config.random_chat_path()
        chat_status = f"{len(self.random_chat_lines)} lines loaded" if chat_path and self.random_chat_lines else "Not set"
        settings_message = (
            f"**Current Settings:**\n"
            f"Log Base Path: {await self.config.log_base_path() or 'Not set'}\n"
            f"Discord Channel: {channel.name if channel else 'Not set'} (ID: {await self.config.discord_channel_id() or 'Not set'})\n"
            f"RCON Host: {await self.config.rcon_host() or 'Not set'}\n"
            f"RCON Port: {await self.config.rcon_port() or 'Not set'}\n"
            f"RCON Password: {'Set' if await self.config.rcon_password() else 'Not set'}\n"
            f"Custom Emoji: {await self.config.custom_emoji() or 'Not set'}\n"
            f"Tracker URL: {await self.config.tracker_url() or 'Not set'}\n"
            f"Bot Name: {await self.config.bot_name() or 'Not set'}\n"
            f"Random Chat File: `{chat_path or 'Not set'}` → {chat_status}\n"
            f"VPN Auto-Kick: **{'ON' if await self.config.vpn_auto_kick() else 'OFF'}**"
        )
        await ctx.send(settings_message)

    # === OTHER COMMANDS ===
    @commands.command(name="jkexec")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkexec(self, ctx, filename: str):
        if not await self.validate_rcon_settings():
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"exec {filename}", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            await ctx.send(f"Executed configuration file: {filename}")
        except Exception as e:
            await ctx.send(f"Failed to execute {filename}: {e}")

    @commands.command(name="jkrcon")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkrcon(self, ctx, *, command: str):
        if not await self.validate_rcon_settings():
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, command, await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            await ctx.send(f"RCON command sent: `{command}`")
        except Exception as e:
            await ctx.send(f"Failed to send RCON command `{command}`: {e}")

    @commands.command(name="jktoggle")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jktoggle(self, ctx):
        current_state = await self.config.join_disconnect_enabled()
        new_state = not current_state
        await self.config.join_disconnect_enabled.set(new_state)
        state_text = "enabled" if new_state else "disabled"
        await ctx.send(f"Join and disconnect messages are now **{state_text}**.")

    @commands.command(name="jkreload", aliases=["jkreloadmonitor"])
    async def reload_monitor(self, ctx: commands.Context = None):
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                logger.debug("Monitoring task canceled successfully.")
            except Exception as e:
                logger.error(f"Error canceling task: {e}")

        await asyncio.sleep(0.5)
        self.is_restarting = False
        self.restart_map = None
        self.start_monitoring()
        if ctx:
            await ctx.send("Log monitoring task reloaded.")

    @commands.command(name="jkstatus")
    async def status(self, ctx):
        async with aiohttp.ClientSession() as session:
            try:
                tracker_url = await self.config.tracker_url()
                if not tracker_url:
                    await ctx.send("Tracker URL not set. Use `jkbridge settrackerurl`.")
                    return

                async with session.get(tracker_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await ctx.send(f"Failed: HTTP {resp.status}")
                        return
                    if 'application/json' not in resp.headers.get('Content-Type', ''):
                        await ctx.send("Failed: Expected JSON.")
                        return
                    data = await resp.json()

                server_info = data.get("serverInfo", {})
                info = data.get("info", {})
                players = data.get("players", [])

                server_name = self.remove_color_codes(server_info.get("servername", "Unknown"))
                map_name = server_info.get("mapname", "Unknown")
                max_players = int(server_info.get("sv_maxclients", "32"))
                humans = sum(1 for p in players if p.get("ping", "0") != "0")
                bots = len(players) - humans
                player_count = f"{len(players)}/{max_players}"

                player_list = "No players" if not players else "```\n" + \
                    "ID  | Name              | Score\n" + \
                    "\n".join(
                        f"{i:<3} | {(self.remove_color_codes(p.get('name', ''))[:17]):<17} | {p.get('score', '0'):<5}"
                        for i, p in enumerate(players)
                    ) + "\n```"

                embed1 = discord.Embed(title=server_name, color=discord.Color.gold())
                embed1.add_field(name="Players", value=player_count, inline=True)
                mod = self.remove_color_codes(info.get("gamename", "Unknown"))
                embed1.add_field(name="Mod", value=mod, inline=True)
                version = info.get("Lugormod_Version")
                if version:
                    embed1.add_field(name="Version", value=self.remove_color_codes(version), inline=True)
                embed1.add_field(name="Map", value=f"`{map_name}`", inline=True)
                embed1.add_field(name="IP", value=server_info.get("serverIPAddress", "Unknown"), inline=True)
                embed1.add_field(name="Location", value=server_info.get("geoIPcountryCode", "??").upper(), inline=True)

                levelshots = server_info.get("levelshotsArray", [])
                if levelshots and levelshots[0]:
                    image_url = f"https://pt.dogi.us/{quote(levelshots[0])}"
                    embed1.set_image(url=image_url)

                embed2 = discord.Embed(color=discord.Color.gold())
                embed2.add_field(name="Players", value=player_list, inline=False)

                await ctx.send(embed=embed1)
                await ctx.send(embed=embed2)
            except Exception as e:
                await ctx.send(f"Failed to fetch status: {e}")

    @commands.command(name="jkplayer")
    async def player_info(self, ctx, username: str):
        if not await self.validate_rcon_settings():
            await ctx.send("RCON not configured.")
            return

        command = f"accountinfo {username}"
        try:
            response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command,
                command, await self.config.rcon_host(),
                await self.config.rcon_port(), await self.config.rcon_password()
            )
            text = response.decode('cp1252', errors='replace')
        except Exception as e:
            await ctx.send(f"Failed to get info: {e}")
            return

        stats = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('\xff'):
                continue
            if ":" in line:
                k, v = map(str.strip, line.split(":", 1))
                stats[self.remove_color_codes(k)] = self.remove_color_codes(v)

        if "Id" not in stats:
            await ctx.send(f"Player `{username}` not found.")
            return

        wins = int(stats.get("Duels won", "0"))
        total = int(stats.get("Total duels", "0"))
        losses = max(0, total - wins)
        playtime = stats.get("Time", "N/A")
        if ":" in playtime:
            playtime = f"{playtime.split(':')[0]} Hrs"

        embed = discord.Embed(
            title=f"Stats: {stats.get('Name', username)}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Playtime", value=playtime, inline=True)
        embed.add_field(name="Level", value=stats.get("Level", "N/A"), inline=True)
        embed.add_field(name="Profession", value=stats.get("Profession", "N/A"), inline=True)
        embed.add_field(name="Credits", value=stats.get("Credits", "N/A"), inline=True)
        embed.add_field(name="Stashes", value=stats.get("Stashes", "N/A"), inline=True)
        embed.add_field(name="Duel Score", value=stats.get("Score", "N/A"), inline=True)
        embed.add_field(name="Duels Won", value=str(wins), inline=True)
        embed.add_field(name="Duels Lost", value=str(losses), inline=True)
        embed.add_field(name="Kills", value=stats.get("Kills", "0"), inline=True)
        embed.set_footer(text=f"Last Login: {stats.get('Last login', 'N/A')}")

        await ctx.send(embed=embed)

    # === CHAT LISTENER ===
    @commands.Cog.listener()
    async def on_message(self, message):
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        prefixes = await self.bot.get_prefix(message)
        if any(message.content.startswith(p) for p in prefixes):
            return

        username = self.clean_for_latin1(message.author.display_name)
        content = self.clean_for_latin1(message.content)
        for member in message.mentions:
            clean_name = self.clean_for_latin1(member.display_name)
            content = content.replace(f"<@!{member.id}>", f"@{clean_name}").replace(f"<@{member.id}>", f"@{clean_name}")
        content = self.replace_emojis_with_names(content)

        prefix = f"say ^5:discord: ^7{username}: ^2"
        max_len = 115
        chunks = []
        remaining = content
        first = True
        while remaining:
            cur_max = max_len if first else 128 - 4
            if len(remaining) <= cur_max:
                chunks.append(remaining)
                break
            split = remaining.rfind(' ', 0, cur_max + 1) or cur_max
            chunks.append(remaining[:split].strip())
            remaining = remaining[split:].strip()
            first = False

        if not await self.validate_rcon_settings():
            await message.channel.send("RCON settings not configured.")
            return

        try:
            for i, chunk in enumerate(chunks):
                cmd = f"{prefix if i == 0 else 'say '}{chunk}"
                await self.bot.loop.run_in_executor(
                    self.executor, self.send_rcon_command,
                    cmd, await self.config.rcon_host(),
                    await self.config.rcon_port(), await self.config.rcon_password()
                )
                await asyncio.sleep(0.1)
        except Exception as e:
            await message.channel.send(f"Failed to send: {e}")

    def replace_emojis_with_names(self, text):
        emoji_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢",
            ">:(": "😡", ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣",
            ":o": "😮", "=D": "😁", "xD": "😆", "O.o": "😳", "B)": "🤓", "-_-": "😴", "^^;": "😅",
            ":/": "😒", ":*": "😘", "8)": "😎", "D:": "😱", ":?": "🤔", "\\o/": "🥳", ">^.^<": "🤗", ":p": "🤪",
            ":pray:": "🙏", ":wave:": "👋", ":-|": "😶", "*.*": "🤩", "O:)": "😇",
            ":jackolantern:": ":jack_o_lantern:", ":christmastree:": ":christmas_tree:", ":lol:": ":rofl:"
        }
        return ''.join(emoji_map.get(c, c) for c in text)

    def replace_text_emotes_with_emojis(self, text):
        emote_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢",
            ">:(": "😡", ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣",
            ":o": "😮", "=D": "😁", "xD": "😆", "O.o": "😳", "B)": "🤓", "-_-": "😴", "^^;": "😅",
            ":/": "😒", ":*": "😘", "8)": "😎", "D:": "😱", ":?": "🤔", "\\o/": "🥳", ">^.^<": "🤗", ":p": "🤪",
            ":pray:": "🙏", ":wave:": "👋", ":-|": "😶", "*.*": "🤩", "O:)": "😇",
            ":jackolantern:": ":jack_o_lantern:", ":christmastree:": ":christmas_tree:", ":lol:": ":rofl:"
        }
        for k, v in emote_map.items():
            text = text.replace(k, v)
        return text

    async def cog_unload(self):
        self.monitoring = False
        for task in [self.monitor_task, self.random_chat_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error during task shutdown: {e}")

        self.executor.shutdown(wait=True)
        logger.info("JKChatBridge unloaded cleanly.")

async def setup(bot):
    await bot.add_cog(JKChatBridge(bot))