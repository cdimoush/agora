# Research: Discord Bot Libraries & SDK Analysis

**Bead:** system_designer-md1.3  
**Date:** 2026-04-04  
**Status:** Complete

---

## 1. Discord API Hard Facts

### 1.1 Rate Limits

Discord rate limits operate at multiple tiers. Every number below is per-bot (identified by auth token), not shared across bots on the same server.

| Scope | Limit | Notes |
|-------|-------|-------|
| **Global** | 50 requests/second per bot | Across all endpoints. Unauthenticated requests limited per-IP instead. |
| **Per-route** | Varies by endpoint | Bucketed by `X-RateLimit-Bucket` header. Grouped by top-level resource (channel_id, guild_id, webhook_id). |
| **Message sending** | 5 messages / 5 seconds / channel | Per-bot, per-channel. Two bots can each send 5 msg/5s to the same channel independently. |
| **Gateway events** | 120 events / 60 seconds / connection | Outbound commands only (IDENTIFY, HEARTBEAT, etc.). ~2 commands/sec. |
| **IDENTIFY** | `max_concurrency` per 5 seconds | Returned in session_start_limit. Typically 1 for small bots. |
| **Invalid requests** | 10,000 / 10 minutes per IP | Requests returning 401, 403, or 429. Triggers temporary IP ban. |

**Critical insight for multi-bot servers:** Rate limits are **per-bot, per-route, per-resource**. If you have 15 bots on one server, each bot gets its own 5 msg/5s limit per channel. They do NOT share a pool. This means 15 bots could collectively send 75 messages per 5 seconds to a single channel — a real flood risk that needs application-level coordination.

Response headers for rate limit tracking:
- `X-RateLimit-Limit` — bucket capacity
- `X-RateLimit-Remaining` — remaining requests
- `X-RateLimit-Reset` — unix timestamp for reset
- `X-RateLimit-Reset-After` — seconds until reset
- `X-RateLimit-Bucket` — unique bucket identifier
- `X-RateLimit-Scope` — `user`, `global`, or `shared`

### 1.2 Gateway Intents

**Standard Intents (no approval needed):**
- GUILDS (1 << 0)
- GUILD_MODERATION (1 << 2)
- GUILD_EXPRESSIONS (1 << 3)
- GUILD_INTEGRATIONS (1 << 4)
- GUILD_WEBHOOKS (1 << 5)
- GUILD_INVITES (1 << 6)
- GUILD_VOICE_STATES (1 << 7)
- GUILD_MESSAGES (1 << 9)
- GUILD_MESSAGE_REACTIONS (1 << 10)
- GUILD_MESSAGE_TYPING (1 << 11)
- DIRECT_MESSAGES (1 << 12)
- DIRECT_MESSAGE_REACTIONS (1 << 13)
- DIRECT_MESSAGE_TYPING (1 << 14)
- GUILD_SCHEDULED_EVENTS (1 << 16)
- AUTO_MODERATION_CONFIGURATION (1 << 20)
- AUTO_MODERATION_EXECUTION (1 << 21)
- GUILD_MESSAGE_POLLS (1 << 24)
- DIRECT_MESSAGE_POLLS (1 << 25)

**Privileged Intents (require Developer Portal toggle; need approval for verified bots in 100+ servers):**
- GUILD_MEMBERS (1 << 1) — full member list, join/leave events
- GUILD_PRESENCES (1 << 8) — online/offline/DND status, rich presence
- MESSAGE_CONTENT (1 << 15) — message text, embeds, attachments, components

### 1.3 MESSAGE_CONTENT Intent — The Critical Details

This is the single most important API fact for the agora project.

**What it gates:** The `content`, `embeds`, `attachments`, and `components` fields in message objects received via gateway events. Without it, these fields arrive as empty strings/arrays.

**Exemptions (content is ALWAYS available for):**
1. Messages the bot itself sends
2. Messages in DMs with the bot
3. Messages that @mention the bot
4. Message objects received via interaction payloads (slash commands, buttons, etc.)

**What this means for agora:**
- Bot A sends a message. Bot B receives the MESSAGE_CREATE event but sees **empty content** unless Bot B has MESSAGE_CONTENT intent enabled.
- **Workaround 1:** Bot B is @mentioned in every message — content becomes visible. Noisy and impractical for natural conversation.
- **Workaround 2:** Every bot enables MESSAGE_CONTENT intent. Fine for unverified bots (<100 servers). For verified bots, Discord will **reject** the intent application unless you can prove you need raw message content for a compelling feature that can't use slash commands.
- **Workaround 3:** Use webhooks or embeds for structured data exchange alongside messages. The embed field IS gated by MESSAGE_CONTENT though.
- **Workaround 4:** Use a shared database/message bus outside Discord. Bots post to Discord for human display but coordinate via Redis/NATS/etc.

**Verification threshold:** Bots in fewer than 100 servers can freely enable privileged intents via the Developer Portal toggle. No application needed. Since agora servers are likely small (tens of users, not thousands), this is manageable — but it means every bot instance needs its own application with the toggle enabled.

### 1.4 Bot-to-Bot Interaction Rules

**Can bots see each other's messages?**
- Yes, bots receive MESSAGE_CREATE events for other bots' messages via the GUILD_MESSAGES intent (not privileged).
- However, the message **content** is empty without MESSAGE_CONTENT intent (see above).
- Bots can detect that a message was sent by a bot via the `author.bot` flag.

**Can bots react to each other's messages?**
- Yes, with ADD_REACTIONS permission. No special restrictions.

**Can bots reply to each other?**
- Yes, using message references. No restrictions.

**Is there a "bot loop" protection?**
- **No built-in protection.** Discord does not prevent bots from triggering each other in infinite loops. This is entirely the developer's responsibility. This is a real risk for agora and needs application-level circuit breakers.

### 1.5 Server Bot Limits

- **Hard limit: 50 bots per server.** Implemented by Discord; servers that exceeded this before the limit was imposed are grandfathered.
- Slash commands are limited to the newest 50 bots — beyond that, slash commands won't register.
- For agora targeting 10-20 agent bots: **well within limits.** Plenty of headroom.
- Each bot requires its own application in the Developer Portal, its own token, and its own gateway connection.

### 1.6 Bot-on-Bot Moderation

**Can a bot timeout another bot?**
- Yes, with MODERATE_MEMBERS permission AND the moderator bot's highest role must be ABOVE the target bot's highest role in the hierarchy.
- Cannot timeout bots with ADMINISTRATOR permission.

**Can a bot kick/ban another bot?**
- Yes, with KICK_MEMBERS/BAN_MEMBERS permission AND role hierarchy advantage.

**Can a bot delete another bot's messages?**
- Yes, with MANAGE_MESSAGES permission. **Role hierarchy does NOT apply to message deletion** — this is a key distinction. MANAGE_MESSAGES grants the ability to delete ANY message in the channel regardless of the author's role position. (Role hierarchy only constrains kick/ban/timeout/role management.)

**Can a bot mute another bot (remove send permission)?**
- Yes, by modifying channel permission overwrites, with MANAGE_CHANNELS or MANAGE_ROLES permission. Role hierarchy applies for role-based approaches.

**Practical implications for agora:**
A dedicated moderator bot with a top-tier role and MODERATE_MEMBERS + MANAGE_MESSAGES + KICK_MEMBERS can:
- Delete any agent's messages (no hierarchy needed)
- Timeout misbehaving agents (needs role hierarchy advantage)
- Kick agents from the server (needs role hierarchy advantage)
- Set channel slow mode to throttle all agents

### 1.7 Discord Native Moderation Tools

**AutoMod (API-configurable):**
- Keyword filters: up to 100 keywords per rule, 60 chars each, regex supported (Rust flavor)
- Can auto-timeout, auto-delete, auto-alert on keyword match
- Configurable via API — a setup bot could configure AutoMod rules programmatically
- Requires MANAGE_GUILD permission to configure
- Supports KEYWORD, MENTION_SPAM, and SPAM trigger types

**Slow Mode:**
- `rate_limit_per_user` on channels: 0-21600 seconds (0 to 6 hours)
- Bots with MANAGE_MESSAGES or MANAGE_CHANNELS bypass slow mode
- Useful for throttling human users but **bots bypass it** if they have the right permissions

**Channel Permissions:**
- Can deny SEND_MESSAGES per-channel for specific bot roles
- Can be modified programmatically by a moderator bot
- This is the most reliable way to "mute" a runaway bot — revoke its send permission

---

## 2. Discord.py 2.x (Python)

### Status & Maintenance

| Metric | Value |
|--------|-------|
| **Latest version** | 2.7.1 (March 3, 2026) |
| **GitHub stars** | ~16,000 |
| **Open issues** | ~86 |
| **PyPI downloads** | ~2.15M/month |
| **Python support** | 3.8 - 3.12 |
| **License** | MIT |
| **Maintainer** | Rapptz (sole primary maintainer) |
| **Status classifier** | Production/Stable |

### Key Characteristics

- **Actively maintained.** Regular releases throughout 2025-2026 (2.5.0 through 2.7.1). The 2021 "discord.py is dead" scare is long over — Rapptz returned and has been shipping consistently.
- **Full Gateway v10 support.** Has been on v10 since the 2.0 rewrite.
- **Async-native.** Built on asyncio, uses `async`/`await` throughout. Good fit for concurrent bot operations.
- **Built-in rate limit handling.** Automatic retry with backoff on 429s. Parses X-RateLimit headers.
- **Reconnection.** Automatic gateway reconnection with resume support.
- **Comprehensive API coverage.** Slash commands, buttons, modals, select menus, threads, forums, AutoMod.

### Multi-Bot Considerations

- No known issues with running multiple discord.py instances on the same server.
- Each bot needs its own `Client` instance with its own token and gateway connection.
- Asyncio event loop is per-process; multiple bots in one process is possible but not recommended (use separate processes).
- Rate limit handling is per-client, which correctly maps to Discord's per-bot limits.

### Forks: Pycord and Nextcord

Both emerged during the 2021 discord.py hiatus. Now that discord.py is back:
- **Pycord (py-cord):** Most popular fork, has diverged with its own features. Active community.
- **Nextcord:** Another active fork, more conservative in divergence.
- **Recommendation:** Use discord.py directly. It's the original, has the most downloads, best docs, and Rapptz is actively maintaining it. The forks exist but add fragmentation without clear advantage for new projects.

### Documentation Quality

Excellent. ReadTheDocs-hosted, comprehensive API reference, migration guides, intent primer, extensive examples. The discord.py docs are considered the gold standard for Discord library documentation.

---

## 3. discord.js (Node.js / TypeScript)

### Status & Maintenance

| Metric | Value |
|--------|-------|
| **Latest version** | 14.26.2 (April 3, 2025) |
| **GitHub stars** | ~25,000+ |
| **npm dependents** | ~6,000 packages |
| **License** | Apache-2.0 |
| **TypeScript** | First-class support, ships types |
| **Maintenance** | Very active, multiple releases per week |

### Key Characteristics

- **Most popular Discord library overall.** Largest community, most tutorials, most Stack Overflow answers.
- **TypeScript-first.** Ships with complete type definitions. Excellent for type-safe bot development.
- **Comprehensive.** Full API coverage including voice, threads, AutoMod, application commands.
- **Mature rate limit handling.** Built-in queue system with bucket tracking.
- **Well-organized codebase.** Monorepo with separate packages (@discordjs/rest, @discordjs/ws, @discordjs/builders, etc.).

### Considerations for agora

**Pros:**
- Largest ecosystem and community
- TypeScript provides good DX for library consumers
- npm distribution is familiar to JS/TS developers
- Excellent documentation and guides

**Cons:**
- `node_modules` bloat — dependency tree is heavy
- Node.js runtime requirement adds complexity for distribution
- Less natural fit for AI/ML developers (most AI tooling is Python-first)
- Process model (single-threaded event loop) means one bot per process is the natural pattern

---

## 4. DiscordGo (Go)

### Status & Maintenance

| Metric | Value |
|--------|-------|
| **Latest version** | v0.29.0 (May 24, 2025) |
| **GitHub stars** | ~5,900 |
| **Commits** | 1,637 |
| **Forks** | 913 |
| **License** | BSD-3-Clause |
| **API version** | Not explicitly stated; tracks current Discord API |

### Key Characteristics

- **Low-level bindings.** Maps closely to Discord's REST and WebSocket APIs. Not an opinionated framework.
- **Nearly complete API coverage.** Endpoints, websocket, and voice interface.
- **Still v0.x.** Explicitly warns: "This library and the Discord API are unfinished. Because of that there may be major changes to library in the future."
- **Maintains backward compatibility** as a design principle, which some find limiting.
- **Active but slow-paced.** Sustainable maintenance, but not rapid feature development.

### Go Alternatives

- **Arikawa** (~500 stars): More modular, type-safe snowflakes (ChannelID vs MessageID), but smaller community.
- **Disgo**: Modular wrapper, newer, less proven.

### Considerations for agora

**Pros:**
- Single binary distribution — `curl | install` for end users
- Excellent concurrency model (goroutines) — natural fit for multi-bot coordination
- Low memory footprint per bot instance
- No dependency hell — everything compiles into one binary

**Cons:**
- v0.x stability concerns
- Smaller community means fewer examples, less Stack Overflow help
- Less familiar to AI/ML developers
- Building a user-friendly framework on top of low-level bindings requires significant effort
- No equivalent to discord.py's decorator-based command framework built-in

---

## 5. Rust Discord Libraries

### Serenity

| Metric | Value |
|--------|-------|
| **Latest version** | v0.12.5 (December 20, 2025) |
| **GitHub stars** | ~5,500 |
| **Total releases** | 87 |
| **MSRV** | Rust 1.74 |

- Batteries-included, opinionated framework
- Standard framework deprecated in favor of Poise (command framework)
- Active maintenance, regular releases
- Ecosystem: Songbird (voice), Poise (commands), Lavalink-rs (audio)

### Twilight

- More modular, lower-level alternative to Serenity
- MSRV: Rust 1.89 (very current)
- Targets advanced Rust developers who want full control

### Considerations for agora

**Pros:**
- Single binary, tiny memory footprint
- Best performance characteristics of any option
- Strong type system catches errors at compile time

**Cons:**
- Steep learning curve — Rust is hard for most developers
- Compile times are long
- Smaller ecosystem than Python or JS
- Neither library is v1.0 yet
- AI/ML integration is weakest here — most AI SDKs are Python-first
- Would significantly limit contributor pool

---

## 6. Language Tradeoff Analysis

### Distribution & Installation Experience

| Language | Install Experience | Binary? | Dependency Pain |
|----------|-------------------|---------|-----------------|
| **Python** | `pip install agora` | No | virtualenv, Python version conflicts, pip vs pipx vs poetry |
| **Go** | `curl -L url \| tar xz && ./agora` | Yes | None — single binary |
| **Node/TS** | `npm install agora` | No | node_modules bloat, Node version management |
| **Rust** | `cargo install agora` or download binary | Yes | None if pre-built, long compile if from source |

### Developer Ecosystem Fit

| Factor | Python | Go | Node/TS | Rust |
|--------|--------|-----|---------|------|
| AI/ML SDK availability | Excellent | Poor | Good | Poor |
| Discord library maturity | Excellent | Good | Excellent | Good |
| Async model quality | Good (asyncio) | Excellent (goroutines) | Good (event loop) | Excellent (tokio) |
| Library consumer DX | Good | Good | Excellent (types) | Good (types) |
| Contributor accessibility | High | Medium | High | Low |
| Multi-bot orchestration | Good | Excellent | Good | Excellent |

### The Real Question: Who Is the User?

The target user for agora is an **AI/ML developer** who wants to set up a multi-agent Discord server. This person:
- Almost certainly has Python installed and knows pip
- Probably has some Node.js experience
- Unlikely to have Go or Rust toolchains installed
- Cares about integration with LLM APIs (OpenAI, Anthropic, etc.) — all Python-first
- Wants `pip install` + config file + run, not "compile from source"

### Recommendation

**Python (discord.py) is the right choice.** Here's why:

1. **User base alignment.** AI/ML developers live in Python. Making them install Go or Node to run agent bots creates unnecessary friction.
2. **discord.py is rock-solid.** 2.7.1, Production/Stable, 2M+ monthly downloads, active maintenance, excellent docs.
3. **Ecosystem.** Every LLM SDK (openai, anthropic, langchain, etc.) is Python-first. Bot agents need to call these — Python makes this trivial.
4. **Distribution.** `pip install agora` is the expected UX. Yes, virtualenv is a pain, but it's a known pain that the audience already deals with daily.
5. **Async model.** discord.py's asyncio base works well with modern async LLM clients.

**Go as a secondary option** is worth considering if the project later needs a standalone orchestrator/moderator daemon that doesn't need LLM integration. A single Go binary for the "server setup + moderator" component could complement Python agent bots.

---

## 7. Comparison Table

| Dimension | discord.py (Python) | discord.js (Node/TS) | discordgo (Go) | serenity (Rust) |
|-----------|--------------------|--------------------|---------------|----------------|
| **Maturity** | Production/Stable | Production/Stable | v0.x (pre-1.0) | v0.x (pre-1.0) |
| **Latest version** | 2.7.1 (Mar 2026) | 14.26.2 (Apr 2025) | 0.29.0 (May 2025) | 0.12.5 (Dec 2025) |
| **GitHub stars** | ~16K | ~25K | ~5.9K | ~5.5K |
| **Downloads** | 2.15M/month (PyPI) | Very high (npm) | N/A (Go modules) | N/A (crates.io) |
| **API completeness** | Full | Full | Nearly complete | Full |
| **Rate limit handling** | Built-in, automatic | Built-in, queued | Built-in | Built-in |
| **Gateway v10** | Yes | Yes | Yes (implicit) | Yes |
| **Async model** | asyncio | Event loop | Goroutines | Tokio |
| **Documentation** | Excellent | Excellent | Good | Good |
| **Maintenance cadence** | Monthly | Weekly | Quarterly | Monthly |
| **AI/ML ecosystem fit** | Excellent | Good | Poor | Poor |
| **Distribution simplicity** | pip install | npm install | Single binary | Binary or cargo |
| **Multi-bot suitability** | Good | Good | Excellent | Excellent |
| **Command framework** | Built-in (ext.commands) | Built-in | None (DIY) | Poise (separate) |
| **Contributor pool** | Large | Largest | Medium | Small |
| **License** | MIT | Apache-2.0 | BSD-3 | ISC |

---

## 8. Key Findings Summary

### Discord API Facts That Shape the Design

1. **Rate limits are per-bot.** 15 bots can flood a channel with 75 msg/5s. Application-level coordination is mandatory.
2. **MESSAGE_CONTENT is privileged** but freely available for bots in <100 servers. Each bot needs the toggle enabled in Developer Portal.
3. **Bot-to-bot message reading requires MESSAGE_CONTENT intent.** Without it, bots see each other's messages arrive but content is empty.
4. **No built-in bot-loop protection.** Discord will happily let bots trigger each other forever. Circuit breakers are the library's job.
5. **50 bot limit per server.** 10-20 agents is well within bounds.
6. **Message deletion ignores role hierarchy.** A moderator bot with MANAGE_MESSAGES can delete any bot's messages regardless of role position.
7. **Timeout/kick/ban respect role hierarchy.** Moderator bot needs the highest role to control all agents.
8. **Slow mode doesn't affect bots** with MANAGE_MESSAGES/MANAGE_CHANNELS. Not useful for throttling agents.
9. **AutoMod is API-configurable** and can auto-timeout on keyword match — useful for safety rails.
10. **Channel permission overwrites** are the most reliable way to mute a runaway bot (deny SEND_MESSAGES).

### Library Recommendation

**Use discord.py.** It's the right choice for a Python-ecosystem AI tool. The library is mature, actively maintained, well-documented, and aligns perfectly with the target user base of AI/ML developers.
