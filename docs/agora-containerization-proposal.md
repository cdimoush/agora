# Agora Containerization & Distribution — Design Proposal

**Date:** April 6, 2026
**Author:** Stanley Hopcroft
**Status:** Phase 1 merged (PR #5, April 7 2026). Execution contexts, `agora run`, container lifecycle landed. Phases 2+ remain proposals.

---

## 1. Context

Agora is a Python library that connects AI agents to a shared Discord server. Today, each agent is a Python process that an operator runs on their own machine. The library handles connection, loop prevention, peer discovery, and message routing — Discord itself is the infrastructure.

The current repo structure looks like this:

```
agora/
├── agora/              # Library source (~1,400 lines, 11 modules)
├── examples/           # Minimal examples (echo, keyword)
├── testbed/            # 4 agents: echo, citizen-a, citizen-b, moderator
│   └── citizen-a/
│       ├── agent.yaml  # Agent config
│       ├── citizen.py  # Agent logic
│       └── CLAUDE.md   # Agent personality
└── docs/
```

This works for a single developer. It does not work for:

- **Collaboration**: Multiple people building different agents from the same library
- **Deployment**: Running several agents on the same server without them interfering
- **Development**: An agent that needs to work on a separate codebase (coding assistant use case)

This proposal addresses all three with a phased plan.

---

## 2. Goals

1. **Clone and go**: A new contributor clones the repo (or a fork), runs one command, and has a working agent connected to Discord
2. **Isolation**: Multiple agents on the same machine can't see each other's filesystems or environment variables
3. **Dev attachment**: An agent container can mount and work inside a separate project directory (the "dev container" pattern)
4. **Source divergence with sync**: Agents can carry their own modifications to the Agora library while still pulling upstream improvements

---

## 3. User Flows

### Flow A — "I want to run an existing agent"

```
git clone https://github.com/.../agora.git
cd agora
cp .env.example .env        # Add bot token + LLM API key
docker compose up citizen-a  # Agent is live on Discord
```

**Who**: Someone who wants to try Agora or deploy a known agent type.
**What matters**: Zero Python environment setup. One command to live agent.

### Flow B — "I want to build my own agent"

```
git clone https://github.com/.../agora.git
cd agora
cp -r templates/citizen templates/my-agent
# Edit my-agent/agent.yaml, my-agent/bot.py, my-agent/CLAUDE.md
docker compose up my-agent   # Test on Discord
```

The contributor works inside their fork. Their agent template lives alongside the library source. They can modify either.

**Who**: A developer building a new agent personality or behavior.
**What matters**: Library source is editable and right there. Hot-reload during development.

### Flow C — "I want my agent to code on a project"

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up my-agent
```

This mounts a host directory (e.g., `~/projects/my-app`) into the agent container at `/workspace`. The agent can read, write, and run code inside that project — but its own Agora runtime and config remain separate.

**Who**: Someone using an Agora agent as a coding assistant or project worker.
**What matters**: Clean separation between "agent brain" and "project workspace."

### Flow D — "I want to run 3 agents on one server"

```yaml
# docker-compose.yml
services:
  citizen-a:
    build: { context: ., dockerfile: Dockerfile, args: { AGENT: citizen-a } }
    env_file: ./agents/citizen-a/.env
  citizen-b:
    build: { context: ., dockerfile: Dockerfile, args: { AGENT: citizen-b } }
    env_file: ./agents/citizen-b/.env
  coder:
    build: { context: ., dockerfile: Dockerfile, args: { AGENT: coder } }
    env_file: ./agents/coder/.env
    volumes:
      - ~/projects/target-repo:/workspace
```

Each agent is fully isolated: separate filesystem, separate env vars, separate bot token. They communicate only through Discord.

**Who**: A server operator running a fleet.
**What matters**: No cross-contamination. Easy to add/remove agents. Logs per container.

---

## 4. Repo Structure (Target)

```
agora/
├── agora/                  # Library source (shared across all agents)
│   ├── bot.py
│   ├── gateway.py
│   ├── config.py
│   ├── safety.py
│   └── ...
├── templates/              # Agent templates (one per type)
│   ├── citizen/            # Conversational agent
│   │   ├── agent.yaml
│   │   ├── bot.py
│   │   └── CLAUDE.md
│   ├── coder/              # Coding assistant agent
│   │   ├── agent.yaml
│   │   ├── bot.py
│   │   └── CLAUDE.md
│   └── echo/               # Minimal test agent
│       ├── agent.yaml
│       └── bot.py
├── Dockerfile              # Single Dockerfile, AGENT build arg selects template
├── docker-compose.yml      # Default: one agent
├── docker-compose.dev.yml  # Override: adds workspace mount
├── .env.example
├── docs/
└── tests/
```

Key decisions:

- **One Dockerfile**, parameterized by `AGENT` build arg — not one Dockerfile per agent
- **Templates are directories**, not config files — each can contain arbitrary code
- **Library source is copied into every container** — agents can modify it locally

---

## 5. Git Strategy for Agent Divergence

The collaboration model needs to handle a specific tension: Agora library source should stay in sync, but agent templates will diverge intentionally.

**Approach: Fork + selective sync**

```
upstream/agora (main repo)
    │
    ├── fork: alice/agora     (Alice's agents live in templates/)
    ├── fork: bob/agora       (Bob's agents live in templates/)
    └── fork: ian/agora       (Ian's agents live in templates/)
```

- Each contributor forks the repo
- `agora/` (library source) syncs upstream regularly via `git pull upstream main`
- `templates/` (agent definitions) are per-fork and rarely merge upstream
- Contributors can open PRs to upstream for library improvements they've made

**Sync workflow:**

```bash
git remote add upstream https://github.com/.../agora.git
git fetch upstream
git merge upstream/main          # Library updates flow in
# Conflicts only happen if you edited agora/ source — resolve normally
```

**Future possibility**: Agents that self-modify `agora/` source and propose merges to each other via GitHub PRs. This is an interesting direction but not in scope for Phase 1-2. It requires inter-agent communication sophisticated enough for code review discussions.

---

## 6. Phased Plan

### Phase 1 — Dockerize (Week 1-2)

**Goal**: Any agent from the testbed runs in a container with one command.

Deliverables:

- [ ] `Dockerfile` — Python 3.11 slim, installs `agora` from local source, copies selected template, runs `bot.py`
- [ ] `docker-compose.yml` — services for each testbed agent (citizen-a, citizen-b, echo, moderator)
- [ ] `.env.example` with clear documentation of required variables
- [ ] `.dockerignore` to keep images small
- [ ] Migrate testbed agents into `templates/` directory structure
- [ ] Update README with Docker quickstart
- [ ] Verify: `docker compose up citizen-a` connects to Discord and responds

**Design questions to resolve:**

- Image size budget? (slim vs. alpine vs. full)
- Do we pin discord.py and anthropic SDK versions in the image or let agent templates declare their own?

### Phase 2 — Dev Container Attachment (Week 3-4)

**Goal**: An agent container can mount an external project and work inside it.

Deliverables:

- [ ] `docker-compose.dev.yml` override that adds `/workspace` volume mount
- [ ] "Coder" agent template that expects a workspace and can run shell commands within it
- [ ] Documentation for the dev attachment workflow
- [ ] Security boundary definition: what the agent can/cannot access outside `/workspace`
- [ ] Hot-reload support: agent code changes without full container rebuild

**Design questions to resolve:**

- Does the dev workspace need its own container (two-container model), or is a volume mount into the agent container sufficient for Phase 2?
- How does the agent invoke tools (shell, file read/write) in the workspace? Direct execution vs. tool-server sidecar?
- Resource limits (CPU, memory, network) per container?

### Phase 3 — Multi-Agent Fleet & Orchestration (Week 5-8)

**Goal**: Run N agents on one machine with centralized management.

Deliverables:

- [ ] Fleet `docker-compose.yml` generator or template for N agents
- [ ] Per-agent logging and health checks
- [ ] Agent discovery: containers can see which other agents are online (via Discord, not Docker networking)
- [ ] Queue system for shared workspace access (one agent at a time per project)
- [ ] CLI tooling: `agora up <agent>`, `agora status`, `agora logs <agent>`

**Design questions to resolve:**

- Orchestration: Docker Compose for small fleets, Kubernetes for larger? Or stay Compose-only?
- How do agents queue for workspace access? External lock file? Discord-based signaling?
- Monitoring: simple health endpoint per container, or centralized dashboard?

### Phase 4 — Self-Modifying Agents & Social Sync (Future)

**Goal**: Agents can modify their own copy of the Agora library and share improvements.

This phase is exploratory. Key ideas:

- Each agent's container includes a full git repo of Agora (not just installed package)
- Agents can modify library source to add capabilities they need
- A sync protocol lets agents propose changes to each other (via Discord or GitHub PRs)
- Merge coordination happens through agent-to-agent conversation

This requires significant advances in agent autonomy and inter-agent trust. It's the long-term vision, not near-term work.

---

## 7. What a Designer Should Focus On

This proposal is heavy on infrastructure and light on user-facing design. A designer's input would be most valuable on:

1. **The "clone and go" experience** — What does the first 5 minutes look like for someone who just cloned the repo? Where do they get stuck? What should the terminal output look like?

2. **Agent template authoring** — What files does someone create to define a new agent? Is YAML + Python + Markdown the right set, or is there a simpler starting point?

3. **Fleet visibility** — When running 3+ agents, how does the operator understand what's happening? Terminal dashboard? Discord status channel? Web UI?

4. **The dev attachment UX** — When an agent is working on your code in `/workspace`, how do you observe what it's doing? How do you interrupt it? How do you review its changes?

5. **The fork/sync workflow** — For non-git-experts, what does "sync upstream library but keep my agents" look like in practice? Is there a simpler mental model?

---

## 8. Open Questions

| Question | Context | Needs input from |
|----------|---------|-----------------|
| Single Dockerfile vs. per-template Dockerfiles? | One is simpler, many allows per-agent optimization | Engineering |
| Volume mount vs. two-container model for dev? | Volume is simpler, two-container is cleaner isolation | Engineering + Design |
| How should agents declare their tool capabilities? | Currently in CLAUDE.md, may need something more structured | Design |
| Agent personality format — YAML, Markdown, or something new? | CLAUDE.md works for Claude-powered agents, not general | Design |
| Should the repo include a "create new agent" CLI wizard? | `agora new my-agent --template=citizen` | Design + Engineering |
| Self-hosted model support — when and how? | Larger container with PyTorch, or sidecar? | Engineering (future) |

---

*This document is intended as a starting point for design discussion, not a final specification. Phase 1 is concrete enough to begin immediately. Phases 2-4 should be refined through design review.*
