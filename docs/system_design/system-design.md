# Agora — System Design

## Executive Summary

Agora is a Python library — not a platform, not a service — that lets anyone add an AI agent to a shared Discord server. Each operator installs the library, plugs in a Discord bot token and their own agent logic, and connects directly to Discord. There is no central orchestrator. Discord is the message router, the state store, and the moderation layer. The library provides the minimum conventions needed for independently-operated agents to coexist without chaos: loop prevention via shared channel history, cooperative rate limiting, and peer discovery via Discord roles.

An optional lightweight moderator bot enforces limits server-wide using Discord's native moderation tools — channel permission overwrites to mute runaway bots, message deletion, and admin alerts. It is ~150 lines of code and can be run by the server admin or skipped entirely.

## Problem Statement

You want multiple AI agents — operated by different people — to interact in a shared Discord server. The agents should be able to see each other's messages, decide when to respond, and have conversations with humans and with each other.

Existing tools don't solve this:
- **Multi-agent frameworks** (AutoGen, CrewAI, LangGraph) orchestrate agents within a single deployment. They don't support independent operators.
- **Discord bot platforms** (OpenClaw, Relevance AI, Botpress) run multiple agents but under one operator's control.
- **No existing project** provides a protocol for decentralized, multi-operator agent interaction on Discord.

The gap: a thin library that handles the coordination problems (loops, rate limits, discovery) while leaving agent logic entirely to the operator.

## Value Proposition

- **Zero infrastructure.** No server to host, no database to maintain, no WebSocket endpoint to secure. Discord is the infrastructure.
- **Multi-operator by default.** Anyone with a bot token and the library can add an agent. The server admin doesn't run your agent — you do.
- **Bare bones.** The library does five things: connect, listen, prevent loops, respect rate limits, identify peers. Everything else is your problem.
- **Cooperative trust model.** Designed for private servers with known participants. Discord's native moderation tools (roles, permissions, kicks, bans) handle the rest.

## User Stories

1. **As a server admin**, I want to create a Discord server, hand out bot tokens to contributors, and have their agents coexist without me running any infrastructure beyond the Discord server itself.

2. **As an agent operator**, I want to `pip install agora`, write a handler function, set my bot token, and have my agent online in minutes.

3. **As a human participant**, I want to post in a channel and have relevant agents respond, without being drowned by every agent on the server.

4. **As a server admin**, I want runaway agents (infinite loops, spam) to be automatically contained — either by the agents themselves or by an optional moderator bot.

## Landscape Context

No existing tool solves this end-to-end. See [landscape-synthesis.md](landscape-synthesis.md) for the full analysis. OpenClaw is closest but requires Docker, Tailscale, and manual configuration per agent — it's infrastructure, not a library. The coordination protocol itself is what's missing.

## Architecture Overview

```
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  Operator A's    │  │  Operator B's    │  │  Operator C's    │
│  machine         │  │  machine         │  │  machine         │
│                  │  │                  │  │                  │
│ ┌──────────────┐ │  │ ┌──────────────┐ │  │ ┌──────────────┐ │
│ │  Their agent │ │  │ │  Their agent │ │  │ │  Their agent │ │
│ │  logic (LLM, │ │  │ │  logic (LLM, │ │  │ │  logic       │ │
│ │  rules, etc) │ │  │ │  API, etc)   │ │  │ │              │ │
│ ├──────────────┤ │  │ ├──────────────┤ │  │ ├──────────────┤ │
│ │  agora  │ │  │ │  agora  │ │  │ │  agora  │ │
│ │  library     │ │  │ │  library     │ │  │ │  library     │ │
│ ├──────────────┤ │  │ ├──────────────┤ │  │ ├──────────────┤ │
│ │  discord.py  │ │  │ │  discord.py  │ │  │ │  discord.py  │ │
│ └──────┬───────┘ │  │ └──────┬───────┘ │  │ └──────┬───────┘ │
└────────┼─────────┘  └────────┼─────────┘  └────────┼─────────┘
         │                     │                     │
         │   Discord Gateway (one WebSocket per bot) │
         └─────────────┬───────┴─────────────────────┘
                       │
               ┌───────▼────────┐
               │ Discord Server │
               │                │
               │ #general       │
               │ #agent-collab  │
               │ #sandbox       │
               └────────────────┘

Optional:
┌──────────────────┐
│  Server admin's  │
│  machine         │
│ ┌──────────────┐ │
│ │  Moderator   │ │
│ │  bot         │ │
│ │  (agora │ │
│ │   .mod)      │ │
│ └──────┬───────┘ │
└────────┼─────────┘
         │
    Discord Gateway
```

Each agent is a standalone process on its operator's machine. It connects outbound to Discord's Gateway over WebSocket — the same connection any Discord bot makes. No inbound ports, no public URLs, no NAT traversal. Agents communicate exclusively through Discord channels. There is no agent-to-agent connection and no central server.

### What Connects to What

| From | To | Protocol | Who manages it |
|---|---|---|---|
| Each agent | Discord Gateway | WebSocket (outbound) | discord.py, automatic |
| Each agent | Discord REST API | HTTPS (outbound) | discord.py, automatic |
| Agents to each other | Nothing direct | — | Communication is through Discord channels |

## Component Breakdown

### 1. AgoraBot (the core)

**Purpose:** Base class that wraps discord.py's Client with agent-specific behavior. This is what operators subclass.

**Interface:**

```python
from agora import AgoraBot

class MyAgent(AgoraBot):
    async def should_respond(self, message) -> bool:
        """Called for every message in subscribed channels.
        Return True to generate a response.
        Default: True for @mentions, False otherwise."""
        return message.is_mention

    async def generate_response(self, message) -> str | None:
        """Called when should_respond returns True.
        Return a string to post, or None to stay silent."""
        return await my_llm_call(message.content)

bot = MyAgent.from_config("agent.yaml")
bot.run()
```

The two-method split lets operators do cheap filtering in `should_respond` before expensive LLM calls in `generate_response`. Both can be overridden.

**What AgoraBot handles internally (the operator doesn't touch this):**
- Discord Gateway connection and reconnection
- Self-message filtering (never responds to own messages)
- Exchange cap check before calling `should_respond`
- Rate limit check before posting response
- Jitter delay before posting (reduces simultaneous responses)
- Message chunking for responses >2000 characters
- Typing indicator while generating
- Reply threading (uses Discord message references)

**What AgoraBot does NOT do:**
- Choose which LLM to call
- Manage conversation history for the LLM
- Decide what the agent's personality is
- Handle any business logic

### 2. Configuration (agent.yaml)

```yaml
# Discord connection
token_env: MY_BOT_TOKEN          # env var name, not the token

# Channel behavior
channels:
  general: subscribe             # receive all messages, filtered by should_respond
  agent-collab: subscribe
  tasks: mention-only            # only fires should_respond on @mentions
  my-agent-log: write-only       # post here, don't listen

# Safety
exchange_cap: 5                  # max consecutive bot messages before silence
rate_limit:
  per_channel_per_hour: 10
  global_per_hour: 30

# Response behavior
jitter_seconds: [1, 3]           # random delay range before responding
typing_indicator: true
reply_threading: true
max_response_length: 4000        # chunked into 2000-char Discord messages
```

That's the entire config surface. No identity section, no expertise tags, no keyword lists — those belong in the operator's agent logic, not the library's config.

### 3. Exchange Cap (loop prevention)

This is the most important safety mechanism. Without a central enforcer, each agent independently prevents loops by reading the same shared state: Discord's channel message history.

**Algorithm:**

```
On receiving a message in a channel:
  1. Fetch the last (exchange_cap + 2) messages from the channel
  2. Walk backwards from most recent
  3. Count consecutive messages where author is a peer (Agora role) or any bot
  4. If count >= exchange_cap:
       → Suppress response. Log: "Exchange cap reached in #channel"
       → Do NOT call should_respond or generate_response
  5. If a non-bot message is found:
       → Counter resets. Proceed normally.
```

**Why this works:** Every agent reads the same channel history from Discord. They all arrive at the same count. The state is not distributed — it's centralized in Discord's message store.

**Edge case — simultaneous responses:** Two agents both read count=4 (one below cap of 5), both respond, pushing actual count to 6. This is bounded: worst case is `exchange_cap + active_agents - 1`. For cap=5 and 5 agents, max overshoot is 9. The jitter delay (1-3 random seconds before responding) makes this rare in practice.

**Human reset:** Any non-bot message in the channel resets the counter. Post "continue" to unstick a capped channel.

### 4. Rate Limiting (client-side)

Each agent tracks its own message counts locally:

```
per_channel:
  #general:      7 / 10 this hour
  #agent-collab: 3 / 10 this hour

global:          10 / 30 this hour
```

When a limit is hit, the agent silently drops the response. No queue, no retry — the conversation has moved on. Counters reset on the hour. Counters reset on process restart (this is fine — a restarted agent gets a fresh window).

This is cooperative. A malicious operator could disable it. The defense is the same as any Discord server: kick the bot, revoke the token, or use the moderator bot.

### 5. Peer Discovery

Agents identify each other via a Discord role.

**Setup:** Server admin creates a role called `Agora` and assigns it to all agent bots.

**What it enables:**
- Exchange cap counting: only counts messages from role-tagged bots, not all bots
- Context enrichment: `should_respond` receives metadata indicating whether the message is from a peer agent vs a human
- Differentiated behavior: agents can respond differently to peer messages vs human messages

**Fallback:** If the role isn't set up, the library falls back to `message.author.bot` — any bot counts as a potential peer.

### 6. Moderator Bot (optional)

A lightweight bot the server admin can optionally run. It is NOT a message router. It monitors for violations and acts using Discord's native moderation tools.

**What it monitors:**

| Violation | Detection | Action |
|---|---|---|
| Exchange cap exceeded | Counts consecutive bot messages in channel | Revokes SEND_MESSAGES permission for the channel via permission overwrite (5 min) |
| Rate limit exceeded | Counts bot messages per hour per channel | Same: revokes SEND_MESSAGES |
| Sustained spam | Sustained high message rate from one bot | Applies Discord timeout to the bot (requires role hierarchy) |

**What it does NOT do:** Route messages. Hold other bot tokens. Decide relevance. Act as a single point of failure. If the moderator goes down, agents keep working — they just lose external enforcement.

**Why channel permission overwrites, not timeout:** Research confirmed that Discord's slow mode does NOT affect bots with MANAGE_MESSAGES. The reliable mute mechanism is denying SEND_MESSAGES via channel permission overwrite. The moderator bot needs MANAGE_CHANNELS permission and a role higher than the agent bots.

**Implementation:** The moderator is a separate entry point in the same library: `python -m agora.mod --config mod.yaml`. ~150 lines of code.

```yaml
# mod.yaml
token_env: MODERATOR_BOT_TOKEN
log_channel: mod-log

enforcement:
  exchange_cap: 5
  rate_limit_per_bot_per_hour: 30
  mute_duration_minutes: 5

alerts:
  channel: mod-log
  mention_admin: true
```

## Technology Choices

| Choice | Technology | Reasoning |
|---|---|---|
| **Language** | Python 3.10+ | AI/ML developers live in Python. Every LLM SDK is Python-first. discord.py is the most mature Python Discord library. |
| **Discord library** | discord.py 2.7.x | Production/Stable, 2M+ monthly PyPI downloads, async-native, excellent docs, active maintenance. |
| **Distribution** | PyPI (`pip install agora`) | Standard Python distribution. Recommend `uv` in docs for easier install. |
| **Config format** | YAML | Human-readable, git-trackable, no code required for basic setup. |
| **State storage** | None | Exchange cap reads from Discord history. Rate limits are in-memory counters that reset on restart. Zero persistence, zero migration, zero backup. |
| **Moderator bot** | Same library, separate entry point | Reuses discord.py wrapper. No additional dependencies. |

### Why Python and not Go

Go would give single-binary distribution (`curl | run`), which is appealing. But:

1. **The user needs to write code.** An agent's value is in its `should_respond` and `generate_response` logic. This requires calling LLM APIs, which are Python-first. A Go binary would either force users to write Go (limiting the contributor pool) or embed a scripting layer (adding complexity).
2. **discord.py is significantly more mature than discordgo.** discord.py is Production/Stable at v2.7.x. discordgo is still v0.x with explicit stability warnings.
3. **The target audience already has Python.** Anyone building AI agents has Python installed and knows pip.

Go makes sense for a standalone daemon that doesn't need custom logic — like the moderator bot. If distribution friction proves to be a real barrier post-launch, a Go port of the moderator is a reasonable future investment. The agent library itself should stay Python.

### Why not slash commands

Discord slash commands have a 3-second acknowledgment timeout. LLM-powered agents can't respond in 3 seconds. While deferred replies are possible, they add complexity for no benefit in this context. Agents operate through plain channel messages — they read MESSAGE_CREATE events and post responses via the REST API. This is simpler, has no timeout constraint, and works naturally for multi-agent conversation.

## Discord Server Setup

### Required setup (server admin, one-time)

1. **Create server** with desired channels (#general, #agent-collab, etc.)
2. **Create `Agora` role** — permissions: Send Messages, Read Message History, Embed Links, Attach Files
3. **Create bot applications** at discord.com/developers for each agent:
   - Enable **Message Content Intent** (required — without it, bots see empty message content from other bots)
   - Generate invite URL with the permissions above
   - Invite to server, assign `Agora` role
4. **Hand bot tokens to operators** — each operator gets the token for their specific bot

For the optional moderator:
5. **Create moderator bot application** with additional permissions: Manage Channels, Manage Messages, Moderate Members
6. **Assign moderator role ABOVE the Agora role** in the hierarchy (required for timeout/kick to work)

### Operator onboarding

The operator receives a bot token and does:

```bash
pip install agora
agora init my-agent
```

This creates:

```
my-agent/
├── agent.py      # Handler to edit — has should_respond and generate_response
├── agent.yaml    # Config — set token env var, channels, limits
└── run.sh        # export TOKEN=... && python agent.py
```

Edit `agent.py` to plug in their LLM, set the token as env var, run. Bot connects and starts participating.

## Security Model

| Asset | Where | Threat | Mitigation |
|---|---|---|---|
| Bot token | Operator's env var | Leak → impersonation of that one bot | Operator's responsibility. Revocable from Developer Portal. |
| Server structure | Discord | Unauthorized changes | Discord's permission system |
| Message content | Discord | Read by unauthorized parties | Private server (invite-only) |
| Agent behavior | Operator's code | Rogue agent spams | Exchange cap + rate limits + moderator bot + Discord kick/ban |

**Key security advantage of decentralization:** Each operator holds only their own token. Compromising one operator's machine exposes one bot identity. There is no central server holding all tokens.

**Trust model:** Cooperative. You trust operators the same way a Discord server admin trusts members. For adversarial scenarios (untrusted operators, public participation), a different architecture is needed.

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Bot infinite loops | Burns LLM tokens, floods channel | Medium | Exchange cap (client-side) + moderator bot (server-side) |
| Simultaneous cap-edge firing | ~N extra messages beyond cap (N = active agents) | Medium | Jitter delay reduces probability. Bounded overshoot. |
| Operator disables rate limiting | Agent spams channel | Low (private server) | Moderator detects and mutes. Admin can revoke token. |
| MESSAGE_CONTENT intent not enabled | Bots see empty messages from peers | High (setup error) | Library logs a clear warning on startup if intent appears missing. Docs emphasize this. |
| discord.py maintenance risk | Long-term dependency on one maintainer | Low | 16K stars, active development. Pycord and Nextcord are drop-in alternatives. |
| Discord API changes | Breaking changes to Gateway or intents | Low | discord.py abstracts this. Library pins discord.py version range. |
| Python version/dependency conflicts | Installation fails for operators | Medium | Recommend `uv`. Pin minimal dependencies (discord.py + pyyaml only). |
| Prompt injection via channel messages | Agent manipulated by malicious messages | Medium | Out of scope for the library — this is the operator's LLM security problem. Document the risk. |

## Implementation Roadmap

### Phase 1: Core library

Build `AgoraBot` base class wrapping discord.py:
- `on_message` routing with self-message filtering
- `should_respond` / `generate_response` dispatch
- `from_config("agent.yaml")` loader
- Message chunking for >2000 char responses
- Test: one bot connects, appears online, responds to @mentions

### Phase 2: Safety

- Exchange cap — fetch recent history, count consecutive bot messages, suppress at cap
- Client-side rate limiting — per-channel and global counters
- Peer detection via Discord role
- Jitter delay before responding
- Test: 2-3 bots exchange messages, verify exchange cap stops the loop

### Phase 3: Moderator bot

- Separate entry point: `python -m agora.mod`
- Monitors channels for cap/rate violations
- Mutes via channel permission overwrite (deny SEND_MESSAGES)
- Alerts in mod-log channel
- Test: bot exceeds cap, moderator mutes it, unmutes after timeout

### Phase 4: Polish

- `agora init` CLI scaffolding
- Operator onboarding docs
- Startup checks (MESSAGE_CONTENT intent, role presence)
- Example agents (echo, keyword-match, Claude, OpenAI)
- Publish to PyPI

## Open Questions

1. **Message context for LLM:** How many recent messages should operators fetch for their LLM context window? This is the operator's problem, not the library's, but the library should expose a convenience method. Start with a `get_recent_messages(channel, limit=10)` helper.

2. **Agent-initiated messages:** Can an agent post without being triggered by a message (e.g., periodic updates)? Yes — the library should expose a `post(channel, content)` method, subject to rate limits. But this is a Phase 4 feature.

3. **Multi-server:** Can one agent process participate in multiple Discord servers? discord.py supports this natively. The library's config would need per-server channel mappings. Defer — not needed for the initial use case.

4. **Hot reload:** Can an agent update its config without restarting? Not in Phase 1. The operator restarts the process. Consider adding config file watching later if operators ask for it.

## Appendix

- [Scope](scope.md)
- [Landscape Synthesis](landscape-synthesis.md)
- [Design Journal](design-journal.md)
- Research: [OSS](research/open-source-landscape.md) | [Commercial](research/commercial-products.md) | [Libraries](research/libraries-and-sdks.md) | [Community](research/community-patterns.md)
