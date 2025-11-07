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
    RANDOM_CHAT_INTERVAL = 300   # 5 minutes
    RANDOM_CHAT_CHANCE = 0.5     # 50%

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
            random_chat_path=None
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
        # Start auto-reload task
        self.bot.loop.create_task(self.auto_reload_monitor())

    async def cog_load(self) -> None:
        """Called when the cog is loaded."""
        logger.debug("Cog loaded.")
        await self.load_random_chat_lines()

    async def _start_random_chat_when_ready(self):
        """Wait for bot to be ready before starting random chat."""
        await self.bot.wait_until_ready()
        await self.start_random_chat_task()

    async def load_random_chat_lines(self):
        """Load random chat lines from file."""
        path = await self.config.random_chat_path()
        self.random_chat_lines = []
        if not path or not os.path.exists(path):
            return
        try:
            async with aiofiles.open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = await f.read()
            lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith('#')
            ]
            self.random_chat_lines = lines
            logger.info(f"Loaded {len(lines)} random chat lines from {path}")
        except Exception as e:
            logger.error(f"Failed to load random chat lines: {e}")

    async def start_random_chat_task(self):
        """Start the background task for random chat messages."""
        if self.random_chat_task and not self.random_chat_task.done():
            self.random_chat_task.cancel()
            try:
                await self.random_chat_task
            except asyncio.CancelledError:
                pass
        self.random_chat_task = self.bot.loop.create_task(self.random_chat_loop())

    async def random_chat_loop(self):
        """Every X minutes, Y% chance to send a random line via sayasbot."""
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
        """Run silent reload_monitor every 5 minutes."""
        while True:
            try:
                await asyncio.sleep(300)  # 5 minutes
                await self.reload_monitor()  # Call existing reload_monitor (silent by default)
                logger.debug("Auto-reload triggered")
            except Exception as e:
                logger.error(f"Error in auto_reload_monitor: {e}")
                await asyncio.sleep(300)

    async def _safe_restart_monitor(self):
        """Restart only if task is dead."""
        if self.monitor_task and not self.monitor_task.done():
            return
        logger.info("Restarting log monitor due to crash or missing file.")
        self.start_monitoring()

    async def validate_rcon_settings(self) -> bool:
        return all([
            await self.config.rcon_host(),
            await self.config.rcon_port(),
            await self.config.rcon_password()
        ])

    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx: commands.Context) -> None:
        """Configure the JK chat bridge (also available as 'jk')."""
        pass

    @jkbridge.command()
    async def setlogbasepath(self, ctx: commands.Context, path: str) -> None:
        """Set the base path for the qconsole.log file."""
        await self.config.log_base_path.set(path)
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            await self.monitor_task
        self.start_monitoring()
        await ctx.send(f"Log base path set to: {path}. Monitoring task restarted.")

    @jkbridge.command()
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the Discord channel for the chat bridge."""
        await self.config.discord_channel_id.set(channel.id)
        await ctx.send(f"Discord channel set to: {channel.name} (ID: {channel.id})")

    @jkbridge.command()
    async def setrconhost(self, ctx: commands.Context, host: str) -> None:
        """Set the RCON host (IP or address)."""
        await self.config.rcon_host.set(host)
        await ctx.send(f"RCON host set to: {host}")

    @jkbridge.command()
    async def setrconport(self, ctx: commands.Context, port: int) -> None:
        """Set the RCON port."""
        await self.config.rcon_port.set(port)
        await ctx.send(f"RCON port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx: commands.Context, password: str) -> None:
        """Set the RCON password."""
        await self.config.rcon_password.set(password)
        await ctx.send("RCON password set.")

    @jkbridge.command()
    async def setcustomemoji(self, ctx: commands.Context, emoji: str) -> None:
        """Set the custom emoji for game-to-Discord chat messages."""
        await ctx.send("Custom emoji feature has been removed and is no longer used.")

    @jkbridge.command()
    async def settrackerurl(self, ctx: commands.Context, url: str) -> None:
        """Set the ParaTracker JSON URL."""
        await self.config.tracker_url.set(url)
        await ctx.send(f"Tracker URL set to: {url}")

    @jkbridge.command()
    async def setbotname(self, ctx: commands.Context, name: str) -> None:
        """Set the bot name for sayasbot commands."""
        await self.config.bot_name.set(name)
        await ctx.send(f"Bot name set to: {name}")

    @jkbridge.command()
    async def setvpnkey(self, ctx: commands.Context, key: str) -> None:
        """Set the vpnapi.io API key."""
        await self.config.vpn_api_key.set(key)
        await ctx.send("VPN API key set.")

    @jkbridge.command()
    async def togglevpncheck(self, ctx: commands.Context) -> None:
        """Toggle VPN detection on/off."""
        new = not await self.config.vpn_check_enabled()
        await self.config.vpn_check_enabled.set(new)
        await ctx.send(f"VPN detection {'enabled' if new else 'disabled'}.")

    @jkbridge.command()
    async def setchatpath(self, ctx: commands.Context, path: str) -> None:
        """Set the path to the random chat lines .txt file."""
        await self.config.random_chat_path.set(path)
        await self.load_random_chat_lines()
        count = len(self.random_chat_lines)
        await ctx.send(f"Random chat file set to: `{path}`\nLoaded **{count}** lines. Use `[p]reload JKChatBridge` after editing.")

    @jkbridge.command()
    async def showsettings(self, ctx: commands.Context) -> None:
        """Show the current settings for the JK chat bridge."""
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
            f"Random Chat File: `{chat_path or 'Not set'}` → {chat_status}"
        )
        await ctx.send(settings_message)

    @commands.command(name="jkstatus")
    async def status(self, ctx):
        """Display detailed server status with emojis using ParaTracker data."""
        async with aiohttp.ClientSession() as session:
            try:
                tracker_url = await self.config.tracker_url()
                if not tracker_url:
                    await ctx.send("Tracker URL not configured. Use `jkbridge settrackerurl` to set it.")
                    return

                async with session.get(tracker_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Tracker fetch failed: HTTP {response.status} - {error_text[:200]}")
                        await ctx.send(f"Failed to retrieve server status: HTTP {response.status}")
                        return
                    content_type = response.headers.get('Content-Type', '')
                    if 'application/json' not in content_type:
                        raw_text = await response.text()
                        logger.error(f"Unexpected mimetype: {content_type} - Response: {raw_text[:200]}")
                        await ctx.send(f"Failed to retrieve server status: Expected JSON, got {content_type}")
                        return
                    data = await response.json()

                server_info = data.get("serverInfo", {})
                info = data.get("info", {})
                players = data.get("players", [])

                server_name = self.remove_color_codes(server_info.get("servername", "Unknown Server"))
                map_name = server_info.get("mapname", "Unknown Map")
                max_players = int(server_info.get("sv_maxclients", "32"))

                humans = sum(1 for p in players if p.get("ping", "0") != "0")
                bots = sum(1 for p in players if p.get("ping", "0") == "0")
                total_players = humans + bots
                player_count = f"{total_players}/{max_players}"

                player_list = "No players online" if not players else "```\n" + \
                    "ID  | Name              | Score\n" + \
                    "\n".join(
                        f"{i:<3} | {(self.remove_color_codes(p.get('name', '(null)') or '(null)')[:17]):<17} | {p.get('score', '0'):<5}"
                        for i, p in enumerate(players)
                    ) + "\n```"

                embed1 = discord.Embed(title=f"{server_name}", color=discord.Color.gold())
                embed1.add_field(name="Players", value=player_count, inline=True)
                mod_name = self.remove_color_codes(info.get("gamename", "Unknown Mod"))
                embed1.add_field(name="Mod", value=mod_name, inline=True)
                lugormod_version = info.get("Lugormod_Version")
                if lugormod_version:
                    version_clean = self.remove_color_codes(lugormod_version)
                    embed1.add_field(name="Version", value=version_clean, inline=True)
                embed1.add_field(name="Map", value=f"`{map_name}`", inline=True)
                server_ip = server_info.get("serverIPAddress", "Unknown")
                geoip = server_info.get("geoIPcountryCode", "Unknown")
                embed1.add_field(name="IP", value=server_ip, inline=True)
                embed1.add_field(name="Location", value=geoip.upper(), inline=True)
                levelshots = server_info.get("levelshotsArray", [])
                if levelshots and levelshots[0]:
                    levelshot_path = quote(levelshots[0])
                    image_url = f"https://pt.dogi.us/{levelshot_path}"
                    embed1.set_image(url=image_url)

                embed2 = discord.Embed(color=discord.Color.gold())
                embed2.add_field(name="Online Players", value=player_list, inline=False)

                await ctx.send(embed=embed1)
                await ctx.send(embed=embed2)
            except asyncio.TimeoutError:
                logger.error("Tracker request timed out")
                await ctx.send("Failed to retrieve server status: Request timed out")
            except Exception as e:
                logger.error(f"Error in jkstatus: {str(e)}")
                await ctx.send(f"Failed to retrieve server status: {str(e)}")

    @commands.command(name="jkplayer")
    async def player_info(self, ctx, username: str):
        """Display player stats for the given username (still uses RCON)."""
        if not await self.validate_rcon_settings():
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        command = f"accountinfo {username}"
        try:
            response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, command, await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            response_text = response.decode('cp1252', errors='replace')
            response_lines = response_text.splitlines()
        except Exception as e:
            await ctx.send(f"Failed to retrieve player info: {e}")
            return

        stats = {}
        timestamp_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        for line in response_lines:
            line = line.strip()
            if timestamp_pattern.match(line) or line.startswith('\xff\xff\xff\xffprint'):
                continue
            if ":" in line:
                key, value = map(str.strip, line.split(":", 1))
            else:
                parts = re.split(r'\s{2,}', line)
                if len(parts) >= 2:
                    key, value = parts[0], parts[-1]
                else:
                    continue
            stats[self.remove_color_codes(key)] = self.remove_color_codes(value)

        if "Id" not in stats and "Username" not in stats:
            await ctx.send(f"Player '{username}' not found.")
            return

        wins = int(stats.get("Duels won", "0"))
        total_duels = int(stats.get("Total duels", "0"))
        losses = max(0, total_duels - wins)
        playtime = stats.get("Time", "N/A")
        if ":" in playtime and playtime != "N/A":
            playtime = f"{playtime.split(':')[0]} Hrs"

        player_name = stats.get("Name", username).encode('utf-8', 'replace').decode()
        embed = discord.Embed(title=f"Player Stats for {player_name} *({stats.get('Username', 'N/A')})*", color=discord.Color.blue())
        embed.add_field(name="Playtime", value=playtime, inline=True)
        embed.add_field(name="Level", value=stats.get("Level", "N/A"), inline=True)
        embed.add_field(name="Profession", value=stats.get("Profession", "N/A"), inline=True)
        embed.add_field(name="Credits", value=stats.get("Credits", "N/A"), inline=True)
        embed.add_field(name="Stashes", value=stats.get("Stashes", "N/A"), inline=True)
        embed.add_field(name="Duel Score", value=stats.get("Score", "N/A"), inline=True)
        embed.add_field(name="Duels Won", value=str(wins), inline=True)
        embed.add_field(name="Duels Lost", value=str(losses), inline=True)
        embed.add_field(name="Total Kills", value=stats.get("Kills", "0"), inline=True)
        embed.set_footer(text=f"Last Login: {stats.get('Last login', 'N/A')}")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages from Discord and send them to the game server via RCON."""
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        
        prefixes = await self.bot.get_prefix(message)
        if any(message.content.startswith(prefix) for prefix in prefixes):
            return

        discord_username = self.clean_for_latin1(message.author.display_name)
        message_content = self.clean_for_latin1(message.content)
        for member in message.mentions:
            clean_mention = self.clean_for_latin1(member.display_name)
            message_content = message_content.replace(f"<@!{member.id}>", f"@{clean_mention}").replace(f"<@{member.id}>", f"@{clean_mention}")
        message_content = self.replace_emojis_with_names(message_content)

        initial_prefix = f"say ^7(^5Discord^7) ^7{discord_username}: ^2"
        continuation_prefix = "say "
        max_length = 115
        chunks = []
        remaining = message_content
        is_first_chunk = True
        while remaining:
            current_max_length = max_length if is_first_chunk else (128 - len(continuation_prefix))
            if len(remaining) <= current_max_length:
                chunks.append(remaining)
                break
            split_point = remaining.rfind(' ', 0, current_max_length + 1) or current_max_length
            chunks.append(remaining[:split_point].strip())
            remaining = remaining[split_point:].strip()
            is_first_chunk = False

        if not await self.validate_rcon_settings():
            await message.channel.send("RCON settings not fully configured.")
            return

        try:
            for i, chunk in enumerate(chunks):
                server_command = f"{initial_prefix if i == 0 else continuation_prefix}{chunk}"
                await self.bot.loop.run_in_executor(self.executor, self.send_rcon_command, server_command, await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password())
                await asyncio.sleep(0.1)
        except Exception as e:
            await message.channel.send(f"Failed to send to game: {e}")

    def replace_emojis_with_names(self, text):
        """Replace custom Discord emojis and convert standard Unicode emojis to text representations."""
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        emoji_map = {
            "😊": ":)", "😄": ":D", "😂": "XD", "🤣": "xD", "😉": ";)", "😛": ":P", "😢": ":(", "😡": ">:(",
            "👍": ":+1:", "👎": ":-1:", "❤️": "<3", "💖": "<3", "😍": ":*", "🙂": ":)", "😣": ":S", "😜": ";P",
            "😮": ":o", "😁": "=D", "😆": "xD", "😳": "O.o", "🤓": "B)", "😴": "-_-", "😅": "^^;", "😒": ":/",
            "😘": ":*", "😎": "8)", "😱": "D:", "🤔": "?:", "🥳": "\\o/", "🤗": ">^.^<", "🤪": ":p",
            "🙏": ":pray:", "👋": ":wave:", "😃": ":D", "😓": ":S", "😤": ">:(" , "😋": ":P", "😶": ":-|",
            "🥰": "<3", "🤩": "*.*", "😬": ":/", "😇": "O:)", "🎃": ":jack_o_lantern:", "🎄": ":christmas_tree:"
        }
        return ''.join(emoji_map.get(c, c) for c in text)

    def clean_for_latin1(self, text):
        """Remove or replace characters that can't be encoded in Latin-1."""
        text = self.replace_emojis_with_names(text)
        return ''.join(c if ord(c) < 256 else '' for c in text)

    def send_rcon_command(self, command, host, port, password):
        """Send an RCON command to the game server and return the response."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        clean_command = self.clean_for_latin1(command)
        clean_password = self.clean_for_latin1(password)
        packet = b'\xff\xff\xff\xffrcon ' + clean_password.encode('latin-1') + b' ' + clean_command.encode('latin-1')
        try:
            sock.sendto(packet, (host, port))
            time.sleep(0.1)
            response = b""
            start_time = time.time()
            while time.time() - start_time < 5:
                try:
                    data, _ = sock.recvfrom(16384)
                    response += data
                except socket.timeout:
                    break
            if not response:
                raise Exception("No response received from server.")
            return response
        except socket.timeout:
            raise Exception("RCON command timed out.")
        except Exception as e:
            raise Exception(f"Error sending RCON command: {e}")
        finally:
            sock.close()

    def remove_color_codes(self, text):
        """Remove Jedi Academy color codes from text."""
        return re.sub(r'\^\d', '', text or '')

    def replace_text_emotes_with_emojis(self, text):
        """Convert common text emoticons from Jedi Knight to Discord emojis."""
        text_emote_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢",
            ">:(": "😡", ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣",
            ":o": "😮", "=D": "😁", "xD": "😆", "O.o": "😳", "B)": "🤓", "-_-": "😴", "^^;": "😅",
            ":/": "😒", ":*": "😘", "8)": "😎", "D:": "😱", ":?": "🤔", "\\o/": "🥳", ">^.^<": "🤗", ":p": "🤪",
            ":pray:": "🙏", ":wave:": "👋", ":-|": "😶", "*.*": "🤩", "O:)": "😇",
            ":jackolantern:": ":jack_o_lantern:", ":christmastree": ":christmas_tree:"
        }
        for text_emote, emoji in text_emote_map.items():
            text = text.replace(text_emote, emoji)
        return text

    async def monitor_log(self):
        """Monitor qconsole.log for events and trigger actions."""
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

                        # === VPN Detection: Immediate check on IP line ===
                        if "info: IP: " in line and await self.config.vpn_check_enabled():
                            parts = line.split()
                            if len(parts) >= 5:
                                ip = parts[2]
                                player_id_str = parts[-1]
                                if player_id_str.isdigit():
                                    player_id = int(player_id_str)
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
                                winner_with_colors = parts[0].strip()
                                loser_with_colors = parts[1].strip()
                                if await self.validate_rcon_settings():
                                    bot_name = await self.config.bot_name()
                                    if not bot_name:
                                        logger.warning("Bot name not set, skipping duel message")
                                        continue
                                    duel_message = f"sayasbot {bot_name} {winner_with_colors} ^7has defeated {loser_with_colors} ^7in a duel^5! :crown:"
                                    try:
                                        await self.bot.loop.run_in_executor(
                                            self.executor, 
                                            self.send_rcon_command, 
                                            duel_message, 
                                            await self.config.rcon_host(), 
                                            await self.config.rcon_port(), 
                                            await self.config.rcon_password()
                                        )
                                    except Exception as e:
                                        logger.error(f"Failed to send duel message in-game: {e}")

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

                        elif "Going from CS_PRIMED to CS_ACTIVE for" in line:
                            join_name = line.split("Going from CS_PRIMED to CS_ACTIVE for ")[1].strip()
                            join_name_clean = self.remove_color_codes(join_name)
                            if not join_name_clean.endswith("-Bot") and not self.is_restarting:
                                if await self.config.join_disconnect_enabled():
                                    await channel.send(f"<:jk_connect:1349009924306374756> **{join_name_clean}** has joined the game!")
                                    bot_name = await self.config.bot_name()
                                    if bot_name and await self.validate_rcon_settings():
                                        current_time = time.time()
                                        if current_time - self.last_welcome_time >= 5:
                                            self.last_welcome_time = current_time
                                            welcome_message = f"sayasbot {bot_name} ^7Hey {join_name}^7, welcome to the server^5! :jackolantern:"
                                            self.bot.loop.create_task(self.send_welcome_message(welcome_message))

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

    async def send_welcome_message(self, message: str):
        """Send a welcome message to the game server after a 5-second delay."""
        await asyncio.sleep(5)
        try:
            await self.bot.loop.run_in_executor(
                self.executor,
                self.send_rcon_command,
                message,
                await self.config.rcon_host(),
                await self.config.rcon_port(),
                await self.config.rcon_password()
            )
        except Exception as e:
            logger.error(f"Failed to send welcome message: {e}")

    async def reset_restart_flag(self, channel):
        """Reset current_time = time.time()Reset the restart flag after 30 seconds if no map change occurs."""
        await asyncio.sleep(30)
        if self.is_restarting:
            self.is_restarting = False
            self.restart_map = None
            await channel.send("Server Integration Resumed: Restart timed out, resuming normal operation.")

    def start_monitoring(self):
        """Safely start log monitoring — only if not already running."""
        if self.monitor_task and not self.monitor_task.done():
            logger.debug("Monitor task already running — skipping.")
            return
        logger.info("Starting log monitor task.")
        self.monitor_task = self.bot.loop.create_task(self.monitor_log())

    def parse_chat_line(self, line):
        """Parse a chat line from the log into player name and message."""
        say_index = line.find("say: ")
        if say_index != -1:
            chat_part = line[say_index + 5:]
            colon_index = chat_part.find(": ")
            if colon_index != -1:
                player_name = chat_part[:colon_index].strip()
                message = chat_part[colon_index + 2:].strip()
                return self.remove_color_codes(player_name), self.remove_color_codes(message)
        return None, None

    async def _handle_vpn_check(self, player_id: int, ip: str):
        """Check IP via vpnapi.io and announce if VPN."""
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
                            self.executor,
                            self.send_rcon_command,
                            msg,
                            await self.config.rcon_host(),
                            await self.config.rcon_port(),
                            await self.config.rcon_password()
                        )
        except Exception:
            pass  # Silent fail

    async def cog_unload(self):
        """Forcefully shut down all tasks and release file handles."""
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

    @commands.command(name="jkexec")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkexec(self, ctx, filename: str):
        """Execute a server config file via RCON (Bot Owners/Admins only)."""
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
        """Send any RCON command to the server (Bot Owners/Admins only)."""
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
        """Toggle join and disconnect messages on or off (Bot Owners/Admins only)."""
        current_state = await self.config.join_disconnect_enabled()
        new_state = not current_state
        await self.config.join_disconnect_enabled.set(new_state)
        state_text = "enabled" if new_state else "disabled"
        await ctx.send(f"Join and disconnect messages are now **{state_text}**.")

    @commands.command(name="jkreload", aliases=["jkreloadmonitor"])
    async def reload_monitor(self, ctx: commands.Context = None):
        """Reload the log monitoring task to refresh the bot's connection."""
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

async def setup(bot):
    """Set up the JKChatBridge cog when the bot loads."""
    await bot.add_cog(JKChatBridge(bot))