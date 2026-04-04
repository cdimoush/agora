# Agora Phase 2 — Implementation Plan

**Goal:** Add exchange cap safety to the library, refactor the test instance into a committable testbed, and prepare the AgoraGenesis Discord server for multi-bot testing.

**End state:** The agora library enforces an exchange cap (consecutive bot message limit) in the dispatch pipeline. The `instance/` directory is replaced by `testbed/` with a structure that supports moderator and citizen bots. Secrets are gitignored. The AgoraGenesis server has bot applications created for two citizen bots and a moderator. All unit tests pass.

**Prerequisite:** Phase 1 complete (library skeleton, dispatch pipeline, config, message wrapper, chunker, CLI, example agents, unit tests).

---

## Design Principles (Governing This Phase)

These were established during the Phase 2 design review and apply to all safety work:

1. **Safety is self-interested.** Client-side safety protects the operator's wallet. If you bypass it, you pay for the consequences.
2. **Server-side enforcement is the server owner's job.** The library provides defaults. The moderator (Phase 3) enforces server rules. If the server has no moderator, that's the admin's problem.
3. **Exchange cap counts own messages.** A bot's own messages count toward the consecutive bot message cap. This prevents two-bot ping-pong from running beyond the cap.
4. **No rate limiting in the library (yet).** Exchange cap is sufficient. Rate limiting adds complexity for marginal benefit. Operators use `--max-budget-usd` on Claude calls for per-invocation cost protection.

---

## Current State (What Exists Today)

### Library (`agora/`)

| File | Status | Relevant to Phase 2 |
|---|---|---|
| `bot.py` | Complete (158 lines) | Dispatch pipeline needs exchange cap check inserted between Step 4 and Step 5 |
| `config.py` | Complete (96 lines) | Has `exchange_cap` field (default 5) and `rate_limit` field (to be removed) |
| `message.py` | Complete (55 lines) | Needs `is_agent` property for peer detection |
| `chunker.py` | Complete (91 lines) | No changes needed |
| `cli.py` | Complete (118 lines) | No changes needed |
| `__init__.py` | Complete | No changes needed |

### Config fields today

```python
@dataclass
class RateLimitConfig:
    per_channel_per_hour: int = 10
    global_per_hour: int = 30

@dataclass
class Config:
    token_env: str
    channels: dict[str, str] = field(default_factory=dict)
    exchange_cap: int = 5
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    jitter_seconds: tuple[float, float] = (1.0, 3.0)
    typing_indicator: bool = True
    reply_threading: bool = True
    max_response_length: int = 4000
```

`exchange_cap` exists in config but is not enforced. `rate_limit` and `RateLimitConfig` exist but are being removed.

### Dispatch pipeline today (bot.py `_on_message`)

```
Step 1:  Ignore own messages
Step 2:  Check channel config
Step 3:  Build Message wrapper
Step 4:  Enforce mention-only mode
Step 5:  Operator's should_respond          ← exchange cap check goes BEFORE this
Step 6:  Jitter delay
Step 7:  Typing indicator
Step 8:  Operator's generate_response
Step 9:  Truncate and chunk
Step 10: Send response
```

### Instance directory today (`instance/`)

```
instance/
├── agent.py        # Runs EchoAgent with local config
├── agent.yaml      # Config (token_env: DISCORD_BOT_TOKEN, channels: general: mention-only)
├── .env            # REAL SECRET: Discord bot token + app ID
└── run.sh          # Shell runner
```

Currently gitignored entirely (`instance/` in `.gitignore`). The agent.py imports from `examples/echo_agent.py`.

### Tests today

| File | Tests | Status |
|---|---|---|
| `test_config.py` | Config loading, validation, defaults | Pass |
| `test_message.py` | All Message properties | Pass |
| `test_bot_unit.py` | Dispatch pipeline (22 tests) | Pass |
| `test_chunker.py` | Message chunking | Pass |
| `test_cli.py` | CLI scaffolding | Pass |
| `integration/test_live_bot.py` | Live Discord tests | Requires `--live` flag |

---

## Target State (After Phase 2)

### Library changes

```
agora/
├── __init__.py          # No change
├── bot.py               # Exchange cap check added to dispatch pipeline
├── config.py            # RateLimitConfig removed; rate_limit field removed
├── message.py           # is_agent property added
├── safety.py            # NEW: ExchangeCapChecker class
├── chunker.py           # No change
└── cli.py               # No change
```

### Testbed structure (replaces instance/)

```
testbed/
├── README.md            # What this directory is, how to use it
├── echo/                # Migrated from instance/ — the existing echo bot
│   ├── agent.py         # Runs EchoAgent
│   ├── agent.yaml       # Config
│   └── run.sh           # Shell runner (sources .env)
├── moderator/           # Placeholder for Phase 3
│   └── .gitkeep
├── citizen-a/           # Placeholder for Phase 4
│   └── .gitkeep
└── citizen-b/           # Placeholder for Phase 4
    └── .gitkeep
```

**Secrets strategy:** Each bot subdirectory has its own `.env` file (gitignored via `testbed/*/.env` pattern). Config files (`agent.yaml`) use `token_env` to reference env var names — safe to commit. The `.gitignore` is updated to ignore `testbed/*/.env` instead of the blanket `instance/` ignore.

### Updated dispatch pipeline

```
Step 1:   Ignore own messages
Step 2:   Check channel config
Step 3:   Build Message wrapper
Step 4:   Enforce mention-only mode
Step 4.5: Exchange cap check (NEW)
Step 5:   Operator's should_respond
Step 6:   Jitter delay
Step 7:   Typing indicator
Step 8:   Operator's generate_response
Step 9:   Truncate and chunk
Step 10:  Send response
```

---

## Phase 2.0: Prerequisites — Discord Server & Repo Prep

### What this sub-phase delivers

The AgoraGenesis Discord server is ready for multi-bot testing and the repo structure supports a committable testbed.

### 2.0a: AgoraGenesis Discord Server Setup

These are manual steps performed in the browser at discord.com/developers and in the Discord app.

**Channels (create if not already present):**

| Channel | Purpose |
|---|---|
| `#general` | Humans and agents — mention-only for bots |
| `#bot-chat` | Agents talk to each other, humans can observe and intervene |
| `#mod-log` | Moderator logs actions here (write-only for mod bot) |

**Roles (create in this order, higher = more power):**

| Role | Permissions | Assigned to |
|---|---|---|
| `Moderator` | Manage Channels, Manage Messages | Moderator bot (Phase 3) |
| `Agora` | Send Messages, Read Message History, Embed Links | All agent bots |

**Bot applications to create at discord.com/developers:**

| Bot | Application Name | Intents | OAuth2 Permissions | Role |
|---|---|---|---|---|
| Existing | (already created — echo bot) | Message Content | Send Messages, Read Message History | Agora |
| Citizen A | "Agora Citizen A" (or similar) | Message Content | Send Messages, Read Message History, Embed Links | Agora |
| Citizen B | "Agora Citizen B" (or similar) | Message Content | Send Messages, Read Message History, Embed Links | Agora |
| Moderator | "Agora Mod" | Message Content | Send Messages, Read Message History, Manage Channels, Manage Messages | Moderator + Agora |

For each new bot:
1. New Application → name it
2. Bot tab → Reset Token → save token securely (will go in `.env`)
3. Bot tab → enable **Message Content Intent**
4. OAuth2 → URL Generator → Scopes: `bot` → select permissions above → use generated URL to invite
5. In Discord server → assign appropriate role(s)

**Verify role hierarchy in server settings:**
```
Server Owner (you)
  Moderator        ← Agora Mod bot
  Agora            ← All agent bots (including Mod)
  @everyone
```

### 2.0b: Repo Restructure — instance/ to testbed/

**Goal:** Replace the gitignored `instance/` directory with a committable `testbed/` directory where only `.env` files are secret.

**Steps:**

1. Create `testbed/` directory structure:
   ```
   testbed/
   ├── README.md
   ├── echo/
   │   ├── agent.py
   │   ├── agent.yaml
   │   └── run.sh
   ├── moderator/
   │   └── .gitkeep
   ├── citizen-a/
   │   └── .gitkeep
   └── citizen-b/
       └── .gitkeep
   ```

2. Migrate `instance/` contents to `testbed/echo/`:
   - `instance/agent.py` → `testbed/echo/agent.py` (update import paths)
   - `instance/agent.yaml` → `testbed/echo/agent.yaml`
   - `instance/run.sh` → `testbed/echo/run.sh` (update paths)
   - `instance/.env` → `testbed/echo/.env` (stays gitignored)

3. Update `.gitignore`:
   ```diff
   -# Local instance (tokens, config, runner)
   -instance/
   +# Testbed secrets (tokens are per-bot, never committed)
   +testbed/*/.env
   ```

4. Create `testbed/README.md`:
   ```markdown
   # Agora Testbed

   Development bots for testing the agora library on the AgoraGenesis Discord server.

   ## Bots

   - `echo/` — Echo agent (from examples/). Used for basic library testing.
   - `moderator/` — Rule-based moderator (Phase 3).
   - `citizen-a/` — Claude-powered agent, personality A (Phase 4).
   - `citizen-b/` — Claude-powered agent, personality B (Phase 4).

   ## Setup

   Each bot needs a `.env` file with its Discord bot token:

       echo/.env:
       DISCORD_BOT_TOKEN=your-token-here

   These `.env` files are gitignored. Get tokens from the AgoraGenesis server admin.

   ## Running

       cd testbed/echo && bash run.sh
   ```

5. Delete `instance/` after migration is verified.

**File: `testbed/echo/agent.py`**

```python
"""Run the echo agent against the testbed config."""

import sys
from pathlib import Path

# Add repo root to path so agora and examples are importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from examples.echo_agent import EchoAgent

bot = EchoAgent.from_config(
    str(Path(__file__).resolve().parent / "agent.yaml")
)
bot.run()
```

**File: `testbed/echo/agent.yaml`**

```yaml
# Echo agent on AgoraGenesis
token_env: DISCORD_BOT_TOKEN

channels:
  general: mention-only
  bot-chat: subscribe

exchange_cap: 5

jitter_seconds: [1.0, 3.0]
typing_indicator: true
reply_threading: true
max_response_length: 4000
```

Note: `rate_limit` removed from config (decision: exchange cap only).

**File: `testbed/echo/run.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then
    set -a; source .env; set +a
fi
cd ../..
.venv/bin/python testbed/echo/agent.py
```

### 2.0b verification

- `git status` shows testbed/ files as new (not ignored)
- `testbed/echo/.env` does NOT appear in `git status`
- `pytest tests/` still passes (no library changes yet)
- Echo bot runs from testbed: `cd testbed/echo && bash run.sh`

---

## Phase 2a: Exchange Cap Implementation — `safety.py`

### What this sub-phase delivers

A standalone `ExchangeCapChecker` class in `agora/safety.py` that reads Discord channel history and determines whether the exchange cap has been reached.

### New file: `agora/safety.py`

```python
"""Exchange cap — the safety layer.

The exchange cap prevents infinite bot-to-bot loops by limiting
consecutive bot messages in a channel. When the cap is reached,
the bot suppresses its response. A human message resets the counter.

This is cooperative, client-side safety. It protects the operator's
wallet. Server-side enforcement (moderator) is a separate concern.
"""

from __future__ import annotations

import logging

import discord

logger = logging.getLogger("agora")

AGORA_ROLE_NAME = "Agora"


class ExchangeCapChecker:
    """Reads Discord channel history to count consecutive bot messages.

    Each agent independently reads the same shared state (Discord's message
    history) and arrives at the same conclusion. No distributed coordination.
    """

    def __init__(self, cap: int):
        self.cap = cap

    async def is_capped(self, channel: discord.TextChannel) -> bool:
        """Return True if the exchange cap has been reached.

        Algorithm:
        1. Fetch the last (cap + 1) messages from the channel
        2. Walk from most recent backwards
        3. Count consecutive messages where author is a bot or has Agora role
        4. If count >= cap: suppress
        5. If a non-bot human message is found: counter resets, proceed
        """
        messages = []
        async for msg in channel.history(limit=self.cap + 1):
            messages.append(msg)

        consecutive_bot = 0
        for msg in messages:
            if self._is_agent(msg):
                consecutive_bot += 1
            else:
                break  # Human message resets counter

        if consecutive_bot >= self.cap:
            logger.info(
                f"Exchange cap reached in #{channel.name} "
                f"({consecutive_bot} consecutive bot messages, cap={self.cap})"
            )
            return True
        return False

    @staticmethod
    def _is_agent(message: discord.Message) -> bool:
        """Check if a message author is an Agora agent.

        Priority: Agora role > bot flag. The Agora role allows non-bot
        accounts to be recognized as agents. Falls back to the bot flag
        for agents that don't have the role assigned.
        """
        if hasattr(message.author, "roles"):
            for role in message.author.roles:
                if role.name == AGORA_ROLE_NAME:
                    return True
        return message.author.bot
```

**Key differences from the external design doc:**

1. **Own messages count.** The original design had `if msg.author.id == client_user_id: continue` — removed. All bot messages count equally toward the cap. This prevents two-bot ping-pong from running 2x longer than intended.

2. **No `client_user_id` parameter.** Since we don't skip own messages, `is_capped` only needs the channel. Simpler API.

3. **History limit is `cap + 1`, not `cap + 2`.** We only need enough messages to detect whether `cap` consecutive bot messages exist. `cap + 1` gives us one extra to see if a human message follows the bot sequence.

---

## Phase 2b: Peer Detection — `message.py`

### What this sub-phase delivers

An `is_agent` property on `Message` that operators can use in `should_respond` and `generate_response` to know whether a message came from another Agora agent.

### Change to `agora/message.py`

Add one property:

```python
@property
def is_agent(self) -> bool:
    """True if the author has the Agora role or is a bot.

    Uses the same detection logic as the exchange cap checker:
    Agora role takes priority, falls back to the bot flag.
    """
    if hasattr(self._msg.author, "roles"):
        for role in self._msg.author.roles:
            if role.name == "Agora":
                return True
    return self._msg.author.bot
```

**Why this is separate from `is_bot`:**

- `is_bot` is the raw Discord bot flag — True for any bot account.
- `is_agent` is Agora-aware — True for accounts with the Agora role OR the bot flag. This catches the edge case of a human-operated account running as an Agora agent via webhooks or similar.

Operators can use `message.is_agent` in `should_respond` to decide whether to engage with other agents.

---

## Phase 2c: Config Cleanup — Remove Rate Limiting

### What this sub-phase delivers

Remove `RateLimitConfig` and `rate_limit` from the config. Exchange cap is the only safety mechanism in the library for now.

### Changes to `agora/config.py`

1. Delete the `RateLimitConfig` dataclass entirely.
2. Remove the `rate_limit` field from `Config`.
3. Remove the `rate_limit` parsing logic from `from_yaml` (the `rate_raw = raw.pop("rate_limit", {})` block).
4. Update `Config` constructor call in `from_yaml` to not pass `rate_limit`.

### Changes to `agent.yaml` (repo root example)

Remove the `rate_limit` section:

```yaml
# Agora agent configuration
token_env: DISCORD_BOT_TOKEN

channels:
  general: mention-only
  bot-chat: subscribe

exchange_cap: 5

jitter_seconds: [1.0, 3.0]
typing_indicator: true
reply_threading: true
max_response_length: 4000
```

### Changes to tests

- `test_config.py`: Remove any tests that assert on `rate_limit` or `RateLimitConfig`. Add a test that `rate_limit` key in YAML is silently ignored (backward compatibility — old configs with `rate_limit` should still load without error).

---

## Phase 2d: Wire Exchange Cap into Dispatch Pipeline — `bot.py`

### What this sub-phase delivers

The exchange cap checker is instantiated from config and called in the dispatch pipeline before `should_respond`.

### Changes to `agora/bot.py`

**In `__init__`:**

```python
from agora.safety import ExchangeCapChecker

# After existing init code:
self._exchange_cap = ExchangeCapChecker(config.exchange_cap)
```

**In `_on_message`, insert Step 4.5 between Step 4 and Step 5:**

```python
# Step 4: Enforce mention-only mode
if mode == "mention-only" and not message.is_mention:
    return

# Step 4.5: Exchange cap check
if await self._exchange_cap.is_capped(discord_message.channel):
    return

# Step 5: Operator's should_respond
```

**Why before `should_respond`:**

The exchange cap check is a cheap Discord API call (fetch N messages from history). `should_respond` may invoke an LLM or do expensive processing. We want to avoid that cost when we're already capped. If the cap is reached, the bot silently does nothing — same as being in mention-only mode with no mention.

### Updated pipeline (complete)

```
Step 1:   Ignore own messages
Step 2:   Check channel config (skip if None or write-only)
Step 3:   Build Message wrapper
Step 4:   Enforce mention-only mode (skip if not mentioned)
Step 4.5: Exchange cap check (skip if consecutive bot messages >= cap)   ← NEW
Step 5:   Operator's should_respond
Step 6:   Jitter delay
Step 7:   Typing indicator
Step 8:   Operator's generate_response
Step 9:   Truncate and chunk
Step 10:  Send response
```

---

## Phase 2e: Tests

### What this sub-phase delivers

Unit tests for the exchange cap checker, peer detection, config cleanup, and the updated dispatch pipeline. All mocked, no Discord connection.

### New file: `tests/test_safety.py`

```
Test 1 — Cap not reached (mixed messages)
  Mock channel.history returning 3 bot messages then 1 human
  cap = 5
  Assert: is_capped returns False

Test 2 — Cap reached (all bot messages)
  Mock channel.history returning 5 consecutive bot messages
  cap = 5
  Assert: is_capped returns True

Test 3 — Cap exactly at threshold
  Mock channel.history returning 5 bot messages, cap = 5
  Assert: is_capped returns True (>= not >)

Test 4 — Human message resets counter
  Mock: 2 bot, 1 human, 3 bot (from most recent)
  cap = 5
  Assert: is_capped returns False (only 2 consecutive from top)

Test 5 — Own messages count toward cap
  Mock: 5 bot messages, some with same ID as the bot itself
  cap = 5
  Assert: is_capped returns True (own messages are NOT skipped)

Test 6 — Agora role detected as agent
  Mock message.author with roles including "Agora" and bot=False
  Assert: _is_agent returns True

Test 7 — Bot flag detected as agent (no roles)
  Mock message.author without roles but with bot=True
  Assert: _is_agent returns True

Test 8 — Human not detected as agent
  Mock message.author with roles not including "Agora" and bot=False
  Assert: _is_agent returns False

Test 9 — Empty channel history
  Mock channel.history returning 0 messages
  Assert: is_capped returns False

Test 10 — Cap of 1 (minimum valid)
  Mock channel.history returning 1 bot message
  cap = 1
  Assert: is_capped returns True
```

### Updates to `tests/test_message.py`

```
Test — is_agent with Agora role
  Mock author with roles list containing "Agora"
  Assert: message.is_agent is True

Test — is_agent with bot flag
  Mock author with bot=True, no Agora role
  Assert: message.is_agent is True

Test — is_agent for human
  Mock author with bot=False, no Agora role
  Assert: message.is_agent is False
```

### Updates to `tests/test_bot_unit.py`

```
Test — Exchange cap suppresses response
  Configure bot with exchange_cap=3
  Mock channel.history to return 3 consecutive bot messages
  Send a message that would normally trigger should_respond
  Assert: should_respond is never called
  Assert: no response sent

Test — Exchange cap allows response when not reached
  Configure bot with exchange_cap=5
  Mock channel.history to return 2 bot messages then 1 human
  Send a message
  Assert: should_respond IS called (pipeline continues)

Test — Exchange cap allows response after human message
  Configure bot with exchange_cap=3
  Mock channel.history: 1 bot, 1 human, 3 bot (from most recent)
  Assert: should_respond IS called (only 1 consecutive from top)
```

### Updates to `tests/test_config.py`

```
Test — Config loads without rate_limit field
  YAML with no rate_limit key
  Assert: loads successfully, no rate_limit attribute

Test — Config ignores unknown rate_limit field (backward compat)
  YAML with rate_limit: { per_channel_per_hour: 10 }
  Assert: loads successfully (key is silently consumed or ignored)
```

### Test run

```bash
pytest tests/test_safety.py tests/test_message.py tests/test_bot_unit.py tests/test_config.py -v
```

All tests mocked. No Discord connection needed.

---

## Phase 2f: Verification & Cleanup

### What this sub-phase delivers

Confirmation that all changes work together. Full test suite passes. Testbed echo bot runs against AgoraGenesis.

### Verification steps

1. **Full test suite:** `pytest tests/ -v` — all tests pass
2. **Testbed echo bot:** `cd testbed/echo && bash run.sh` — connects to AgoraGenesis, responds to @mentions
3. **Exchange cap live test (manual):**
   - Set `exchange_cap: 2` in testbed echo config
   - @mention the echo bot twice rapidly
   - On third consecutive bot message, bot should stop responding
   - Post a human message → counter resets → bot responds again
4. **Git status check:** `testbed/echo/.env` is not tracked; all other testbed files are tracked
5. **Backward compatibility:** Old `agent.yaml` files with `rate_limit` still load without error

### Cleanup

- Remove `instance/` directory
- Ensure no references to `instance/` remain in code or docs
- Update `SETUP.md` if it references `instance/`

---

## Development Order Summary

| Sub-phase | Scope | Files Changed | New Files |
|---|---|---|---|
| **2.0a** | Discord server prep | (manual, browser) | — |
| **2.0b** | Testbed restructure | `.gitignore` | `testbed/README.md`, `testbed/echo/*`, `testbed/*/. gitkeep` |
| **2a** | Exchange cap checker | — | `agora/safety.py` |
| **2b** | Peer detection | `agora/message.py` | — |
| **2c** | Config cleanup | `agora/config.py`, `agent.yaml` | — |
| **2d** | Wire into pipeline | `agora/bot.py` | — |
| **2e** | Tests | `tests/test_config.py`, `tests/test_message.py`, `tests/test_bot_unit.py` | `tests/test_safety.py` |
| **2f** | Verification | (no new changes) | — |

**Estimated scope:** ~80 lines of new library code (`safety.py` + changes to `bot.py`, `message.py`, `config.py`) + ~120 lines of new tests + testbed restructure.

---

## What Phase 2 Does NOT Include

These are explicitly deferred:

- **Client-side rate limiting** — dropped from library; exchange cap is sufficient
- **Moderator bot** (Phase 3) — placeholders in testbed only
- **Citizen bots** (Phase 4) — placeholders in testbed only
- **`is_agent` property using `members` intent** — we use role inspection on the message author, which doesn't require the privileged members intent
- **PyPI publishing** — still deferred
- **Startup intent validation** — still deferred
