import discord
from discord.ext import commands
from redbot.core import commands, Config
import aiohttp
from aiohttp import web
import asyncio
from m podstawie import MCRcon  # Use mcrcon instead of aiorcon
import mcstatus
import json
import random
import logging

class MCChatBridge(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {
            "discord_channel_id": None,
            "rcon_host": "localhost",
            "rcon_port": 25575,
            "rcon_password": "",
            "webhook_port": 8080,
            "secret_token": "",
            "server_ip": "localhost:25565"
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
        self.logger = logging.getLogger("red.MCChatBridge")
        self.session = aiohttp.ClientSession()

    async def cog_load(self):
        try:
            await self.start_webhook_server()
        except Exception as e:
            self.logger.error(f"Failed to start webhook server: {str(e)}")
            raise

    async def cog_unload(self):
        if self.webhook_task:
            self.webhook_task.cancel()
            await self.webhook_app.shutdown()
            await self.webhook_app.cleanup()
        await self.session.close()

    async def start_webhook_server(self):
        guild = self.bot.guilds[0]
        port = await self.config.guild(guild).webhook_port()
        runner = web.AppRunner(self.webhook_app)
        await runner.setup()
        try:
            site = web.TCPSite(runner, '127.0.0.1', port)  # Bind to localhost
            await site.start()
            self.logger.info(f"Webhook server started on port {port}")
            self.webhook_task = asyncio.create_task(asyncio.sleep(0))
        except OSError as e:
            self.logger.error(f"Failed to bind to port {port}: {str(e)}")
            self.logger.error(f"Port {port} is in use. Use [p]mcbridge setwebhookport <new_port> to change it (e.g., 8081).")
            raise

    async def handle_webhook(self, request):
        guild = self.bot.guilds[0]
        secret_token = await self.config.guild(guild).secret_token()
        if request.headers.get('Authorization') != secret_token:
            self.logger.info(f"Unauthorized webhook request from {request.remote}")
            return web.Response(status=401, text="Unauthorized")
        
        data = await request.json()
        event = data.get('event')
        content = data.get('data')
        channel_id = await self.config.guild(guild).discord_channel_id()
        channel = self.bot.get_channel(channel_id)
        if not channel:
            return web.Response(status=400, text="Channel not found")

        if event == "chat":
            try:
                player_name, message = content.split(": ", 1)
                await channel.send(f"**{player_name}**: {message}")
            except ValueError:
                await channel.send(f"**{content}**")
        elif event == "connect":
            player_name = content.split(" joined the server")[0]
            await channel.send(f"<:jk_connect:1349009924306374756> **{player_name}** has joined the game!")
        elif event == "disconnect":
            player_name = content.split(" left the server")[0]
            await channel.send(f"<:jk_disconnect:1349010016044187713> **{player_name}** has disconnected.")
        elif event == "death":
            emoji = next((e for k, e in self.death_emojis.items() if k in content.lower()), "💀")
            await channel.send(f"{emoji} **{content}**")
        elif event == "advancement":
            await channel.send(f"🏆 **{content}**")
        else:
            return web.Response(status=400, text="Unknown event")

        return web.Response(status=200)

    async def send_to_minecraft(self, message, author_name):
        guild = self.bot.guilds[0]
        host = await self.config.guild(guild).rcon_host()
        port = await self.config.guild(guild).rcon_port()
        password = await self.config.guild(guild).rcon_password()

        self.logger.info(f"Attempting to send to Minecraft: host={host}, port={port}, message=[Discord] {author_name}: {message}")
        try:
            def run_mcrcon():
                with MCRcon(host, password, port=port, timeout=5) as client:
                    response = client.command(f"say [Discord] {author_name}: {message}")
                    return response

            self.logger.debug("Creating RCON client")
            response = await self.bot.loop.run_in_executor(None, run_mcrcon)
            self.logger.debug("RCON client connected, sent command")
            self.logger.info(f"Sent to Minecraft: [Discord] {author_name}: {message}, Response: {response}")
            return response
        except Exception as e:
            self.logger.error(f"Failed to send to Minecraft: host={host}, port={port}, error={str(e)}", exc_info=True)
            raise

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        guild = message.guild
        if not guild:
            return
        channel_id = await self.config.guild(guild).discord_channel_id()
        if message.channel.id != channel_id:
            return
        prefixes = await self.bot.get_prefix(message)
        if any(message.content.startswith(prefix) for prefix in prefixes):
            return
        try:
            await self.send_to_minecraft(message.content, message.author.name)
        except Exception as e:
            self.logger.error(f"Failed to forward Discord message to Minecraft: {str(e)}")
        await self.bot.process_commands(message)

    @commands.command()
    async def mcstatus(self, ctx):
        guild = ctx.guild
        server_ip = await self.config.guild(guild).server_ip()

        try:
            server = await self.bot.loop.run_in_executor(None, mcstatus.JavaServer.lookup, server_ip)
            status = await server.async_status()
            embed = discord.Embed(title="Minecraft Server Status", color=discord.Color.blue())
            embed.add_field(name="Online Players", value=f"{status.players.online}/{status.players.max}", inline=False)
            embed.add_field(name="Server Version", value=status.version.name, inline=False)
            embed.add_field(name="Latency", value=f"{status.latency:.2f} ms", inline=False)
            embed.add_field(name="MOTD", value=status.description, inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            self.logger.error(f"Failed to get server status: {str(e)}")
            await ctx.send(f"Failed to connect to server: {str(e)}")

    @commands.group(name="mcbridge", aliases=["mc"])
    @commands.is_owner()
    async def mcbridge(self, ctx):
        """Configure the Minecraft chat bridge (also available as 'mc'). Restricted to bot owner."""
        pass

    @mcbridge.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for the chat bridge."""
        await self.config.guild(ctx.guild).discord_channel_id.set(channel.id)
        await ctx.send(f"Discord channel set to: {channel.name} (ID: {channel.id})")

    @mcbridge.command()
    async def setrconhost(self, ctx, host: str):
        """Set the RCON host (IP or address)."""
        await self.config.guild(ctx.guild).rcon_host.set(host)
        await ctx.send(f"RCON host set to: {host}")

    @mcbridge.command()
    async def setrconport(self, ctx, port: int):
        """Set the RCON port."""
        await self.config.guild(ctx.guild).rcon_port.set(port)
        await ctx.send(f"RCON port set to: {port}")

    @mcbridge.command()
    async def setrconpassword(self, ctx, password: str):
        """Set the RCON password."""
        await self.config.guild(ctx.guild).rcon_password.set(password)
        await ctx.send("RCON password set.")

    @mcbridge.command()
    async def setwebhookport(self, ctx, port: int):
        """Set the webhook port."""
        await self.config.guild(ctx.guild).webhook_port.set(port)
        await ctx.send(f"Webhook port set to: {port}")
        await ctx.send("Please restart the bot to apply webhook port changes")

    @mcbridge.command()
    async def setsecrettoken(self, ctx, token: str):
        """Set the secret token for webhook authentication."""
        await self.config.guild(ctx.guild).secret_token.set(token)
        await ctx.send("Secret token set.")

    @mcbridge.command()
    async def setserverip(self, ctx, server_ip: str):
        """Set the Minecraft server IP and port (e.g., localhost:25565)."""
        await self.config.guild(ctx.guild).server_ip.set(server_ip)
        await ctx.send(f"Server IP set to: {server_ip}")

    @mcbridge.command()
    async def showsettings(self, ctx):
        """Show the current settings for the Minecraft chat bridge."""
        channel = self.bot.get_channel(await self.config.guild(ctx.guild).discord_channel_id()) if await self.config.guild(ctx.guild).discord_channel_id() else None
        settings_message = (
            f"**Current Settings:**\n"
            f"Discord Channel: {channel.name if channel else 'Not set'} (ID: {await self.config.guild(ctx.guild).discord_channel_id() or 'Not set'})\n"
            f"RCON Host: {await self.config.guild(ctx.guild).rcon_host() or 'Not set'}\n"
            f"RCON Port: {await self.config.guild(ctx.guild).rcon_port() or 'Not set'}\n"
            f"RCON Password: {'Set' if await self.config.guild(ctx.guild).rcon_password() else 'Not set'}\n"
            f"Webhook Port: {await self.config.guild(ctx.guild).webhook_port() or 'Not set'}\n"
            f"Secret Token: {'Set' if await self.config.guild(ctx.guild).secret_token() else 'Not set'}\n"
            f"Server IP: {await self.config.guild(ctx.guild).server_ip() or 'Not set'}"
        )
        await ctx.send(settings_message)