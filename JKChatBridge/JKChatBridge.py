import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import os
from datetime import datetime

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord via commands.txt, with dynamic log file support for Lugormod."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_base_path=None,  # Base path for log files (e.g., C:\\GameServers\\StarWarsJKA\\GameData\\lugormod)
            discord_channel_id=None,
            command_file_path=r"C:\GameServers\StarWarsJKA\GameData\commands.txt"
        )
        self.bot.loop.create_task(self.monitor_log())
        print("JKChatBridge cog initialized.")

    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (also available as 'jk')."""
        pass

    @jkbridge.command()
    async def setlogbasepath(self, ctx, path: str):
        """Set the base path for Lugormod log files (e.g., C:\\GameServers\\StarWarsJKA\\GameData\\lugormod)."""
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
    async def setcommandfile(self, ctx, path: str):
        """Set the path to the commands.txt file (use double backslashes on Windows)."""
        await self.config.command_file_path.set(path)
        print(f"Command file path set to: {path}")
        await ctx.send(f"Command file path set to: {path}")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        log_base_path = await self.config.log_base_path()
        discord_channel_id = await self.config.discord_channel_id()
        command_file_path = await self.config.command_file_path()
        channel_name = "Not set"
        if discord_channel_id:
            channel = self.bot.get_channel(discord_channel_id)
            channel_name = channel.name if channel else "Unknown channel"
        settings_message = (
            f"**Current Settings:**\n"
            f"Log Base Path: {log_base_path or 'Not set'}\n"
            f"Discord Channel: {channel_name}\n"
            f"Command File Path: {command_file_path or 'Not set'}\n"
        )
        print("Showing settings:", settings_message)
        await ctx.send(settings_message)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle messages from Discord and write them to commands.txt."""
        channel_id = await self.config.discord_channel_id()
        command_file_path = await self.config.command_file_path()

        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return

        discord_username = message.author.name
        server_command = f"say [Discord] {discord_username}: {message.content}"
        print(f"Received message from {discord_username}: {message.content}")
        print(f"Formatted command: {server_command}")

        if not command_file_path:
            print("Error: Command file path not set.")
            await message.channel.send("Command file path not set. Use [p]jk setcommandfile.")
            return

        try:
            print(f"Writing command to {command_file_path}: {server_command}")
            async with aiofiles.open(command_file_path, mode='a') as f:
                await f.write(server_command + "\n")
            print(f"Successfully wrote command to {command_file_path}")
            await message.channel.send("Message sent to game server.")
        except Exception as e:
            print(f"Error writing to {command_file_path}: {e}")
            await message.channel.send(f"Failed to send to game: {e}")

    async def monitor_log(self):
        """Monitor the latest Lugormod log file and send messages to Discord."""
        while True:
            log_base_path = await self.config.log_base_path()
            channel_id = await self.config.discord_channel_id()
            if not log_base_path or not channel_id:
                print("Log base path or channel ID not set. Sleeping for 5 seconds.")
                await asyncio.sleep(5)
                continue

            # Generate the current log file name based on today's date
            current_date = datetime.now().strftime("%m-%d-%Y")  # e.g., "03-11-2025"
            log_file_path = os.path.join(log_base_path, f"games_{current_date}.log")
            print(f"Attempting to monitor log file: {log_file_path}")

            try:
                async with aiofiles.open(log_file_path, mode='r') as f:
                    await f.seek(0, 2)  # Start at end of file
                    print(f"Monitoring log file: {log_file_path}")
                    while True:
                        line = await f.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            discord_message = f"[In-Game] {player_name}: {message}"
                            print(f"Parsed log line - Player: {player_name}, Message: {message}")
                            print(f"Sending to Discord: {discord_message}")
                            channel = self.bot.get_channel(channel_id)
                            if channel:
                                await channel.send(discord_message)
            except FileNotFoundError:
                print(f"Log file not found: {log_file_path}. Waiting for file to be created.")
                await asyncio.sleep(5)  # Wait and retry
            except Exception as e:
                print(f"Log monitoring error: {e}")
                await asyncio.sleep(5)

    def parse_chat_line(self, line):
        """Parse a chat line from the log into player name and message."""
        parts = line.split(":", 2)
        player_name = parts[0].strip()
        message = parts[2].strip() if len(parts) > 2 else ""
        print(f"Parsed log line - Player: {player_name}, Message: {message}")
        return player_name, message

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        print("JKChatBridge cog unloaded.")