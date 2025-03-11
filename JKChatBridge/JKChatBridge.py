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
            log_base_path=None,  # Base path for log files (e.g., C:\\GameServers\\StarWarsJKA\\GameData\\lugormod\\logs)
            discord_channel_id=None,
            rcon_host="127.0.0.1",
            rcon_port=29070,
            rcon_password=None,
            custom_emoji="<:jk:1219115870928900146>"  # Updated with proper emoji reference
        )
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.monitoring = False  # Control flag for monitoring
        self.monitor_task = None
        self.start_monitoring()
        print("JKChatBridge cog initialized.")

    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (also available as 'jk')."""
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
        await ctx.send(f"Discord channel set to: {channel.name}")

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
        """Set the custom emoji for game-to-Discord messages (e.g., <:jk:1219115870928900146>)."""
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
            f"Discord Channel: {channel_name}\n"
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
        self.start_monitoring()
        await ctx.send("Log monitoring task reloaded.")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages from Discord and send them to the game server via RCON."""
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        discord_username = message.author.display_name
        message_content = self.replace_emojis_with_names(message.content)
        # Updated format: ^5{Discord} ^7username^2
        server_command = f"say ^5{{Discord}} ^7{discord_username}^2: {message_content}"
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        if not all([rcon_host, rcon_port, rcon_password]):
            print("RCON settings not fully configured.")
            await message.channel.send("RCON settings not fully configured. Use [p]jk setrconhost, [p]jk setrconport, and [p]jk setrconpassword.")
            return
        try:
            print(f"Sending RCON command: {server_command}")
            await self.bot.loop.run_in_executor(self.executor, self.send_rcon_command, server_command, rcon_host, rcon_port, rcon_password)
            print("RCON command sent successfully.")
        except Exception as e:
            print(f"Error sending RCON command: {e}")
            await message.channel.send(f"Failed to send to game: {e}")

    def replace_emojis_with_names(self, text):
        """Replace Discord emojis with their names, including standard Unicode emojis."""
        # First handle custom emojis
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        # Then handle standard Unicode emojis
        emoji_map = {
            "😄": ":smile:",
            "😂": ":joy:",
            "😊": ":blush:",
            "😉": ":wink:",
            "😍": ":heart_eyes:",
            "😢": ":cry:",
            "😡": ":angry:",
            "👍": ":thumbsup:",
            "👎": ":thumbsdown:",
            # Add more common emojis as needed
        }
        for unicode_emoji, name in emoji_map.items():
            text = text.replace(unicode_emoji, name)
        return text

    def send_rcon_command(self, command, host, port, password):
        """Send an RCON command to the game server."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        packet = b'\xff\xff\xff\xffrcon ' + password.encode() + b' ' + command.encode()
        try:
            sock.sendto(packet, (host, port))
            response, _ = sock.recvfrom(4096)
            print("RCON response:", response.decode(errors='replace'))
        except socket.timeout:
            raise Exception("RCON command timed out.")
        except Exception as e:
            raise Exception(f"Error sending RCON command: {e}")
        finally:
            sock.close()

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

                # Add debug logging to verify channel ID
                channel = self.bot.get_channel(channel_id)
                print(f"Using channel ID: {channel_id}, Channel name: {channel.name if channel else 'Not found'}")

                # Get the current date without leading zeros
                now = datetime.now()
                month = str(now.month)
                day = str(now.day)
                year = str(now.year)
                current_date = f"{month}-{day}-{year}"

                log_file_path = os.path.join(log_base_path, f"games_{current_date}.log")
                print(f"Attempting to monitor log file: {log_file_path}")

                async with aiofiles.open(log_file_path, mode='r') as f:
                    await f.seek(0, 2)  # Start at end of file
                    print(f"Monitoring log file: {log_file_path}")
                    while self.monitoring:
                        line = await f.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message:
                                discord_message = f"{custom_emoji} **{player_name}**: {message}"
                                print(f"Sending to Discord channel {channel_id}: {discord_message}")
                                channel = self.bot.get_channel(channel_id)  # Refresh channel object
                                if channel:
                                    await channel.send(discord_message)
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
            chat_part = line[say_index + 5:]  # Skip past "say: "
            colon_index = chat_part.find(": ")
            if colon_index != -1:
                player_name = chat_part[:colon_index].strip()
                message = chat_part[colon_index + 2:].strip()
                # Remove color codes from both
                player_name = self.remove_color_codes(player_name)
                message = self.remove_color_codes(message)
                return player_name, message
        return None, None

    async def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.monitoring = False  # Signal the loop to stop
        if self.monitor_task and not self.monitor_task.done():
            print(f"Canceling task: {id(self.monitor_task)}")
            self.monitor_task.cancel()
            try:
                await asyncio.sleep(0)  # Yield control to allow cancellation
                await self.monitor_task  # Wait for the task to finish
            except asyncio.CancelledError:
                pass
        self.executor.shutdown(wait=False)
        print("JKChatBridge cog unloaded.")

async def setup(bot):
    cog = JKChatBridge(bot)
    await bot.add_cog(cog)