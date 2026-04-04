# Agora — Decentralized Library Architecture

## What we're designing

A minimal library that lets anyone add an AI agent to a shared Discord server. No central orchestrator, no hosted service, no platform. Discord is the infrastructure — message routing, connection management, permissions, moderation. Each operator installs the library, configures their bot token and LLM, and connects directly to Discord's Gateway. Agents communicate through Discord channels exactly like human users do.

The library standardizes the minimal conventions needed for independently-operated agents to coexist: self-identification, loop prevention, and rate limiting. Everything else is the operator's problem.

## Why it matters

The user currently runs multiple AI agents via Relay on Telegram and wants to expand into multi-agent interaction where agents (operated by different people) can collaborate in a shared space. The key constraint: this must support multiple contributors, not just the server owner. The centralized orchestrator designs (original monolith and Alt1) fail this test — they require all agents to route through infrastructure the server admin operates and maintains. The decentralized model pushes infrastructure to Discord (free, reliable, already built) and pushes agent logic to each operator.

## Domain constraints

- **Platform**: Discord (Gateway WebSocket + REST API)
- **Language**: To be determined by research — Python (simplest path, discord.py ecosystem) vs Go (single binary distribution) vs other
- **Deployment**: Each agent runs on its operator's own infrastructure (laptop, VPS, container)
- **Scale**: 5-20 agents on a single Discord server. Not designing for hundreds.
- **Trust model**: Cooperative. Known participants, private server. Not adversarial.

## Key questions this design should answer

1. Does this project already exist? Is there an existing library that does exactly this?
2. Can Discord's native permissions and rate limiting handle runaway bots, or do we need a lightweight moderator bot?
3. What language gives the best tradeoff between ease of contribution (SDK for agent authors) and ease of deployment (curl a binary vs pip install)?
4. What are the real Discord API gotchas for multi-bot servers (rate limits, intent requirements, message content access)?
5. What is the absolute minimum viable library surface — what can we defer?

## Success criteria for the design document

- Grounded in real Discord API capabilities and limitations, not assumptions
- Makes a clear language recommendation with reasoning
- Specifies the exact library API surface (what operators implement, what the library handles)
- Addresses moderation with the minimum viable approach
- Someone could read this and start building immediately
