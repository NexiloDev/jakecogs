import discord
from discord.ext import tasks
from redbot.core import commands, Config
from redbot.core.bot import Red
import github
from github import Github, Auth
from datetime import datetime, timezone
import logging
import re

class RepoMonitor(commands.Cog):
    """A cog to monitor up to 5 GitHub repositories for new issues, PRs, merged PRs, and releases.

    Created by Jakendary for the Nexilo.org community.
    Use `[p]rm tokenset` to set your GitHub API token, then `[p]rm addrepoN` and `[p]rm setchannelN` (N=1 to 5) to configure repositories and channels.
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210)
        default_guild = {
            "repos": [None] * 5,
            "channels": [None] * 5,
            "last_issue_times": [None] * 5,
            "last_pr_times": [None] * 5,
            "last_merged_pr_times": [None] * 5,
            "last_release_times": [None] * 5
        }
        self.config.register_guild(**default_guild)
        self.github_client = None
        self.monitor_task.start()

    def cog_unload(self):
        self.monitor_task.cancel()

    async def initialize_github_client(self):
        """Initialize the GitHub client with the stored token."""
        token = await self.bot.get_shared_api_tokens("github.com")
        if not token.get("token"):
            logging.error("GitHub API token not set. Use '[p]rm tokenset <your-token>'.")
            return None
        return Github(auth=Auth.Token(token["token"]))

    def parse_repo_name(self, input_str: str) -> str:
        """Parse a repository name or URL into owner/repo-name format."""
        url_pattern = r"https?://github\.com/([^/]+)/([^/]+)"
        match = re.match(url_pattern, input_str)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
        return input_str

    @commands.group(name="repomonitor", aliases=["rm"])
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def repo_monitor(self, ctx: commands.Context):
        """Manage GitHub repository monitoring.

        Created by Jakendary for Nexilo.org.
        Use `[p]rm tokenset` to set your GitHub API token.
        Use `[p]rm addrepoN` to add a repository (N=1 to 5).
        Use `[p]rm setchannelN` to set the alert channel for each repository.
        """
        pass

    @repo_monitor.command(name="tokenset")
    async def set_github_token(self, ctx: commands.Context, token: str):
        """Set the GitHub API token for repository monitoring.

        Example: [p]rm tokenset <your-token>
        Obtain a token with 'repo' scope at https://github.com/settings/tokens.
        """
        await self.bot.set_shared_api_tokens("github.com", token=token)
        self.github_client = await self.initialize_github_client()
        if self.github_client:
            await ctx.send("✅ GitHub API token set successfully.")
        else:
            await ctx.send("❌ Failed to set GitHub API token. Please check the token and try again.")

    @repo_monitor.command(name="addrepo1")
    async def add_repo1(self, ctx: commands.Context, repo_name: str):
        """Add a GitHub repository to monitor in slot 1.

        Example: [p]rm addrepo1 owner/repo-name or [p]rm addrepo1 https://github.com/owner/repo-name
        You can monitor up to 5 repositories. Created by Jakendary for Nexilo.org.
        """
        repo_name = self.parse_repo_name(repo_name)
        async with self.config.guild(ctx.guild).repos() as repos:
            repos[0] = repo_name
        await ctx.send(f"✅ Repository {repo_name} added to slot 1.")

    @repo_monitor.command(name="addrepo2")
    async def add_repo2(self, ctx: commands.Context, repo_name: str):
        """Add a GitHub repository to monitor in slot 2.

        Example: [p]rm addrepo2 owner/repo-name or [p]rm addrepo2 https://github.com/owner/repo-name
        You can monitor up to 5 repositories. Created by Jakendary for Nexilo.org.
        """
        repo_name = self.parse_repo_name(repo_name)
        async with self.config.guild(ctx.guild).repos() as repos:
            repos[1] = repo_name
        await ctx.send(f"✅ Repository {repo_name} added to slot 2.")

    @repo_monitor.command(name="addrepo3")
    async def add_repo3(self, ctx: commands.Context, repo_name: str):
        """Add a GitHub repository to monitor in slot 3.

        Example: [p]rm addrepo3 owner/repo-name or [p]rm addrepo3 https://github.com/owner/repo-name
        You can monitor up to 5 repositories. Created by Jakendary for Nexilo.org.
        """
        repo_name = self.parse_repo_name(repo_name)
        async with self.config.guild(ctx.guild).repos() as repos:
            repos[2] = repo_name
        await ctx.send(f"✅ Repository {repo_name} added to slot 3.")

    @repo_monitor.command(name="addrepo4")
    async def add_repo4(self, ctx: commands.Context, repo_name: str):
        """Add a GitHub repository to monitor in slot 4.

        Example: [p]rm addrepo4 owner/repo-name or [p]rm addrepo4 https://github.com/owner/repo-name
        You can monitor up to 5 repositories. Created by Jakendary for Nexilo.org.
        """
        repo_name = self.parse_repo_name(repo_name)
        async with self.config.guild(ctx.guild).repos() as repos:
            repos[3] = repo_name
        await ctx.send(f"✅ Repository {repo_name} added to slot 4.")

    @repo_monitor.command(name="addrepo5")
    async def add_repo5(self, ctx: commands.Context, repo_name: str):
        """Add a GitHub repository to monitor in slot 5.

        Example: [p]rm addrepo5 owner/repo-name or [p]rm addrepo5 https://github.com/owner/repo-name
        You can monitor up to 5 repositories. Created by Jakendary for Nexilo.org.
        """
        repo_name = self.parse_repo_name(repo_name)
        async with self.config.guild(ctx.guild).repos() as repos:
            repos[4] = repo_name
        await ctx.send(f"✅ Repository {repo_name} added to slot 5.")

    @repo_monitor.command(name="setchannel1")
    async def set_channel1(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the Discord channel for alerts from repository in slot 1.

        Example: [p]rm setchannel1 #channel
        If no channel is provided, uses the current channel. Created by Jakendary for Nexilo.org.
        """
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[0] = channel.id
        await ctx.send(f"✅ Alerts for repository in slot 1 will be sent to {channel.mention}.")

    @repo_monitor.command(name="setchannel2")
    async def set_channel2(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the Discord channel for alerts from repository in slot 2.

        Example: [p]rm setchannel2 #channel
        If no channel is provided, uses the current channel. Created by Jakendary for Nexilo.org.
        """
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[1] = channel.id
        await ctx.send(f"✅ Alerts for repository in slot 2 will be sent to {channel.mention}.")

    @repo_monitor.command(name="setchannel3")
    async def set_channel3(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the Discord channel for alerts from repository in slot 3.

        Example: [p]rm setchannel3 #channel
        If no channel is provided, uses the current channel. Created by Jakendary for Nexilo.org.
        """
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[2] = channel.id
        await ctx.send(f"✅ Alerts for repository in slot 3 will be sent to {channel.mention}.")

    @repo_monitor.command(name="setchannel4")
    async def set_channel4(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the Discord channel for alerts from repository in slot 4.

        Example: [p]rm setchannel4 #channel
        If no channel is provided, uses the current channel. Created by Jakendary for Nexilo.org.
        """
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[3] = channel.id
        await ctx.send(f"✅ Alerts for repository in slot 4 will be sent to {channel.mention}.")

    @repo_monitor.command(name="setchannel5")
    async def set_channel5(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Set the Discord channel for alerts from repository in slot 5.

        Example: [p]rm setchannel5 #channel
        If no channel is provided, uses the current channel. Created by Jakendary for Nexilo.org.
        """
        channel = channel or ctx.channel
        async with self.config.guild(ctx.guild).channels() as channels:
            channels[4] = channel.id
        await ctx.send(f"✅ Alerts for repository in slot 5 will be sent to {channel.mention}.")

    @tasks.loop(minutes=5.0)
    async def monitor_task(self):
        """Background task to check for new GitHub events across all configured repositories."""
        if self.github_client is None:
            self.github_client = await self.initialize_github_client()
            if self.github_client is None:
                return

        for guild in self.bot.guilds:
            async with self.config.guild(guild).all() as conf:
                for i in range(5):
                    repo_name = conf["repos"][i]
                    channel_id = conf["channels"][i]
                    if not repo_name or not channel_id:
                        continue

                    channel = guild.get_channel(channel_id)
                    if not channel:
                        continue

                    try:
                        repo = self.github_client.get_repo(repo_name)
                        await self.check_issues(repo, guild, channel, conf, i)
                        await self.check_prs(repo, guild, channel, conf, i)
                        await self.check_releases(repo, guild, channel, conf, i)
                    except github.GithubException as e:
                        logging.error(f"Error accessing repo {repo_name}: {e}")
                        await channel.send(f"⚠️ Error accessing repository {repo_name}: {e.data.get('message', 'Unknown error')}. Please verify the repository name or token.")

    async def check_issues(self, repo, guild, channel, conf, index):
        """Check for new issues in the repository."""
        last_issue_time = conf["last_issue_times"][index]
        last_time = datetime.fromisoformat(last_issue_time.replace("Z", "+00:00")) if last_issue_time else datetime.min.replace(tzinfo=timezone.utc)

        for issue in repo.get_issues(state="open", sort="created", direction="desc"):
            if issue.created_at <= last_time:
                break
            if not issue.pull_request:  # Ensure it's an issue, not a PR
                embed = discord.Embed(
                    title=f"🆕 New Issue: {issue.title}",
                    url=issue.html_url,
                    description=issue.body[:500] + "..." if issue.body and len(issue.body) > 500 else issue.body or "No description provided.",
                    color=discord.Color.red(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_author(name=issue.user.login, icon_url=issue.user.avatar_url)
                embed.add_field(name="Repository", value=repo.full_name, inline=True)
                embed.add_field(name="Issue Number", value=f"#{issue.number}", inline=True)
                embed.set_footer(text="GitHub Issue")
                await channel.send(embed=embed)
                last_time = max(last_time, issue.created_at)

        if last_time != datetime.min.replace(tzinfo=timezone.utc):
            conf["last_issue_times"][index] = last_time.isoformat()

    async def check_prs(self, repo, guild, channel, conf, index):
        """Check for new and merged PRs in the repository."""
        last_pr_time = conf["last_pr_times"][index]
        last_merged_pr_time = conf["last_merged_pr_times"][index]
        last_pr_time_dt = datetime.fromisoformat(last_pr_time.replace("Z", "+00:00")) if last_pr_time else datetime.min.replace(tzinfo=timezone.utc)
        last_merged_pr_time_dt = datetime.fromisoformat(last_merged_pr_time.replace("Z", "+00:00")) if last_merged_pr_time else datetime.min.replace(tzinfo=timezone.utc)

        for pr in repo.get_pulls(state="all", sort="updated", direction="desc"):
            if pr.created_at > last_pr_time_dt and pr.state == "open":
                embed = discord.Embed(
                    title=f"🔄 New Pull Request: {pr.title}",
                    url=pr.html_url,
                    description=pr.body[:500] + "..." if pr.body and len(pr.body) > 500 else pr.body or "No description provided.",
                    color=discord.Color.blue(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_author(name=pr.user.login, icon_url=pr.user.avatar_url)
                embed.add_field(name="Repository", value=repo.full_name, inline=True)
                embed.add_field(name="PR Number", value=f"#{pr.number}", inline=True)
                embed.set_footer(text="GitHub Pull Request")
                await channel.send(embed=embed)
                last_pr_time_dt = max(last_pr_time_dt, pr.created_at)
            if pr.merged_at and pr.merged_at > last_merged_pr_time_dt:
                embed = discord.Embed(
                    title=f"✅ Merged Pull Request: {pr.title}",
                    url=pr.html_url,
                    description=pr.body[:500] + "..." if pr.body and len(pr.body) > 500 else pr.body or "No description provided.",
                    color=discord.Color.green(),
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_author(name=pr.merged_by.login if pr.merged_by else "Unknown", icon_url=pr.merged_by.avatar_url if pr.merged_by else "")
                embed.add_field(name="Repository", value=repo.full_name, inline=True)
                embed.add_field(name="PR Number", value=f"#{pr.number}", inline=True)
                embed.set_footer(text="GitHub Pull Request Merged")
                await channel.send(embed=embed)
                last_merged_pr_time_dt = max(last_merged_pr_time_dt, pr.merged_at)

        if last_pr_time_dt != datetime.min.replace(tzinfo=timezone.utc):
            conf["last_pr_times"][index] = last_pr_time_dt.isoformat()
        if last_merged_pr_time_dt != datetime.min.replace(tzinfo=timezone.utc):
            conf["last_merged_pr_times"][index] = last_merged_pr_time_dt.isoformat()

    async def check_releases(self, repo, guild, channel, conf, index):
        """Check for new releases in the repository."""
        last_release_time = conf["last_release_times"][index]
        last_time = datetime.fromisoformat(last_release_time.replace("Z", "+00:00")) if last_release_time else datetime.min.replace(tzinfo=timezone.utc)

        for release in repo.get_releases():
            if release.created_at <= last_time:
                break
            embed = discord.Embed(
                title=f"🎉 New Release: {release.title}",
                url=release.html_url,
                description=release.body[:500] + "..." if release.body and len(release.body) > 500 else release.body or "No description provided.",
                color=discord.Color.purple(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_author(name=release.author.login, icon_url=release.author.avatar_url青海省
            embed.add_field(name="Repository", value=repo.full_name, inline=True)
            embed.add_field(name="Tag", value=release.tag_name, inline=True)
            embed.set_footer(text="GitHub Release")
            await channel.send(embed=embed)
            last_time = max(last_time, release.created_at)

        if last_time != datetime.min.replace(tzinfo=timezone.utc):
            conf["last_release_times"][index] = last_time.isoformat()

    @monitor_task.before_loop
    async def before_monitor(self):
        await self.bot.wait_until_ready()