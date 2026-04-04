# Agora — Landscape Synthesis

## Executive Summary

No existing project — open source or commercial — builds what Agora aims to build: a lightweight library that lets independently-operated AI agents coexist on a shared Discord server without central orchestration. The space has hundreds of "put an AI agent on Discord" projects and dozens of multi-agent orchestration frameworks, but zero solutions for the decentralized multi-operator case.

Discord's architecture is surprisingly well-suited for this. Rate limits are per-bot-token (not shared), bots can read each other's messages with the MESSAGE_CONTENT intent, there's a hard cap of 50 bots per server (plenty of headroom for 10-20 agents), and Discord provides real moderation tools — a bot with the right role can timeout, kick, or revoke send permissions for other bots. The critical missing piece is a coordination layer: loop prevention, rate awareness, and peer discovery built on top of Discord's existing primitives.

The one major gotcha: Discord has **no built-in bot-loop protection**. Two bots can trigger each other infinitely. This must be solved in the library. The good news: Discord's channel history is a shared source of truth that every agent can read independently — making cooperative client-side loop detection viable without centralization.

## Comparison Matrix

| Tool/Project | Type | Language | Stars/Users | Decentralized? | Multi-Operator? | Status |
|---|---|---|---|---|---|---|
| OpenClaw | Self-hosted gateway | TypeScript | 347K | Partially (w/ Tailscale) | Yes (heavy setup) | Active |
| claude-code-discord-bridge | Claude Code bridge | Python | 28 | No | No | Active |
| claudecode-discord | Multi-machine hub | TS/C#/Swift/Py | 34 | No | No | Active |
| AutoGen | Agent framework | Python | 56.7K | No | No | Active |
| CrewAI | Agent orchestration | Python | 44.3K | No | No | Active |
| LangGraph | DAG agent workflows | Python | 24.8K | No | No | Active |
| Relevance AI | SaaS bot platform | — | — | No | No | Active |
| Botpress | Bot platform | — | — | No (central router) | No | Active |
| Character.AI | Consumer chat | — | — | No (walled garden) | No | Active |
| Google A2A Protocol | Interop standard | — | — | Yes (HTTP/SSE) | Yes | Draft |

## Build vs Buy Recommendation

**Build.** Nothing to buy. The coordination protocol is the product.

### Why not "just use X"

- **OpenClaw** is the closest but requires Docker, Tailscale, and manual per-agent configuration. It's infrastructure, not a library. The agora user wants `pip install` + config file + run.
- **A2A Protocol** defines the right concepts (opaque agents communicating over a standard protocol) but runs over HTTP/SSE. Nobody has adapted it to Discord as a transport. It's a reference for design thinking, not a dependency.
- **Multi-agent frameworks** (AutoGen, CrewAI, LangGraph) solve orchestration within a single deployment. They don't address independent operators sharing a Discord server.

### What to build

A thin Python library on top of discord.py that provides:
1. **Connection management** — wraps discord.py Client with agent-specific defaults
2. **Loop prevention** — reads Discord channel history to count consecutive bot messages, suppresses at cap
3. **Client-side rate limiting** — per-channel and global message caps, cooperative
4. **Peer discovery** — identifies other Agora agents via Discord role
5. **Message formatting** — chunking, reply threading, typing indicators

That's it. No LLM integration, no agent framework, no orchestration. The operator brings their own agent logic.

## Key Technologies to Incorporate

| Technology | Role | Why |
|---|---|---|
| **discord.py 2.7.x** | Discord connection | Production/Stable, 2M+ monthly downloads, async-native, excellent docs. The only serious choice for Python Discord bots. |
| **Python 3.10+** | Library language | AI/ML developers live in Python. Every LLM SDK is Python-first. `uv` is making distribution less painful. |
| **YAML** | Agent configuration | Human-readable, git-trackable, no code required for basic setup |
| **Discord roles** | Peer discovery | Native mechanism, no external infrastructure |
| **Discord channel history** | Loop detection state | Shared source of truth, no database needed |
| **Discord channel permission overwrites** | Moderation (muting bots) | The only reliable way to silence a bot — slow mode doesn't affect bots with MANAGE_MESSAGES |

### Key Discord API Facts That Shape the Design

1. **Rate limits are per-bot-token.** 15 bots can collectively push 75 msg/5s into one channel. Application-level coordination is mandatory.
2. **MESSAGE_CONTENT intent is privileged** but freely toggleable for bots in <100 servers. Each bot needs it enabled in Developer Portal.
3. **No built-in bot-loop protection.** Circuit breakers are the library's job.
4. **50 bot limit per server.** 10-20 agents is well within bounds.
5. **Slow mode does NOT affect bots** with MANAGE_MESSAGES/MANAGE_CHANNELS. Channel permission overwrites (deny SEND_MESSAGES) are the reliable mute mechanism.
6. **Timeout/kick/ban respect role hierarchy.** A moderator bot needs the highest role.
7. **Message deletion ignores role hierarchy.** MANAGE_MESSAGES can delete any message.
8. **3-second interaction timeout** — LLM-powered agents must use deferred replies for slash commands, or skip slash commands entirely and use plain messages.
