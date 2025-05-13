from .mcchatbridge import MCChatBridge

def setup(bot):
    bot.add_cog(MCChatBridge(bot))