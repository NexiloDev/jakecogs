# JKChatBridge Cog for Red-DiscordBot

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Red-DiscordBot](https://img.shields.io/badge/Red%20Bot-3.5+-red.svg)
![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)

## Overview

`JKChatBridge` is a custom cog for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) designed to bridge public chat between a **Jedi Knight: Jedi Academy (JKA)** game server and a Discord server. It leverages RCON (Remote Console) for real-time communication and monitors the game’s `qconsole.log` file to relay in-game events to Discord. Built with Lugormod support in mind, this cog enhances community interaction by connecting players across platforms.

## Features

- **Two-Way Chat Bridge**: Send messages from Discord to JKA and vice versa.
- **Server Status**: Use `!jkstatus` to get a detailed server overview with player list, map, and mod info.
- **Player Stats**: Check individual player stats with `!jkplayer <username>`.
- **Event Notifications**: Get notified in Discord about player joins, disconnects, logins, logouts, and duel wins.
- **Daily Server Restart**: Automatically restarts the server at midnight with pre-warnings.
- **Emoji Support**: Converts common text emotes (e.g., `:)` to 😊) and supports custom Discord emojis.

## How It Works

1. **RCON Integration**: Uses RCON to send commands and fetch data from the JKA server (e.g., player lists, status).
2. **Log Monitoring**: Reads `qconsole.log` to detect in-game events like chat messages, joins, and duels.
3. **Discord Interaction**: Posts updates to a designated Discord channel and relays Discord messages to the game server.

### Technical Details

- **Dependencies**: `discord.py`, `aiofiles`, `redbot-core`.
- **Requirements**: A running JKA server with RCON enabled and access to its `qconsole.log` file.
- **Platform**: Windows (due to file paths and batch file usage), but adaptable with minor tweaks.

## Installation

1. **Add the Cog**:
   - Place the `jkchatbridge.py` file in your Red bot’s cog directory (e.g., `data/cogs/`).
   - Load the cog with: `[p]load jkchatbridge`.

2. **Configure Settings** (Bot Owner Only):
   - Use the `[p]jkbridge` command group to set up the cog. Example commands:
     - `[p]jkbridge setchannel #channel-name`: Set the Discord channel for chat bridging.
     - `[p]jkbridge setrconhost 127.0.0.1`: Set the JKA server IP.
     - `[p]jkbridge setrconport 29070`: Set the RCON port.
     - `[p]jkbridge setrconpassword yourpassword`: Set the RCON password.
     - `[p]jkbridge setlogbasepath C:\GameServers\StarWarsJKA\GameData\lugormod`: Set the log file path.
     - `[p]jkbridge showsettings`: View current settings.
   - Optional settings:
     - `[p]jkbridge setcustomemoji <:jk:1219115870928900146>`: Set a custom emoji for game messages.
     - `[p]jkbridge setserverexecutable openjkded.x86.exe`: Set the server executable for restarts.
     - `[p]jkbridge setstartbatchfile C:\GameServers\StarWarsJKA\GameData\start_jka_server.bat`: Set the restart batch file.

3. **Restart the Bot**: Ensure the cog loads properly with your settings.

## Usage

- **For All Users**:
  - `!jkstatus`: Displays server status (players, map, mod).
  - `!jkplayer <username>`: Shows stats for a specific player (e.g., `!jkplayer Padawan`).
  - Chat in the designated Discord channel to send messages to the game server.

- **For Admins/Bot Owners**:
  - `!jkexec <filename>`: Execute a server config file via RCON (e.g., `!jkexec server.cfg`).
  - Use `[p]jkbridge reloadmonitor` to refresh the log monitoring and player data if needed.

## Modifying Settings

To adjust settings, use the `[p]jkbridge` commands listed above. Ensure you have bot owner permissions. For example:
- Change the log path if your server setup differs: `[p]jkbridge setlogbasepath /new/path/to/lugormod]`.
- Update the RCON details if your server moves: `[p]jkbridge setrconhost new.ip.address`.

Check current settings with `[p]jkbridge showsettings` and tweak as needed. Restart the bot or use `[p]reload jkchatbridge` to apply changes.

## Contributing

Feel free to fork this repository, submit issues, or create pull requests. Planned features include:
- Enhanced event detection (e.g., kills, team changes).
- Customizable message formatting.
- Cross-platform support (Linux/Mac).

## License

This project is licensed under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with help from Grok (xAI) for debugging and optimization.
- Designed for the JKA community with Lugormod in mind.