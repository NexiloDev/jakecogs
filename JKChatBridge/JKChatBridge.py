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
import queue

# Custom handler for Discord logging
class DiscordLogHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        msg = self.format(record)
        self.log_queue.put(msg)

class JKChatBridge(commands.Cog):
    __version__ = "1.0.23"
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
            start_batch_file="C:\\GameServers\\StarWarsJKA\\GameData\\start_jka_server.bat",
            log_channel_id=None  # Config for log channel
        )
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.monitoring = False
        self.monitor_task = None
        self.log_task = None  # Task for sending logs
        self.client_names = {}  # {client_id: (name, username)}
        self.client_teams = {}  # {client_id: team}
        self.url_pattern = re.compile(
            r'(https?://[^\s]+|www\.[^\s]+|\b[a-zA-Z0-9-]+\.(com|org|net|edu|gov|io|co|uk|ca|de|fr|au|us|ru|ch|it|nl|se|no|es|mil)(/[^\s]*)?)',
            re.IGNORECASE
        )
        self.is_restarting = False
        self.restart_map = None
        self.restart_completion_time = None

        # Logging setup
        self.logger = logging.getLogger("JKChatBridge")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.log_queue = queue.Queue()
        handler = DiscordLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(handler)

        self.start_monitoring()

    async def cog_load(self):
        self.logger.debug("Cog loaded.")
        self.log_task = self.bot.loop.create_task(self.send_logs())

    async def send_logs(self):
        """Background task to send logs to Discord with markdown formatting."""
        while True:
            try:
                msg = await self.bot.loop.run_in_executor(None, self.log_queue.get)
                log_channel_id = await self.config.log_channel_id()
                if log_channel_id:
                    channel = self.bot.get_channel(log_channel_id)
                    if channel:
                        # Format log with markdown
                        parts = msg.split(' - ', 2)
                        if len(parts) == 3:
                            timestamp, level, log_msg = parts
                            formatted_msg = f"**{level}** - ```log\n{log_msg}\n```"
                        else:
                            formatted_msg = f"```log\n{msg}\n```"
                        if len(formatted_msg) > 1900:
                            formatted_msg = formatted_msg[:1900] + "... [truncated]\n```"
                        await channel.send(formatted_msg)
                    else:
                        print(msg)  # Fallback to console
                else:
                    print(msg)  # Fallback to console
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error sending log: {e}")

    async def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.monitoring = False
        for task in [self.monitor_task, self.log_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self.executor.shutdown(wait=False)

    async def refresh_player_data(self, join_name=None):
        """Refresh player data using rcon status (primary) and playerlist (refinement)."""
        if not await self.validate_rcon_settings():
            self.logger.warning("RCON settings not configured, skipping refresh_player_data.")
            return

        try:
            status_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "status", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            status_text = status_response.decode(errors='replace')
            self.logger.debug(f"RAW status response in refresh_player_data:\n{status_text}")
            status_data = {}
            parsing_players = False
            for line in status_text.splitlines():
                if "score ping" in line:
                    parsing_players = True
                    continue
                if parsing_players and line.strip():
                    if len(line) >= 38:
                        client_id = line[0:2].strip()
                        if client_id.isdigit():
                            name = line[14:29].strip()
                            player_name = self.remove_color_codes(name)
                            status_data[client_id] = player_name
                            self.logger.debug(f"Parsed from status: ID={client_id}, Name={player_name}")

            await asyncio.sleep(1)

            playerlist_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "playerlist", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
            )
            playerlist_text = playerlist_response.decode(errors='replace')
            self.logger.debug(f"RAW playerlist response in refresh_player_data:\n{playerlist_text}")
            playerlist_data = {}
            for line in playerlist_text.splitlines():
                line = line.strip()
                if not line or "Credits in the world" in line or "Total number of registered accounts" in line or "Ind Player" in line or "----" in line:
                    continue
                parts = re.split(r"\s+", line)
                if len(parts) >= 3 and parts[0].startswith("^") and self.remove_color_codes(parts[0]).isdigit():
                    client_id = self.remove_color_codes(parts[0])
                    name_end = len(parts)
                    for i in range(1, len(parts)):
                        if parts[i].isdigit() or parts[i] == "****":
                            name_end = i
                            break
                    name_parts = parts[1:name_end]
                    full_name = self.remove_color_codes(" ".join(name_parts))
                    username = parts[-1] if len(parts) > name_end and not parts[-1].isdigit() else None
                    playerlist_data[client_id] = (full_name, username)
                    self.logger.debug(f"Parsed from playerlist: ID={client_id}, Name={full_name}, Username={username}")

            for client_id, status_name in status_data.items():
                pl_name, username = playerlist_data.get(client_id, (status_name, None))
                final_name = pl_name if "padawan" not in pl_name.lower() else status_name
                self.client_names[client_id] = (final_name, username)
                self.logger.debug(f"Stored in client_names: ID={client_id}, Name={final_name}, Username={username}")

            if join_name:
                join_name_clean = self.remove_color_codes(join_name)
                for client_id, status_name in status_data.items():
                    if join_name_clean == self.remove_color_codes(status_name):
                        pl_name, username = playerlist_data.get(client_id, (status_name, None))
                        final_name = pl_name if "padawan" not in pl_name.lower() else status_name
                        self.client_names[client_id] = (final_name, username)
                        self.logger.debug(f"Join name matched: ID={client_id}, Name={final_name}, Username={username}")
                        break

        except Exception as e:
            self.logger.error(f"Error in refresh_player_data: {e}")

    async def validate_rcon_settings(self):
        """Check if RCON settings are fully configured."""
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
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for debug logs."""
        await self.config.log_channel_id.set(channel.id)
        await ctx.send(f"Log channel set to: {channel.name} (ID: {channel.id})")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        channel = self.bot.get_channel(await self.config.discord_channel_id()) if await self.config.discord_channel_id() else None
        log_channel = self.bot.get_channel(await self.config.log_channel_id()) if await self.config.log_channel_id() else None
        settings_message = (
            f"**Current Settings:**\n"
            f"Log Base Path: {await self.config.log_base_path() or 'Not set'}\n"
            f"Discord Channel: {channel.name if channel else 'Not set'} (ID: {await self.config.discord_channel_id() or 'Not set'})\n"
            f"Log Channel: {log_channel.name if log_channel else 'Not set'} (ID: {await self.config.log_channel_id() or 'Not set'})\n"
            f"RCON Host: {await self.config.rcon_host() or 'Not set'}\n"
            f"RCON Port: {await self.config.rcon_port() or 'Not set'}\n"
            f"RCON Password: {'Set' if await self.config.rcon_password() else 'Not set'}\n"
            f"Custom Emoji: {await self.config.custom_emoji() or 'Not set'}\n"
            f"Server Executable: {await self.config.server_executable() or 'Not set'}\n"
            f"Start Batch File: {await self.config.start_batch_file() or 'Not set'}"
        )
        await ctx.send(settings_message)

    @jkbridge.command()
    async def reloadmonitor(self, ctx):
        """Force reload the log monitoring task."""
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            try:
                await self.monitor_task
                self.logger.info("Monitoring task canceled successfully.")
            except asyncio.CancelledError:
                self.logger.info("Monitoring task canceled successfully.")
            except Exception as e:
                self.logger.error(f"Error canceling task: {e}")

        await asyncio.sleep(1)

        self.client_names.clear()
        self.client_teams.clear()
        self.is_restarting = False
        self.restart_map = None
        self.restart_completion_time = None

        self.start_monitoring()

        await ctx.send("Log monitoring task reloaded.")

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
            status_text = status_response.decode(errors='replace')
            self.logger.debug(f"RAW status response in jkstatus:\n{status_text}")
            status_lines = status_text.splitlines()

            server_name = "Unknown"
            mod_name = "Unknown"
            map_name = "Unknown"
            player_count = "0 humans, 0 bots"

            for line in status_lines:
                if "hostname:" in line:
                    server_name = self.remove_color_codes(line.split("hostname:")[1].strip()).encode('ascii', 'ignore').decode()
                elif "game    :" in line:
                    mod_name = line.split("game    :")[1].strip()
                elif "map     :" in line:
                    map_name = line.split("map     :")[1].split()[0].strip()
                elif "players :" in line:
                    player_count = line.split("players :")[1].strip()

            players = [(cid, f"{self.client_names[cid][0]}{' (' + self.client_names[cid][1] + ')' if self.client_names[cid][1] else ''}")
                       for cid in self.client_names.keys()]
            player_list = "No players online" if not players else "```\n" + "\n".join(f"{cid:<3} {name}" for cid, name in players) + "\n```"

            embed = discord.Embed(title=f"🌌 {server_name} 🌌", color=discord.Color.gold())
            embed.add_field(name="👥 Players", value=f"{player_count}", inline=True)
            embed.add_field(name="🗺️ Map", value=f"`{map_name}`", inline=True)
            embed.add_field(name="🎮 Mod", value=f"{mod_name}", inline=True)
            embed.add_field(name="📋 Online Players", value=player_list, inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Error in jkstatus: {e}")
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
        """Monitor qconsole.log for events and trigger actions, excluding specific lines."""
        self.monitoring = True
        log_file = os.path.join(await self.config.log_base_path(), "qconsole.log")
        self.logger.debug(f"Monitoring log file: {log_file}")

        while self.monitoring:
            try:
                channel_id = await self.config.discord_channel_id()
                custom_emoji = await self.config.custom_emoji()
                if not all([await self.config.log_base_path(), channel_id, custom_emoji]):
                    self.logger.warning("Missing configuration, pausing monitor.")
                    await asyncio.sleep(5)
                    continue

                channel = self.bot.get_channel(channel_id)
                if not channel:
                    self.logger.warning(f"Channel not found: {channel_id}")
                    await asyncio.sleep(5)
                    continue

                if not os.path.exists(log_file):
                    self.logger.error(f"Log file not found: {log_file}")
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

                        # Exclude specific log lines
                        if line.strip() == "" or \
                        ("SV packet" in line and ": rcon" in line) or \
                        ("SV packet" in line and ("getstatus" in line or "getinfo" in line)) or \
                        line.startswith("setteam:") or \
                        ("clientCommand:" in line and ("login" in line or "score" in line)) or \
                        "*****************************Weapon Log:" in line or \
                        "------------------------------------------------------------" in line or \
                        ("Damage:" in line and "Kills:" in line) or \
                        ("Pickups:" in line and "Deaths:" in line) or \
                        line.startswith("Loading account:") or \
                        line.startswith("Can't find models/") or \
                        "ERROR: Server tried to modelindex" in line or \
                        "WARNING: CM_AddFacetBevels" in line or \
                        ("Object" in line and "touching" in line and "areas at" in line) or \
                        line.startswith("Can't find maps/") or \
                        "CM_LoadMap" in line:
                            continue  # Skip these lines

                        self.logger.debug(f"Log line: {line}")

                        # Chat message handling
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message and not self.url_pattern.search(message):
                                message = self.replace_text_emotes_with_emojis(message)
                                await channel.send(f"{custom_emoji} **{player_name}**: {message}")

                        # Duel event handling
                        elif "duel:" in line and "won a duel against" in line:
                            parts = line.split("duel:")[1].split("won a duel against")
                            if len(parts) == 2:
                                winner = self.remove_color_codes(parts[0].strip())
                                loser = self.remove_color_codes(parts[1].strip())
                                await channel.send(f"<a:peepoBeatSaber:1228624251800522804> **{winner}** won a duel against **{loser}**!")

                        # Server shutdown/restart handling
                        elif "ShutdownGame:" in line and not self.is_restarting:
                            self.is_restarting = True
                            self.client_names.clear()
                            self.client_teams.clear()
                            await channel.send("⚠️ **Standby**: Server integration suspended while map changes or server restarts.")
                            self.logger.debug("Server shutdown detected")
                            self.bot.loop.create_task(self.reset_restart_flag(channel))
                        elif "------ Server Initialization ------" in line and not self.is_restarting:
                            self.is_restarting = True
                            self.client_names.clear()
                            self.client_teams.clear()
                            await channel.send("⚠️ **Standby**: Server integration suspended while map changes or server restarts.")
                            self.logger.debug("Server initialization detected")
                            self.bot.loop.create_task(self.reset_restart_flag(channel))

                        # Map change handling
                        elif "Server: " in line and self.is_restarting:
                            self.restart_map = line.split("Server: ")[1].strip()
                            self.logger.debug(f"New map detected: {self.restart_map}")
                            await asyncio.sleep(10)
                            if self.restart_map:
                                await channel.send(f"✅ **Server Integration Resumed**: Map {self.restart_map} loaded.")
                            self.is_restarting = False
                            self.restart_map = None
                            self.logger.debug("Server restart/map change completed")

                        # Player join handling
                        elif "Going from CS_CONNECTED to CS_PRIMED for" in line:
                            join_name = line.split("Going from CS_CONNECTED to CS_PRIMED for ")[1].strip()
                            join_name_clean = self.remove_color_codes(join_name)
                            if not join_name_clean.endswith("-Bot") and not self.is_restarting:
                                await channel.send(f"<:jk_connect:1349009924306374756> **{join_name_clean}** has joined the game!")
                                self.logger.debug(f"Join detected: {join_name_clean}")
                            await asyncio.sleep(2)
                            await self.refresh_player_data(join_name=join_name)

                        # Player login handling
                        elif "has logged in" in line:
                            await self.refresh_player_data()
                            self.logger.debug("Login detected, player data refreshed")

                        # Player logout handling
                        elif "has logged out" in line:
                            self.logger.debug("Logout detected, keeping stored name")

                        # Player disconnect handling
                        elif "disconnected" in line:
                            match = re.search(r"info:\s*(.+?)\s*disconnected\s*\((\d+)\)", line)
                            if match:
                                name = match.group(1)
                                client_id = match.group(2)
                                name_clean = self.remove_color_codes(name)
                                if not self.is_restarting and not name_clean.endswith("-Bot") and name_clean.strip():
                                    await channel.send(f"<:jk_disconnect:1349010016044187713> **{name_clean}** has disconnected.")
                                self.logger.debug(f"Disconnect detected: {name_clean} (ID: {client_id})")
                                if client_id in self.client_names:
                                    del self.client_names[client_id]
                                if client_id in self.client_teams:
                                    del self.client_teams[client_id]

                        # Team update handling
                        elif "ClientUserinfoChanged:" in line:
                            match = re.search(r"ClientUserinfoChanged: (\d+) (.*)", line)
                            if match:
                                client_id, userinfo = match.group(1), match.group(2)
                                team_match = re.search(r"\\t\\(\d+)", userinfo)
                                if team_match:
                                    self.client_teams[client_id] = int(team_match.group(1))

            except Exception as e:
                self.logger.error(f"Error in monitor_log: {e}")
                await asyncio.sleep(5)

    async def reset_restart_flag(self, channel):
        """Reset the restart flag after 30 seconds if no map change occurs."""
        await asyncio.sleep(30)
        if self.is_restarting:
            self.is_restarting = False
            self.restart_map = None
            await channel.send("✅ **Server Integration Resumed**: Restart timed out, resuming normal operation.")
            self.logger.debug("Restart flag reset due to timeout")

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

async def setup(bot):
    """Set up the JKChatBridge cog when the bot loads."""
    await bot.add_cog(JKChatBridge(bot))