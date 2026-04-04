# Agora Phase 1 — Implementation Plan

**Goal:** One agent connects to Discord, receives messages, dispatches to `should_respond` / `generate_response`, and posts a response. This is the core library skeleton that everything else builds on.

**End state:** An operator can `pip install` the library (or install from local path), subclass `AgoraBot`, implement two methods, point at a YAML config, and have a working Discord bot.

---

## Package Structure

```
agora/
├── __init__.py              # Public API: exports AgoraBot, Message, Config
├── bot.py                   # AgoraBot base class — the core
├── config.py                # Config loader (YAML → dataclass)
├── message.py               # Message wrapper (thin layer over discord.py Message)
├── chunker.py               # Message chunking for >2000 char responses
└── cli.py                   # `agora init` scaffolding command

agent.yaml                   # Example config (lives in repo root for reference)
pyproject.toml               # Package metadata, dependencies
examples/
├── echo_agent.py            # Simplest possible agent — echoes messages
└── keyword_agent.py         # Responds to keyword matches (no LLM)
tests/
├── test_config.py           # Config loading, validation, defaults
├── test_chunker.py          # Message chunking logic
├── test_message.py          # Message wrapper
└── test_bot_unit.py         # AgoraBot logic (mocked discord.py)
```

---

## Core Objects

### 1. `Config` (config.py)

A dataclass that holds all configuration. Loaded from YAML. No surprises.

```python
from dataclasses import dataclass, field

@dataclass
class RateLimitConfig:
    per_channel_per_hour: int = 10
    global_per_hour: int = 30

@dataclass
class Config:
    # Discord connection
    token_env: str                              # env var name holding the bot token

    # Channel behavior — maps channel name to mode
    channels: dict[str, str] = field(default_factory=dict)
    # Valid modes: "subscribe", "mention-only", "write-only"

    # Safety
    exchange_cap: int = 5
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)

    # Response behavior
    jitter_seconds: tuple[float, float] = (1.0, 3.0)
    typing_indicator: bool = True
    reply_threading: bool = True
    max_response_length: int = 4000

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        """Load config from a YAML file. Validates required fields."""
        ...

    @property
    def token(self) -> str:
        """Reads the actual token from the environment variable named by token_env.
        Raises ConfigError if the env var is not set or empty."""
        ...
```

**Key decisions:**
- `token_env` stores the env var *name*, never the token itself. Config files are safe to commit.
- Channel modes are strings, not enums — keeps YAML simple. Validated at load time.
- All fields have defaults except `token_env` — an agent with zero config beyond the token should still work (subscribes to no channels, responds only to @mentions in any channel it can see).

**Validation on load:**
- `token_env` must be present and the env var must be set
- Channel modes must be one of: `subscribe`, `mention-only`, `write-only`
- `exchange_cap` must be >= 1
- `jitter_seconds` must be a 2-element list where min <= max
- `max_response_length` must be >= 1

### 2. `Message` (message.py)

A thin wrapper around `discord.Message` that exposes only what the operator needs in `should_respond` and `generate_response`. Shields operators from discord.py internals.

```python
class Message:
    """Immutable view of a Discord message, tailored for agent decision-making."""

    def __init__(self, discord_message: discord.Message, bot_user_id: int):
        self._msg = discord_message
        self._bot_user_id = bot_user_id

    @property
    def content(self) -> str:
        """The message text. Empty string if MESSAGE_CONTENT intent is missing."""

    @property
    def author_name(self) -> str:
        """Display name of the message author."""

    @property
    def author_id(self) -> int:
        """Discord user ID of the author."""

    @property
    def is_bot(self) -> bool:
        """True if the author is a bot."""

    @property
    def is_mention(self) -> bool:
        """True if this message @mentions our bot."""

    @property
    def channel_name(self) -> str:
        """Name of the channel this message was posted in."""

    @property
    def channel_id(self) -> int:
        """Discord channel ID."""

    @property
    def id(self) -> int:
        """Discord message ID. Useful for reply threading."""

    @property
    def reference_id(self) -> int | None:
        """If this message is a reply, the ID of the message it's replying to."""
```

**What this does NOT expose:**
- Raw `discord.Message` object (keeps the operator's code decoupled from discord.py)
- Embeds, attachments, components (Phase 1 is text-only)
- Server/guild info (not needed for agent decisions)
- Reaction data

**Why a wrapper and not the raw discord.Message:**
- Operators should be able to write `should_respond` and `generate_response` without importing discord.py
- If we ever port to another platform (Slack, Matrix), the operator's code doesn't change
- We control the surface — no accidental dependency on discord.py internals

### 3. `AgoraBot` (bot.py)

The core class. Operators subclass this and override two methods. Everything else is handled internally.

```python
import discord
import asyncio
import random
import logging

logger = logging.getLogger("agora")

class AgoraBot:
    """Base class for Agora agents. Subclass and override
    should_respond() and generate_response()."""

    def __init__(self, config: Config):
        self.config = config

        # discord.py client setup
        intents = discord.Intents.default()
        intents.message_content = True          # Required — logs warning if rejected
        intents.members = False                 # Not needed for Phase 1
        self._client = discord.Client(intents=intents)

        # Internal state
        self._channel_map: dict[str, str] = {}  # channel_name → mode (populated on_ready)
        self._channel_ids: dict[str, int] = {}   # channel_name → channel_id

        # Wire up discord.py events
        self._client.event(self._on_ready)
        self._client.event(self._on_message)

    # ──────────────────────────────────────────────
    # PUBLIC: operators override these
    # ──────────────────────────────────────────────

    async def should_respond(self, message: Message) -> bool:
        """Override to control when the agent responds.
        Called for every eligible message (after internal filtering).
        Default: respond to @mentions only."""
        return message.is_mention

    async def generate_response(self, message: Message) -> str | None:
        """Override to generate a response.
        Return a string to post, or None to stay silent.
        Called only when should_respond() returns True."""
        return None

    # ──────────────────────────────────────────────
    # PUBLIC: lifecycle
    # ──────────────────────────────────────────────

    @classmethod
    def from_config(cls, path: str) -> "AgoraBot":
        """Create an AgoraBot (or subclass) from a YAML config file."""
        config = Config.from_yaml(path)
        return cls(config)

    def run(self):
        """Start the bot. Blocks until the bot is stopped.
        This is the only method the operator calls after construction."""
        logger.info("Starting Agora bot...")
        self._client.run(self.config.token)

    # ──────────────────────────────────────────────
    # INTERNAL: discord.py event handlers
    # ──────────────────────────────────────────────

    async def _on_ready(self):
        """Called when the bot connects to Discord.
        Resolves channel names to IDs, validates intents, logs status."""
        logger.info(f"Connected as {self._client.user} (ID: {self._client.user.id})")
        self._resolve_channels()
        self._check_intents()

    async def _on_message(self, discord_message: discord.Message):
        """Main message handler. Implements the full dispatch pipeline."""
        # Step 1: Ignore own messages
        if discord_message.author.id == self._client.user.id:
            return

        # Step 2: Check if this channel is in our config
        channel_name = discord_message.channel.name
        mode = self._get_channel_mode(channel_name)
        if mode is None or mode == "write-only":
            return

        # Step 3: Build our Message wrapper
        message = Message(discord_message, self._client.user.id)

        # Step 4: If mode is "mention-only", skip unless we're mentioned
        if mode == "mention-only" and not message.is_mention:
            return

        # Step 5: Call operator's should_respond
        try:
            if not await self.should_respond(message):
                return
        except Exception as e:
            logger.error(f"should_respond raised: {e}")
            return

        # Step 6: Jitter delay
        jitter = random.uniform(*self.config.jitter_seconds)
        await asyncio.sleep(jitter)

        # Step 7: Typing indicator
        if self.config.typing_indicator:
            await discord_message.channel.trigger_typing()

        # Step 8: Call operator's generate_response
        try:
            response = await self.generate_response(message)
        except Exception as e:
            logger.error(f"generate_response raised: {e}")
            return

        if response is None:
            return

        # Step 9: Truncate and chunk
        response = response[:self.config.max_response_length]
        chunks = chunk_message(response)

        # Step 10: Send response (reply to the original message if threading enabled)
        for i, chunk in enumerate(chunks):
            if i == 0 and self.config.reply_threading:
                await discord_message.reply(chunk)
            else:
                await discord_message.channel.send(chunk)

    # ──────────────────────────────────────────────
    # INTERNAL: helpers
    # ──────────────────────────────────────────────

    def _resolve_channels(self):
        """Map configured channel names to Discord channel IDs.
        Logs warnings for channels that don't exist on the server."""
        for guild in self._client.guilds:
            for channel in guild.text_channels:
                if channel.name in self.config.channels:
                    self._channel_map[channel.name] = self.config.channels[channel.name]
                    self._channel_ids[channel.name] = channel.id

        # Warn about configured channels not found
        for name in self.config.channels:
            if name not in self._channel_map:
                logger.warning(f"Channel '{name}' in config but not found on server")

    def _get_channel_mode(self, channel_name: str) -> str | None:
        """Get the configured mode for a channel, or None if not configured.
        If no channels are configured, treats all channels as 'mention-only'."""
        if not self.config.channels:
            return "mention-only"  # Default: respond to @mentions in any channel
        return self._channel_map.get(channel_name)

    def _check_intents(self):
        """Log a warning if MESSAGE_CONTENT intent appears to be missing.
        Detection: check if we're receiving content in messages. Can't check
        directly at connect time — we observe on first message instead."""
        # Set a flag; actual check happens in _on_message when we see empty content
        self._intent_warned = False
```

**Key design decisions in AgoraBot:**

1. **`from_config` is a classmethod, not `__init__`.** This means subclasses automatically inherit it — `MyAgent.from_config("agent.yaml")` returns a `MyAgent`, not an `AgoraBot`.

2. **`run()` blocks.** This is the simplest possible lifecycle. One agent per process. No async entry point needed — `run()` calls `client.run()` which sets up the event loop internally.

3. **Exception handling in should_respond/generate_response.** If the operator's code throws, we log and move on. The bot doesn't crash. This is critical for robustness — an LLM API timeout shouldn't kill the process.

4. **Jitter happens AFTER should_respond, BEFORE generate_response.** This is intentional. We want to know the agent wants to respond before introducing delay. The delay reduces simultaneous posts from multiple agents.

5. **No channels configured = mention-only everywhere.** An operator who sets just `token_env` and nothing else gets a bot that responds to @mentions in any channel. Useful for quick testing.

6. **Typing indicator fires before generate_response.** This gives users visual feedback that the agent is working. discord.py's `trigger_typing()` shows "Bot is typing..." for 10 seconds or until a message is sent.

### 4. `chunk_message` (chunker.py)

```python
DISCORD_MAX_LENGTH = 2000

def chunk_message(text: str, max_length: int = DISCORD_MAX_LENGTH) -> list[str]:
    """Split a message into chunks that fit within Discord's character limit.

    Splitting strategy (in priority order):
    1. Split on double newline (paragraph boundary)
    2. Split on single newline
    3. Split on space (word boundary)
    4. Hard split at max_length (last resort)

    Returns a list of 1+ strings, each <= max_length characters.
    """
    ...
```

**Rules:**
- Never splits mid-word if possible
- Preserves code blocks — if a chunk starts inside a code block, prepend ``` and close properly
- Returns `[""]` for empty input (never returns empty list)
- Each chunk is stripped of leading/trailing whitespace

### 5. CLI scaffolding (cli.py)

```python
"""Entry point for `agora init <name>` command."""

def init_agent(name: str):
    """Create a new agent project directory with starter files.

    Creates:
        <name>/
        ├── agent.py      # Subclass with should_respond / generate_response stubs
        ├── agent.yaml    # Config template with token_env and channel placeholders
        └── run.sh        # Shell script: export TOKEN=... && python agent.py
    """
    ...
```

Registered as a console_scripts entry point in pyproject.toml:
```toml
[project.scripts]
agora = "agora.cli:main"
```

---

## Method Reference (complete public API for Phase 1)

### AgoraBot

| Method | Type | Description |
|---|---|---|
| `__init__(config: Config)` | constructor | Creates bot with config. Normally not called directly — use `from_config`. |
| `from_config(path: str) -> Self` | classmethod | Load config from YAML, create bot instance. Subclass-safe. |
| `run()` | blocking | Connect to Discord and start processing messages. Blocks forever. |
| `should_respond(message: Message) -> bool` | async, override | Return True to trigger response generation. Default: True for @mentions. |
| `generate_response(message: Message) -> str \| None` | async, override | Return response text or None. Default: None (no response). |

### Config

| Method/Property | Type | Description |
|---|---|---|
| `from_yaml(path: str) -> Config` | classmethod | Load and validate config from YAML file. |
| `token` | property | Read token from env var. Raises if missing. |
| `token_env` | field | Name of the environment variable holding the Discord bot token. |
| `channels` | field | Dict mapping channel names to modes: `subscribe`, `mention-only`, `write-only`. |
| `exchange_cap` | field | Max consecutive bot messages before suppression. Default: 5. |
| `rate_limit` | field | `RateLimitConfig` with `per_channel_per_hour` and `global_per_hour`. |
| `jitter_seconds` | field | `(min, max)` random delay range in seconds. Default: (1.0, 3.0). |
| `typing_indicator` | field | Show typing indicator while generating. Default: True. |
| `reply_threading` | field | Use Discord reply threading. Default: True. |
| `max_response_length` | field | Max chars before truncation. Default: 4000. |

### Message

| Property | Type | Description |
|---|---|---|
| `content` | str | Message text. Empty if MESSAGE_CONTENT intent missing. |
| `author_name` | str | Display name of author. |
| `author_id` | int | Discord user ID. |
| `is_bot` | bool | True if author is a bot. |
| `is_mention` | bool | True if our bot is @mentioned. |
| `channel_name` | str | Channel name. |
| `channel_id` | int | Channel ID. |
| `id` | int | Message ID. |
| `reference_id` | int \| None | ID of the message this replies to, if any. |

### Free functions

| Function | Module | Description |
|---|---|---|
| `chunk_message(text, max_length=2000) -> list[str]` | chunker | Split text into Discord-safe chunks. |
| `init_agent(name: str)` | cli | Create agent project scaffold. |

---

## Development Order

### Step 1: Package scaffold and Config

**Create:**
- `pyproject.toml` with metadata, dependencies (`discord.py>=2.7,<3`, `pyyaml>=6`)
- `agora/__init__.py` with version and public exports
- `agora/config.py` — Config and RateLimitConfig dataclasses, `from_yaml`, validation

**Test:**
- `tests/test_config.py`:
  - Loads valid YAML, all fields populated correctly
  - Defaults applied when fields omitted
  - Raises on missing `token_env`
  - Raises on invalid channel mode
  - Raises on invalid `exchange_cap` (0, negative)
  - Raises on invalid `jitter_seconds` (min > max, non-numeric)
  - `token` property reads from env var
  - `token` property raises when env var not set

**Runs with:** `pytest tests/test_config.py` — no Discord connection needed.

### Step 2: Message wrapper and chunker

**Create:**
- `agora/message.py` — Message class
- `agora/chunker.py` — `chunk_message` function

**Test:**
- `tests/test_message.py`:
  - All properties return correct values from a mock discord.Message
  - `is_mention` correctly detects when our bot is mentioned
  - `is_bot` correctly reads author.bot flag
  - Handles edge cases: empty content, no reference

- `tests/test_chunker.py`:
  - Short message → single chunk
  - Message exactly at 2000 chars → single chunk
  - Message at 2001 chars → two chunks
  - Splits on paragraph boundary
  - Splits on newline when no paragraph boundary
  - Splits on space when no newline
  - Hard splits when no space (e.g., long URL)
  - Preserves code blocks across chunks
  - Empty string → `[""]`
  - Unicode characters (emoji, CJK) → correct byte counting

**Runs with:** `pytest tests/test_message.py tests/test_chunker.py` — no Discord connection needed. Uses mock objects.

### Step 3: AgoraBot core (the big one)

**Create:**
- `agora/bot.py` — AgoraBot class with full dispatch pipeline

**Test (unit, mocked):**
- `tests/test_bot_unit.py`:
  - Bot ignores its own messages
  - Bot ignores messages in unconfigured channels
  - Bot ignores messages in write-only channels
  - Bot ignores non-mention messages in mention-only channels
  - Bot calls should_respond for subscribe channels
  - Bot calls should_respond for @mentions in mention-only channels
  - Bot calls generate_response when should_respond returns True
  - Bot does NOT call generate_response when should_respond returns False
  - Bot sends response via channel.send or message.reply based on reply_threading config
  - Bot chunks long responses and sends multiple messages
  - Bot swallows exceptions from should_respond (logs, doesn't crash)
  - Bot swallows exceptions from generate_response (logs, doesn't crash)
  - Bot with empty channels config treats all channels as mention-only
  - from_config creates the correct subclass instance

**Mocking strategy:** Create a mock `discord.Message` and mock `discord.TextChannel` that record calls to `send()` and `reply()`. Mock `discord.Client` to simulate `on_ready` and `on_message` events. All tests run without a real Discord connection.

**Runs with:** `pytest tests/test_bot_unit.py` — no Discord connection needed.

### Step 4: CLI scaffolding

**Create:**
- `agora/cli.py` — `init_agent` function and `main` entry point
- Template files embedded as strings in the module (agent.py template, agent.yaml template, run.sh template)

**Test:**
- `tests/test_cli.py`:
  - `init_agent("my-bot")` creates directory with expected files
  - Created `agent.py` is valid Python (compiles without error)
  - Created `agent.yaml` loads successfully via Config.from_yaml
  - Created `run.sh` is executable
  - Raises if directory already exists
  - Name with spaces/special chars is handled (slugified or rejected)

**Runs with:** `pytest tests/test_cli.py` — creates files in a temp directory.

### Step 5: Example agents

**Create:**
- `examples/echo_agent.py` — echoes back any message it's mentioned in (for testing)
- `examples/keyword_agent.py` — responds when configurable keywords are detected

These are NOT tested in CI — they're for manual testing with a real Discord server.

### Step 6: Integration test (requires Discord)

This is the "user helps set up" test. It requires a real Discord server and bot token.

**Setup (one-time, manual):**
1. Create a test Discord server
2. Create a bot application at discord.com/developers
3. Enable MESSAGE_CONTENT intent in Developer Portal
4. Invite bot to server with Send Messages + Read Message History permissions
5. Create `#test` channel
6. Set `TEST_BOT_TOKEN` environment variable

**Test script** (`tests/integration/test_live_bot.py`):

```
Test 1 — Connection
  Start echo agent pointing at #test channel
  Assert: bot appears online within 10 seconds
  Assert: log shows "Connected as <bot-name>"

Test 2 — Mention response
  Post "@BotName hello" in #test (via a second bot or manual)
  Assert: bot replies within jitter_max + 5 seconds
  Assert: reply content is "hello" (echo)
  Assert: reply is threaded (references the original message)

Test 3 — Non-mention ignored
  Post "hello" in #test without @mention
  Assert: bot does NOT respond within 10 seconds

Test 4 — Write-only channel respected
  Configure #test as write-only
  Post "@BotName hello" in #test
  Assert: bot does NOT respond

Test 5 — Long message chunking
  Trigger echo agent with a 5000-char message
  Assert: bot sends 3 messages (2000 + 2000 + 1000 chars)

Test 6 — Typing indicator
  Trigger echo agent (with artificial delay in generate_response)
  Assert: typing indicator fires before response

Test 7 — Graceful error handling
  Subclass with should_respond that raises RuntimeError
  Trigger with @mention
  Assert: bot does NOT crash
  Assert: bot logs the error
  Assert: bot responds to next message normally
```

**How to run:** `pytest tests/integration/ --live` (skipped by default, requires `--live` flag and `TEST_BOT_TOKEN` env var).

---

## Dependencies

```toml
[project]
name = "agora"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "discord.py>=2.7,<3",
    "pyyaml>=6,<7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
]
```

Two runtime dependencies. That's it. No requests, no aiohttp (discord.py bundles its own), no database drivers, no config frameworks.

---

## What Phase 1 Does NOT Include

These are explicitly deferred to later phases:

- **Exchange cap checking** (Phase 2) — the dispatch pipeline has a placeholder comment for where this goes
- **Client-side rate limiting** (Phase 2) — same, placeholder in the pipeline
- **Peer discovery via Discord role** (Phase 2)
- **Moderator bot** (Phase 3)
- **PyPI publishing** (Phase 4)
- **Startup intent validation** (Phase 4 — tricky to detect reliably, better to do after we have real usage patterns)

Phase 1 gets the skeleton right. Phase 2 adds the safety mechanisms on top of it.
