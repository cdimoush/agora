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
