"""Keyword agent — responds when configurable keywords are detected.

No LLM required. Useful for testing and simple automation.
"""

from agora import Agora

# Keywords and their responses
KEYWORDS = {
    "hello": "Hello! How can I help?",
    "help": "I'm a keyword-matching bot. Try saying 'hello' or 'status'.",
    "status": "All systems operational.",
}


class KeywordAgent(Agora):
    async def on_message(self, message):
        text = message.content.lower()
        for keyword, response in KEYWORDS.items():
            if keyword in text:
                return response
        return None


if __name__ == "__main__":
    bot = KeywordAgent.from_config("agent.yaml")
    bot.run()
