import asyncio
import discord
from redbot.core import Config, commands
import aiofiles  # Install with: pip install aiofiles
# Replace with your actual async RCON library, e.g., aiorcon
from your_rcon_library import AsyncRconClient  # Adjust as needed

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            server_host=None,  # Server IP or hostname for RCON
            server_port=None,  # Server port for RCON, usually the game server port
            rcon_password=None,
            log_file_path=None,
            discord_channel_id=None
        )
        self.rcon_client = AsyncRconClient()  # Initialize your RCON client
        self.bot.loop.create_task(self.monitor_log())

    # Configuration commands
    @commands.group()
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge. Use these commands to set up the game server connection."""
        pass

    @jkbridge.command()
    async def setserverhost(self, ctx, host: str):
        """Set the server host (IP or address) for the game server.
        
        Example: [p]jkbridge setserverhost play.mysticforces.net
        """
        await self.config.server_host.set(host)
        await ctx.send(f"Server host set to: {host}")

    @jkbridge.command()
    async def setserverport(self, ctx, port: int):
        """Set the server port (typically the game server port).
        
        Example: [p]jkbridge setserverport 29070
        """
        await self.config.server_port.set(port)
        await ctx.send(f"Server port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx, password: str):
        """Set the RCON password for the server.
        
        Example: [p]jkbridge setrconpassword yourpassword
        """
        await self.config.rcon_password.set(password)
        await ctx.send("RCON password set.")

    @jkbridge.command()
    async def setlogfile(self, ctx, path: str):
        """Set the path to the game server log file.
        
        Example: [p]jkbridge setlogfile /path/to/games.log
        """
        await self.config.log_file_path.set(path)
        await ctx.send(f"Log file path set to: {path}")

    @jkbridge.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for the chat bridge.
        
        Example: [p]jkbridge setchannel #chat-bridge
        """
        await self.config.discord_channel_id.set(channel.id)
        await ctx.send(f"Discord channel set to: {channel.name}")

    # Relay Discord messages to game
    @commands.Cog.listener()
    async def on_message(self, message):
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        server_host = await self.config.server_host()
        server_port = await self.config.server_port()
        rcon_password = await self.config.rcon_password()
        if not all([server_host, server_port, rcon_password]):
            await message.channel.send("Server settings incomplete. Use `[p]jkbridge` to configure.")
            return
        discord_username = message.author.name
        rcon_command = f"say [Discord] {discord_username}: {message.content}"
        try:
            await self.rcon_client.send(server_host, server_port, rcon_password, rcon_command)
        except Exception as e:
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
        # Adjust based on your log format, e.g., "PlayerName: say: Hello!"
        parts = line.split(":", 2)
        player_name = parts[0].strip()
        message = parts[2].strip()
        return player_name, message