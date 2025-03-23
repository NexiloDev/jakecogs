import discord
from redbot.core import commands, Config
import websocket
import json
import asyncio

class ArmaEvents(commands.Cog):
    """Monitors Arma Reforger server events via the Server Admin Tools Events API and posts them to Discord."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=987654321, force_registration=True)
        self.config.register_global(
            discord_channel_id=None,  # Channel to post events
            api_token="defaultToken123",  # Default token (change this!)
            api_address="ws://localhost:8080/events",  # Default WebSocket address
        )
        self.ws = None
        self.running = True
        self.task = self.bot.loop.create_task(self.start_websocket())

    async def start_websocket(self):
        """Connect to the Arma Reforger Events API and listen for events."""
        await self.bot.wait_until_ready()
        while self.running:
            try:
                token = await self.config.api_token()
                address = await self.config.api_address()
                channel_id = await self.config.discord_channel_id()

                if not all([token, address, channel_id]):
                    print("ArmaEvents: Missing config (token, address, or channel). Use !arma commands to set.")
                    await asyncio.sleep(10)
                    continue

                self.ws = websocket.WebSocket()
                full_address = f"{address}?token={token}"
                self.ws.connect(full_address)
                print(f"ArmaEvents: Connected to {full_address}")

                while self.running:
                    event = json.loads(self.ws.recv())
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        if event["type"] == "serveradmintools_player_joined":
                            await channel.send(f"🧍 **[Arma] {event['data']['playerName']}** has rejoined the fight for survival!")
                        elif event["type"] == "serveradmintools_player_killed":
                            killer = event['data']['killerName']
                            victim = event['data']['victimName']
                            if "zombie" in killer.lower():  # Check if killer is an AI zombie
                                await channel.send(f"🧟 **[Arma] {victim}** got mauled by a zombie! 💀")
                            else:
                                await channel.send(f"💀 **[Arma] {killer}** took down **{victim}** in the chaos! 🔪")
                        elif event["type"] == "serveradmintools_server_fps_low":
                            await channel.send(f"⚠️ **[Arma] Server FPS dropping** - Brace for some lag! ⏳")
                    await asyncio.sleep(0.5)  # Yield to keep the loop smooth
            except Exception as e:
                print(f"ArmaEvents: WebSocket error: {e}")
                if self.ws:
                    self.ws.close()
                await asyncio.sleep(5)

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.running = False
        self.task.cancel()
        if self.ws:
            self.ws.close()

    @commands.group(name="arma")
    @commands.is_owner()
    async def arma_group(self, ctx):
        """Commands to configure the Arma Reforger Events API bridge."""
        pass

    @arma_group.command(name="setchannel")
    async def set_channel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for Arma events. Usage: !arma setchannel #channel"""
        await self.config.discord_channel_id.set(channel.id)
        await ctx.send(f"✅ **Channel Set!** Arma events will now post to {channel.mention} (ID: `{channel.id}`). 🎉")

    @arma_group.command(name="settoken")
    async def set_token(self, ctx, token: str):
        """Set the API token for the Events API. Usage: !arma settoken yourtoken"""
        await self.config.api_token.set(token)
        await ctx.send(f"🔑 **Token Updated!** API token is now `{token}`. Make sure it matches your `ServerAdminTools_Config.json`! ⚙️")

    @arma_group.command(name="setaddress")
    async def set_address(self, ctx, address: str):
        """Set the WebSocket address for the Events API. Usage: !arma setaddress ws://localhost:8080/events"""
        if not address.startswith("ws://"):
            await ctx.send("❌ **Oops!** Address must start with `ws://` (e.g., `ws://localhost:8080/events`). Try again! 🚫")
            return
        await self.config.api_address.set(address)
        await ctx.send(f"🌐 **Address Set!** API address is now `{address}`. Ensure your Arma server is configured to match! 🖥️")

    @arma_group.command(name="showsettings")
    async def show_settings(self, ctx):
        """Display the current ArmaEvents settings."""
        channel = self.bot.get_channel(await self.config.discord_channel_id()) if await self.config.discord_channel_id() else None
        settings_message = (
            "⚙️ **ArmaEvents Settings** ⚙️\n"
            f"**Discord Channel:** {channel.mention if channel else 'Not set'} (ID: `{await self.config.discord_channel_id() or 'Not set'}`) 📢\n"
            f"**API Token:** `{await self.config.api_token()}` 🔑\n"
            f"**API Address:** `{await self.config.api_address()}` 🌐\n"
            "🔧 Use `!arma setchannel`, `!arma settoken`, or `!arma setaddress` to tweak these!"
        )
        await ctx.send(settings_message)

async def setup(bot):
    """Load the ArmaEvents cog into Red Bot."""
    await bot.add_cog(ArmaEvents(bot))