import discord
from redbot.core import Config, commands

class ConfigHandler:
    """Handles Red config + the `!jkbridge` / `!jk` command group."""
    def setup_cog(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_base_path=None,
            discord_channel_id=None,
            rcon_host=None,
            rcon_port=None,
            rcon_password=None,
            custom_emoji=None,
            join_disconnect_enabled=True,
            vpn_api_key=None,
            vpn_check_enabled=False,
            tracker_url=None,
            bot_name=None,
            random_chat_path=None
        )

        # ------------------------------------------------------------------
        @commands.group(name="jkbridge", aliases=["jk"])
        @commands.is_owner()
        async def jkbridge(ctx: commands.Context):
            """Configure the JK chat bridge (also available as 'jk')."""
            pass

        self.jkbridge = jkbridge
        self._add_config_subcommands()
        self.bot.add_command(self.jkbridge)   # only ONE registration

    # ------------------------------------------------------------------
    def _add_config_subcommands(self):
        @self.jkbridge.command()
        async def setlogbasepath(self, ctx: commands.Context, path: str):
            await self.config.log_base_path.set(path)
            if self.monitor_task and not self.monitor_task.done():
                self.monitoring = False
                self.monitor_task.cancel()
                try:
                    await self.monitor_task
                except asyncio.CancelledError:
                    pass
            self.start_monitoring()
            await ctx.send(f"Log base path set to: `{path}`. Monitoring restarted.")

        @self.jkbridge.command()
        async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
            await self.config.discord_channel_id.set(channel.id)
            await ctx.send(f"Discord channel set to: {channel.mention} (ID: {channel.id})")

        @self.jkbridge.command()
        async def setrconhost(self, ctx: commands.Context, host: str):
            await self.config.rcon_host.set(host)
            await ctx.send(f"RCON host set to: `{host}`")

        @self.jkbridge.command()
        async def setrconport(self, ctx: commands.Context, port: int):
            await self.config.rcon_port.set(port)
            await ctx.send(f"RCON port set to: `{port}`")

        @self.jkbridge.command()
        async def setrconpassword(self, ctx: commands.Context, password: str):
            await self.config.rcon_password.set(password)
            await ctx.send("RCON password set.")

        @self.jkbridge.command()
        async def setcustomemoji(self, ctx: commands.Context, emoji: str):
            await ctx.send("Custom emoji feature has been removed and is no longer used.")

        @self.jkbridge.command()
        async def settrackerurl(self, ctx: commands.Context, url: str):
            await self.config.tracker_url.set(url)
            await ctx.send(f"Tracker URL set to: `{url}`")

        @self.jkbridge.command()
        async def setbotname(self, ctx: commands.Context, name: str):
            await self.config.bot_name.set(name)
            await ctx.send(f"Bot name set to: `{name}`")

        @self.jkbridge.command()
        async def setvpnkey(self, ctx: commands.Context, key: str):
            await self.config.vpn_api_key.set(key)
            await ctx.send("VPN API key set.")

        @self.jkbridge.command()
        async def togglevpncheck(self, ctx: commands.Context):
            new = not await self.config.vpn_check_enabled()
            await self.config.vpn_check_enabled.set(new)
            await ctx.send(f"VPN detection **{'enabled' if new else 'disabled'}**.")

        @self.jkbridge.command()
        async def setchatpath(self, ctx: commands.Context, path: str):
            await self.config.random_chat_path.set(path)
            await self.load_random_chat_lines()
            count = len(self.random_chat_lines)
            await ctx.send(f"Random chat file set to: `{path}`\nLoaded **{count}** lines. Use `[p]reload JKChatBridge` after editing.")

        @self.jkbridge.command()
        async def showsettings(self, ctx: commands.Context):
            channel = self.bot.get_channel(await self.config.discord_channel_id()) if await self.config.discord_channel_id() else None
            chat_path = await self.config.random_chat_path()
            chat_status = f"{len(self.random_chat_lines)} lines loaded" if chat_path and self.random_chat_lines else "Not set"
            msg = (
                f"**Current Settings:**\n"
                f"Log Base Path: `{await self.config.log_base_path() or 'Not set'}`\n"
                f"Discord Channel: {channel.mention if channel else 'Not set'} (ID: {await self.config.discord_channel_id() or 'Not set'})\n"
                f"RCON Host: `{await self.config.rcon_host() or 'Not set'}`\n"
                f"RCON Port: `{await self.config.rcon_port() or 'Not set'}`\n"
                f"RCON Password: {'Set' if await self.config.rcon_password() else 'Not set'}\n"
                f"Custom Emoji: `{await self.config.custom_emoji() or 'Not set'}`\n"
                f"Tracker URL: `{await self.config.tracker_url() or 'Not set'}`\n"
                f"Bot Name: `{await self.config.bot_name() or 'Not set'}`\n"
                f"Random Chat File: `{chat_path or 'Not set'}` → {chat_status}"
            )
            await ctx.send(msg)