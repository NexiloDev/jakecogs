import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import os

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord via a command file."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_file_path=None,
            discord_channel_id=None,
            command_file_path=None  # Path to the command file
        )
        self.bot.loop.create_task(self.monitor_log())

    # Configuration commands with alias 'jk'
    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (also available as 'jk')."""
        pass

    @jkbridge.command()
    async def setlogfile(self, ctx, path: str):
        """Set the path to the game server log file (use double backslashes on Windows)."""
        await self.config.log_file_path.set(path)
        await ctx.send(f"Log file path set to: {path}")

    @jkbridge.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for the chat bridge."""
        await self.config.discord_channel_id.set(channel.id)
        await ctx.send(f"Discord channel set to: {channel.name}")

    @jkbridge.command()
    async def setcommandfile(self, ctx, path: str):
        """Set the path to the command file (e.g., C:\\GameServers\\StarWarsJKA\\GameData\\commands.txt)."""
        await self.config.command_file_path.set(path)
        await ctx.send(f"Command file path set to: {path}")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        log_file_path = await self.config.log_file_path()
        discord_channel_id = await self.config.discord_channel_id()
        command_file_path = await self.config.command_file_path()
        channel_name = "Not set"
        if discord_channel_id:
            channel = self.bot.get_channel(discord_channel_id)
            channel_name = channel.name if channel else "Unknown channel"
        settings_message = (
            f"**Current Settings:**\n"
            f"Log File Path: {log_file_path or 'Not set'}\n"
            f"Discord Channel: {channel_name}\n"
            f"Command File Path: {command_file_path or 'Not set'}\n"
        )
        await ctx.send(settings_message)

    # Relay Discord messages to game
    @commands.Cog.listener()
    async def on_message(self, message):
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        discord_username = message.author.name
        server_command = f"say [Discord] {discord_username}: {message.content}"
        command_file_path = await self.config.command_file_path()
        if not command_file_path:
            await message.channel.send("Command file path not set. Use [p]jk setcommandfile.")
            return
        try:
            print(f"Writing command to file: {server_command}")
            with open(command_file_path, "a") as f:
                f.write(server_command + "\n")
            print("Command written successfully")
            await message.channel.send("Message sent to game server.")
        except Exception as e:
            print(f"Error writing to command file: {e}")
            await message.channel.send(f"Failed to send to game: {e}")

    # Monitor game log for public messages
    async def monitor_log(self):
        while True:
            log_file_path = await self.config.log_file_path()
            channel_id = await self.config.discord_channel_id()
            if not log_file_path or not channel_id:
                await asyncio.sleep(5)
                continue
            try:
                async with aiofiles.open(log_file_path, mode='r') as f:
                    await f.seek(0, 2)  # Start at end of file
                    while True:
                        line = await f.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            discord_message = f"[In-Game] {player_name}: {message}"
                            channel = self.bot.get_channel(channel_id)
                            if channel:
                                await channel.send(discord_message)
            except FileNotFoundError:
                await asyncio.sleep(5)
            except Exception as e:
                print(f"Log monitoring error: {e}")
                await asyncio.sleep(5)

    def parse_chat_line(self, line):
        # Adjust based on your log format, e.g., "PlayerName: say: Message!"
        parts = line.split(":", 2)
        player_name = parts[0].strip()
        message = parts[2].strip()
        return player_name, message