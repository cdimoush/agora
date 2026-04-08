"""{{name}} — a custom Agora agent."""

from agora import Agora


class {{class_name}}(Agora):
    async def on_message(self, message):
        # Implement your agent logic here
        return None


if __name__ == "__main__":
    bot = {{class_name}}.from_config("agent.yaml")
    bot.run()
