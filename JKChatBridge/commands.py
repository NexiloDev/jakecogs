import aiohttp
import discord
from redbot.core import commands
import re
from urllib.parse import quote

class JKCommands:
    @commands.command(name="jkrcon")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkrcon(self, ctx, *, command: str):
        """Send any RCON command to the server."""
        if not await self.validate_rcon_settings():
            await ctx.send("RCON settings not configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command,
                command, await self.config.rcon_host(),
                await self.config.rcon_port(), await self.config.rcon_password()
            )
            await ctx.send(f"RCON command sent: `{command}`")
        except Exception as e:
            await ctx.send(f"Failed to send RCON command `{command}`: {e}")

    @commands.command(name="jkstatus")
    async def status(self, ctx):
        """Display server status using ParaTracker."""
        async with aiohttp.ClientSession() as session:
            try:
                tracker_url = await self.config.tracker_url()
                if not tracker_url:
                    await ctx.send("Tracker URL not set. Use `jkbridge settrackerurl`.")
                    return

                async with session.get(tracker_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await ctx.send(f"Failed: HTTP {resp.status}")
                        return
                    if 'application/json' not in resp.headers.get('Content-Type', ''):
                        await ctx.send("Failed: Expected JSON.")
                        return
                    data = await resp.json()

                server_info = data.get("serverInfo", {})
                info = data.get("info", {})
                players = data.get("players", [])

                server_name = self.remove_color_codes(server_info.get("servername", "Unknown"))
                map_name = server_info.get("mapname", "Unknown")
                max_players = int(server_info.get("sv_maxclients", "32"))
                humans = sum(1 for p in players if p.get("ping", "0") != "0")
                bots = len(players) - humans
                player_count = f"{len(players)}/{max_players}"

                player_list = "No players" if not players else "```\n" + \
                    "ID  | Name              | Score\n" + \
                    "\n".join(
                        f"{i:<3} | {(self.remove_color_codes(p.get('name', ''))[:17]):<17} | {p.get('score', '0'):<5}"
                        for i, p in enumerate(players)
                    ) + "\n```"

                embed1 = discord.Embed(title=server_name, color=discord.Color.gold())
                embed1.add_field(name="Players", value=player_count, inline=True)
                mod = self.remove_color_codes(info.get("gamename", "Unknown"))
                embed1.add_field(name="Mod", value=mod, inline=True)
                version = info.get("Lugormod_Version")
                if version:
                    embed1.add_field(name="Version", value=self.remove_color_codes(version), inline=True)
                embed1.add_field(name="Map", value=f"`{map_name}`", inline=True)
                embed1.add_field(name="IP", value=server_info.get("serverIPAddress", "Unknown"), inline=True)
                embed1.add_field(name="Location", value=server_info.get("geoIPcountryCode", "??").upper(), inline=True)

                levelshots = server_info.get("levelshotsArray", [])
                if levelshots and levelshots[0]:
                    image_url = f"https://pt.dogi.us/{quote(levelshots[0])}"
                    embed1.set_image(url=image_url)

                embed2 = discord.Embed(color=discord.Color.gold())
                embed2.add_field(name="Players", value=player_list, inline=False)

                await ctx.send(embed=embed1)
                await ctx.send(embed=embed2)
            except Exception as e:
                await ctx.send(f"Failed to fetch status: {e}")

    @commands.command(name="jkplayer")
    async def player_info(self, ctx, username: str):
        """Show player stats via accountinfo."""
        if not await self.validate_rcon_settings():
            await ctx.send("RCON not configured.")
            return

        command = f"accountinfo {username}"
        try:
            response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command,
                command, await self.config.rcon_host(),
                await self.config.rcon_port(), await self.config.rcon_password()
            )
            text = response.decode('cp1252', errors='replace')
        except Exception as e:
            await ctx.send(f"Failed to get info: {e}")
            return

        stats = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('\xff'):
                continue
            if ":" in line:
                k, v = map(str.strip, line.split(":", 1))
                stats[self.remove_color_codes(k)] = self.remove_color_codes(v)

        if "Id" not in stats:
            await ctx.send(f"Player `{username}` not found.")
            return

        wins = int(stats.get("Duels won", "0"))
        total = int(stats.get("Total duels", "0"))
        losses = max(0, total - wins)
        playtime = stats.get("Time", "N/A")
        if ":" in playtime:
            playtime = f"{playtime.split(':')[0]} Hrs"

        embed = discord.Embed(
            title=f"Stats: {stats.get('Name', username)}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Playtime", value=playtime, inline=True)
        embed.add_field(name="Level", value=stats.get("Level", "N/A"), inline=True)
        embed.add_field(name="Profession", value=stats.get("Profession", "N/A"), inline=True)
        embed.add_field(name="Credits", value=stats.get("Credits", "N/A"), inline=True)
        embed.add_field(name="Stashes", value=stats.get("Stashes", "N/A"), inline=True)
        embed.add_field(name="Duel Score", value=stats.get("Score", "N/A"), inline=True)
        embed.add_field(name="Duels Won", value=str(wins), inline=True)
        embed.add_field(name="Duels Lost", value=str(losses), inline=True)
        embed.add_field(name="Kills", value=stats.get("Kills", "0"), inline=True)
        embed.set_footer(text=f"Last Login: {stats.get('Last login', 'N/A')}")

        await ctx.send(embed=embed)