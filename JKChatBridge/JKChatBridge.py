import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import os
import socket
from concurrent.futures import ThreadPoolExecutor
import re
from datetime import datetime, timedelta
import time
import subprocess
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("JKChatBridge")

class JKChatBridge(commands.Cog):
    __version__ = "1.0.5"  # Updated version for name fix
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord via RCON, with log file support for Lugormod."""

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
            server_executable="openjkded.x86.exe",
            start_batch_file="C:\\GameServers\\StarWarsJKA\\GameData\\start_jka_server.bat"
        )
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.monitoring = False
        self.monitor_task = None
        self.refresh_task = None
        self.client_names = {}
        self.previous_client_names = {}
        self.last_seen = {}
        self.url_pattern = re.compile(
            r'(https?://[^\s]+|www\.[^\s]+|\b[a-zA-Z0-9-]+\.(com|org|net|edu|gov|io|co|uk|ca|de|fr|au|us|ru|ch|it|nl|se|no|es|mil)(/[^\s]*)?)',
            re.IGNORECASE
        )
        self.recent_joins = {}
        self.is_restarting = False
        self.restart_map = None
        self.start_monitoring()
        self.start_refresh_loop()
        self.restart_task = self.bot.loop.create_task(self.schedule_daily_restart())

    async def cog_load(self):
        await self.refresh_player_data()
        logger.debug("Cog loaded, initial player data fetched.")

    async def refresh_player_data(self):
        """Refresh all player data using RCON playerlist and validate with status."""
        if not await self.validate_rcon_settings():
            logger.warning("RCON settings not configured, skipping refresh_player_data.")
            return

        try:
            channel_id = await self.config.discord_channel_id()
            channel = self.bot.get_channel(channel_id) if channel_id else None

            # Fetch playerlist
            playerlist_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "playerlist", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            response_text = playerlist_response.decode(errors='replace')
            logger.debug(f"playerlist response: {response_text}")
            new_client_names = {}
            for line in response_text.splitlines():
                line = line.strip()
                if not line or "Credits in the world" in line or "Total number of registered accounts" in line or "Ind Player" in line or "----" in line:
                    continue
                parts = re.split(r"\s+", line)
                if len(parts) >= 3 and parts[0].startswith("^") and self.remove_color_codes(parts[0]).isdigit():
                    client_id = self.remove_color_codes(parts[0])
                    # Find the first numeric field after client_id
                    name_end = len(parts)
                    for i in range(1, len(parts)):
                        if parts[i].isdigit():
                            name_end = i
                            break
                    # Take all parts up to the first numeric field as the name
                    name_parts = parts[1:name_end]
                    player_name = self.remove_color_codes(" ".join(name_parts))
                    # Find the last non-numeric part as username
                    username = None
                    for part in reversed(parts[name_end:]):
                        if part and not part.isdigit():
                            username = self.remove_color_codes(part)
                            break
                    new_client_names[client_id] = (player_name, username)
                    logger.debug(f"Parsed: ID={client_id}, Name={player_name}, Username={username}")

            # Validate "Padawan" names with status
            padawan_ids = [cid for cid, (name, _) in new_client_names.items() if name.startswith("Padawan")]
            if padawan_ids:
                try:
                    status_response = await self.bot.loop.run_in_executor(
                        self.executor, self.send_rcon_command, "status", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
                    )
                    status_lines = status_response.decode(errors='replace').splitlines()
                    temp_client_names = {}
                    parsing_players = False
                    for line in status_lines:
                        if "score ping" in line:
                            parsing_players = True
                            continue
                        if parsing_players and line.strip():
                            parts = re.split(r"\s+", line, 4)
                            if len(parts) >= 4 and parts[0].isdigit():
                                client_id = parts[0]
                                player_name = self.remove_color_codes(parts[3]) if len(parts) > 3 else "Unknown"
                                temp_client_names[client_id] = player_name
                    for client_id in padawan_ids:
                        if client_id in temp_client_names:
                            status_name = temp_client_names[client_id]
                            old_name, old_username = new_client_names[client_id]
                            if not status_name.startswith("Padawan") and status_name != old_name:
                                new_client_names[client_id] = (status_name, old_username)
                                if channel and client_id in self.client_names:
                                    await channel.send(f"✏️ **{old_name} (ID: {client_id})** has renamed to **{status_name} (ID: {client_id})**!")
                                logger.debug(f"Updated Padawan name: {old_name} -> {status_name} (ID: {client_id})")
                except Exception as e:
                    logger.error(f"Failed to fetch status for Padawan validation: {e}")

            # Detect joins and disconnects after validation
            if self.previous_client_names:
                # Disconnects
                if not self.is_restarting:
                    for client_id, (name, _) in self.previous_client_names.items():
                        if client_id not in new_client_names and not name.endswith("-Bot"):
                            if channel:
                                await channel.send(f"<:jk_disconnect:1349010016044187713> **{name} (ID: {client_id})** has disconnected.")
                            logger.debug(f"Disconnect detected: {name} (ID: {client_id})")
                            if client_id in self.recent_joins:
                                del self.recent_joins[client_id]
                # Joins
                for client_id, (name, _) in new_client_names.items():
                    if client_id not in self.previous_client_names and client_id not in self.last_seen:
                        current_time = datetime.now()
                        if client_id not in self.recent_joins or (current_time - self.recent_joins[client_id]).total_seconds() > 2.0:
                            self.recent_joins[client_id] = current_time
                            if channel:
                                await channel.send(f"<:jk_connect:1349009924306374756> **{name} (ID: {client_id})** has joined the game!")
                            logger.debug(f"Join detected: {name} (ID: {client_id})")

            self.previous_client_names = self.client_names.copy()
            self.client_names = new_client_names
            self.last_seen = new_client_names.copy()
            logger.debug(f"Updated client_names: {self.client_names}")

        except Exception as e:
            logger.error(f"Error in refresh_player_data: {e}")

    async def refresh_loop(self):
        """Periodically refresh player data every 5 seconds."""
        while True:
            try:
                await self.refresh_player_data()
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error in refresh_loop: {e}")
                await asyncio.sleep(5)

    async def validate_rcon_settings(self):
        """Check if RCON settings are fully configured."""
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        return all([rcon_host, rcon_port, rcon_password])

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
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                logger.debug("Monitor task cancelled.")
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
    async def setserverexecutable(self, ctx, executable: str):
        """Set the server executable name."""
        await self.config.server_executable.set(executable)
        await ctx.send(f"Server executable set to: {executable}")

    @jkbridge.command()
    async def setstartbatchfile(self, ctx, batch_file: str):
        """Set the .bat file to start the server."""
        await self.config.start_batch_file.set(batch_file)
        await ctx.send(f"Start batch file set to: {batch_file}")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        log_base_path = await self.config.log_base_path()
        discord_channel_id = await self.config.discord_channel_id()
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        custom_emoji = await self.config.custom_emoji()
        server_executable = await self.config.server_executable()
        start_batch_file = await self.config.start_batch_file()
        channel_name = "Not set"
        if discord_channel_id:
            channel = self.bot.get_channel(discord_channel_id)
            channel_name = channel.name if channel else "Unknown channel"
        settings_message = (
            f"**Current Settings:**\n"
            f"Log Base Path: {log_base_path or 'Not set'}\n"
            f"Discord Channel: {channel_name} (ID: {discord_channel_id or 'Not set'})\n"
            f"RCON Host: {rcon_host or 'Not set'}\n"
            f"RCON Port: {rcon_port or 'Not set'}\n"
            f"RCON Password: {'Set' if rcon_password else 'Not set'}\n"
            f"Custom Emoji: {custom_emoji or 'Not set'}\n"
            f"Server Executable: {server_executable or 'Not set'}\n"
            f"Start Batch File: {start_batch_file or 'Not set'}"
        )
        await ctx.send(settings_message)

    @jkbridge.command()
    async def reloadmonitor(self, ctx):
        """Force reload the log monitoring task and refresh player data."""
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                logger.debug("Monitor task cancelled.")
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                logger.debug("Refresh task cancelled.")
        self.client_names.clear()
        self.previous_client_names.clear()
        self.last_seen.clear()
        self.recent_joins.clear()
        self.is_restarting = False
        self.restart_map = None
        await self.refresh_player_data()
        self.start_monitoring()
        self.start_refresh_loop()
        await ctx.send("Log monitoring and player data refresh tasks reloaded.")

    @commands.command(name="jkstatus")
    async def status(self, ctx):
        """Display detailed server status with emojis using stored player data."""
        if not await self.validate_rcon_settings():
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        try:
            await self.refresh_player_data()
            status_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "status", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            status_lines = status_response.decode(errors='replace').splitlines()

            server_name = "Unknown"
            mod_name = "Unknown"
            map_name = "Unknown"
            player_count = "0 humans, 0 bots"

            for line in status_lines:
                if "hostname:" in line:
                    server_name = self.remove_color_codes(line.split("hostname:")[1].strip()).replace("Ç", "").encode().decode('ascii', 'ignore')
                elif "game    :" in line:
                    mod_name = line.split("game    :")[1].strip()
                elif "map     :" in line:
                    map_name = line.split("map     :")[1].split()[0].strip()
                elif "players :" in line:
                    player_count = line.split("players :")[1].strip()

            players = [(cid, f"{self.client_names[cid][0]}{' (' + self.client_names[cid][1] + ')' if self.client_names[cid][1] else ''}")
                       for cid in self.client_names.keys() if not cid.startswith("temp_")]
            player_list = "No players online"
            if players:
                player_lines = [f"{client_id:<3} {name_with_username}" for client_id, name_with_username in players]
                player_list = "```\n" + "\n".join(player_lines) + "\n```"

            embed = discord.Embed(
                title=f"🌌 {server_name} 🌌",
                color=discord.Color.gold()
            )
            embed.add_field(name="👥 Players", value=f"{player_count}", inline=True)
            embed.add_field(name="🗺️ Map", value=f"`{map_name}`", inline=True)
            embed.add_field(name="🎮 Mod", value=f"{mod_name}", inline=True)
            embed.add_field(name="📋 Online Players", value=player_list, inline=False)

            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in jkstatus: {e}")
            await ctx.send(f"Failed to retrieve server status: {e}")

    @commands.command(name="jkplayer")
    async def player_info(self, ctx, username: str):
        """Display player stats for the given username."""
        if not await self.validate_rcon_settings():
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        command = f"accountinfo {username}"
        try:
            response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, command, await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            try:
                response_text = response.decode('utf-8')
            except UnicodeDecodeError:
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
                    key = parts[0]
                    value = parts[-1]
                else:
                    continue
            clean_key = self.remove_color_codes(key)
            clean_value = self.remove_color_codes(value)
            if clean_key and clean_value:
                stats[clean_key] = clean_value

        if "Id" not in stats and "Username" not in stats:
            await ctx.send(f"Player '{username}' not found.")
            return

        wins = int(stats.get("Duels won", "0"))
        total_duels = int(stats.get("Total duels", "0"))
        losses = max(0, total_duels - wins)

        playtime = stats.get("Time", "N/A")
        if ":" in playtime and playtime != "N/A":
            hours = playtime.split(":")[0]
            playtime = f"{hours} Hrs"

        player_name = stats.get("Name", username)
        player_username = stats.get("Username", "N/A")
        try:
            player_name = player_name.encode().decode('utf-8', errors='replace')
        except (UnicodeEncodeError, UnicodeDecodeError):
            player_name = ''.join(c for c in player_name if ord(c) < 128)
        embed_title = f"Player Stats for {player_name} *({player_username})*"
        embed = discord.Embed(
            title=embed_title,
            color=discord.Color.blue()
        )
        embed.description = "\n"

        embed.add_field(name="⏱️ Playtime", value=playtime, inline=True)
        embed.add_field(name="🔼 Level", value=stats.get("Level", "N/A"), inline=True)
        embed.add_field(name="🛡️ Profession", value=stats.get("Profession", "N/A"), inline=True)
        embed.add_field(name="💰 Credits", value=stats.get("Credits", "N/A"), inline=True)
        embed.add_field(name="💼 Stashes", value=stats.get("Stashes", "N/A"), inline=True)
        embed.add_field(name="🏆 Duel Score", value=stats.get("Score", "N/A"), inline=True)
        embed.add_field(name="⚔️ Duels Won", value=str(wins), inline=True)
        embed.add_field(name="⚔️ Duels Lost", value=str(losses), inline=True)
        embed.add_field(name="🗡️ Total Kills", value=stats.get("Kills", "0"), inline=True)

        last_login = stats.get("Last login", "N/A")
        embed.set_footer(text=f"Last Login: {last_login}")

        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages from Discord and send them to the game server via RCON."""
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        prefix = await self.bot.command_prefix(self.bot, message)
        if isinstance(prefix, (tuple, list)):
            prefix = prefix[0]
        else:
            prefix = str(prefix)

        discord_username = message.author.display_name
        discord_username = discord_username.replace("’", "'").replace("‘", "'")
        discord_username = discord_username.replace("“", "\"").replace("”", "\"")
        discord_username = discord_username.replace("«", "\"").replace("»", "\"")
        discord_username = discord_username.replace("–", "-").replace("—", "-")
        discord_username = discord_username.replace("…", "...")
        
        message_content = message.content
        for member in message.mentions:
            mention_str = f"<@{member.id}>"
            if mention_str in message_content:
                message_content = message_content.replace(mention_str, f"@{member.display_name}")
            nick_mention_str = f"<@!{member.id}>"
            if nick_mention_str in message_content:
                message_content = message_content.replace(nick_mention_str, f"@{member.display_name}")

        message_content = message_content.replace("’", "'").replace("‘", "'")
        message_content = message_content.replace("“", "\"").replace("”", "\"")
        message_content = message_content.replace("«", "\"").replace("»", "\"")
        message_content = message_content.replace("–", "-").replace("—", "-")
        message_content = message_content.replace("…", "...")

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
            split_point = remaining.rfind(' ', 0, current_max_length + 1)
            if split_point == -1:
                split_point = current_max_length
            chunk = remaining[:split_point].strip()
            chunks.append(chunk)
            remaining = remaining[split_point:].strip()
            is_first_chunk = False

        if not await self.validate_rcon_settings():
            await message.channel.send("RCON settings not fully configured. Please contact an admin.")
            return
        
        try:
            for i, chunk in enumerate(chunks):
                if i == 0:
                    server_command = f"{initial_prefix}{chunk}"
                else:
                    server_command = f"{continuation_prefix}{chunk}"
                await self.bot.loop.run_in_executor(self.executor, self.send_rcon_command, server_command, await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password())
                await asyncio.sleep(0.1)
        except Exception as e:
            await message.channel.send(f"Failed to send to game: {e}")

    def replace_emojis_with_names(self, text):
        """Replace custom Discord emojis with :name: and convert standard Unicode emojis."""
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        emoji_map = {
            "😊": ":)", "😄": ":D", "😂": "XD", "🤣": "xD", "😉": ";)", "😛": ":P", "😢": ":(", "😡": ">:(",
            "👍": ":+1:", "👎": ":-1:", "❤️": "<3", "💖": "<3", "😍": ":*", "🙂": ":)", "😣": ":S", "😜": ";P",
            "😮": ":o", "😁": "=D", "😆": "xD", "😳": "O.o", "🤓": "B)", "😴": "-_-", "😅": "^^;", "😒": ":/",
            "😘": ":*", "😎": "8)", "😱": "D:", "🤔": ":?", "🥳": "\\o/", "🤗": ">^.^<", "🤪": ":p"
        }
        for unicode_emoji, text_emote in emoji_map.items():
            text = text.replace(unicode_emoji, text_emote)
        return text

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
        sock.settimeout(5)
        packet = b'\xff\xff\xff\xffrcon ' + password.encode() + b' ' + command.encode()
        try:
            sock.sendto(packet, (host, port))
            response, _ = sock.recvfrom(4096)
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
        """Monitor the qconsole.log file for chat, duel events, and server restarts."""
        self.monitoring = True
        log_file = os.path.join(await self.config.log_base_path(), "qconsole.log")
        logger.debug(f"Monitoring log file: {log_file}")

        while self.monitoring:
            try:
                log_base_path = await self.config.log_base_path()
                channel_id = await self.config.discord_channel_id()
                custom_emoji = await self.config.custom_emoji()
                if not all([log_base_path, channel_id, custom_emoji]):
                    logger.warning(f"Missing configuration: log_base_path={log_base_path}, channel_id={channel_id}, custom_emoji={custom_emoji}")
                    await asyncio.sleep(5)
                    continue

                channel = self.bot.get_channel(channel_id)
                if not channel:
                    logger.warning(f"Channel not found for ID: {channel_id}")
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
                        logger.debug(f"Read log line: {line}")
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message and not self.url_pattern.search(message):
                                message = self.replace_text_emotes_with_emojis(message)
                                discord_message = f"{custom_emoji} **{player_name}**: {message}"
                                if channel:
                                    await channel.send(discord_message)
                        elif "duel:" in line and "won a duel against" in line:
                            parts = line.split("duel:")[1].split("won a duel against")
                            if len(parts) == 2 and channel:
                                winner = self.remove_color_codes(parts[0].strip())
                                loser = self.remove_color_codes(parts[1].strip())
                                winner_id = loser_id = "Unknown"
                                for cid, (name, _) in self.client_names.items():
                                    if name == winner:
                                        winner_id = cid
                                    elif name == loser:
                                        loser_id = cid
                                await channel.send(f"<a:peepoBeatSaber:1228624251800522804> **{winner} (ID: {winner_id})** won a duel against **{loser} (ID: {loser_id})**!")
                                logger.debug(f"Duel win: {winner} (ID: {winner_id}) vs {loser} (ID: {loser_id})")
                        elif "------ Server Initialization ------" in line:
                            self.is_restarting = True
                            self.client_names.clear()
                            self.previous_client_names.clear()
                            self.last_seen.clear()
                            self.recent_joins.clear()
                            if channel:
                                await channel.send("⚠️ **Standby**: Server integration suspended while map changes or server restarts.")
                            logger.debug("Server restart/map change detected")
                            self.bot.loop.create_task(self.reset_restart_flag(channel))
                        elif "Server: " in line and self.is_restarting:
                            self.restart_map = line.split("Server: ")[1].strip()
                            logger.debug(f"New map detected: {self.restart_map}")
                        elif "ClientBegin:" in line and self.is_restarting:
                            await asyncio.sleep(10)
                            if channel and self.restart_map:
                                await channel.send(f"✅ **Server Integration Resumed**: Map {self.restart_map} loaded.")
                            self.is_restarting = False
                            self.restart_map = None
                            logger.debug("Server restart/map change completed")
            except Exception as e:
                logger.error(f"Error in monitor_log: {e}")
                await asyncio.sleep(5)

    async def reset_restart_flag(self, channel):
        """Reset the restart flag after 30 seconds if no ClientBegin occurs."""
        await asyncio.sleep(30)
        if self.is_restarting:
            self.is_restarting = False
            self.restart_map = None
            if channel:
                await channel.send("✅ **Server Integration Resumed**: Restart timed out, resuming normal operation.")
            logger.debug("Restart flag reset due to timeout")

    def start_monitoring(self):
        """Start the log monitoring task if it's not already running."""
        if not self.monitor_task or self.monitor_task.done():
            self.monitor_task = self.bot.loop.create_task(self.monitor_log())

    def start_refresh_loop(self):
        """Start the player data refresh loop if it's not already running."""
        if not self.refresh_task or self.refresh_task.done():
            self.refresh_task = self.bot.loop.create_task(self.refresh_loop())

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
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
        if self.restart_task and not self.restart_task.done():
            self.restart_task.cancel()
            try:
                await self.restart_task
            except asyncio.CancelledError:
                pass
        self.executor.shutdown(wait=False)

    @commands.command(name="jkexec")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkexec(self, ctx, filename: str):
        """Execute a server config file via RCON (Bot Owners/Admins only)."""
        if not await self.validate_rcon_settings():
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"exec {filename}", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            await ctx.send(f"Executed configuration file: {filename}")
        except Exception as e:
            await ctx.send(f"Failed to execute {filename}: {e}")

    async def schedule_daily_restart(self):
        """Schedule daily restart announcements and server restart at midnight."""
        while True:
            now = datetime.now()
            next_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_seconds = (next_midnight - now).total_seconds()

            await asyncio.sleep(wait_seconds)

            if await self.validate_rcon_settings() and await self.config.discord_channel_id():
                channel = self.bot.get_channel(await self.config.discord_channel_id())
                if channel:
                    await channel.send("⚠️ **Server Restart Warning**: The server will restart in 1 minute as part of the daily reset.")
                await self.bot.loop.run_in_executor(
                    self.executor, self.send_rcon_command, "say ^1Server will restart in 1 minute for daily reset!",
                    await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
                )

            await asyncio.sleep(30)

            if await self.validate_rcon_settings() and await self.config.discord_channel_id():
                channel = self.bot.get_channel(await self.config.discord_channel_id())
                if channel:
                    await channel.send("⏰ **Server Restart**: 30 seconds remaining until restart.")
                await self.bot.loop.run_in_executor(
                    self.executor, self.send_rcon_command, "say ^1Server restarting in 30 seconds!",
                    await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
                )

            await asyncio.sleep(30)

            if await self.validate_rcon_settings():
                try:
                    server_executable = await self.config.server_executable()
                    subprocess.run(["taskkill", "/IM", server_executable, "/F"], check=True)
                    await asyncio.sleep(10)

                    start_batch_file = await self.config.start_batch_file()
                    subprocess.run(["start", "", start_batch_file], shell=True, check=True)
                    await asyncio.sleep(10)

                    log_base_path = await self.config.log_base_path()
                    log_file = os.path.join(log_base_path, "qconsole.log")
                    if os.path.exists(log_file):
                        self.monitoring = False
                        if self.monitor_task and not self.monitor_task.done():
                            self.monitor_task.cancel()
                            try:
                                await self.monitor_task
                            except asyncio.CancelledError:
                                pass
                        if self.refresh_task and not self.refresh_task.done():
                            self.refresh_task.cancel()
                            try:
                                await self.refresh_task
                            except asyncio.CancelledError:
                                pass
                        self.monitoring = True
                        self.start_monitoring()
                        self.start_refresh_loop()
                        if await self.config.discord_channel_id():
                            channel = self.bot.get_channel(await self.config.discord_channel_id())
                            if channel:
                                await channel.send("✅ **Server Restart Successful!**")
                except subprocess.CalledProcessError as e:
                    if await self.config.discord_channel_id():
                        channel = self.bot.get_channel(await self.config.discord_channel_id())
                        if channel:
                            await channel.send(f"❌ **Restart Failed**: Error shutting down or starting server - {e}.")
                except Exception as e:
                    if await self.config.discord_channel_id():
                        channel = self.bot.get_channel(await self.config.discord_channel_id())
                        if channel:
                            await channel.send(f"❌ **Restart Failed**: Unexpected error - {e}.")

async def setup(bot):
    """Set up the JKChatBridge cog when the bot loads."""
    cog = JKChatBridge(bot)
    await bot.add_cog(cog)