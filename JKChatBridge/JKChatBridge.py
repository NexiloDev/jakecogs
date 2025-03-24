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

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("JKChatBridge")

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord using RCON and log monitoring, with ParaTracker JSON for server status."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_base_path="C:\\GameServers\\StarWarsJKA\\GameData\\lugormod",
            discord_channel_id=None,
            rcon_host="127.0.0.1",
            rcon_port=29070,
            rcon_password=None,
            custom_emoji="<:jk:1219115870928900146>",
            join_disconnect_enabled=True,
            tracker_url="https://pt.dogi.us/?ip=jka.mysticforces.net&port=29070&JSONReload=1"
        )
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.monitoring = False
        self.monitor_task = None
        self.url_pattern = re.compile(
            r'(https?://[^\s]+|www\.[^\s]+|\b[a-zA-Z0-9-]+\.(com|org|net|edu|gov|io|co|uk|ca|de|fr|au|us|ru|ch|it|nl|se|no|es|mil)(/[^\s]*)?)',
            re.IGNORECASE
        )
        self.is_restarting = False
        self.restart_map = None
        self.start_monitoring()

    async def cog_load(self):
        logger.debug("Cog loaded.")

    async def validate_rcon_settings(self):
        """Check if RCON settings are fully configured for chat and player commands."""
        return all([await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()])

    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (also available as 'jk'). Restricted to bot owner."""
        pass

    @jkbridge.command()
    async def setlogbasepath(self, ctx, path: str):
        """Set the base path for the qconsole.log file."""
        await self.config.log_base_path.set(path)
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            await self.monitor_task
        self.start_monitoring()
        await ctx.send(f"Log base path set to: {path}. Monitoring task restarted.")

    @jkbridge.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for the chat bridge."""
        await self.config.discord_channel_id.set(channel.id)
        await ctx.send(f"Discord channel set to: {channel.name} (ID: {channel.id})")

    @jkbridge.command()
    async def setrconhost(self, ctx, host: str):
        """Set the RCON host (IP or address)."""
        await self.config.rcon_host.set(host)
        await ctx.send(f"RCON host set to: {host}")

    @jkbridge.command()
    async def setrconport(self, ctx, port: int):
        """Set the RCON port."""
        await self.config.rcon_port.set(port)
        await ctx.send(f"RCON port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx, password: str):
        """Set the RCON password."""
        await self.config.rcon_password.set(password)
        await ctx.send("RCON password set.")

    @jkbridge.command()
    async def setcustomemoji(self, ctx, emoji: str):
        """Set the custom emoji for game-to-Discord chat messages."""
        await self.config.custom_emoji.set(emoji)
        await ctx.send(f"Custom emoji set to: {emoji}")

    @jkbridge.command()
    async def settrackerurl(self, ctx, url: str):
        """Set the ParaTracker JSON URL."""
        await self.config.tracker_url.set(url)
        await ctx.send(f"Tracker URL set to: {url}")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        channel = self.bot.get_channel(await self.config.discord_channel_id()) if await self.config.discord_channel_id() else None
        settings_message = (
            f"**Current Settings:**\n"
            f"Log Base Path: {await self.config.log_base_path() or 'Not set'}\n"
            f"Discord Channel: {channel.name if channel else 'Not set'} (ID: {await self.config.discord_channel_id() or 'Not set'})\n"
            f"RCON Host: {await self.config.rcon_host() or 'Not set'}\n"
            f"RCON Port: {await self.config.rcon_port() or 'Not set'}\n"
            f"RCON Password: {'Set' if await self.config.rcon_password() else 'Not set'}\n"
            f"Custom Emoji: {await self.config.custom_emoji() or 'Not set'}\n"
            f"Tracker URL: {await self.config.tracker_url() or 'Not set'}"
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

                # Handle case where serverInfo or players might be missing
                server_info = data.get("serverInfo", {})
                players = data.get("players", [])

                server_name = self.remove_color_codes(server_info.get("servername", "Unknown Server"))
                map_name = server_info.get("mapname", "Unknown Map")
                max_players = int(server_info.get("sv_maxclients", "32"))

                # Combine humans and bots into a single count
                humans = sum(1 for p in players if p.get("ping", "0") != "0")
                bots = sum(1 for p in players if p.get("ping", "0") == "0")
                total_players = humans + bots
                player_count = f"{total_players}/{max_players}"

                # Format player list with fixed-width columns, removing Ping column
                player_list = "No players online" if not players else "```\n" + \
                    "ID  | Name            | Score\n" + \
                    "\n".join(
                        f"{i:<3} | {self.remove_color_codes(p.get('name', 'Unknown'))[:15]:<15} | {p.get('score', '0'):<5}"
                        for i, p in enumerate(players)  # Use enumeration for client ID
                    ) + "\n```"

                # Build embed without Location field, with Map above Online Players
                embed = discord.Embed(title=f"{server_name}", color=discord.Color.gold())
                embed.add_field(name="👥 Players", value=player_count, inline=True)
                embed.add_field(name="🎮 Mod", value="Lugormod", inline=True)
                embed.add_field(name="🗺️ Map", value=f"`{map_name}`", inline=False)

                # Add map image above Online Players
                levelshots = server_info.get("levelshotsArray", [])
                if levelshots and levelshots[0]:
                    levelshot_path = quote(levelshots[0])
                    image_url = f"https://pt.dogi.us/{levelshot_path}"
                    embed.add_field(name="🖼️ Map Preview", value="\u200b", inline=False)
                    embed.set_image(url=image_url)

                embed.add_field(name="📋 Online Players", value=player_list, inline=False)

                await ctx.send(embed=embed)
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
        embed.add_field(name="⏱️ Playtime", value=playtime, inline=True)
        embed.add_field(name="🔼 Level", value=stats.get("Level", "N/A"), inline=True)
        embed.add_field(name="🛡️ Profession", value=stats.get("Profession", "N/A"), inline=True)
        embed.add_field(name="💰 Credits", value=stats.get("Credits", "N/A"), inline=True)
        embed.add_field(name="💼 Stashes", value=stats.get("Stashes", "N/A"), inline=True)
        embed.add_field(name="🏆 Duel Score", value=stats.get("Score", "N/A"), inline=True)
        embed.add_field(name="⚔️ Duels Won", value=str(wins), inline=True)
        embed.add_field(name="⚔️ Duels Lost", value=str(losses), inline=True)
        embed.add_field(name="🗡️ Total Kills", value=stats.get("Kills", "0"), inline=True)
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

        discord_username = message.author.display_name.replace("’", "'").replace("“", '"').replace("–", "-").replace("…", "...")
        message_content = message.content.replace("’", "'").replace("“", '"').replace("–", "-").replace("…", "...")
        for member in message.mentions:
            message_content = message_content.replace(f"<@!{member.id}>", f"@{member.display_name}").replace(f"<@{member.id}>", f"@{member.display_name}")
        message_content = self.replace_emojis_with_names(message_content)

        if self.url_pattern.search(message_content):
            return

        initial_prefix = f"say ^7{discord_username}^2: "
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
        """Replace custom Discord emojis and convert standard Unicode emojis."""
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        emoji_map = {
            "😊": ":)", "😄": ":D", "😂": "XD", "🤣": "xD", "😉": ";)", "😛": ":P", "😢": ":(", "😡": ">:(",
            "👍": ":+1:", "👎": ":-1:", "❤️": "<3", "💖": "<3", "😍": ":*", "🙂": ":)", "😣": ":S", "😜": ";P",
            "😮": ":o", "😁": "=D", "😆": "xD", "😳": "O.o", "🤓": "B)", "😴": "-_-", "😅": "^^;", "😒": ":/",
            "😘": ":*", "😎": "8)", "😱": "D:", "🤔": ":?", "🥳": "\\o/", "🤗": ">^.^<", "🤪": ":p"
        }
        return ''.join(emoji_map.get(c, c) for c in text)

    def replace_text_emotes_with_emojis(self, text):
        """Convert common text emoticons from Jedi Knight to Discord emojis."""
        text_emote_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢",
            ">:(": "😡", ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣",
            ":o": "😮", "=D": "😁", "xD": "😆", "O.o": "😳", "B)": "🤓", "-_-": "😴", "^^;": "😅",
            ":/": "😒", ":*": "😘", "8)": "😎", "D:": "😱", ":?": "🤔", "\\o/": "🥳", ">^.^<": "🤗", ":p": "🤪"
        }
        for text_emote, emoji in text_emote_map.items():
            text = text.replace(text_emote, emoji)
        return text

    def send_rcon_command(self, command, host, port, password):
        """Send an RCON command to the game server and return the response."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        packet = b'\xff\xff\xff\xffrcon ' + password.encode() + b' ' + command.encode()
        try:
            sock.sendto(packet, (host, port))
            time.sleep(0.1)
            response = b""
            start_time = time.time()
            packet_count = 0
            while time.time() - start_time < 5:
                try:
                    data, _ = sock.recvfrom(16384)
                    response += data
                    packet_count += 1
                    print(f"Received packet {packet_count}: {len(data)} bytes")
                except socket.timeout:
                    print(f"Stopped receiving after {packet_count} packets")
                    break
            if not response:
                raise Exception("No response received from server.")
            print(f"Total packets received: {packet_count}, Total bytes: {len(response)}")
            return response
        except socket.timeout:
            raise Exception("RCON command timed out.")
        except Exception as e:
            raise Exception(f"Error sending RCON command: {e}")
        finally:
            sock.close()

    def remove_color_codes(self, text):
        """Remove Jedi Academy color codes from text."""
        return re.sub(r'\^\d', '', text)

    async def monitor_log(self):
        """Monitor qconsole.log for events and trigger actions."""
        self.monitoring = True
        log_file = os.path.join(await self.config.log_base_path(), "qconsole.log")

        while self.monitoring:
            try:
                channel_id = await self.config.discord_channel_id()
                custom_emoji = await self.config.custom_emoji()
                if not all([await self.config.log_base_path(), channel_id, custom_emoji]):
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

                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message and not self.url_pattern.search(message):
                                message = self.replace_text_emotes_with_emojis(message)
                                await channel.send(f"{custom_emoji} **{player_name}**: {message}")

                        elif "duel:" in line and "won a duel against" in line:
                            parts = line.split("duel:")[1].split("won a duel against")
                            if len(parts) == 2:
                                winner = self.remove_color_codes(parts[0].strip())
                                loser = self.remove_color_codes(parts[1].strip())
                                await channel.send(f"<a:peepoBeatSaber:1228624251800522804> **{winner}** won a duel against **{loser}**!")

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

                        elif "Going from CS_CONNECTED to CS_PRIMED for" in line:
                            join_name = line.split("Going from CS_CONNECTED to CS_PRIMED for ")[1].strip()
                            join_name_clean = self.remove_color_codes(join_name)
                            if not join_name_clean.endswith("-Bot") and not self.is_restarting:
                                if await self.config.join_disconnect_enabled():
                                    await channel.send(f"<:jk_connect:1349009924306374756> **{join_name_clean}** has joined the game!")

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
        """Reset the restart flag after 30 seconds if no map change occurs."""
        await asyncio.sleep(30)
        if self.is_restarting:
            self.is_restarting = False
            self.restart_map = None
            await channel.send("✅ **Server Integration Resumed**: Restart timed out, resuming normal operation.")

    def start_monitoring(self):
        """Start the log monitoring task if it's not already running."""
        if not self.monitor_task or self.monitor_task.done():
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

    async def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.monitoring = False
        for task in [self.monitor_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.executor.shutdown(wait=False)

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
            full_command = f"rcon {command}"
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, command, await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            await ctx.send(f"RCON command sent: `{full_command}`")
        except Exception as e:
            await ctx.send(f"Failed to send RCON command `{full_command}`: {e}")

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
    async def reload_monitor(self, ctx):
        """Reload the log monitoring task to refresh the bot's connection."""
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                print("Monitoring task canceled successfully.")
            except Exception as e:
                print(f"Error canceling task: {e}")

        await asyncio.sleep(1)
        self.is_restarting = False
        self.restart_map = None
        self.start_monitoring()
        await ctx.send("✅ **Log monitoring task reloaded.**")

async def setup(bot):
    """Set up the JKChatBridge cog when the bot loads."""
    await bot.add_cog(JKChatBridge(bot))