from redbot.core import commands
import re

class ChatHandler:
    @commands.Cog.listener()
    async def on_message(self, message):
        channel_id = await self.config.discord_channel_id()
        if not channel_id or message.channel.id != channel_id or message.author.bot:
            return
        prefixes = await self.bot.get_prefix(message)
        if any(message.content.startswith(p) for p in prefixes):
            return

        username = self.clean_for_latin1(message.author.display_name)
        content = self.clean_for_latin1(message.content)
        for member in message.mentions:
            clean_name = self.clean_for_latin1(member.display_name)
            content = content.replace(f"<@!{member.id}>", f"@{clean_name}").replace(f"<@{member.id}>", f"@{clean_name}")
        content = self.replace_emojis_with_names(content)

        prefix = f"say ^7(^5Discord^7) ^7{username}: ^2"
        max_len = 115
        chunks = []
        remaining = content
        first = True
        while remaining:
            cur_max = max_len if first else 128 - 4
            if len(remaining) <= cur_max:
                chunks.append(remaining)
                break
            split = remaining.rfind(' ', 0, cur_max + 1) or cur_max
            chunks.append(remaining[:split].strip())
            remaining = remaining[split:].strip()
            first = False

        if not await self.validate_rcon_settings():
            await message.channel.send("RCON settings not configured.")
            return

        try:
            for i, chunk in enumerate(chunks):
                cmd = f"{prefix if i == 0 else 'say '}{chunk}"
                await self.bot.loop.run_in_executor(
                    self.executor, self.send_rcon_command,
                    cmd, await self.config.rcon_host(),
                    await self.config.rcon_port(), await self.config.rcon_password()
                )
                await asyncio.sleep(0.1)
        except Exception as e:
            await message.channel.send(f"Failed to send: {e}")

    def replace_emojis_with_names(self, text):
        emoji_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢",
            ">:(": "😡", ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣",
            ":o": "😮", "=D": "😁", "xD": "😆", "O.o": "😳", "B)": "🤓", "-_-": "😴", "^^;": "😅",
            ":/": "😒", ":*": "😘", "8)": "😎", "D:": "😱", ":?": "🤔", "\\o/": "🥳", ">^.^<": "🤗", ":p": "🤪",
            ":pray:": "🙏", ":wave:": "👋", ":-|": "😶", "*.*": "🤩", "O:)": "😇",
            ":jackolantern:": ":jack_o_lantern:", ":christmastree:": ":christmas_tree:"
        }
        return ''.join(emoji_map.get(c, c) for c in text)

    def clean_for_latin1(self, text):
        text = self.replace_emojis_with_names(text)
        return ''.join(c if ord(c) < 256 else '' for c in text)

    def replace_text_emotes_with_emojis(self, text):
        emote_map = {
            ":)": "😊", ":D": "😄", "XD": "😂", "xD": "🤣", ";)": "😉", ":P": "😛", ":(": "😢",
            ">:(": "😡", ":+1:": "👍", ":-1:": "👎", "<3": "❤️", ":*": "😍", ":S": "😣",
            ":o": "😮", "=D": "😁", "xD": "😆", "O.o": "😳", "B)": "🤓", "-_-": "😴", "^^;": "😅",
            ":/": "😒", ":*": "😘", "8)": "😎", "D:": "😱", ":?": "🤔", "\\o/": "🥳", ">^.^<": "🤗", ":p": "🤪",
            ":pray:": "🙏", ":wave:": "👋", ":-|": "😶", "*.*": "🤩", "O:)": "😇",
            ":jackolantern:": ":jack_o_lantern:", ":christmastree:": ":christmas_tree:"
        }
        for k, v in emote_map.items():
            text = text.replace(k, v)
        return text