import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import win32com.client
import time
import win32gui

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord via server console (RCON settings optional for future use)."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            server_host=None,  # Optional: IP for potential RCON use
            server_port=None,  # Optional: Port for potential RCON use
            rcon_password=None,  # Optional: Password for potential RCON use
            log_file_path=None,
            discord_channel_id=None
        )
        self.bot.loop.create_task(self.monitor_log())

    # Configuration commands with alias 'jk'
    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (also available as 'jk'). Use these commands to set up the game server connection."""
        pass

    @jkbridge.command()
    async def setserverhost(self, ctx, host: str):
        """Set the server host (IP or address, optional for future RCON use)."""
        await self.config.server_host.set(host)
        await ctx.send(f"Server host set to: {host}")

    @jkbridge.command()
    async def setserverport(self, ctx, port: int):
        """Set the server port (optional for future RCON use)."""
        await self.config.server_port.set(port)
        await ctx.send(f"Server port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx, password: str):
        """Set the RCON password (optional for future RCON use)."""
        await self.config.rcon_password.set(password)
        await ctx.send("RCON password set.")

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
    async def showsettings(self, ctx):
        """Show the current settings for the JK chat bridge."""
        server_host = await self.config.server_host()
        server_port = await self.config.server_port()
        rcon_password = await self.config.rcon_password()
        log_file_path = await self.config.log_file_path()
        discord_channel_id = await self.config.discord_channel_id()
        channel_name = "Not set"
        if discord_channel_id:
            channel = self.bot.get_channel(discord_channel_id)
            channel_name = channel.name if channel else "Unknown channel"
        settings_message = (
            f"**Current Settings:**\n"
            f"Server Host: {server_host or 'Not set'} (optional for RCON)\n"
            f"Server Port: {server_port or 'Not set'} (optional for RCON)\n"
            f"RCON Password: {'Set' if rcon_password else 'Not set'} (optional for RCON)\n"
            f"Log File Path: {log_file_path or 'Not set'}\n"
            f"Discord Channel: {channel_name}\n"
        )
        await ctx.send(settings_message)

    def find_server_window(self):
        """Find the first 'OpenJK (MP) Dedicated Server Console' window."""
        def enum_windows_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_title = win32gui.GetWindowText(hwnd)
                if "OpenJK (MP) Dedicated Server Console" in window_title:
                    windows.append(hwnd)
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        return windows[0] if windows else None  # Return the handle of the first matching window

    def send_to_console(self, command):
        """Send a command to the server console window."""
        try:
            hwnd = self.find_server_window()
            if hwnd is None:
                raise Exception("Could not find any 'OpenJK (MP) Dedicated Server Console' window.")
            shell = win32com.client.Dispatch("WScript.Shell")
            if not shell.AppActivate(hwnd):
                raise Exception("Could not activate the server console window.")
            shell.SendKeys(command + "{ENTER}")
            time.sleep(0.5)  # Small delay to ensure the command is sent
        except Exception as e:
            raise Exception(f"Failed to send command to console: {e}")

    # Relay Discord messages to game
    @commands.Cog.listener()
    async def on_message(self, message):
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        discord_username = message.author.name
        server_command = f"say [Discord] {discord_username}: {message.content}"
        try:
            print(f"Sending command to server console: {server_command}")
            self.send_to_console(server_command)
            print("Command sent successfully")
            await message.channel.send("Message sent to game server.")
        except Exception as e:
            print(f"Error sending to server console: {e}")
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