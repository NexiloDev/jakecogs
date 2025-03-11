import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
from asyncrcon import AsyncRCON, AuthenticationException, NullResponseException, MaxRetriesExceedException

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            server_host=None,
            server_port=None,
            rcon_password=None,
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
        """Set the server host (IP or address)."""
        await self.config.server_host.set(host)
        await ctx.send(f"Server host set to: {host}")

    @jkbridge.command()
    async def setserverport(self, ctx, port: int):
        """Set the server port."""
        await self.config.server_port.set(port)
        await ctx.send(f"Server port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx, password: str):
        """Set the RCON password."""
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
            await message.channel.send("Server settings incomplete. Use `[p]jkbridge` or `[p]jk` to configure.")
            return
        # Combine host and port into the address format expected by AsyncRCON
        rcon_address = f"{server_host}:{server_port}"
        discord_username = message.author.name
        rcon_command = f"say [Discord] {discord_username}: {message.content}"
        try:
            rcon = AsyncRCON(rcon_address, rcon_password)
            await rcon.open_connection()
            response = await rcon.command(rcon_command)
            await rcon.close()
            print(f"RCON response: {response}")
        except AuthenticationException:
            await message.channel.send("Authentication failed. Check your RCON password.")
        except NullResponseException:
            await message.channel.send("Server returned an invalid or empty response.")
        except MaxRetriesExceedException:
            await message.channel.send("Maximum command retries exceeded.")
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
        # Adjust based on your log format, e.g., "PlayerName: say: Message!"
        parts = line.split(":", 2)
        player_name = parts[0].strip()
        message = parts[2].strip()
        return player_name, message