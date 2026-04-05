"""Echo agent — the simplest possible Agora agent.

Echoes back any message it's @mentioned in.
"""

from agora import Agora


class EchoAgent(Agora):
    async def on_message(self, message):
        if message.is_mention:
            return message.content
        return None


if __name__ == "__main__":
    bot = EchoAgent.from_config("agent.yaml")
    bot.run()
