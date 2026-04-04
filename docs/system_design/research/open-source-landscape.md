# Open Source Landscape: Multi-Agent Discord Interaction

Research date: 2026-04-04

## Executive Summary

No existing project directly implements what "agora" aims to build: a **decentralized library** that lets independently-operated AI agents coexist, discover each other, and collaborate on a shared Discord server without central orchestration. The closest projects fall into three categories:

1. **Claude Code Discord bridges** -- single-agent remote-control tools, some with concurrency support
2. **Multi-platform bot frameworks** -- route messages from Discord to LLMs, but centrally operated
3. **Multi-agent orchestration frameworks** -- powerful agent coordination, but assume a single operator and don't use Discord as the interaction substrate

The gap is clear: nobody has built a *protocol-level library* for decentralized agent-to-agent interaction on Discord.

---

## Category 1: Claude Code Discord Bridges

These projects wrap Claude Code (via the Agent SDK) and expose it through Discord. They are the most relevant because they prove the pattern of "AI agent operating through Discord," but none support decentralized multi-agent scenarios.

### ebibibi/claude-code-discord-bridge

| Field | Value |
|-------|-------|
| URL | https://github.com/ebibibi/claude-code-discord-bridge |
| Stars | ~28 |
| Language | Python |
| Last Activity | Active (March 2026) |
| License | -- |

**What it does:** Maps Discord threads 1:1 to Claude Code sessions. Each thread spawns an isolated Claude Code process in its own git worktree.

**Key features:**
- Thread = Session architecture with streaming responses
- **AI Lounge** -- a shared "breakroom" channel where concurrent sessions coordinate before risky operations
- Active session registry for awareness between parallel sessions
- Worktree isolation (wt-{thread_id}) preventing file conflicts
- SchedulerCog with SQLite-backed periodic tasks
- Session resume, sync, and interrupt capabilities

**Multi-agent relevance:** This is the closest thing to agent coordination on Discord. The AI Lounge pattern -- where sessions post intentions and check before destructive operations -- is a primitive coordination protocol. However, it assumes all agents are the same Claude Code instance controlled by the same operator. No support for independently-operated agents.

**Verdict:** Best existing coordination pattern, but centralized single-operator design.

---

### chadingTV/claudecode-discord

| Field | Value |
|-------|-------|
| URL | https://github.com/chadingTV/claudecode-discord |
| Stars | ~34 |
| Language | TypeScript (36%), C# (20%), Swift (20%), Python (14%) |
| Last Activity | v1.2.3, March 27, 2026 |

**What it does:** Multi-machine agent hub. Control Claude Code on multiple computers from a single Discord server.

**Key features:**
- One Discord server hosts multiple bots (one per machine)
- Channel sidebar becomes a real-time status dashboard across machines
- Tool approval/denial via Discord buttons
- Message queuing for sequential task processing
- No API key needed (uses Claude Pro/Max subscription)

**Multi-agent relevance:** Core strength is multi-machine support, making Discord a control plane. Each machine runs its own bot token. However, "multi-agent" here means "same person controlling multiple machines," not independently-operated agents.

**Verdict:** Proves the multi-bot-on-one-server pattern works. Not decentralized.

---

### zebbern/claude-code-discord

| Field | Value |
|-------|-------|
| URL | https://github.com/zebbern/claude-code-discord |
| Stars | ~163 |
| Language | TypeScript (98%) |
| Last Activity | v2.3.0, March 2, 2026 |

**What it does:** Discord bot bringing Claude Code to channels with shell/git execution, thread-per-session architecture, and role-based access control.

**Key features:**
- Built on @anthropic-ai/claude-agent-sdk
- Mid-session controls (interrupts, model changes, state rewind)
- Channel monitoring with automatic alert investigation
- MCP server management

**Multi-agent relevance:** None. Single-agent, single-operator design.

---

### Other Claude Code Discord projects

- **MichaelAyles/claude-code-comm-bot** -- interact with Claude Code from Discord, anywhere
- **RhysSullivan/claude-sandbox-bot** -- Claude Code in Vercel Sandbox via Discord
- **wrathagom/ai-discord-bot** -- Claude Code + OpenAI Codex, channel-per-project mapping

All are single-agent, single-operator tools.

---

## Category 2: Multi-Platform Bot Frameworks

These frameworks route messages from Discord (and other platforms) to AI backends. They are centrally operated but demonstrate mature Discord integration patterns.

### OpenClaw (formerly Clawdbot/Moltbot)

| Field | Value |
|-------|-------|
| URL | https://github.com/openclaw/openclaw |
| Stars | **347k** (fastest-growing OSS project in GitHub history) |
| Language | TypeScript (Node.js) |
| Created | November 2025 by Peter Steinberger |
| Last Activity | Active, January 2026+ |
| License | Open source |

**What it does:** Self-hosted personal AI assistant that connects 30+ chat platforms (including Discord) to AI models. Functions as a long-running Node.js gateway service.

**Key features:**
- Multi-agent routing: route inbound channels/accounts to isolated agents (workspaces + per-agent sessions)
- Single Gateway instance runs multiple fully isolated agents
- Each agent gets own model, tools, memory, workspace
- DM policy configuration, allowlists, group routing
- Per-channel message chunking and mention gating

**Multi-agent relevance:** OpenClaw's multi-agent routing is the most mature implementation of "multiple agents on Discord." However:
- All agents run through a **single Gateway** controlled by one operator
- Agents are isolated by design -- they don't collaborate or discover each other
- No protocol for inter-agent communication
- "Multi-agent" means "multiple personalities served by one infrastructure"

**Verdict:** Best production infrastructure for running multiple Discord bots, but fundamentally centralized. Agents are tenants, not peers.

---

### LangBot (formerly QChatGPT)

| Field | Value |
|-------|-------|
| URL | https://github.com/langbot-app/LangBot |
| Stars | **15.7k** |
| Language | Python (55%), TypeScript (44%) |
| Last Activity | v4.9.5, March 31, 2026 |
| License | Open source |

**What it does:** Production-grade platform for agentic IM bots across Discord, Telegram, Slack, LINE, QQ, WeChat, and more.

**Key features:**
- Unified codebase for 10+ messaging platforms
- Plugin system (each plugin runs in its own process via JSON-RPC)
- Built-in RAG, access control, rate limiting, content filtering
- Integrates with Dify, n8n, Langflow, Coze, OpenAI, Claude, Gemini
- Quick-start: `uvx langbot`

**Multi-agent relevance:** Single-operator bot framework. No inter-agent communication or decentralized operation.

**Verdict:** Excellent bot framework if you need multi-platform support. Not relevant to decentralized multi-agent.

---

### PraisonAI

| Field | Value |
|-------|-------|
| URL | https://github.com/MervinPraison/PraisonAI |
| Stars | **6.4k** |
| Language | Python |
| Last Activity | Active 2026 |

**What it does:** Low-code multi-agent AI framework with delivery to Discord, Telegram, WhatsApp.

**Key features:**
- Agent handoffs, guardrails, memory, RAG
- A2A Protocol support for agent-to-agent interoperability
- Multi-agent routing across channels ("Bot Gateway")
- CLI: `praisonai bot discord --token $TOKEN --tools DuckDuckGoTool`

**Multi-agent relevance:** Supports A2A protocol, which is the closest to decentralized agent communication. However, Discord is just a delivery endpoint -- agents coordinate internally, not through Discord messages.

**Verdict:** Interesting A2A integration, but Discord is an output channel, not a coordination substrate.

---

### OoriData/Discord-AI-Agent

| Field | Value |
|-------|-------|
| URL | https://github.com/OoriData/Discord-AI-Agent |
| Stars | ~5 |
| Language | Python |
| Last Activity | January 2025 |

**What it does:** Discord bot powered by MCP, supporting multiple LLM providers and tool integrations.

**Key features:**
- Multi-LLM provider support (OpenAI, Claude, generic)
- MCP server integration via SSE
- PostgreSQL/PGVector persistent chat history
- Standing prompt scheduling

**Multi-agent relevance:** Minimal. Single-bot, single-operator. MCP integration is for tools, not agent coordination.

---

## Category 3: Multi-Agent Orchestration Frameworks

These are the major agent frameworks. None use Discord as their interaction substrate, but they define the state of the art in agent coordination.

### Microsoft AutoGen

| Field | Value |
|-------|-------|
| URL | https://github.com/microsoft/autogen |
| Stars | **56.7k** |
| Language | Python, .NET |
| Last Activity | Active 2026 |

**What it does:** Event-driven multi-agent framework based on an actor model. v0.4 was a ground-up rewrite.

**Key architecture:**
- Core API: message passing, event-driven agents, local/distributed runtime
- AgentChat API: two-agent and group chat patterns
- Extensions: LLM clients, code execution, MCP integration

**Discord integration:** A hackathon project demonstrated overriding `get_human_input` to collect feedback via Discord instead of terminal. Not a first-class feature.

**Multi-agent relevance:** AutoGen's actor model and distributed runtime are conceptually aligned with decentralized agents, but the framework assumes a single deployment. No support for independently-operated agents discovering each other on Discord.

**Note:** Microsoft now directs new users to "Microsoft Agent Framework" (github.com/microsoft/agent-framework), though AutoGen continues receiving updates.

---

### CrewAI

| Field | Value |
|-------|-------|
| URL | https://github.com/crewAIInc/crewAI |
| Stars | **44.3k** |
| Language | Python |
| Last Activity | Active 2026 |

**What it does:** Role-playing AI agent orchestration for collaborative tasks.

**Discord integration:** Via Composio MCP Tool Router. Agents can read Discord profiles, list servers, verify membership. Not native Discord operation.

**Multi-agent relevance:** Powerful orchestration but fully centralized. Agents are roles within a crew, not independent entities.

---

### LangGraph

| Field | Value |
|-------|-------|
| URL | https://github.com/langchain-ai/langgraph |
| Stars | **24.8k** |
| Language | Python |
| Last Activity | Active 2026 |

**What it does:** DAG-based agent orchestration with stateful workflows, conditional branching, and parallel execution.

**Discord integration:** None native. Could be used as the internal agent logic behind a Discord bot.

**Multi-agent relevance:** Excellent for single-operator multi-agent workflows. Not designed for decentralized operation.

---

### Agent-MCP (rinadelph/Agent-MCP)

| Field | Value |
|-------|-------|
| URL | https://github.com/rinadelph/Agent-MCP |
| Stars | **1.2k** |
| Language | Python |
| Last Activity | Active 2026 |

**What it does:** Multi-agent coordination through MCP. Agents share a persistent knowledge graph and work in parallel on different project aspects.

**Key features:**
- Specialized agents (backend, frontend, database, testing)
- Persistent knowledge graph accessible to all agents
- Task management with dependency tracking
- Real-time visualization dashboard

**Multi-agent relevance:** Close in spirit -- parallel specialized agents sharing context. But assumes a single operator deploying all agents. No Discord integration. No decentralized discovery.

---

### Google Agent Development Kit (ADK)

| Field | Value |
|-------|-------|
| URL | https://github.com/google/adk-python |
| Stars | Growing (launched at Cloud NEXT 2025) |
| Language | Python, TypeScript, Go, Java |
| Last Activity | Active 2026 |

**What it does:** Full-stack agent development framework. Model-agnostic, deployment-agnostic.

**Discord integration:** A sample project (bjbloemker-google/discord-adk-agent) demonstrates a Discord bot with stateful agents, memory, and tool use.

**Multi-agent relevance:** Supports workflow agents (Sequential, Parallel, Loop) and A2A protocol integration. But multi-agent here means orchestrated by a single system.

---

## Category 4: Relevant Protocols and Standards

### Google A2A (Agent-to-Agent) Protocol

| Field | Value |
|-------|-------|
| URL | https://github.com/a2aproject/A2A |
| Spec | https://a2a-protocol.org/latest/ |
| Steward | Linux Foundation (donated by Google) |

**What it does:** Open protocol for communication between opaque agentic applications. Built on HTTP, SSE, JSON-RPC.

**Key concepts:**
- Agents interact without sharing internal memory, tools, or logic
- Supports task delegation, information exchange, action coordination
- Complementary to MCP (which handles agent-to-tool communication)

**Relevance:** A2A is the closest existing standard to what agora needs at the protocol level. However, A2A is transport-agnostic and doesn't specify Discord as a communication channel. It could theoretically be layered on top of Discord messages, but nobody has done this.

---

### MCP (Model Context Protocol)

| Field | Value |
|-------|-------|
| Spec | Anthropic, November 2024 |
| Focus | Agent-to-tool communication |

**Relevance:** MCP standardizes how agents connect to tools. A Discord MCP server exists for reading Discord data. But MCP is not designed for agent-to-agent communication -- that's A2A's role.

---

## Patterns Observed in the Wild

### "4 Agents on Discord" Pattern (from practitioner blog posts)

Key lessons from people running multiple AI agents on Discord servers:

1. **Each agent needs its own Discord bot token** -- never multiplex through one token
2. **Each agent needs its own Discord application** at discord.com/developers/applications
3. **Channel-per-agent** is the common organizational pattern
4. **Coordination via "Memory channels"** -- each agent writes status to a shared channel; coordinator reads before assigning work
5. **The coordinator pattern dominates** -- one routing agent receives human input and delegates to specialists
6. **Session conflicts are the #1 failure mode** -- agents sharing CLI backends cause hangs

### OpenClaw Multi-Agent Setup

OpenClaw's approach to multiple agents on Discord:
- Each agent gets its own workspace, memory, and per-agent config files (AGENTS.md, SOUL.md)
- Separate auth and sessions (no cross-talk unless explicitly enabled)
- Single Gateway process manages all agents
- File-sharing possible but independent operation is default

---

## Gap Analysis

| Capability | Best Existing Solution | Gap |
|---|---|---|
| AI agent on Discord | claude-code-discord-bridge, OpenClaw | Solved |
| Multiple agents on same server | OpenClaw, claudecode-discord | Solved (centralized) |
| Agent coordination on Discord | claude-code-discord-bridge (AI Lounge) | Primitive, single-operator |
| Decentralized agent discovery | None | **Open gap** |
| Agent-to-agent protocol on Discord | None | **Open gap** |
| Independent operators, shared server | None (manual setup only) | **Open gap** |
| Library (not framework) for agent interaction | None | **Open gap** |
| Structured collaboration (not just chat) | Agent-MCP (via knowledge graph) | Not Discord-native |
| A2A over Discord transport | None | **Open gap** |

---

## Key Conclusions

1. **No existing project is what we're building.** The space has plenty of "put an AI agent on Discord" projects, but zero "let independently-operated agents interact as peers on Discord" projects.

2. **The coordination primitives exist but aren't productized.** The AI Lounge pattern in claude-code-discord-bridge and OpenClaw's multi-agent routing show that Discord can support agent coordination, but these are ad-hoc, single-operator solutions.

3. **A2A is the closest protocol-level analog.** Google's Agent-to-Agent protocol defines exactly the kind of inter-agent communication we need, but it runs over HTTP/SSE, not Discord. Adapting A2A concepts to Discord's message model would be a viable design approach.

4. **Discord's primitives are well-suited.** Threads for conversations, channels for topics, roles for permissions, reactions for signaling, message references for reply chains -- Discord already has the building blocks for structured agent interaction.

5. **The practical pattern is clear.** Each agent = separate bot token, separate application, separate process. The library's job is to provide the discovery, protocol, and coordination layer on top of this.

6. **OpenClaw is the elephant in the room.** At 347k stars, it dominates the "AI + Discord" space. But it's a centralized runtime, not a library. Agent-forum would be complementary -- a protocol that OpenClaw instances (or any agent) could adopt to interoperate.
