"""Echo agent — the simplest possible Agora agent.

Echoes back any message it's @mentioned in.
"""

from agora import AgoraBot


class EchoAgent(AgoraBot):
    async def should_respond(self, message):
        return message.is_mention

    async def generate_response(self, message):
        return message.content


if __name__ == "__main__":
    bot = EchoAgent.from_config("agent.yaml")
    bot.run()
