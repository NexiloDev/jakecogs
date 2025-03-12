import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import os
from datetime import datetime
import socket
from concurrent.futures import ThreadPoolExecutor
import re

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord via RCON, with dynamic log file support for Lugormod."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_base_path=None,
            discord_channel_id=None,
            rcon_host="127.0.0.1",
            rcon_port=29070,
            rcon_password=None,
            custom_emoji="<:jk:1219115870928900146>"
        )
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.monitoring = False
        self.monitor_task = None
        self.client_names = {}  # Now stores {client_id: (name, username)}
        self.url_pattern = re.compile(
            r'(https?://[^\s]+|www\.[^\s]+|\b[a-zA-Z0-9-]+\.(com|org|net|edu|gov|io|co|uk|ca|de|fr|au|us|ru|ch|it|nl|se|no|es|mil)(/[^\s]*)?)',
            re.IGNORECASE
        )
        self.start_monitoring()
        print("JKChatBridge cog initialized.")

    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()  # Restrict group to bot owner
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (also available as 'jk'). Restricted to bot owner."""
        pass

    @jkbridge.command()
    async def setlogbasepath(self, ctx, path: str):
        """Set the base path for Lugormod log files (e.g., C:\\GameServers\\StarWarsJKA\\GameData\\lugormod\\logs)."""
        await self.config.log_base_path.set(path)
        print(f"Log base path set to: {path}")
        await ctx.send(f"Log base path set to: {path}")

    @jkbridge.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for the chat bridge."""
        await self.config.discord_channel_id.set(channel.id)
        print(f"Discord channel set to: {channel.name} (ID: {channel.id})")
        await ctx.send(f"Discord channel set to: {channel.name} (ID: {channel.id})")
        print(f"Debug: Stored channel ID in config: {await self.config.discord_channel_id()}")

    @jkbridge.command()
    async def setrconhost(self, ctx, host: str):
        """Set the RCON host (IP or address)."""
        await self.config.rcon_host.set(host)
        print(f"RCON host set to: {host}")
        await ctx.send(f"RCON host set to: {host}")

    @jkbridge.command()
    async def setrconport(self, ctx, port: int):
        """Set the RCON port."""
        await self.config.rcon_port.set(port)
        print(f"RCON port set to: {port}")
        await ctx.send(f"RCON port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx, password: str):
        """Set the RCON password."""
        await self.config.rcon_password.set(password)
        print("RCON password set.")
        await ctx.send("RCON password set.")

    @jkbridge.command()
    async def setcustomemoji(self, ctx, emoji: str):
        """Set the custom emoji for game-to-Discord chat messages (e.g., <:jk:1219115870928900146>)."""
        await self.config.custom_emoji.set(emoji)
        print(f"Custom emoji set to: {emoji}")
        await ctx.send(f"Custom emoji set to: {emoji}")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        log_base_path = await self.config.log_base_path()
        discord_channel_id = await self.config.discord_channel_id()
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        custom_emoji = await self.config.custom_emoji()
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
            f"Custom Emoji: {custom_emoji or 'Not set'}"
        )
        print("Showing settings:", settings_message)
        await ctx.send(settings_message)

    @jkbridge.command()
    async def reloadmonitor(self, ctx):
        """Force reload the log monitoring task."""
        if self.monitor_task and not self.monitor_task.done():
            print(f"Canceling existing monitor task: {id(self.monitor_task)}")
            self.monitoring = False
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        self.client_names.clear()
        self.start_monitoring()
        await ctx.send("Log monitoring task reloaded.")

    @commands.command(name="jkstatus")
    async def status(self, ctx):
        """Display detailed server status with emojis. Accessible to all users."""
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            await ctx.send("RCON settings not fully configured. Please contact an admin.")
            return

        try:
            # Send 'playerlist' command via RCON
            playerlist_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "playerlist", rcon_host, rcon_port, rcon_password
            )
            playerlist_lines = playerlist_response.decode(errors='replace').splitlines()

            # Parse playerlist response
            server_name = "Unknown"  # Playerlist doesn't provide this, so we'll fetch separately if needed
            mod_name = "Unknown"
            map_name = "Unknown"
            player_count = "0 humans, 0 bots"  # We'll update this based on playerlist
            online_client_ids = []

            # Fetch status for server details (since playerlist doesn't include them)
            status_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "status", rcon_host, rcon_port, rcon_password
            )
            status_lines = status_response.decode(errors='replace').splitlines()
            for line in status_lines:
                if "hostname:" in line:
                    server_name = self.remove_color_codes(line.split("hostname:")[1].strip()).replace("Ç", "").encode().decode('ascii', 'ignore')
                elif "game    :" in line:
                    mod_name = line.split("game    :")[1].strip()
                elif "map     :" in line:
                    map_name = line.split("map     :")[1].split()[0].strip()
                elif "players :" in line:
                    player_count = line.split("players :")[1].strip()

            # Parse playerlist for client IDs, names, and usernames
            for line in playerlist_lines:
                if re.match(r"^\d+\s+\S+", line):  # Matches lines starting with a number and a name
                    parts = re.split(r"\s+", line.strip(), maxsplit=12)
                    if len(parts) >= 12:
                        client_id = parts[0]
                        player_name = self.remove_color_codes(parts[1])
                        username = parts[11] if parts[11] != "0" else None  # Username is last column, "0" if not logged in
                        online_client_ids.append(client_id)
                        # Update self.client_names with name and username
                        self.client_names[client_id] = (player_name, username)

            # Get full names from self.client_names (now updated with playerlist data)
            players = []
            for client_id in online_client_ids:
                name, username = self.client_names.get(client_id, (f"Unknown (ID {client_id})", None))
                players.append((client_id, name))

            # Format player list with ID and name
            player_list = "No players online"
            if players:
                player_lines = [f"{client_id:<3} {name}" for client_id, name in players]
                player_list = "```\n" + "\n".join(player_lines) + "\n```"

            # Create fancy embed
            embed = discord.Embed(
                title=f"🌌 {server_name} 🌌",
                color=discord.Color.gold(),
                timestamp=datetime.now()
            )
            embed.add_field(name="👥 Players", value=f"{player_count}", inline=True)
            embed.add_field(name="🗺️ Map", value=f"`{map_name}`", inline=True)
            embed.add_field(name="🎮 Mod", value=f"{mod_name}", inline=True)
            embed.add_field(name="📋 Online Players", value=player_list, inline=False)
            embed.set_footer(text="✨ Updated on March 11, 2025 ✨", icon_url="https://cdn.discordapp.com/emojis/1219115870928900146.png")

            await ctx.send(embed=embed)
        except Exception as e:
            print(f"Error fetching server status: {e}")
            await ctx.send(f"Failed to retrieve server status: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages from Discord and send them to the game server via RCON."""
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        discord_username = message.author.display_name
        
        # Replace typographic punctuation with ASCII equivalents in username
        discord_username = discord_username.replace("’", "'").replace("‘", "'")  # Apostrophes
        discord_username = discord_username.replace("“", "\"").replace("”", "\"")  # Curly quotes
        discord_username = discord_username.replace("«", "\"").replace("»", "\"")  # Angle quotes
        discord_username = discord_username.replace("–", "-").replace("—", "-")  # Dashes
        discord_username = discord_username.replace("…", "...")  # Ellipsis
        
        message_content = message.content  # Start with raw content

        # Replace typographic punctuation with ASCII equivalents in message
        message_content = message_content.replace("’", "'").replace("‘", "'")  # Apostrophes
        message_content = message_content.replace("“", "\"").replace("”", "\"")  # Curly quotes
        message_content = message_content.replace("«", "\"").replace("»", "\"")  # Angle quotes
        message_content = message_content.replace("–", "-").replace("—", "-")  # Dashes
        message_content = message_content.replace("…", "...")  # Ellipsis

        # Process emojis: custom ones to :name:, remove standard Unicode emojis
        message_content = self.replace_emojis_with_names(message_content)

        if self.url_pattern.search(message_content):
            print(f"Blocked Discord message with URL: {message_content}")
            return

        initial_prefix = f"say ^5{{D}}^7{discord_username}^2: "
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

        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            print("RCON settings not fully configured.")
            await message.channel.send("RCON settings not fully configured. Please contact an admin.")
            return
        
        try:
            for i, chunk in enumerate(chunks):
                if i == 0:
                    server_command = f"{initial_prefix}{chunk}"
                else:
                    server_command = f"{continuation_prefix}{chunk}"
                print(f"Sending RCON command (length {len(server_command)}): {server_command}")
                await self.bot.loop.run_in_executor(self.executor, self.send_rcon_command, server_command, rcon_host, rcon_port, rcon_password)
                print("RCON command sent successfully.")
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Error sending RCON command: {e}")
            await message.channel.send(f"Failed to send to game: {e}")

    def replace_emojis_with_names(self, text):
        """Replace custom Discord emojis with :name: and remove standard Unicode emojis."""
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        emoji_map = {
            "😊": "", "😄": "", "😂": "", "🤣": "", "😉": "", "😛": "", "😢": "", "😡": "",
            "👍": "", "👎": "", "❤️": "", "💖": "", "😍": "", "🙂": "", "😣": "", "😜": ""
        }
        for unicode_emoji, _ in emoji_map.items():
            text = text.replace(unicode_emoji, "")
        return text

    def replace_text_emotes_with_emojis(self, text):
        """Convert common text emoticons from Jedi Academy to Discord emojis."""
        text_emote_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢",
            ">:(": "😡", ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣"
        }
        for text_emote, emoji in text_emote_map.items():
            text = text.replace(text_emote, emoji)
        return text

    def send_rcon_command(self, command, host, port, password):
        """Send an RCON command to the game server and return response."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        packet = b'\xff\xff\xff\xffrcon ' + password.encode() + b' ' + command.encode()
        try:
            sock.sendto(packet, (host, port))
            response, _ = sock.recvfrom(4096)
            print("RCON response:", response.decode(errors='replace'))
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
        print("Log monitoring task started.")
        while self.monitoring:
            try:
                log_base_path = await self.config.log_base_path()
                channel_id = await self.config.discord_channel_id()
                custom_emoji = await self.config.custom_emoji()
                if not log_base_path or not channel_id or not custom_emoji:
                    print("Log base path, channel ID, or custom emoji not set. Sleeping for 5 seconds.")
                    await asyncio.sleep(5)
                    continue

                channel = self.bot.get_channel(channel_id)
                print(f"Using channel ID: {channel_id}, Channel name: {channel.name if channel else 'Not found'}")

                now = datetime.now()
                month = str(now.month)
                day = str(now.day)
                year = str(now.year)
                current_date = f"{month}-{day}-{year}"

                log_file_path = os.path.join(log_base_path, f"games_{current_date}.log")
                print(f"Attempting to monitor log file: {log_file_path}")

                async with aiofiles.open(log_file_path, mode='r') as f:
                    await f.seek(0, 2)
                    print(f"Monitoring log file: {log_file_path}")
                    while self.monitoring:
                        line = await f.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        line = line.strip()
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message:
                                if self.url_pattern.search(message):
                                    print(f"Blocked game message with URL: {message}")
                                    continue
                                message = self.replace_text_emotes_with_emojis(message)
                                discord_message = f"{custom_emoji} **{player_name}**: {message}"
                                print(f"Sending to Discord channel {channel_id}: {discord_message}")
                                if channel:
                                    await channel.send(discord_message)
                                else:
                                    print(f"Channel {channel_id} not found!")
                        elif "ClientUserinfoChanged handling info:" in line:
                            client_id = line.split("ClientUserinfoChanged handling info: ")[1].split()[0]
                            name_match = re.search(r'\\n\\([^\\]+)', line)
                            username_match = re.search(r'\\username\\([^\\]+)', line)
                            if name_match:
                                player_name = self.remove_color_codes(name_match.group(1))
                                username = username_match.group(1) if username_match else None
                                # Update with name and username (username None if not logged in)
                                self.client_names[client_id] = (player_name, username)
                                print(f"Updated name for client {client_id}: {player_name}, Username: {username}")
                        elif "ClientBegin:" in line:
                            client_id = line.split("ClientBegin: ")[1].strip()
                            name, username = self.client_names.get(client_id, (f"Unknown (ID {client_id})", None))
                            join_message = f"<:jk_connect:1349009924306374756> **{name}** has joined the game!"
                            print(f"Sending to Discord channel {channel_id}: {join_message}")
                            if channel and not name.endswith("-Bot"):
                                await channel.send(join_message)
                        elif "ClientDisconnect:" in line:
                            client_id = line.split("ClientDisconnect: ")[1].strip()
                            name, username = self.client_names.get(client_id, (f"Unknown (ID {client_id})", None))
                            leave_message = f"<:jk_disconnect:1349010016044187713> **{name}** has disconnected."
                            print(f"Sending to Discord channel {channel_id}: {leave_message}")
                            if channel and not name.endswith("-Bot"):
                                await channel.send(leave_message)
                            if client_id in self.client_names:
                                del self.client_names[client_id]
                        elif "duel:" in line and "won a duel against" in line:
                            parts = line.split("duel:")[1].split("won a duel against")
                            if len(parts) == 2:
                                winner = self.remove_color_codes(parts[0].strip())
                                loser = self.remove_color_codes(parts[1].strip())
                                duel_message = f"<a:peepoBeatSaber:1228624251800522804> **{winner}** won a duel against **{loser}**!"
                                print(f"Sending to Discord channel {channel_id}: {duel_message}")
                                if channel:
                                    await channel.send(duel_message)
                                else:
                                    print(f"Channel {channel_id} not found!")
            except FileNotFoundError:
                print(f"Log file not found: {log_file_path}. Waiting for file to be created.")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Log monitoring error: {e}")
                await asyncio.sleep(5)
        print("Log monitoring task stopped.")

    def start_monitoring(self):
        if not self.monitor_task or self.monitor_task.done():
            self.monitor_task = self.bot.loop.create_task(self.monitor_log())
            print(f"Monitor task created: {id(self.monitor_task)}")

    def remove_color_codes(self, text):
        """Remove Jedi Academy color codes (e.g., ^1, ^7) from text."""
        return re.sub(r'\^\d', '', text)

    def parse_chat_line(self, line):
        """Parse a chat line from the log into player name and message."""
        say_index = line.find("say: ")
        if say_index != -1:
            chat_part = line[say_index + 5:]
            colon_index = chat_part.find(": ")
            if colon_index != -1:
                player_name = chat_part[:colon_index].strip()
                message = chat_part[colon_index + 2:].strip()
                player_name = self.remove_color_codes(player_name)
                message = self.remove_color_codes(message)
                return player_name, message
        return None, None

    async def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.monitoring = False
        if self.monitor_task and not self.monitor_task.done():
            print(f"Canceling task: {id(self.monitor_task)}")
            self.monitor_task.cancel()
            try:
                await asyncio.sleep(0)
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        self.executor.shutdown(wait=False)
        print("JKChatBridge cog unloaded.")

async def setup(bot):
    cog = JKChatBridge(bot)
    await bot.add_cog(cog)