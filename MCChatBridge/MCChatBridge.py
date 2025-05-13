import discord
from discord.ext import commands
from redbot.core import commands, Config, checks
import aiohttp
from aiohttp import web
import asyncio
import rcon.source
import json
import random

class MCChatBridge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {
            "channel_id": None,
            "rcon_host": "localhost",
            "rcon_port": 25575,
            "rcon_password": "",
            "webhook_port": 8080,
            "secret_token": "x7b9p2q8r5t3"
        }
        self.config.register_guild(**default_guild)
        self.webhook_app = web.Application()
        self.webhook_app.router.add_post('/minecraft', self.handle_webhook)
        self.webhook_task = None
        self.death_emojis = {
            "fell from a high place": "🪂",
            "drowned": "🌊",
            "was slain by": "⚔️",
            "burned to death": "🔥",
            "was blown up by": "💥",
            "hit the ground too hard": "🪂",
            "was shot by": "🏹",
            "was killed by": "💀"
        }

    async def cog_load(self):
        await self.start_webhook_server()

    async def cog_unload(self):
        if self.webhook_task:
            self.webhook_task.cancel()
            await self.webhook_app.shutdown()
            await self.webhook_app.cleanup()

    async def start_webhook_server(self):
        guild = self.bot.guilds[0]
        port = await self.config.guild(guild).webhook_port()
        self.webhook_task = asyncio.create_task(web.TCPSite(web.AppRunner(self.webhook_app), '0.0.0.0', port).start())

    async def handle_webhook(self, request):
        guild = self.bot.guilds[0]
        secret_token = await self.config.guild(guild).secret_token()
        if request.headers.get('Authorization') != secret_token:
            return web.Response(status=401, text="Unauthorized")
        
        data = await request.json()
        event = data.get('event')
        content = data.get('data')
        channel_id = await self.config.guild(guild).channel_id()
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return web.Response(status=400, text="Channel not found")

        embed = discord.Embed()
        if event == "chat":
            embed.color = discord.Color.blue()
            embed.description = f"**{content}**"
        elif event == "connect":
            embed.color = discord.Color.green()
            embed.description = f"🎮 **{content}** has joined!"
        elif event == "disconnect":
            embed.color = discord.Color.red()
            embed.description = f"🚪 **{content}** has left!"
        elif event == "death":
            emoji = next((e for k, e in self.death_emojis.items() if k in content.lower()), "💀")
            embed.color = discord.Color.dark_red()
            embed.description = f"{emoji} **{content}**"
        elif event == "advancement":
            embed.color = discord.Color.purple()
            embed.description = f"🏆 **{content}** has made the advancement!"
        else:
            return web.Response(status=400, text="Unknown event")

        await channel.send(embed=embed)
        return web.Response(status=200)

    @commands.command()
    async def mcstatus(self, ctx):
        guild = ctx.guild
        host = await self.config.guild(guild).rcon_host()
        port = await self.config.guild(guild).rcon_port()
        password = await self.config.guild(guild).rcon_password()

        try:
            async with rcon.source.Client(host, port, passwd=password) as client:
                response = await client.run("list")
                players = response.split(": ")[1] if ": " in response else "None"
                server_info = await client.run("version")
                version = server_info.split(" ")[2] if len(server_info.split(" ")) > 2 else "Unknown"
                max_players = await client.run("get maxplayers")
                uptime = await client.run("uptime")

            embed = discord.Embed(title="Minecraft Server Status", color=discord.Color.blue())
            embed.add_field(name="Online Players", value=players, inline=False)
            embed.add_field(name="Server Version", value=version, inline=False)
            embed.add_field(name="Max Players", value=max_players, inline=False)
            embed.add_field(name="Uptime", value=uptime, inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Failed to connect to server: {str(e)}")

    @commands.command()
    async def mcchat(self, ctx, *, message):
        guild = ctx.guild
        host = await self.config.guild(guild).rcon_host()
        port = await self.config.guild(guild).rcon_port()
        password = await self.config.guild(guild).rcon_password()

        try:
            async with rcon.source.Client(host, port, passwd=password) as client:
                await client.run(f"say [Discord] {ctx.author.name}: {message}")
            await ctx.send("Message sent to Minecraft server!")
        except Exception as e:
            await ctx.send(f"Failed to send message: {str(e)}")

    @checks.admin_or_permissions(manage_guild=True)
    @commands.group()
    async def mcset(self, ctx):
        pass

    @mcset.command()
    async def channel_id(self, ctx, channel_id: int):
        await self.config.guild(ctx.guild).channel_id.set(channel_id)
        await ctx.send(f"Set channel ID to {channel_id}")

    @mcset.command()
    async def rcon_host(self, ctx, host: str):
        await self.config.guild(ctx.guild).rcon_host.set(host)
        await ctx.send(f"Set RCON host to {host}")

    @mcset.command()
    async def rcon_port(self, ctx, port: int):
        await self.config.guild(ctx.guild).rcon_port.set(port)
        await ctx.send(f"Set RCON port to {port}")

    @mcset.command()
    async def rcon_password(self, ctx, password: str):
        await self.config.guild(ctx.guild).rcon_password.set(password)
        await ctx.send("RCON password set")

    @mcset.command()
    async def webhook_port(self, ctx, port: int):
        await self.config.guild(ctx.guild).webhook_port.set(port)
        await ctx.send(f"Set webhook port to {port}")
        await ctx.send("Please restart the bot to apply webhook port changes")

    @mcset.command()
    async def secret_token(self, ctx, token: str):
        await self.config.guild(ctx.guild).secret_token.set(token)
        await ctx.send("Secret token set")