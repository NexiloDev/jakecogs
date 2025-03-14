# JKChatBridge Cog for Red-DiscordBot

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Red-DiscordBot](https://img.shields.io/badge/Red%20Bot-3.5+-red.svg)
![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)

## Overview

`JKChatBridge` is a custom cog for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) designed to bridge public chat between a **Jedi Knight: Jedi Academy (JKA)** game server and a Discord server. It uses RCON for real-time player data updates and monitors the game’s `qconsole.log` file to relay in-game chat, duel events, and server status changes. Built with Lugormod support, this cog fosters community engagement across platforms.

## Features

- **Two-Way Chat Bridge**: Relay messages between Discord and JKA.
- **Server Status**: Use `!jkstatus` for a detailed server overview (players, map, mod).
- **Player Stats**: Check stats with `!jkplayer <username>`.
- **Event Notifications**: Real-time updates for joins, disconnects, name changes, and duels, including client IDs (e.g., "Jake (ID: 3) has joined").
- **Player Data Refresh**: Updates player data every 5 seconds via RCON for accurate tracking.
- **Server Restart/Map Change Handling**: Suppresses disconnect spam and notifies Discord with "Standby" and "Resumed" messages during restarts or map changes.
- **Daily Server Restart**: Restarts the server at midnight with pre-warnings.
- **Emoji Support**: Converts text emotes (e.g., `:)` to 😊) and supports custom Discord emojis.

## How It Works

1. **RCON Integration**: Fetches player data (`playerlist`, `status`) every 5 seconds to track joins, disconnects, and name changes.
2. **Log Monitoring**: Reads `qconsole.log` for chat messages, duel wins, and server restart/map change events.
3. **Discord Interaction**: Posts updates to a designated channel and sends Discord messages to the game server.
4. **Restart Handling**: Detects server restarts or map changes, suspends player tracking, and resumes after a delay to account for bot loading.

### Technical Details

- **Dependencies**: `discord.py`, `aiofiles`, `redbot-core`.
- **Requirements**: A JKA server with RCON enabled and access to `qconsole.log`.
- **Platform**: Windows (file paths and batch files), adaptable with tweaks.
- **Refresh Rate**: Player data updates every 5 seconds, lightweight for small servers (~10 players).
- **Restart Detection**: Monitors `qconsole.log` for `------ Server Initialization ------`, suppresses disconnects, and resumes after a 10-second delay post-first `ClientBegin`.

## Installation

1. **Add the Cog**:
   - Place `jkchatbridge.py` in your Red bot’s cog directory (e.g., `data/cogs/`).
   - Load with: `[p]load jkchatbridge`.

2. **Configure Settings** (Bot Owner Only):
   - Use `[p]jkbridge` commands:
     - `[p]jkbridge setchannel #channel-name`: Set the Discord channel.
     - `[p]jkbridge setrconhost 127.0.0.1`: Set the JKA server IP.
     - `[p]jkbridge setrconport 29070`: Set the RCON port.
     - `[p]jkbridge setrconpassword yourpassword`: Set the RCON password.
     - `[p]jkbridge setlogbasepath C:\GameServers\StarWarsJKA\GameData\lugormod`: Set the log path.
     - `[p]jkbridge showsettings`: View settings.
   - Optional:
     - `[p]jkbridge setcustomemoji <:jk:1219115870928900146>`: Custom emoji for game messages.
     - `[p]jkbridge setserverexecutable openjkded.x86.exe`: Server executable for restarts.
     - `[p]jkbridge setstartbatchfile C:\GameServers\StarWarsJKA\GameData\start_jka_server.bat`: Restart batch file.

3. **Restart the Bot**: Apply settings with a restart or `[p]reload jkchatbridge`.

## Usage

- **For All Users**:
  - `!jkstatus`: Server status with player list.
  - `!jkplayer <username>`: Player stats (e.g., `!jkplayer Padawan`).
  - Chat in the designated channel to message the game server.

- **For Admins/Bot Owners**:
  - `!jkexec <filename>`: Execute a config file (e.g., `!jkexec server.cfg`).
  - `[p]jkbridge reloadmonitor`: Refresh log monitoring and player data.

### Server Restart/Map Change Notifications
- When a restart or map change begins: "⚠️ **Standby**: Server integration suspended while map changes or server restarts."
- When completed: "✅ **Server Integration Resumed**: Map <mapname> loaded." (after a 10-second delay to allow players to join).

## Modifying Settings

Adjust settings with `[p]jkbridge` commands (bot owner only). Examples:
- `[p]jkbridge setlogbasepath /new/path]`: Update log path.
- `[p]jkbridge setrconhost new.ip`: Change server IP.

Use `[p]jkbridge showsettings` to verify, then reload with `[p]reload jkchatbridge`.

## Contributing

Fork, submit issues, or create pull requests. Planned features:
- Enhanced event detection (e.g., kills).
- Customizable message formats.
- Cross-platform support.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

## Acknowledgments

- Built with Grok (xAI) assistance.
- Designed for the JKA community with Lugormod support.