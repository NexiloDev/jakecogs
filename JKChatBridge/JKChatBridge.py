import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import os
import socket
from concurrent.futures import ThreadPoolExecutor
import re
from datetime import datetime

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord via RCON, with dynamic log file support for Lugormod.

    **Commands:**
    - `!jkstatus`: Display detailed server status with emojis. Accessible to all users.
      **Usage:** `!jkstatus`
    - `!jkplayer <username>`: Display player stats for the given username. Accessible to all users.
      **Usage:** `!jkplayer <username>` **Example:** `!jkplayer Padawan`
    - `!jkexec <filename>`: Execute a server config file via RCON (Bot Owners/Admins only).
      **Usage:** `!jkexec <filename>` **Example:** `!jkexec server.cfg`
    """

    def __init__(self, bot):
        # Store the bot instance so I can use it throughout the class
        self.bot = bot
        # Set up configuration for storing settings like RCON details and Discord channel ID
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_base_path=None,
            discord_channel_id=None,
            rcon_host="127.0.0.1",
            rcon_port=29070,
            rcon_password=None,
            custom_emoji="<:jk:1219115870928900146>"
        )
        # Create a thread pool to handle RCON commands without blocking the bot
        self.executor = ThreadPoolExecutor(max_workers=2)
        # Flag to control the log monitoring loop
        self.monitoring = False
        # Variable to hold the monitoring task
        self.monitor_task = None
        # Dictionary to store client IDs mapped to their names and usernames
        self.client_names = {}  # Format: {client_id: (name, username)}
        # Track the most recent client ID that connected
        self.last_connected_client = None
        # Regex pattern to detect URLs in messages (to block them)
        self.url_pattern = re.compile(
            r'(https?://[^\s]+|www\.[^\s]+|\b[a-zA-Z0-9-]+\.(com|org|net|edu|gov|io|co|uk|ca|de|fr|au|us|ru|ch|it|nl|se|no|es|mil)(/[^\s]*)?)',
            re.IGNORECASE
        )
        # List of commands to filter out from being sent to the game
        self.filtered_commands = {"jkstatus", "jkbridge", "jk"}
        # Start monitoring the game log file for chat and events
        self.start_monitoring()

    async def cog_load(self):
        """Run after the bot is fully ready to fetch initial player data."""
        await self.fetch_player_data()

    async def fetch_player_data(self, ctx=None):
        """Fetch player data (ID, name, username) from the game server using the RCON 'playerlist' command."""
        # Get RCON settings from the config
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            return  # Can't proceed without RCON settings

        # Skip RCON command if called from a command context (e.g., jkstatus)
        if ctx:
            return

        try:
            # Send the 'playerlist' command to the game server
            playerlist_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "playerlist", rcon_host, rcon_port, rcon_password
            )
            temp_client_names = {}
            # Parse each line of the playerlist response
            for line in playerlist_response.decode(errors='replace').splitlines():
                # Skip irrelevant lines (like summary stats)
                if "Credits in the world" in line or "Total number of registered accounts" in line or "Ind Player" in line or "----" in line:
                    continue
                parts = re.split(r"\s+", line.strip())
                # Check if the line has enough parts and the first part (client ID) starts with a color code
                if len(parts) >= 6 and parts[0].startswith("^") and self.remove_color_codes(parts[0]).isdigit():
                    client_id = self.remove_color_codes(parts[0])
                    player_name = self.remove_color_codes(parts[1])
                    # Last part is the username if it's not a number
                    username = parts[-1] if parts[-1].isalpha() or not parts[-1].isdigit() else None
                    temp_client_names[client_id] = (player_name, username)
            # Update self.client_names, preserving the name if it already exists
            for client_id, (name, username) in temp_client_names.items():
                if client_id in self.client_names:
                    # Keep the existing name, only update the username
                    existing_name, _ = self.client_names[client_id]
                    self.client_names[client_id] = (existing_name, username)
                else:
                    # Add new entry if client_id doesn't exist
                    self.client_names[client_id] = (name, username)
        except Exception as e:
            pass  # Silently fail if fetching player data fails

    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (also available as 'jk'). Restricted to bot owner."""
        pass

    @jkbridge.command()
    async def setlogbasepath(self, ctx, path: str):
        """Set the base path for Lugormod log files (e.g., C:\\GameServers\\StarWarsJKA\\GameData\\lugormod\\logs)."""
        await self.config.log_base_path.set(path)
        await ctx.send(f"Log base path set to: {path}")

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
        """Set the custom emoji for game-to-Discord chat messages (e.g., <:jk:1219115870928900146>)."""
        await self.config.custom_emoji.set(emoji)
        await ctx.send(f"Custom emoji set to: {emoji}")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        # Retrieve all settings from the config
        log_base_path = await self.config.log_base_path()
        discord_channel_id = await self.config.discord_channel_id()
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        custom_emoji = await self.config.custom_emoji()
        # Get the channel name if a channel ID is set
        channel_name = "Not set"
        if discord_channel_id:
            channel = self.bot.get_channel(discord_channel_id)
            channel_name = channel.name if channel else "Unknown channel"
        # Format the settings into a message
        settings_message = (
            f"**Current Settings:**\n"
            f"Log Base Path: {log_base_path or 'Not set'}\n"
            f"Discord Channel: {channel_name} (ID: {discord_channel_id or 'Not set'})\n"
            f"RCON Host: {rcon_host or 'Not set'}\n"
            f"RCON Port: {rcon_port or 'Not set'}\n"
            f"RCON Password: {'Set' if rcon_password else 'Not set'}\n"
            f"Custom Emoji: {custom_emoji or 'Not set'}"
        )
        await ctx.send(settings_message)

    @jkbridge.command()
    async def reloadmonitor(self, ctx):
        """Force reload the log monitoring task and refresh player data."""
        # Stop the current monitoring task if it's running
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        # Clear the client names and restart monitoring
        self.client_names.clear()
        self.start_monitoring()
        await self.fetch_player_data(ctx)
        await ctx.send("Log monitoring task and player data reloaded.")

    @commands.command(name="jkstatus")
    async def status(self, ctx):
        """Display detailed server status with emojis. Accessible to all users.

        **Usage:** `!jkstatus`
        """
        # Get RCON settings
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        try:
            # Fetch player data to ensure client_names is up-to-date
            await self.fetch_player_data(ctx)
            # Send the 'status' command to the game server
            status_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "status", rcon_host, rcon_port, rcon_password
            )
            status_lines = status_response.decode(errors='replace').splitlines()

            # Default values for server info
            server_name = "Unknown"
            mod_name = "Unknown"
            map_name = "Unknown"
            player_count = "0 humans, 0 bots"

            # Parse the status response to extract server details
            for line in status_lines:
                if "hostname:" in line:
                    server_name = self.remove_color_codes(line.split("hostname:")[1].strip()).replace("Ç", "").encode().decode('ascii', 'ignore')
                elif "game    :" in line:
                    mod_name = line.split("game    :")[1].strip()
                elif "map     :" in line:
                    map_name = line.split("map     :")[1].split()[0].strip()
                elif "players :" in line:
                    player_count = line.split("players :")[1].strip()

            # Build a list of online players
            players = [(cid, f"{self.client_names[cid][0]}{'(' + self.client_names[cid][1] + ')' if self.client_names[cid][1] else ''}")
                       for cid in self.client_names.keys()]
            player_list = "No players online"
            if players:
                player_lines = [f"{client_id:<3} {name_with_username}" for client_id, name_with_username in players]
                player_list = "```\n" + "\n".join(player_lines) + "\n```"

            # Create an embed to display the server status
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
            await ctx.send(f"Failed to retrieve server status: {e}")

    @commands.command(name="jkplayer")
    async def player_info(self, ctx, username: str):
        """Display player stats for the given username. Accessible to all users.

        **Usage:** `!jkplayer <username>` **Example:** `!jkplayer Padawan`
        """
        # Get RCON settings
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        # Send the 'accountinfo' command to get player stats
        command = f"accountinfo {username}"
        try:
            response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, command, rcon_host, rcon_port, rcon_password
            )
            # Try decoding the response with different encodings to handle special characters
            try:
                response_text = response.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    response_text = response.decode('latin-1')
                except UnicodeDecodeError:
                    response_text = response.decode('cp1252', errors='replace')
            response_lines = response_text.splitlines()
        except Exception as e:
            await ctx.send(f"Failed to retrieve player info: {e}")
            return

        # Parse the response into a dictionary
        stats = {}
        timestamp_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}')
        for line in response_lines:
            line = line.strip()
            if timestamp_pattern.match(line) or line.startswith('\xff\xff\xff\xffprint'):
                continue  # Skip timestamp lines and initial print marker
            if ":" in line:
                # Handle lines with a colon (e.g., "Duels won: 1159")
                key, value = map(str.strip, line.split(":", 1))
            else:
                # Handle lines without a colon (e.g., "Total duels    1934")
                parts = re.split(r'\s{2,}', line)  # Split on two or more spaces
                if len(parts) >= 2:
                    key = parts[0]
                    value = parts[-1]
                else:
                    continue  # Skip lines that don’t have a key-value pair
            clean_key = self.remove_color_codes(key)
            clean_value = self.remove_color_codes(value)
            if clean_key and clean_value:
                stats[clean_key] = clean_value

        # Check if the player exists by looking for 'Id' or 'Username'
        if "Id" not in stats and "Username" not in stats:
            await ctx.send(f"Player '{username}' not found.")
            return

        # Calculate duels lost (Total duels - Duels won)
        wins = int(stats.get("Duels won", "0"))
        total_duels = int(stats.get("Total duels", "0"))
        losses = max(0, total_duels - wins)  # Ensure no negative losses

        # Format playtime to show only hours
        playtime = stats.get("Time", "N/A")
        if ":" in playtime and playtime != "N/A":
            hours = playtime.split(":")[0]
            playtime = f"{hours} Hrs"

        # Create the embed with the player's stats
        player_name = stats.get("Name", username)
        player_username = stats.get("Username", "N/A")
        # Ensure the player_name is properly encoded for Discord
        try:
            player_name = player_name.encode().decode('utf-8', errors='replace')
        except (UnicodeEncodeError, UnicodeDecodeError):
            player_name = ''.join(c for c in player_name if ord(c) < 128)  # Fallback to ASCII
        embed_title = f"Player Stats for {player_name} *({player_username})*"
        embed = discord.Embed(
            title=embed_title,
            color=discord.Color.blue()
        )
        embed.description = "\n"  # Blank line for separation

        # Add fields to the embed for each stat
        embed.add_field(name="⏱️ Playtime", value=playtime, inline=True)
        embed.add_field(name="🔼 Level", value=stats.get("Level", "N/A"), inline=True)
        embed.add_field(name="🛡️ Profession", value=stats.get("Profession", "N/A"), inline=True)
        embed.add_field(name="💰 Credits", value=stats.get("Credits", "N/A"), inline=True)
        embed.add_field(name="💼 Stashes", value=stats.get("Stashes", "N/A"), inline=True)
        embed.add_field(name="🏆 Duel Score", value=stats.get("Score", "N/A"), inline=True)
        embed.add_field(name="⚔️ Duels Won", value=str(wins), inline=True)
        embed.add_field(name="⚔️ Duels Lost", value=str(losses), inline=True)
        embed.add_field(name="🗡️ Total Kills", value=stats.get("Kills", "0"), inline=True)

        # Set footer with the player's last login time
        last_login = stats.get("Last login", "N/A")
        embed.set_footer(text=f"Last Login: {last_login}")

        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages from Discord and send them to the game server via RCON."""
        # Get the configured Discord channel ID
        channel_id = await self.config.discord_channel_id()
        # Ignore messages that aren't in the configured channel or are from bots
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        # Get the bot's command prefix
        prefix = await self.bot.command_prefix(self.bot, message)
        if isinstance(prefix, (tuple, list)):
            prefix = prefix[0]
        else:
            prefix = str(prefix)

        # Clean up the message content to handle special characters
        discord_username = message.author.display_name
        discord_username = discord_username.replace("’", "'").replace("‘", "'")
        discord_username = discord_username.replace("“", "\"").replace("”", "\"")
        discord_username = discord_username.replace("«", "\"").replace("»", "\"")
        discord_username = discord_username.replace("–", "-").replace("—", "-")
        discord_username = discord_username.replace("…", "...")
        
        message_content = message.content
        message_content = message_content.replace("’", "'").replace("‘", "'")
        message_content = message_content.replace("“", "\"").replace("”", "\"")
        message_content = message_content.replace("«", "\"").replace("»", "\"")
        message_content = message_content.replace("–", "-").replace("—", "-")
        message_content = message_content.replace("…", "...")

        # Replace Discord emojis with their names
        message_content = self.replace_emojis_with_names(message_content)

        # Block messages containing URLs
        if self.url_pattern.search(message_content):
            return

        # Prepare the message prefix for sending to the game
        initial_prefix = f"say ^5{{D}}^7{discord_username}^2: "
        continuation_prefix = "say "
        max_length = 115
        
        # Split the message into chunks if it's too long
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

        # Get RCON settings for sending the message
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            await message.channel.send("RCON settings not fully configured. Please contact an admin.")
            return
        
        try:
            # Send each chunk to the game server
            for i, chunk in enumerate(chunks):
                if i == 0:
                    server_command = f"{initial_prefix}{chunk}"
                else:
                    server_command = f"{continuation_prefix}{chunk}"
                await self.bot.loop.run_in_executor(self.executor, self.send_rcon_command, server_command, rcon_host, rcon_port, rcon_password)
                await asyncio.sleep(0.1)  # Small delay to avoid flooding
        except Exception as e:
            await message.channel.send(f"Failed to send to game: {e}")

    def replace_emojis_with_names(self, text):
        """Replace custom Discord emojis with :name: and remove standard Unicode emojis."""
        # Replace custom emojis with their names (e.g., :emoji_name:)
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        # Map Unicode emojis to text representations for game compatibility
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
        # Map text emotes to their emoji equivalents
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
        # Create a UDP socket for RCON communication
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        # Format the RCON packet
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
        """Remove Jedi Academy color codes (e.g., ^1, ^7) from text."""
        return re.sub(r'\^\d', '', text)

    async def monitor_log(self):
        """Monitor the latest Lugormod log file and send messages to Discord."""
        self.monitoring = True
        while self.monitoring:
            try:
                # Get settings for log monitoring
                log_base_path = await self.config.log_base_path()
                channel_id = await self.config.discord_channel_id()
                custom_emoji = await self.config.custom_emoji()
                if not log_base_path or not channel_id or not custom_emoji:
                    await asyncio.sleep(5)
                    continue

                # Get the Discord channel to send messages to
                channel = self.bot.get_channel(channel_id)

                # Determine the current log file based on the date
                now = datetime.now()
                current_date = f"{now.month}-{now.day}-{now.year}"
                log_file_path = os.path.join(log_base_path, f"games_{current_date}.log")

                # Open and monitor the log file
                async with aiofiles.open(log_file_path, mode='r') as f:
                    await f.seek(0, 2)  # Go to the end of the file
                    while self.monitoring:
                        line = await f.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        line = line.strip()
                        # Handle chat messages from the game
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message:
                                if self.url_pattern.search(message):
                                    continue
                                message = self.replace_text_emotes_with_emojis(message)
                                discord_message = f"{custom_emoji} **{player_name}**: {message}"
                                if channel:
                                    await channel.send(discord_message)
                        # Handle player connect events
                        elif "ClientConnect:" in line:
                            self.last_connected_client = line.split("ClientConnect: ")[1].strip()
                        elif "ClientUserinfoChanged handling info:" in line and self.last_connected_client:
                            client_id = line.split("ClientUserinfoChanged handling info: ")[1].split()[0]
                            if client_id == self.last_connected_client:
                                name_match = re.search(r"\\name\\([^\\]+)", line)
                                if name_match and "Padawan" not in name_match.group(1):
                                    player_name = self.remove_color_codes(name_match.group(1))
                                    self.client_names[client_id] = (player_name, None)
                                    name, username = self.client_names.get(client_id, (f"Unknown (ID {client_id})", None))
                                    join_message = f"<:jk_connect:1349009924306374756> **{name}** has joined the game!"
                                    if channel and not name.endswith("-Bot"):
                                        await channel.send(join_message)
                                    self.last_connected_client = None
                        elif "ClientUserinfoChanged:" in line and self.last_connected_client:
                            client_id = line.split("ClientUserinfoChanged: ")[1].split()[0]
                            if client_id == self.last_connected_client:
                                name_match = re.search(r"n\\([^\\]+)", line)
                                if name_match and "Padawan" not in name_match.group(1):
                                    player_name = self.remove_color_codes(name_match.group(1))
                                    self.client_names[client_id] = (player_name, None)
                                    name, username = self.client_names.get(client_id, (f"Unknown (ID {client_id})", None))
                                    join_message = f"<:jk_connect:1349009924306374756> **{name}** has joined the game!"
                                    if channel and not name.endswith("-Bot"):
                                        await channel.send(join_message)
                                    self.last_connected_client = None
                        # Handle player login events
                        elif "Player" in line and "has logged in" in line:
                            match = re.search(r'Player "([^"]+)" \(([^)]+)\) has logged in', line)
                            if match:
                                player_name = self.remove_color_codes(match.group(1))
                                username = match.group(2)
                                for cid, (name, _) in self.client_names.items():
                                    if name == player_name:
                                        self.client_names[cid] = (player_name, username)
                                        break
                            await self.fetch_player_data()
                        # Handle player logout events
                        elif "Player" in line and "has logged out" in line:
                            match = re.search(r'Player "([^"]+)" \(([^)]+)\) has logged out', line)
                            if match:
                                player_name = self.remove_color_codes(match.group(1))
                                for cid, (name, _) in self.client_names.items():
                                    if name == player_name:
                                        self.client_names[cid] = (name, None)
                                        break
                        # Handle player disconnect events
                        elif "ClientDisconnect:" in line:
                            client_id = line.split("ClientDisconnect: ")[1].strip()
                            name, _ = self.client_names.get(client_id, (f"Unknown (ID {client_id})", None))
                            leave_message = f"<:jk_disconnect:1349010016044187713> **{name}** has disconnected."
                            if channel and not name.endswith("-Bot"):
                                await channel.send(leave_message)
                            if client_id in self.client_names:
                                del self.client_names[client_id]
                        # Handle duel win events
                        elif "duel:" in line and "won a duel against" in line:
                            parts = line.split("duel:")[1].split("won a duel against")
                            if len(parts) == 2 and channel:
                                winner = self.remove_color_codes(parts[0].strip())
                                loser = self.remove_color_codes(parts[1].strip())
                                await channel.send(f"<a:peepoBeatSaber:1228624251800522804> **{winner}** won a duel against **{loser}**!")
            except FileNotFoundError:
                await asyncio.sleep(5)
            except Exception as e:
                await asyncio.sleep(5)

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
        # Stop the monitoring task
        self.monitoring = False
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        # Shut down the thread pool
        self.executor.shutdown(wait=False)

    @commands.command(name="jkexec")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkexec(self, ctx, filename: str):
        """Execute a server config file via RCON (Bot Owners/Admins only).

        **Usage:** `!jkexec <filename>` **Example:** `!jkexec server.cfg`
        """
        # Get RCON settings
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        try:
            # Send the 'exec' command to the game server
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"exec {filename}", rcon_host, rcon_port, rcon_password
            )
            await ctx.send(f"Executed configuration file: {filename}")
        except Exception as e:
            await ctx.send(f"Failed to execute {filename}: {e}")

async def setup(bot):
    """Set up the JKChatBridge cog when the bot loads."""
    cog = JKChatBridge(bot)
    await bot.add_cog(cog)