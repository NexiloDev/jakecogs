from redbot.core import commands, Config
import discord
import aiohttp
import asyncio
from rcon.source import Client as RconClient
from aiohttp import web
import datetime

class MCChatBridge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_global = {
            "channel_id": None,
            "rcon_host": "localhost",
            "rcon_port": 25575,
            "rcon_password": "",
            "webhook_port": 8080,
            "secret_token": "your-secret-token"
        }
        self.config.register_global(**default_global)
        self.app = web.Application()
        self.app.router.add_post('/minecraft', self.handle_webhook)
        self.runner = None
        self.site = None
        self.bot.loop.create_task(self.start_webhook())
        self.server_info = None

    async def start_webhook(self):
        try:
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(self.runner, '0.0.0.0', await self.config.webhook_port())
            await self.site.start()
        except Exception as e:
            print(f"Failed to start webhook: {e}")

    async def handle_webhook(self, request):
        auth = request.headers.get('Authorization')
        expected_token = await self.config.secret_token()
        if auth != expected_token:
            return web.Response(status=403)

        try:
            data = await request.json()
            event = data.get('event')
            message = data.get('data')
            channel_id = await self.config.channel_id()
            channel = self.bot.get_channel(channel_id)
            if not channel:
                return web.Response(status=400)

            embed = discord.Embed()
            if event == 'chat':
                embed.description = message
                embed.colour = discord.Colour.blue()
            elif event == 'connect':
                player = message.split(' joined')[0]
                embed.description = f"🎮 **{player}** has joined!"
                embed.colour = discord.Colour.green()
            elif event == 'disconnect':
                player = message.split(' left')[0]
                embed.description = f"🚪 **{player}** has left!"
                embed.colour = discord.Colour.red()
            elif event == 'death':
                player = message.split(' ')[0]
                death_message = ' '.join(message.split(' ')[1:])
                death_emoji = self.get_death_emoji(death_message)
                embed.description = f"{death_emoji} **{player}** {death_message}!"
                embed.colour = discord.Colour.dark_red()
            elif event == 'advancement':
                player = message.split(' has made')[0]
                advancement = message.split('advancement ')[1]
                embed.description = f"🏆 **{player}** has made the advancement {advancement}!"
                embed.colour = discord.Colour.purple()
            elif event == 'serverinfo':
                self.server_info = dict(pair.split('=') for pair in message.split('|'))
                return web.Response(status=200)
            else:
                return web.Response(status=400)

            await channel.send(embed=embed)
            return web.Response(status=200)
        except Exception as e:
            print(f"Webhook error: {e}")
            return web.Response(status=500)

    def get_death_emoji(self, death_message):
        death_message = death_message.lower()
        if 'fell from' in death_message or 'fell off' in death_message:
            return '🪂'
        elif 'blown up' in death_message or 'exploded' in death_message:
            return '💥'
        elif 'drowned' in death_message:
            return '🌊'
        elif 'slain by' in death_message or 'killed by' in death_message or 'shot by' in death_message:
            return '⚔️'
        elif 'burned' in death_message or 'fire' in death_message or 'lava' in death_message:
            return '🔥'
        elif 'suffocated' in death_message:
            return '🪨'
        elif 'starved' in death_message:
            return '🍽️'
        elif 'fell out of the world' in death_message:
            return '🌌'
        else:
            return '💀'

    async def send_rcon_command(self, command):
        try:
            rcon_host = await self.config.rcon_host()
            rcon_port = await self.config.rcon_port()
            rcon_password = await self.config.rcon_password()
            with RconClient(rcon_host, rcon_port, passwd=rcon_password) as client:
                return client.run(command)
        except Exception as e:
            print(f"RCON error: {e}")
            return None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.channel:
            return
        channel_id = await self.config.channel_id()
        if message.channel.id != channel_id:
            return
        content = message.clean_content.replace('"', '\\"')
        username = message.author.display_name
        command = f'say [Discord] {username}: {content}'
        await self.send_rcon_command(command)

    @commands.command()
    async def mcset(self, ctx, key: str, *, value: str):
        """Set MCChatBridge config: channel_id, rcon_host, rcon_port, rcon_password, webhook_port, secret_token"""
        if key in ["channel_id", "webhook_port", "rcon_port"]:
            try:
                value = int(value)
            except ValueError:
                await ctx.send("Value must be a number.")
                return
        await self.config.__setattr__(key, value)
        await ctx.send(f"Set {key} to {value}")

    @commands.command()
    async def mcstatus(self, ctx):
        """Show Minecraft server status"""
        embed = discord.Embed(title="Minecraft Server Status", colour=discord.Colour.blue())
        
        # Fetch player list
        player_list = await self.send_rcon_command("list")
        if player_list:
            embed.add_field(name="Online Players", value=player_list, inline=False)
        else:
            embed.add_field(name="Online Players", value="Failed to retrieve", inline=False)

        # Fetch server info
        self.server_info = None
        await self.send_rcon_command("serverinfo")
        await asyncio.sleep(1)  # Wait for serverinfo response
        if self.server_info:
            embed.add_field(name="Version", value=self.server_info.get('version', 'Unknown'), inline=True)
            embed.add_field(name="Max Players", value=self.server_info.get('maxPlayers', 'Unknown'), inline=True)
            uptime_seconds = int(self.server_info.get('uptime', 0))
            uptime = str(datetime.timedelta(seconds=uptime_seconds))
            embed.add_field(name="Uptime", value=uptime, inline=True)
        else:
            embed.add_field(name="Server Info", value="Failed to retrieve", inline=False)

        await ctx.send(embed=embed)

    def cog_unload(self):
        if self.site:
            asyncio.create_task(self.site.stop())
        if self.runner:
            asyncio.create_task(self.runner.cleanup())

def setup(bot):
    bot.add_cog(MCChatBridge(bot))