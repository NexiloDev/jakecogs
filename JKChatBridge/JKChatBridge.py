import asyncio
import discord
from redbot.core import Config, commands
import aiofiles
import os
import socket
from concurrent.futures import ThreadPoolExecutor
import re
from datetime import datetime

# Custom permission check for "JKA Server Admin" role or higher
def is_jka_server_staff_or_higher():
    async def predicate(ctx):
        jka_server_admin_role = discord.utils.get(ctx.guild.roles, id=1162780867886862458)
        return (
            (jka_server_admin_role in ctx.author.roles if jka_server_admin_role else False) or
            ctx.author.guild_permissions.administrator or
            await ctx.bot.is_owner(ctx.author)
        )
    return commands.check(predicate)

class JKChatBridge(commands.Cog):
    """Bridges public chat between Jedi Knight: Jedi Academy and Discord via RCON, with dynamic log file support for Lugormod.

    **Commands:**
    - `!jkstatus`: Show server status.
    - `!jkplayer <username>`: Show player stats.
    - `!jkexec <filename>`: Execute a server config file (Bot Owners/Admins only).
    - `!jkkill <player>`: Kill a player (Bot Owners/Admins only).
    - `!jkkick <player>`: Kick a player (Bot Owners/Admins only).
    - `!jknextmap`: Call and pass a vote for the next map (JKA Server Admin, Bot Owners, Admins).
    - `!jkchpasswd <player> <newpassword>`: Change a player's password (Bot Owners/Admins only).
    - `!jkbridge`: Configure the cog (Bot Owner only).
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        self.config.register_global(
            log_base_path=None,
            discord_channel_id=None,
            rcon_host="127.0.0.1",
            rcon_port=29070,
            rcon_password=None,
            custom_emoji="<:jk:1219115870928900146>",
            log_channel_id=None
        )
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.monitoring = False
        self.monitor_task = None
        self.client_names = {}
        self.last_connected_client = None
        self.url_pattern = re.compile(
            r'(https?://[^\s]+|www\.[^\s]+|\b[a-zA-Z0-9-]+\.(com|org|net|edu|gov|io|co|uk|ca|de|fr|au|us|ru|ch|it|nl|se|no|es|mil)(/[^\s]*)?)',
            re.IGNORECASE
        )
        self.start_monitoring()

    async def cog_load(self):
        """Initialize player data when the cog loads."""
        await self.fetch_player_data()

    async def validate_rcon_settings(self):
        """Validate that RCON settings are fully configured."""
        rcon_host = await self.config.rcon_host()
        rcon_port = await self.config.rcon_port()
        rcon_password = await self.config.rcon_password()
        return (all([rcon_host, rcon_port, rcon_password]), (rcon_host, rcon_port, rcon_password))

    async def fetch_player_data(self, ctx=None):
        """Fetch and update player data from the game server."""
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid or ctx:
            return
        try:
            playerlist_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "playerlist", rcon_host, rcon_port, rcon_password
            )
            temp_client_names = {}
            for line in playerlist_response.decode(errors='replace').splitlines():
                if "Credits in the world" in line or "Total number of registered accounts" in line or "Ind Player" in line or "----" in line:
                    continue
                parts = re.split(r"\s+", line.strip())
                if len(parts) >= 6 and parts[0].startswith("^") and self.remove_color_codes(parts[0]).isdigit():
                    client_id = self.remove_color_codes(parts[0])
                    player_name = self.remove_color_codes(parts[1])
                    username = parts[-1] if (parts[-1].isalpha() or not parts[-1].isdigit()) else None
                    temp_client_names[client_id] = (player_name, username)
            for client_id, (name, username) in temp_client_names.items():
                existing_name, _ = self.client_names.get(client_id, (None, None))
                self.client_names[client_id] = (existing_name or name, username)
        except Exception:
            pass

    ### Configuration Commands
    @commands.group(name="jkbridge", aliases=["jk"])
    @commands.is_owner()
    async def jkbridge(self, ctx):
        """Configure the JK chat bridge (Bot Owner only)."""
        pass

    @jkbridge.command()
    async def setlogbasepath(self, ctx, path: str):
        """Set the base path for Lugormod log files."""
        await self.config.log_base_path.set(path)
        await ctx.send(f"Log base path set to: {path}")

    @jkbridge.command()
    async def setchannel(self, ctx, channel: discord.TextChannel):
        """Set the Discord channel for chat bridging."""
        await self.config.discord_channel_id.set(channel.id)
        await ctx.send(f"Discord channel set to: {channel.name} (ID: {channel.id})")

    @jkbridge.command()
    async def setrconhost(self, ctx, host: str):
        """Set the RCON host address."""
        await self.config.rcon_host.set(host)
        await ctx.send(f"RCON host set to: {host}")

    @jkbridge.command()
    async def setrconport(self, ctx, port: int):
        """Set the RCON port."""
        await self.config.rcon_port.set(port)
        await ctx.send(f"RCON port set to: {port}")

    @jkbridge.command()
    async def setrconpassword(self, ctx, password: str):
        """Set the RCON password."""
        await self.config.rcon_password.set(password)
        await ctx.send("RCON password set.")

    @jkbridge.command()
    async def setcustomemoji(self, ctx, emoji: str):
        """Set the custom emoji for game-to-Discord messages."""
        await self.config.custom_emoji.set(emoji)
        await ctx.send(f"Custom emoji set to: {emoji}")

    @jkbridge.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the private log channel for admin actions and errors."""
        await self.config.log_channel_id.set(channel.id)
        await ctx.send(f"Log channel set to: {channel.name} (ID: {channel.id})")

    @jkbridge.command()
    async def showsettings(self, ctx):
        """Display current configuration settings."""
        settings = {
            "Log Base Path": await self.config.log_base_path() or "Not set",
            "Discord Channel": (channel := self.bot.get_channel(await self.config.discord_channel_id())) and channel.name or "Not set",
            "RCON Host": await self.config.rcon_host() or "Not set",
            "RCON Port": await self.config.rcon_port() or "Not set",
            "RCON Password": "Set" if await self.config.rcon_password() else "Not set",
            "Custom Emoji": await self.config.custom_emoji() or "Not set",
            "Log Channel": (log_channel := self.bot.get_channel(await self.config.log_channel_id())) and log_channel.name or "Not set"
        }
        await ctx.send("**Current Settings:**\n" + "\n".join(f"{k}: {v}" for k, v in settings.items()))

    @jkbridge.command()
    async def reloadmonitor(self, ctx):
        """Reload the log monitoring task and refresh player data."""
        if self.monitor_task and not self.monitor_task.done():
            self.monitoring = False
            self.monitor_task.cancel()
            await self.monitor_task
        self.client_names.clear()
        self.start_monitoring()
        await self.fetch_player_data()
        await ctx.send("Log monitoring and player data reloaded.")

    ### Public Commands
    @commands.command(name="jkstatus")
    async def status(self, ctx):
        """Display server status with player count and details.

        **Usage:** `!jkstatus`
        """
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.fetch_player_data()
            status_response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "status", rcon_host, rcon_port, rcon_password
            )
            status_lines = status_response.decode(errors='replace').splitlines()
            server_info = {"server_name": "Unknown", "mod_name": "Unknown", "map_name": "Unknown", "player_count": "0 humans, 0 bots"}
            for line in status_lines:
                if "hostname:" in line:
                    server_info["server_name"] = self.remove_color_codes(line.split("hostname:")[1].strip()).encode('ascii', 'ignore').decode()
                elif "game    :" in line:
                    server_info["mod_name"] = line.split("game    :")[1].strip()
                elif "map     :" in line:
                    server_info["map_name"] = line.split("map     :")[1].split()[0].strip()
                elif "players :" in line:
                    server_info["player_count"] = line.split("players :")[1].strip()
            players = [f"{cid:<3} {name}{f' ({username})' if username else ''}" for cid, (name, username) in self.client_names.items()]
            embed = discord.Embed(title=f"🌌 {server_info['server_name']} 🌌", color=discord.Color.gold())
            embed.add_field(name="👥 Players", value=server_info["player_count"], inline=True)
            embed.add_field(name="🗺️ Map", value=f"`{server_info['map_name']}`", inline=True)
            embed.add_field(name="🎮 Mod", value=server_info["mod_name"], inline=True)
            embed.add_field(name="📋 Online Players", value="```\n" + ("\n".join(players) or "No players online") + "\n```", inline=False)
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Failed to retrieve server status: {e}")
            await self.log_action(f"Error retrieving server status: {e}")

    @commands.command(name="jkplayer")
    async def player_info(self, ctx, username: str):
        """Display detailed stats for a player.

        **Usage:** `!jkplayer <username>`
        **Example:** `!jkplayer Padawan`
        """
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            response = await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"accountinfo {username}", rcon_host, rcon_port, rcon_password
            )
            response_text = response.decode('utf-8', errors='replace')
            stats = {}
            for line in response_text.splitlines():
                if re.match(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', line) or line.startswith('\xff\xff\xff\xffprint'):
                    continue
                if ":" in line:
                    key, value = map(str.strip, line.split(":", 1))
                else:
                    parts = re.split(r'\s{2,}', line)
                    if len(parts) >= 2:
                        key, value = parts[0], parts[-1]
                    else:
                        continue
                stats[self.remove_color_codes(key)] = self.remove_color_codes(value)
            if "Id" not in stats and "Username" not in stats:
                await ctx.send(f"Player '{username}' not found.")
                return
            wins = int(stats.get("Duels won", "0"))
            total_duels = int(stats.get("Total duels", "0"))
            playtime = stats.get("Time", "N/A")
            if ":" in playtime and playtime != "N/A":
                playtime = f"{playtime.split(':')[0]} Hrs"
            player_name = stats.get("Name", username).encode('utf-8', 'replace').decode()
            embed = discord.Embed(title=f"Player Stats for {player_name} *({stats.get('Username', 'N/A')})*", color=discord.Color.blue())
            embed.add_field(name="⏱️ Playtime", value=playtime, inline=True)
            embed.add_field(name="🔼 Level", value=stats.get("Level", "N/A"), inline=True)
            embed.add_field(name="🛡️ Profession", value=stats.get("Profession", "N/A"), inline=True)
            embed.add_field(name="💰 Credits", value=stats.get("Credits", "N/A"), inline=True)
            embed.add_field(name="💼 Stashes", value=stats.get("Stashes", "N/A"), inline=True)
            embed.add_field(name="🏆 Duel Score", value=stats.get("Score", "N/A"), inline=True)
            embed.add_field(name="⚔️ Duels Won", value=str(wins), inline=True)
            embed.add_field(name="⚔️ Duels Lost", value=str(max(0, total_duels - wins)), inline=True)
            embed.add_field(name="🗡️ Total Kills", value=stats.get("Kills", "0"), inline=True)
            embed.set_footer(text=f"Last Login: {stats.get('Last login', 'N/A')}")
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"Failed to retrieve player info: {e}")
            await self.log_action(f"Error retrieving player info for {username}: {e}")

    ### Chat Bridging
    @commands.Cog.listener()
    async def on_message(self, message):
        """Send Discord messages to the game server."""
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        prefix = await self.bot.command_prefix(self.bot, message)
        prefix = prefix[0] if isinstance(prefix, (tuple, list)) else str(prefix)
        username = self.clean_special_characters(message.author.display_name)
        content = self.replace_emojis_with_names(self.clean_special_characters(message.content))
        if self.url_pattern.search(content):
            return
        chunks = []
        remaining = content
        is_first = True
        while remaining:
            max_len = 115 if is_first else 128 - len("say ")
            if len(remaining) <= max_len:
                chunks.append(remaining)
                break
            split_point = remaining.rfind(' ', 0, max_len + 1) or max_len
            chunks.append(remaining[:split_point].strip())
            remaining = remaining[split_point:].strip()
            is_first = False
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await message.channel.send("RCON settings not fully configured.")
            return
        try:
            for i, chunk in enumerate(chunks):
                cmd = f"say ^5{{D}}^7{username}^2: {chunk}" if i == 0 else f"say {chunk}"
                await self.bot.loop.run_in_executor(self.executor, self.send_rcon_command, cmd, rcon_host, rcon_port, rcon_password)
                await asyncio.sleep(0.1)
        except Exception as e:
            await message.channel.send(f"Failed to send to game: {e}")
            await self.log_action(f"Failed to send message to game: {e}")

    def clean_special_characters(self, text):
        """Replace special characters with simpler equivalents."""
        replacements = {"’": "'", "‘": "'", "“": "\"", "”": "\"", "«": "\"", "»": "\"", "–": "-", "—": "-", "…": "..."}
        return "".join(replacements.get(c, c) for c in text)

    def replace_emojis_with_names(self, text):
        """Convert emojis to text representations."""
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        emoji_map = {
            "😊": ":)", "😄": ":D", "😂": "XD", "🤣": "xD", "😉": ";)", "😛": ":P", "😢": ":(", "😡": ">:(", 
            "👍": ":+1:", "👎": ":-1:", "❤️": "<3", "💖": "<3", "😍": ":*", "🙂": ":)", "😣": ":S", "😜": ";P",
            "😮": ":o", "😁": "=D", "😆": "xD", "😳": "O.o", "🤓": "B)", "😴": "-_-", "😅": "^^;", "😒": ":/", 
            "😘": ":*", "😎": "8)", "😱": "D:", "🤔": ":?", "🥳": "\\o/", "🤗": ">^.^<", "🤪": ":p"
        }
        return "".join(emoji_map.get(c, c) for c in text)

    def replace_text_emotes_with_emojis(self, text):
        """Convert text emotes to emojis."""
        emote_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢", ">:(": "😡",
            ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣", ";P": "😜", ":o": "😮", "=D": "😁",
            "O.o": "😳", "B)": "🤓", "-_-": "😴", "^^;": "😅", ":/": "😒", "8)": "😎", "D:": "😱", ":?": "🤔",
            "\\o/": "🥳", ">^.^<": "🤗", ":p": "🤪"
        }
        for emote, emoji in emote_map.items():
            text = text.replace(emote, emoji)
        return text

    ### Log Monitoring
    async def monitor_log(self):
        """Monitor game logs and send events to Discord."""
        self.monitoring = True
        while self.monitoring:
            log_base_path = await self.config.log_base_path()
            channel_id = await self.config.discord_channel_id()
            custom_emoji = await self.config.custom_emoji()
            if not all([log_base_path, channel_id, custom_emoji]):
                await asyncio.sleep(5)
                continue
            channel = self.bot.get_channel(channel_id)
            log_file = os.path.join(log_base_path, f"games_{datetime.now().strftime('%m-%d-%Y')}.log")
            try:
                async with aiofiles.open(log_file, 'r') as f:
                    await f.seek(0, 2)
                    while self.monitoring:
                        line = await f.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        line = line.strip()
                        if "say:" in line and "tell:" not in line and "[Discord]" not in line:
                            player_name, message = self.parse_chat_line(line)
                            if player_name and message and not self.url_pattern.search(message):
                                await channel.send(f"{custom_emoji} **{player_name}**: {self.replace_text_emotes_with_emojis(message)}")
                        elif "ClientConnect:" in line:
                            self.last_connected_client = line.split("ClientConnect: ")[1].strip()
                        elif "ClientUserinfoChanged" in line and self.last_connected_client:
                            client_id = line.split("ClientUserinfoChanged")[1].split(": ")[1].split()[0]
                            if client_id == self.last_connected_client and "Padawan" not in line:
                                name = self.remove_color_codes(re.search(r"(\\name\\|n\\)([^\\]+)", line).group(2))
                                self.client_names[client_id] = (name, None)
                                if not name.endswith("-Bot"):
                                    await channel.send(f"<:jk_connect:1349009924306374756> **{name}** has joined the game!")
                                self.last_connected_client = None
                        elif "has logged in" in line:
                            match = re.search(r'Player "([^"]+)" \(([^)]+)\) has logged in', line)
                            if match:
                                name, username = self.remove_color_codes(match.group(1)), match.group(2)
                                for cid, (n, _) in self.client_names.items():
                                    if n == name:
                                        self.client_names[cid] = (name, username)
                                        break
                                await self.fetch_player_data()
                        elif "has logged out" in line:
                            match = re.search(r'Player "([^"]+)" \(([^)]+)\) has logged out', line)
                            if match:
                                name = self.remove_color_codes(match.group(1))
                                for cid, (n, _) in self.client_names.items():
                                    if n == name:
                                        self.client_names[cid] = (n, None)
                                        break
                        elif "ClientDisconnect:" in line:
                            client_id = line.split("ClientDisconnect: ")[1].strip()
                            name, _ = self.client_names.pop(client_id, (f"Unknown (ID {client_id})", None))
                            if not name.endswith("-Bot"):
                                await channel.send(f"<:jk_disconnect:1349010016044187713> **{name}** has disconnected.")
                        elif "duel:" in line and "won a duel against" in line:
                            winner, loser = map(self.remove_color_codes, line.split("duel:")[1].split("won a duel against"))
                            await channel.send(f"<a:peepoBeatSaber:1228624251800522804> **{winner.strip()}** won a duel against **{loser.strip()}**!")
            except Exception as e:
                await self.log_action(f"Error in monitor_log: {e}")
                await asyncio.sleep(5)

    def start_monitoring(self):
        """Start the log monitoring task."""
        if not self.monitor_task or self.monitor_task.done():
            self.monitor_task = self.bot.loop.create_task(self.monitor_log())

    def parse_chat_line(self, line):
        """Extract player name and message from a chat log line."""
        say_idx = line.find("say: ")
        if say_idx != -1:
            chat = line[say_idx + 5:]
            colon_idx = chat.find(": ")
            if colon_idx != -1:
                return self.remove_color_codes(chat[:colon_idx].strip()), self.remove_color_codes(chat[colon_idx + 2:].strip())
        return None, None

    ### Admin Commands
    @commands.command(name="jkexec")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkexec(self, ctx, filename: str):
        """Execute a server configuration file.

        **Usage:** `!jkexec <filename>`
        **Example:** `!jkexec server.cfg`
        """
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"exec {filename}", rcon_host, rcon_port, rcon_password
            )
            await ctx.send(f"Executed configuration file: {filename}")
            await self.log_action(f"Admin {ctx.author.name} executed {filename}")
        except Exception as e:
            await ctx.send(f"Failed to execute {filename}: {e}")
            await self.log_action(f"Error: Failed to execute {filename} - {e}")

    @commands.command(name="jkkill")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkkill(self, ctx, player: str):
        """Kill a player in the game.

        **Usage:** `!jkkill <player>`
        **Example:** `!jkkill Padawan`
        """
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"killother {player}", rcon_host, rcon_port, rcon_password
            )
            await ctx.send(f"Player {player} has been killed.")
            await self.log_action(f"Admin {ctx.author.name} killed player {player}")
        except Exception as e:
            await ctx.send(f"Failed to kill player: {e}")
            await self.log_action(f"Error: Failed to kill player {player} - {e}")

    @commands.command(name="jkkick")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkkick(self, ctx, player: str):
        """Kick a player from the game.

        **Usage:** `!jkkick <player>`
        **Example:** `!jkkick Padawan`
        """
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"kick {player}", rcon_host, rcon_port, rcon_password
            )
            await ctx.send(f"Player {player} has been kicked.")
            await self.log_action(f"Admin {ctx.author.name} kicked player {player}")
        except Exception as e:
            await ctx.send(f"Failed to kick player: {e}")
            await self.log_action(f"Error: Failed to kick player {player} - {e}")

    @commands.command(name="jknextmap")
    @is_jka_server_staff_or_higher()
    async def jknextmap(self, ctx):
        """Call and pass a vote for the next map.

        **Usage:** `!jknextmap`
        """
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "callvote nextmap", rcon_host, rcon_port, rcon_password
            )
            await asyncio.sleep(0.5)
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, "passvote", rcon_host, rcon_port, rcon_password
            )
            await ctx.send("Vote for next map has been called and passed.")
            await self.log_action(f"{ctx.author.name} called and passed nextmap vote")
        except Exception as e:
            await ctx.send(f"Failed to call/pass nextmap vote: {e}")
            await self.log_action(f"Error: Failed to call/pass nextmap vote - {e}")

    @commands.command(name="jkchpasswd")
    @commands.is_owner()
    @commands.has_permissions(administrator=True)
    async def jkchpasswd(self, ctx, player: str, newpassword: str):
        """Change a player's password.

        **Usage:** `!jkchpasswd <player> <newpassword>`
        **Example:** `!jkchpasswd Padawan newpass123`
        """
        is_valid, (rcon_host, rcon_port, rcon_password) = await self.validate_rcon_settings()
        if not is_valid:
            await ctx.send("RCON settings not fully configured.")
            return
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command, f"chpasswd {player} {newpassword}", rcon_host, rcon_port, rcon_password
            )
            await ctx.send(f"Password for {player} has been changed to {newpassword}.")
            await self.log_action(f"Admin {ctx.author.name} changed password for {player}")
        except Exception as e:
            await ctx.send(f"Failed to change password: {e}")
            await self.log_action(f"Error: Failed to change password for {player} - {e}")

    ### Utility Methods
    def send_rcon_command(self, command, host, port, password):
        """Send an RCON command to the game server."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(5)
        packet = b'\xff\xff\xff\xffrcon ' + password.encode() + b' ' + command.encode()
        try:
            sock.sendto(packet, (host, port))
            return sock.recvfrom(4096)[0]
        except socket.timeout:
            raise Exception("RCON command timed out.")
        except Exception as e:
            raise Exception(f"Error sending RCON command: {e}")
        finally:
            sock.close()

    def remove_color_codes(self, text):
        """Remove Jedi Academy color codes from text."""
        return re.sub(r'\^\d', '', text)

    async def log_action(self, message):
        """Log an action or error to the configured log channel."""
        log_channel_id = await self.config.log_channel_id()
        if log_channel_id and (log_channel := self.bot.get_channel(log_channel_id)):
            await log_channel.send(f"[{datetime.now()}] {message}")

    async def cog_unload(self):
        """Clean up when unloading the cog."""
        self.monitoring = False
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            await self.monitor_task
        self.executor.shutdown(wait=False)

async def setup(bot):
    """Load the JKChatBridge cog into the bot."""
    await bot.add_cog(JKChatBridge(bot))