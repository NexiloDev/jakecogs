# JakeCogs - Custom Red Bot Cogs for Gaming Communities

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Red-DiscordBot](https://img.shields.io/badge/Red%20Bot-3.5+-red.svg)
![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)

## Hey, I’m JakeFTL!

Welcome to `jakecogs`, my collection of custom cogs for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot). I built these for my Mystic Gaming community to bridge our game servers—like Jedi Knight: Jedi Academy and Arma Reforger—with Discord, keeping everyone connected and in the loop. They’re tailored to our needs, but I’ve made them flexible and well-documented so anyone can use or tweak them for their own servers. Feel free to grab them, play around, and make them yours!

---

## Current Cogs

### JKChatBridge
#### Overview
`JKChatBridge` links a **Jedi Knight: Jedi Academy (JKA)** server to Discord. It uses RCON and log monitoring (`qconsole.log`) to relay chat, track player events, and manage server status—all with a sleek, emoji-rich vibe.

#### Features
- **Two-Way Chat**: Send messages between Discord and JKA.
- **Server Status**: `!jkstatus` shows players, map, and mod.
- **Player Stats**: `!jkplayer <username>` for detailed stats.
- **Events**: Join/disconnect, duels, and restart notifications (e.g., "⚠️ Standby" and "✅ Resumed").
- **Emoji Magic**: Converts text emotes (e.g., `:)` to 😊) and supports custom emojis.

#### Setup
1. Place `jkchatbridge.py` in `data/yourbotname/cogs/`.
2. Install: `pip install aiofiles`.
3. Load: `[p]load jkchatbridge`.
4. Configure (bot owner only):
   - `[p]jkbridge setchannel #channel`
   - `[p]jkbridge setrconhost 127.0.0.1`
   - `[p]jkbridge setrconport 29070`
   - `[p]jkbridge setrconpassword yourpass`
   - `[p]jkbridge setlogbasepath C:\path\to\lugormod`
   - `[p]jkbridge showsettings` to check.

#### Commands
- **All Users**: `!jkstatus`, `!jkplayer <username>`.
- **Admins**: `[p]jkexec <file>`, `[p]jkrcon <command>`, `[p]jktoggle` (join/disconnect messages).

#### Notes
- Built for Lugormod, tweak the log path for other mods.
- Windows-focused but adaptable.

---

### ArmaEvents
#### Overview
`ArmaEvents` connects an **Arma Reforger** server (think DayZ Reforged) to Discord via the Server Admin Tools Events API. It posts real-time updates for player joins, kills (player or zombie), and FPS drops.

#### Features
- **Event Posts**: Styled updates like “🧍 **[Arma] Jake** has rejoined the fight for survival!” or “🧟 **[Arma] Jake** got mauled by a zombie! 💀”.
- **Configurable**: Set everything via Discord commands.
- **DayZ Vibes**: Tailored for zombie survival servers.

#### Setup
1. Place `armaevents.py` in `data/yourbotname/cogs/`.
2. Install: `pip install websocket-client`.
3. Load: `!load armaevents`.
4. Configure (bot owner only):
   - `!arma setchannel #channel`
   - `!arma settoken yourtoken`
   - `!arma setaddress ws://localhost:8080/events`
   - `!arma showsettings` to verify.
5. In `ServerAdminTools_Config.json`:
   ```json
   "eventsApiToken": "yourtoken",
   "eventsApiAddress": "ws://localhost:8080/events",
   "eventsApiRatelimitSeconds": 10