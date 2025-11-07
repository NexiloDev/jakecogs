import discord
from redbot.core import Config, commands

class ConfigHandler:
    def setup_config(self, bot):
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

        # Group command
        @commands.group(name="jkbridge", aliases=["jk"])
        @commands.is_owner()
        async def jkbridge(ctx):
            """JKChatBridge settings"""
            pass

        self.jkbridge = jkbridge

        # Subcommands
        @self.jkbridge.command()
        async def setlogbasepath(self, ctx, path: str):
            await self.config.log_base_path.set(path)
            if self.monitor_task and not self.monitor_task.done():
                self.monitoring = False
                self.monitor_task.cancel()
                try:
                    await self.monitor_task
                except asyncio.CancelledError:
                    pass
            self.start_monitoring()
            await ctx.send(f"Log base path set to: {path}. Monitoring restarted.")

        @self.jkbridge.command()
        async def setchannel(self, ctx, channel: discord.TextChannel):
            await self.config.discord_channel_id.set(channel.id)
            await ctx.send(f"Discord channel set to: {channel.name} (ID: {channel.id})")

        @self.jkbridge.command()
        async def setrconhost(self, ctx, host: str):
            await self.config.rcon_host.set(host)
            await ctx.send(f"RCON host set to: {host}")

        @self.jkbridge.command()
        async def setrconport(self, ctx, port: int):
            await self.config.rcon_port.set(port)
            await ctx.send(f"RCON port set to: {port}")

        @self.jkbridge.command()
        async def setrconpassword(self, ctx, password: str):
            await self.config.rcon_password.set(password)
            await ctx.send("RCON password set.")

        @self.jkbridge.command()
        async def setcustomemoji(self, ctx, emoji: str):
            await ctx.send("Custom emoji feature has been removed and is no longer used.")

        @self.jkbridge.command()
        async def settrackerurl(self, ctx, url: str):
            await self.config.tracker_url.set(url)
            await ctx.send(f"Tracker URL set to: {url}")

        @self.jkbridge.command()
        async def setbotname(self, ctx, name: str):
            await self.config.bot_name.set(name)
            await ctx.send(f"Bot name set to: {name}")

        @self.jkbridge.command()
        async def setvpnkey(self, ctx, key: str):
            await self.config.vpn_api_key.set(key)
            await ctx.send("VPN API key set.")

        @self.jkbridge.command()
        async def togglevpncheck(self, ctx):
            new = not await self.config.vpn_check_enabled()
            await self.config.vpn_check_enabled.set(new)
            await ctx.send(f"VPN detection {'enabled' if new else 'disabled'}.")

        @self.jkbridge.command()
        async def setchatpath(self, ctx, path: str):
            await self.config.random_chat_path.set(path)
            await self.load_random_chat_lines()
            count = len(self.random_chat_lines)
            await ctx.send(f"Random chat file set to: `{path}`\nLoaded **{count}** lines. Use `[p]reload JKChatBridge` after editing.")

        @self.jkbridge.command()
        async def showsettings(self, ctx):
            channel = self.bot.get_channel(await self.config.discord_channel_id()) if await self.config.discord_channel_id() else None
            chat_path = await self.config.random_chat_path()
            chat_status = f"{len(self.random_chat_lines)} lines loaded" if chat_path and self.random_chat_lines else "Not set"
            settings_message = (
                f"**Current Settings:**\n"
                f"Log Base Path: {await self.config.log_base_path() or 'Not set'}\n"
                f"Discord Channel: {channel.name if channel else 'Not set'} (ID: {await self.config.discord_channel_id() or 'Not set'})\n"
                f"RCON Host: {await self.config.rcon_host() or 'Not set'}\n"
                f"RCON Port: {await self.config.rcon_port() or 'Not set'}\n"
                f"RCON Password: {'Set' if await self.config.rcon_password() else 'Not set'}\n"
                f"Custom Emoji: {await self.config.custom_emoji() or 'Not set'}\n"
                f"Tracker URL: {await self.config.tracker_url() or 'Not set'}\n"
                f"Bot Name: {await self.config.bot_name() or 'Not set'}\n"
                f"Random Chat File: `{chat_path or 'Not set'}` → {chat_status}"
            )
            await ctx.send(settings_message)

        # Add jkexec, jkrcon, jktoggle, jkreload here as subcommands
        @self.jkbridge.command(name="jkexec")
        @commands.is_owner()
        @commands.has_permissions(administrator=True)
        async def jkexec(self, ctx, filename: str):
            if not await self.validate_rcon_settings():
                await ctx.send("RCON settings not fully configured.")
                return
            try:
                await self.bot.loop.run_in_executor(
                    self.executor, self.send_rcon_command, f"exec {filename}", await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
                )
                await ctx.send(f"Executed configuration file: {filename}")
            except Exception as e:
                await ctx.send(f"Failed to execute {filename}: {e}")

        @self.jkbridge.command(name="jkrcon")
        @commands.is_owner()
        @commands.has_permissions(administrator=True)
        async def jkrcon(self, ctx, *, command: str):
            if not await self.validate_rcon_settings():
                await ctx.send("RCON settings not fully configured.")
                return
            try:
                await self.bot.loop.run_in_executor(
                    self.executor, self.send_rcon_command, command, await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()
                )
                await ctx.send(f"RCON command sent: `{command}`")
            except Exception as e:
                await ctx.send(f"Failed to send RCON command `{command}`: {e}")

        @self.jkbridge.command(name="jktoggle")
        @commands.is_owner()
        @commands.has_permissions(administrator=True)
        async def jktoggle(self, ctx):
            current_state = await self.config.join_disconnect_enabled()
            new_state = not current_state
            await self.config.join_disconnect_enabled.set(new_state)
            state_text = "enabled" if new_state else "disabled"
            await ctx.send(f"Join and disconnect messages are now **{state_text}**.")

        @self.jkbridge.command(name="jkreload", aliases=["jkreloadmonitor"])
        async def reload_monitor(self, ctx: commands.Context = None):
            if self.monitor_task and not self.monitor_task.done():
                self.monitoring = False
                self.monitor_task.cancel()
                try:
                    await self.monitor_task
                except asyncio.CancelledError:
                    logger.debug("Monitoring task canceled successfully.")
                except Exception as e:
                    logger.error(f"Error canceling task: {e}")

            await asyncio.sleep(0.5)
            self.is_restarting = False
            self.restart_map = None
            self.start_monitoring()
            if ctx:
                await ctx.send("Log monitoring task reloaded.")