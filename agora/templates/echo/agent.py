"""{{name}} -- an Agora agent."""

from agora import Agora


class {{class_name}}(Agora):
    async def on_message(self, message):
        if message.is_mention:
            return f"Hello {message.author_name}, you said: {message.content}"
        return None


if __name__ == "__main__":
    bot = {{class_name}}.from_config("agent.yaml")
    bot.run()
