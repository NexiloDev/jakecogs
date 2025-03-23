import discord
from redbot.core import commands, Config
from aiohttp import web
import json
import asyncio

class ArmaEvents(commands.Cog):
    """Monitors Arma Reforger server events via the Server Admin Tools Events API and posts them to Discord."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=987654321, force_registration=True)
        self.config.register_global(
            discord_channel_id=None,  # Channel to post events
            api_token="defaultToken123",  # Token for validation
            api_address="http://localhost:8081/events",  # Default HTTP endpoint
            server_port=8081  # Port for the cog's HTTP server
        )
        self.app = web.Application()
        self.app.router.add_post('/events', self.handle_event)
        self.runner = None
        self.site = None
        self.running = True
        self.task = self.bot.loop.create_task(self.start_server())

    async def handle_event(self, request):
        """Handle incoming POST requests from the Arma Events API."""
        try:
            data = await request.json()
            print(f"ArmaEvents: Received event: {json.dumps(data)}")  # Log the raw event
            token = await self.config.api_token()

            # Validate token if provided in Authorization header or body
            auth_header = request.headers.get('Authorization', '').replace('Bearer ', '')
            body_token = data.get('token', '')
            print(f"ArmaEvents: Auth header: {auth_header}, Body token: {body_token}, Expected: {token}")
            if token and token != "defaultToken123" and token not in (auth_header, body_token):
                print("ArmaEvents: Token validation failed")
                return web.Response(status=401, text="Unauthorized: Invalid token")

            channel_id = await self.config.discord_channel_id()
            channel = self.bot.get_channel(channel_id)
            if not channel:
                print("ArmaEvents: Discord channel not set or invalid.")
                return web.Response(status=200)

            event_type = data.get('type')
            print(f"ArmaEvents: Event type: {event_type}")
            if event_type == "serveradmintools_player_joined":
                await channel.send(f"🧍 **[Arma] {data['data']['playerName']}** has rejoined the fight for survival!")
            elif event_type == "serveradmintools_player_killed":
                killer = data['data']['killerName']
                victim = data['data']['victimName']
                if "zombie" in killer.lower():
                    await channel.send(f"🧟 **[Arma] {victim}** got mauled by a zombie! 💀")
                else:
                    await channel.send(f"💀 **[Arma] {killer}** took down **{victim}** in the chaos! 🔪")
            elif event_type == "serveradmintools_server_fps_low":
                await channel.send(f"⚠️ **[Arma] Server FPS dropping** - Brace for some lag! ⏳")

            return web.Response(status=200)
        except Exception as e:
            print(f"ArmaEvents: Error processing event: {e}")
            return web.Response(status=500)

    async def start_server(self):
        """Start the HTTP server to receive Arma events."""
        await self.bot.wait_until_ready()
        while self.running:
            try:
                port = await self.config.server_port()
                channel_id = await self.config.discord_channel_id()
                if not channel_id:
                    print("ArmaEvents: Discord channel not set. Use !arma setchannel.")
                    await asyncio.sleep(10)
                    continue

                self.runner = web.AppRunner(self.app)
                await self.runner.setup()
                self.site = web.TCPSite(self.runner, '0.0.0.0', port)
                await self.site.start()
                print(f"ArmaEvents: HTTP server running on http://0.0.0.0:{port}/events")
                while self.running:
                    await asyncio.sleep(1)  # Keep the task alive
            except Exception as e:
                print(f"ArmaEvents: Server error: {e}")
                await self.cleanup()
                await asyncio.sleep(5)

    async def cleanup(self):
        """Clean up the HTTP server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.running = False
        self.task.cancel()
        self.bot.loop.create_task(self.cleanup())

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
        await ctx.send(f"🔑 **Token Updated!** API token is now `{token}`. Set it in `ServerAdminTools_Config.json` too! ⚙️")

    @arma_group.command(name="setaddress")
    async def set_address(self, ctx, address: str):
        """Set the API address for the Events API. Usage: !arma setaddress http://localhost:8081/events"""
        if not address.startswith("http://"):
            await ctx.send("❌ **Oops!** Address must start with `http://` (e.g., `http://localhost:8081/events`). Try again! 🚫")
            return
        await self.config.api_address.set(address)
        await ctx.send(f"🌐 **Address Set!** API endpoint is now `{address}`. Update `ServerAdminTools_Config.json`! 🖥️")

    @arma_group.command(name="setport")
    async def set_port(self, ctx, port: int):
        """Set the port for the HTTP server. Usage: !arma setport 8081"""
        if not (1024 <= port <= 65535):
            await ctx.send("❌ **Oops!** Port must be between 1024 and 65535. Try again! 🚫")
            return
        await self.config.server_port.set(port)
        address = f"http://localhost:{port}/events"
        await self.config.api_address.set(address)
        await ctx.send(f"🔌 **Port Set!** Server will run on port `{port}` (`{address}`). Restart the cog to apply! 🔄")

    @arma_group.command(name="showsettings")
    async def show_settings(self, ctx):
        """Display the current ArmaEvents settings."""
        channel = self.bot.get_channel(await self.config.discord_channel_id()) if await self.config.discord_channel_id() else None
        settings_message = (
            "⚙️ **ArmaEvents Settings** ⚙️\n"
            f"**Discord Channel:** {channel.mention if channel else 'Not set'} (ID: `{await self.config.discord_channel_id() or 'Not set'}`) 📢\n"
            f"**API Token:** `{await self.config.api_token()}` 🔑\n"
            f"**API Address:** `{await self.config.api_address()}` 🌐\n"
            f"**Server Port:** `{await self.config.server_port()}` 🔌\n"
            "🔧 Use `!arma setchannel`, `!arma settoken`, `!arma setaddress`, or `!arma setport` to tweak these!"
        )
        await ctx.send(settings_message)

async def setup(bot):
    """Load the ArmaEvents cog into Red Bot."""
    await bot.add_cog(ArmaEvents(bot))