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
        for emoji in self.bot.emojis:
            text = text.replace(str(emoji), f":{emoji.name}:")
        emoji_map = {
            ":)": "SMILING_FACE_WITH_SMILING_EYES", ":D": "GRINNING_FACE_WITH_SMILING_EYES", "XD": "FACE_WITH_TEARS_OF_JOY", "xD": "ROLLING_ON_THE_FLOOR_LAUGHING",
            ";)": "WINKING_FACE", ":P": "FACE_WITH_TONGUE", ":(": "CRYING_FACE", ">:(": "ANGRY_FACE", ":+1:": "THUMBS_UP", ":-1:": "THUMBS_DOWN",
            "<3": "HEART_SUIT", ":*": "HEART_EYES", ":S": "PERSPIRING_FACE", ":o": "FACE_WITHOUT_MOUTH", "=D": "GRINNING_FACE", "xD": "GRINNING_FACE_WITH_BIG_EYES",
            "O.o": "FLUSHED_FACE", "B)": "NERD_FACE", "-_-": "SLEEPING_FACE", "^^;": "GRIMACING_FACE", ":/": "UNAMUSED_FACE", ":*": "KISSING_FACE",
            "8)": "COOL_FACE", "D:": "SCREAMING_FACE", ":?": "THINKING_FACE", "\\o/": "PARTYING_FACE", ">^.^<": "HUGGING_FACE", ":p": "ZANY_FACE",
            ":pray:": "PRAYING_HANDS", ":wave:": "WAVING_HAND", ":-|": "NEUTRAL_FACE", "*.*": "STAR_STRUCK", "O:)": "INNOCENT_FACE",
            ":jackolantern:": "JACK_O_LANTERN", ":christmastree": "CHRISTMAS_TREE"
        }
        return ''.join(emoji_map.get(c, c) for c in text)

    def clean_for_latin1(self, text):
        text = self.replace_emojis_with_names(text)
        return ''.join(c if ord(c) < 256 else '' for c in text)

    def remove_color_codes(self, text):
        return re.sub(r'\^\d', '', text or '')

    def replace_text_emotes_with_emojis(self, text):
        emote_map = {
            ":)": "SMILING_FACE_WITH_SMILING_EYES", ":D": "SMILING_FACE_WITH_SMILING_EYES", "XD": "FACE_WITH_TEARS_OF_JOY", "xD": "ROLLING_ON_THE_FLOOR_LAUGHING",
            ";)": "WINKING_FACE", ":P": "FACE_WITH_TONGUE", ":(": "CRYING_FACE", ">:(": "ANGRY_FACE", ":+1:": "THUMBS_UP", ":-1:": "THUMBS_DOWN",
            "<3": "HEART_SUIT", ":*": "HEART_EYES", ":S": "PERSPIRING_FACE", ":o": "FACE_WITHOUT_MOUTH", "=D": "GRINNING_FACE", "xD": "GRINNING_FACE_WITH_BIG_EYES",
            "O.o": "FLUSHED_FACE", "B)": "NERD_FACE", "-_-": "SLEEPING_FACE", "^^;": "GRIMACING_FACE", ":/": "UNAMUSED_FACE", ":*": "KISSING_FACE",
            "8)": "COOL_FACE", "D:": "SCREAMING_FACE", ":?": "THINKING_FACE", "\\o/": "PARTYING_FACE", ">^.^<": "HUGGING_FACE", ":p": "ZANY_FACE",
            ":pray:": "PRAYING_HANDS", ":wave:": "WAVING_HAND", ":-|": "NEUTRAL_FACE", "*.*": "STAR_STRUCK", "O:)": "INNOCENT_FACE",
            ":jackolantern:": ":jack_o_lantern:", ":christmastree": ":christmas_tree:"
        }
        for k, v in emote_map.items():
            text = text.replace(k, v)
        return text

    def parse_chat_line(self, line):
        say_idx = line.find("say: ")
        if say_idx == -1:
            return None, None
        chat = line[say_idx + 5:]
        colon_idx = chat.find(": ")
        if colon_idx == -1:
            return None, None
        name = self.remove_color_codes(chat[:colon_idx].strip())
        msg = self.remove_color_codes(chat[colon_idx + 2:].strip())
        return name, msg