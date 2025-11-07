import aiohttp
import discord
from redbot.core import commands
import re
from urllib.parse import quote

class CommandHandler:
    """Standalone commands – jkrcon, jkstatus, jkplayer."""

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
    async def jkstatus(self, ctx):
        """Show server status via ParaTracker."""
        async with aiohttp.ClientSession() as session:
            try:
                url = await self.config.tracker_url()
                if not url:
                    await ctx.send("Tracker URL not set. Use `jkbridge settrackerurl`.")
                    return
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await ctx.send(f"HTTP {resp.status}")
                        return
                    if 'application/json' not in resp.headers.get('Content-Type', ''):
                        await ctx.send("Expected JSON.")
                        return
                    data = await resp.json()

                si = data.get("serverInfo", {})
                info = data.get("info", {})
                players = data.get("players", [])

                name = self.remove_color_codes(si.get("servername", "Unknown"))
                map_ = si.get("mapname", "Unknown")
                maxc = int(si.get("sv_maxclients", "32"))
                player_count = f"{len(players)}/{maxc}"

                player_list = "No players" if not players else "```\n" + \
                    "ID | Name              | Score\n" + \
                    "\n".join(
                        f"{i:<2} | {(self.remove_color_codes(p.get('name',''))[:17]):<17} | {p.get('score','0'):<5}"
                        for i, p in enumerate(players)
                    ) + "\n```"

                e1 = discord.Embed(title=name, color=discord.Color.gold())
                e1.add_field(name="Players", value=player_count, inline=True)
                e1.add_field(name="Mod", value=self.remove_color_codes(info.get("gamename","")), inline=True)
                if v := info.get("Lugormod_Version"):
                    e1.add_field(name="Version", value=self.remove_color_codes(v), inline=True)
                e1.add_field(name="Map", value=f"`{map_}`", inline=True)
                e1.add_field(name="IP", value=si.get("serverIPAddress",""), inline=True)
                e1.add_field(name="Location", value=si.get("geoIPcountryCode","??").upper(), inline=True)

                if (ls := si.get("levelshotsArray")) and ls[0]:
                    e1.set_image(url=f"https://pt.dogi.us/{quote(ls[0]}" )

                e2 = discord.Embed(color_color=discord.Color.gold())
                e2.add_field(name="Players", value=player_list, inline=False)

                await ctx.send(embed=e1)
                await ctx.send(embed=e2)
            except Exception as e:
                await ctx.send(f"Failed: {e}")

    @commands.command(name="jkplayer")
    async def jkplayer(self, ctx, username: str):
        """Show player stats via accountinfo."""
        if not await self.validate_rcon_settings():
            await ctx.send("RCON not configured.")
            return
        cmd = f"accountinfo {username}"
        try:
            resp = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command,
                cmd, await self.config.rcon_host(),
                await self.config.rcon_port(), await self.config.rcon_password()
            )
            text = resp.decode('cp1252', errors='replace')
        except Exception as e:
            await ctx.send(f"Failed: {e}")
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

        embed = discord.Embed(title=f"Stats: {stats.get('Name', username)}", color=discord.Color.blue())
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