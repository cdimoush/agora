# Agora Phase 3 — Implementation Plan

**Goal:** Fill the testbed with two Claude-powered citizen bots and an MVP moderator. A human starts one process, opens Discord, and sees agents conversing. They can talk with the citizens or watch them talk to each other.

**End state:** `python testbed/run.py` starts three bots (moderator + two citizens) on AgoraGenesis. Citizens respond to messages using `claude -p` with haiku. The moderator watches for exchange cap violations and warns in `#mod-log`. An integration test forces a short conversation and verifies the exchange cap fires. The whole thing runs as a long-lived process until Ctrl+C.

**Prerequisite:** Phase 2 complete (exchange cap in library, testbed structure, bot tokens created for all three bots on AgoraGenesis).

---

## Current State (After Phase 2)

### Library (`agora/`)

| File | Status | Relevant to Phase 3 |
|---|---|---|
| `bot.py` | Complete | `AgoraBot` base class, dispatch pipeline with exchange cap at Step 4.5. `run()` blocks — citizens and moderator subclass this. |
| `safety.py` | Complete | `ExchangeCapChecker.is_capped(channel)` — moderator reuses this directly. |
| `config.py` | Complete | `Config` with `exchange_cap`, `channels`, `jitter_seconds`, etc. |
| `message.py` | Complete | `Message` with `is_agent`, `is_bot`, `is_mention`, `content`, etc. |

### Testbed (`testbed/`)

```
testbed/
├── README.md
├── echo/              # Working echo bot (from Phase 2)
│   ├── agent.py
│   ├── agent.yaml
│   ├── run.sh
│   └── .env           # DISCORD_BOT_TOKEN (gitignored)
├── moderator/
│   ├── .gitkeep
│   └── .env           # AGORA_MOD_TOKEN (gitignored, already has token)
├── citizen-a/
│   ├── .gitkeep
│   └── .env           # AGORA_CITIZEN_A_TOKEN (gitignored, already has token)
└── citizen-b/
    ├── .gitkeep
    └── .env           # AGORA_CITIZEN_B_TOKEN (gitignored, already has token)
```

All three bot tokens already exist in `.env` files. Bot applications are created on AgoraGenesis with Message Content Intent enabled.

### AgoraGenesis Discord Server

| Channel | Purpose |
|---|---|
| `#general` | Humans and agents — mention-only for bots |
| `#bot-chat` | Agents talk to each other, humans observe and intervene |
| `#mod-log` | Moderator posts warnings here |

---

## Target State (After Phase 3)

### Testbed structure

```
testbed/
├── README.md            # Updated with run instructions
├── run.py               # NEW: starts all three bots, runs until Ctrl+C
├── echo/                # Unchanged from Phase 2
│   ├── ...
├── moderator/
│   ├── mod.py           # NEW: ModeratorBot subclass
│   ├── agent.yaml       # NEW: moderator config
│   └── .env             # Existing token
├── citizen-a/
│   ├── citizen.py       # NEW: CitizenBot subclass
│   ├── agent.yaml       # NEW: citizen config
│   ├── CLAUDE.md        # NEW: personality A
│   └── .env             # Existing token
└── citizen-b/
    ├── citizen.py        # NEW: CitizenBot subclass (same code, symlink or copy)
    ├── agent.yaml        # NEW: citizen config
    ├── CLAUDE.md         # NEW: personality B (different from A)
    └── .env              # Existing token
```

### New integration test

```
tests/integration/test_testbed_live.py   # NEW: forces a short convo, checks cap
```

---

## Phase 3a: Citizen Bot Implementation

### What this sub-phase delivers

A `CitizenBot` class that subclasses `AgoraBot` and overrides `generate_response` to spawn `claude -p` via subprocess. Two instances with different personalities.

### File: `testbed/citizen-a/citizen.py`

The citizen bot's `generate_response`:

1. Fetches recent channel history (last 10 messages) via `discord_message.channel.history(limit=10)`
2. Formats history into a prompt: `[bot] Alice: hello\n[human] Dave: what's up?\n...`
3. Appends the triggering message
4. Spawns `claude -p "<prompt>" --output-format json --model haiku --max-budget-usd 0.02 --dangerously-skip-permissions --append-system-prompt "..."`
5. `cwd=` set to the citizen's directory so Claude reads that citizen's `CLAUDE.md`
6. Parses JSON response, returns `result` text

**Subprocess pattern (lifted from relay/src/relay/agent.py):**

```python
async def _call_claude(self, prompt: str) -> str | None:
    """Spawn claude -p subprocess and return the response text."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)  # Prevent nested session error

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", "haiku",
        "--max-budget-usd", "0.02",
        "--append-system-prompt", SYSTEM_PROMPT,
        "--dangerously-skip-permissions",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=self._project_dir,  # Claude reads CLAUDE.md from here
        env=env,
        start_new_session=True,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=60
        )
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        await proc.wait()
        return None

    if proc.returncode != 0:
        logger.error("Claude error: %s", stderr.decode()[:500])
        return None

    try:
        data = json.loads(stdout.decode())
    except json.JSONDecodeError:
        return None

    return data.get("result", "") or None
```

**Key details:**

- `SYSTEM_PROMPT` tells Claude it's in a Discord conversation, to keep responses to 1-2 sentences, avoid markdown headers, and stay conversational.
- `cwd=self._project_dir` points to the citizen's directory — Claude picks up `CLAUDE.md` automatically.
- 60-second timeout (haiku is fast — this is generous).
- `start_new_session=True` for clean process group kills on timeout.
- `env.pop("CLAUDECODE", None)` prevents nested Claude Code session errors.

**`should_respond` override:**

```python
async def should_respond(self, message: Message) -> bool:
    if message.is_mention:
        return True
    # In subscribe channels, respond to non-bot messages
    # (Let exchange cap handle bot-to-bot loop prevention)
    return not message.is_bot or message.is_mention
```

Citizens respond to human messages and @mentions. They also respond to bot messages (enabling agent-to-agent conversation), but the exchange cap in the dispatch pipeline (Step 4.5) prevents infinite loops.

**Building the prompt from channel history:**

```python
async def generate_response(self, message: Message) -> str | None:
    # Access the raw discord channel for history
    channel = self._client.get_channel(message.channel_id)
    if not channel:
        return None

    # Fetch recent history for context
    history_lines = []
    async for msg in channel.history(limit=10):
        if msg.id == message.id:
            continue
        role = "bot" if msg.author.bot else "human"
        history_lines.append(f"[{role}] {msg.author.display_name}: {msg.content}")
    history_lines.reverse()

    prompt = f"Channel: #{message.channel_name}\n"
    if history_lines:
        prompt += f"Recent messages:\n" + "\n".join(history_lines) + "\n\n"
    prompt += f"{message.author_name}: {message.content}"

    return await self._call_claude(prompt)
```

**Note on `self._client` access:** The citizen needs access to the raw discord client to fetch channel history. `AgoraBot` already exposes `self._client` as an attribute (set in `__init__`). The citizen uses `self._client.get_channel(message.channel_id)` to get the channel object for history fetching.

### File: `testbed/citizen-a/agent.yaml`

```yaml
token_env: AGORA_CITIZEN_A_TOKEN

channels:
  general: mention-only
  bot-chat: subscribe

exchange_cap: 5
jitter_seconds: [1.0, 3.0]
typing_indicator: true
reply_threading: true
max_response_length: 2000
```

### File: `testbed/citizen-a/CLAUDE.md`

```markdown
# Citizen A — Nova

You are Nova, a curious AI participating in a Discord server. You love asking
follow-up questions and exploring ideas. You find everything genuinely interesting.

Rules:
- 1-2 sentences max. Always.
- Ask a follow-up question when you can.
- Never use markdown headers or bullet lists.
- Sound like a person texting, not an assistant writing a report.
```

### File: `testbed/citizen-b/CLAUDE.md`

```markdown
# Citizen B — Rex

You are Rex, a dry and opinionated AI participating in a Discord server.
You have strong takes and you say them plainly. Not rude, just direct.

Rules:
- 1-2 sentences max. Always.
- State your opinion, don't hedge.
- Never use markdown headers or bullet lists.
- Sound like a person texting, not an assistant writing a report.
```

### citizen-b/citizen.py

Same code as citizen-a. The only differences between the two citizens are:
- `agent.yaml` — different `token_env` (`AGORA_CITIZEN_B_TOKEN`)
- `CLAUDE.md` — different personality
- `cwd` when calling Claude — points to its own directory

The `citizen.py` file can be identical. Either copy it or symlink — copy is simpler for a testbed.

### citizen-b/agent.yaml

```yaml
token_env: AGORA_CITIZEN_B_TOKEN

channels:
  general: mention-only
  bot-chat: subscribe

exchange_cap: 5
jitter_seconds: [1.5, 4.0]     # Slightly different jitter to reduce collision
typing_indicator: true
reply_threading: true
max_response_length: 2000
```

---

## Phase 3b: MVP Moderator

### What this sub-phase delivers

A `ModeratorBot` that subclasses `AgoraBot`, imports `ExchangeCapChecker` from the library, and posts warnings to `#mod-log` when the exchange cap is reached. No LLM. No muting. No new library features.

### File: `testbed/moderator/mod.py`

```python
class ModeratorBot(AgoraBot):
    """Server-side observer. Watches for exchange cap violations, warns in mod-log."""

    async def should_respond(self, message: Message) -> bool:
        """Monitor all bot messages."""
        return message.is_agent

    async def generate_response(self, message: Message) -> str | None:
        """Check exchange cap. If violated, warn in mod-log. Return None always."""
        channel = self._client.get_channel(message.channel_id)
        if channel is None:
            return None

        if await self._exchange_cap.is_capped(channel):
            await self._warn_mod_log(
                f"Exchange cap reached in #{message.channel_name} "
                f"({self.config.exchange_cap} consecutive bot messages)"
            )

        return None  # Moderator never posts visible responses

    async def _warn_mod_log(self, text: str) -> None:
        """Post a warning to #mod-log."""
        for guild in self._client.guilds:
            for ch in guild.text_channels:
                if ch.name == "mod-log":
                    await ch.send(f"[MOD] {text}")
                    return
        logger.warning("No #mod-log channel found: %s", text)
```

**Key point:** The moderator uses `self._exchange_cap` which is already instantiated by `AgoraBot.__init__` from `config.exchange_cap`. Zero new code in the library — the moderator just reuses the Phase 2 safety module from a different vantage point.

**Why `generate_response` returns None:** The moderator communicates through `#mod-log` only, never as a reply in conversation channels. Returning None means the dispatch pipeline's Step 9/10 (truncate, chunk, send) are skipped.

**Why `should_respond` filters on `is_agent`:** The moderator only needs to check cap on bot messages. Human messages can't trigger an exchange cap violation (they reset it). This avoids unnecessary `channel.history()` API calls.

### File: `testbed/moderator/agent.yaml`

```yaml
token_env: AGORA_MOD_TOKEN

channels:
  general: subscribe        # Monitor everything
  bot-chat: subscribe
  mod-log: write-only       # Post warnings, don't listen

exchange_cap: 5
jitter_seconds: [0.0, 0.0]  # Moderator acts immediately
typing_indicator: false
reply_threading: false
max_response_length: 4000
```

---

## Phase 3c: Testbed Launcher

### What this sub-phase delivers

`testbed/run.py` — a single script that starts all three bots concurrently in one asyncio event loop. Runs until Ctrl+C.

### File: `testbed/run.py`

```python
"""Start the full Agora testbed — moderator + two citizens.

Usage:
    python testbed/run.py

Runs until Ctrl+C. Requires .env files in each bot subdirectory.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from testbed.moderator.mod import ModeratorBot
from testbed.citizen_a.citizen import CitizenBot as CitizenA  # or import from path
from testbed.citizen_b.citizen import CitizenBot as CitizenB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("testbed")


async def main():
    # Load .env files for each bot
    _load_env(repo_root / "testbed" / "moderator" / ".env")
    _load_env(repo_root / "testbed" / "citizen-a" / ".env")
    _load_env(repo_root / "testbed" / "citizen-b" / ".env")

    # Create bot instances from their configs
    mod = ModeratorBot.from_config(str(repo_root / "testbed" / "moderator" / "agent.yaml"))
    citizen_a = CitizenA.from_config(str(repo_root / "testbed" / "citizen-a" / "agent.yaml"))
    citizen_b = CitizenB.from_config(str(repo_root / "testbed" / "citizen-b" / "agent.yaml"))

    # Start all three (client.start is the async version of client.run)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [
        asyncio.create_task(mod._client.start(mod.config.token)),
        asyncio.create_task(citizen_a._client.start(citizen_a.config.token)),
        asyncio.create_task(citizen_b._client.start(citizen_b.config.token)),
    ]

    logger.info("Testbed started — moderator + 2 citizens. Ctrl+C to stop.")

    await stop_event.wait()

    logger.info("Shutting down...")
    for bot in [mod, citizen_a, citizen_b]:
        await bot._client.close()
    for task in tasks:
        task.cancel()


def _load_env(path: Path) -> None:
    """Source a .env file into os.environ."""
    if not path.exists():
        logger.warning("No .env at %s — skipping", path)
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ[key.strip()] = value.strip()


if __name__ == "__main__":
    import os
    asyncio.run(main())
```

**Why `client.start()` not `bot.run()`:** `bot.run()` calls `client.run()` which blocks and creates its own event loop. We need all three bots in the same loop. `client.start()` is the async coroutine version — it connects to Discord and runs until closed.

**Why `_load_env` instead of python-dotenv:** Avoids adding a dependency for something trivial. The `.env` files are simple `KEY=VALUE` lines.

**Signal handling:** SIGINT (Ctrl+C) and SIGTERM both set the stop event, which triggers graceful shutdown — close all three Discord clients, cancel tasks.

---

## Phase 3d: Integration Test

### What this sub-phase delivers

One integration test that starts the testbed bots, sends a message to `#bot-chat`, verifies a citizen responds, and verifies the exchange cap fires after enough consecutive bot messages.

### File: `tests/integration/test_testbed_live.py`

```
Test 1 — Citizen responds to human message
  Start citizen-a (only) against AgoraGenesis
  Post "@CitizenA hello" in #bot-chat via a helper bot or the test client
  Assert: citizen-a responds within 30 seconds
  Assert: response is non-empty and reasonably short (< 500 chars)

Test 2 — Exchange cap stops conversation
  Start citizen-a and citizen-b
  Post a message in #bot-chat to trigger conversation
  Wait for exchange cap (5 consecutive bot messages)
  Assert: no further bot messages after cap reached
  Assert: moderator posts "[MOD] Exchange cap reached" in #mod-log
```

These tests require `--live` flag and real bot tokens. They're slow (30+ seconds for Claude responses). Run with:

```bash
pytest tests/integration/test_testbed_live.py --live -v
```

---

## Phase 3e: Verification & PR

### Verification steps

1. **Unit tests pass:** `pytest tests/ -v --ignore=tests/integration` — no regressions
2. **Manual testbed run:**
   - `python testbed/run.py` — all three bots come online
   - Open Discord → `#bot-chat` → type "Hey Nova, what do you think about music?"
   - Citizen A (Nova) responds with a curious follow-up
   - Citizen B (Rex) may chime in with a dry take
   - After 5 bot messages, both citizens stop (exchange cap)
   - `#mod-log` shows `[MOD] Exchange cap reached in #bot-chat`
   - Type "keep going" in `#bot-chat` — human message resets cap, citizens resume
   - Ctrl+C — all three bots disconnect cleanly
3. **Integration tests pass:** `pytest tests/integration/test_testbed_live.py --live -v`
4. **Git status clean:** no secrets committed, `.env` files gitignored
5. **PR ready:** commit all testbed code, create PR to main

### Cleanup

- Remove `.gitkeep` files from directories that now have real files
- Update `testbed/README.md` with run instructions
- Verify `testbed/citizen-a/.env` and `testbed/citizen-b/.env` are not tracked

---

## Development Order Summary

| Sub-phase | Scope | New Files |
|---|---|---|
| **3a** | Citizen bot implementation | `testbed/citizen-a/citizen.py`, `testbed/citizen-a/agent.yaml`, `testbed/citizen-a/CLAUDE.md`, same for citizen-b |
| **3b** | MVP moderator | `testbed/moderator/mod.py`, `testbed/moderator/agent.yaml` |
| **3c** | Testbed launcher | `testbed/run.py` |
| **3d** | Integration test | `tests/integration/test_testbed_live.py` |
| **3e** | Verification & PR | (no new files) |

**Estimated scope:** ~150 lines citizen code (shared), ~40 lines moderator, ~80 lines launcher, ~60 lines integration test. ~330 lines total new code + CLAUDE.md personality files.

**No library changes.** Phase 3 adds zero lines to `agora/`. Everything is in `testbed/` and `tests/integration/`. The citizens and moderator are pure consumers of the Phase 2 library.

---

## What Phase 3 Does NOT Include

- **Session management (`--resume`)** — each message is a fresh Claude call with channel history as context
- **Moderator enforcement (muting, kicking)** — warn only in `#mod-log`
- **Rate limiting** — exchange cap is the only safety mechanism
- **Persistent conversation memory** — context comes from Discord channel history, nothing stored locally
- **Multiple model options** — hardcoded to haiku for cost control
- **Any changes to the agora library** — testbed only
