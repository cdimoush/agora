# Agora — Design Journal

## Research Synthesis — 2026-04-04

### Conclusions
- No existing project does what we're building. The decentralized multi-operator Discord agent niche is completely unserved.
- Discord's API is well-suited: per-bot rate limits, bots can read each other's messages, 50-bot cap is plenty, native moderation tools work on bots.
- The critical gap: no built-in bot-loop protection. Must be solved in the library.
- Channel permission overwrites (deny SEND_MESSAGES) are the only reliable way to mute a bot — slow mode doesn't work on bots.
- MESSAGE_CONTENT intent is required and freely available for bots in <100 servers.

### Build rationale
Nothing to buy or adopt. OpenClaw is closest but it's infrastructure, not a library. The coordination protocol itself — loop prevention, peer discovery, rate awareness — is the product.

### Starting assumptions
- Python + discord.py is the right choice for the library (ecosystem fit for AI/ML developers)
- Target: 5-20 agents on a private Discord server with known, trusted operators
- Cooperative trust model — client-side enforcement is sufficient, with an optional moderator bot as safety net
- Discord channel history serves as shared state — no database needed
- Bare bones: no LLM integration, no agent framework, no governance system

## Iteration 1 — 2026-04-04

### Changes from Alt2
- Stripped identity/expertise/keywords from library config — those belong in operator's agent logic, not the library
- Replaced Discord timeout with channel permission overwrites for muting — research confirmed slow mode doesn't affect bots with MANAGE_MESSAGES
- Removed Watcher's "unauthorized channel" detection and "non-library bot" detection — too much feature creep
- Dropped slash commands entirely — 3-second interaction timeout is incompatible with LLM response times
- Simplified moderator to ~150 lines focused on exchange cap + rate limit enforcement only
- Added startup checks for MESSAGE_CONTENT intent (the #1 setup gotcha from research)
- Justified Python over Go with concrete reasoning from research (discordgo is v0.x, AI developers are Python-native)
- Added `agora init` CLI scaffolding for operator onboarding

### Decisions made
1. **Python, not Go.** Target audience is AI/ML developers who already have Python. Go binary distribution is appealing but forces users into Go for custom agent logic, which is a dealbreaker.
2. **No slash commands.** Plain messages only. Avoids 3-second timeout, simpler implementation, more natural for multi-agent conversation.
3. **Channel permission overwrites for muting.** The only reliable way to silence a bot. Slow mode doesn't work. Timeout requires role hierarchy which is fragile.
4. **Minimal config surface.** Token, channels, exchange cap, rate limits, jitter, response behavior. That's it.
5. **No prompt injection protection in the library.** That's the operator's LLM security problem. Document the risk, don't try to solve it.

### Remaining unknowns
- All remaining unknowns are implementation-level, not architectural. Ready to build.

## Phase 2 Design Review — 2026-04-04

### Context
Reviewed the external system design doc (`system_designer/designs/2026-04-04/agora-testbed/system-design.md`) which proposed Phases 2–4 with sibling directories, a moderator bot, and a citizen bot. The review surfaced several issues and the user made key decisions.

### Design Philosophy — Established

**Agora's safety is self-interested, not policed.**

- Client-side safety exists to protect the operator's wallet. If you bypass your own exchange cap and your bot loops, you pay for it.
- Server-side safety (moderator) is the server owner's responsibility. If the moderator goes down, that's an ops problem, not a library bug.
- Agora ships safe defaults. Operators can modify or bypass them. The library doesn't try to prevent misuse — it makes the default behavior safe.
- Servers will have moderators. If an operator removes their client-side safety, the server moderator will enforce limits. If the server has no moderator, that's the server admin's problem.

This philosophy will eventually become a formal statement in the Agora repository (similar to a PEP or project charter).

### Decisions Made

1. **Sibling directories confirmed.** Each bot is a standalone project that depends on agora as a library. For development speed, testbed bots live inside the agora repo under `testbed/`. They graduate to standalone repos when stable.

2. **Moderator is a server-owner concern, not core library.** The agora library provides client-side safety (exchange cap). A moderator bot is something the server admin builds or deploys — it's not a required component. We build one for testing purposes in the testbed.

3. **Claude CLI subprocess for citizen bots — confirmed.** This is how the user builds agents. The citizen bot spawns `claude -p` as a subprocess. This is a hard dependency for Claude-powered agents, but non-Claude agents (echo, keyword) work without it.

4. **Exchange cap counts own messages.** The original design skipped the bot's own messages when counting consecutive bot messages. Correction: a bot's own messages MUST count toward the cap. This prevents two-bot ping-pong loops from running longer than necessary.

5. **Rate limiting dropped from library.** Exchange cap is sufficient for loop prevention. Rate limiting adds complexity for marginal benefit at this stage. Operators can set `--max-budget-usd` on their Claude calls for per-invocation cost protection. Rate limiting can be added later if exchange cap proves insufficient. The `rate_limit` config field and `RateLimitConfig` dataclass will be removed from the library.

6. **Two citizen bots for testing.** Since the moderator is rule-based and doesn't converse, we need two citizen bots to observe agent-to-agent interaction during live testing. Different CLAUDE.md personalities, same code, different tokens.

7. **instance/ refactored to testbed/.** The existing `instance/` directory (single echo bot) becomes `testbed/` with subdirectories for moderator and citizens. Secrets (.env files) stay gitignored.

### What Changed from External Design Doc

| External Design | Agora Decision |
|---|---|
| Three sibling git repos (`~/agora/`, `~/agora-mod/`, `~/agora-citizen/`) | Testbed inside agora repo; sibling repos later |
| One citizen bot | Two citizen bots (needed for agent-to-agent testing) |
| Rate limiting in library (RateLimiter class in safety.py) | Dropped — exchange cap only |
| Exchange cap skips own messages | Exchange cap counts own messages |
| Moderator as a first-class deliverable | Moderator in testbed for testing; not core library |
| Moderator mutes bots via channel permission overwrites | Deferred — moderator starts as warn-only (logs to mod-log) |
| Citizen `should_respond` heuristic (keyword matching) | Needs redesign — too broad, fires on common English words |

### Remaining Questions (for later phases)

- Moderator enforcement actions: warn-only vs mute vs kick — decide after observing two citizens talking
- Channel topology for AgoraGenesis server — what channels, what purposes
- Citizen `should_respond` logic — start mention-only and open up subscribe after observing behavior
- What the testbed graduates into — examples? Templates? Standalone repos?
