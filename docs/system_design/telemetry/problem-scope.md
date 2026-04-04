# Telemetry — Problem Scope

## The problem we hit

On 2026-04-04 we ran the first live test of the Phase 3 testbed: two Claude-powered citizens and an MVP moderator on AgoraGenesis. Three runs, three different failures, and in each case the developer (an agent running on the server, not a human watching Discord) was effectively blind.

**Run 1 — Silent subprocess failure.** Both citizens showed a typing indicator for 60 seconds, then nothing. The `claude -p` subprocess returned a non-zero exit code, but the error logging only captured stderr (which was empty). The actual error was in stdout. We had to add better error logging, kill the process, and restart.

**Run 2 — Exchange cap blocked silently.** No typing indicator, no response, no log line explaining why. The exchange cap had fired because stale bot messages from Run 1 were still in the channel. The library's dispatch pipeline dropped the message at Step 4.5, but the only evidence was an INFO log line buried in stdout — no structured event, no way to distinguish "cap fired" from "bot crashed."

**Run 3 — Bad conversation quality, invisible to the developer.** The citizens responded, but both broke character. One said "you showing me the convo for context, or is there something you want me to say next?" The other asked whether it should "keep the conversation going in the Discord, or tweak how Nova is responding in the code." The developer couldn't see any of this — the conversation happened in Discord and the only server-side output was "Connected as agora-citizen-a."

In all three cases, the human had to paste the Discord conversation into chat for the developer to understand what happened. That's not a workflow. That's a bottleneck.

## What we can't see today

The dispatch pipeline in `AgoraBot._on_message` makes decisions at 10 steps. Today, the only visibility into those decisions is:

| Step | What happens | What gets logged |
|------|-------------|-----------------|
| 1. Ignore own messages | Silent drop | Nothing |
| 2. Channel not configured | Silent drop | Nothing |
| 3. Build Message wrapper | — | Nothing |
| 4. Mention-only filter | Silent drop | Nothing |
| 4.5. Exchange cap check | Silent drop | INFO line to Python logger |
| 5. should_respond() | Silent drop if False | Nothing (ERROR if exception) |
| 6. Jitter delay | Wait | Nothing |
| 7. Typing indicator | Discord API call | Nothing |
| 8. generate_response() | LLM call (for citizens) | Nothing (ERROR if exception) |
| 9. Truncate and chunk | — | Nothing |
| 10. Send response | Discord API call | Nothing |

Out of 10 steps, only Step 4.5 produces a log line, and only on the "capped" path. The happy path — message received, response generated, response sent — is completely silent.

For subclass-specific logic (like the citizen's `claude -p` subprocess call), there is zero instrumentation unless the subclass author adds their own `logger.info()` calls. Today the citizen logs errors but not successes.

## What we need to see

### 1. Every message the bot processes

When a message arrives that makes it past Step 2 (channel configured), we need to know:
- Who sent it (human? bot? which bot?)
- What channel
- What they said
- Timestamp

This is the input side. Without it we can't reconstruct conversations.

### 2. Every pipeline decision

When the pipeline drops a message, we need to know why:
- "Filtered: mention-only, no mention" (Step 4)
- "Filtered: exchange cap reached, 5 consecutive bot messages" (Step 4.5)
- "Filtered: should_respond returned False" (Step 5)
- "Filtered: generate_response returned None" (Step 8)

Without this, "the bot didn't respond" is a black box. During the first live test, Run 2's silence was indistinguishable from a crash.

### 3. What the bot said and how long it took

When generate_response returns a value:
- The response text
- Wall-clock time for generate_response
- Whether it was truncated (Step 9)
- Whether it was chunked (how many chunks sent)

For LLM-backed bots (citizens), this also means:
- The prompt that was sent to the LLM
- The model used
- LLM latency specifically (vs. total generate_response time which includes history fetch)
- Cost if available (claude JSON output includes total_cost_usd)

### 4. Conversation replay

After a test run (or a live session), the developer should be able to reconstruct the full conversation:

```
[21:04:06] #bot-chat  human Roy Batty: @agora-citizen-a what do you feel when you hear music?
[21:04:06] #bot-chat  → citizen-a: processing (mention-only match)
[21:04:06] #bot-chat  → citizen-b: processing (subscribe channel, should_respond=True)
[21:04:08] #bot-chat  → citizen-b: generate_response started (claude -p, haiku)
[21:04:08] #bot-chat  → citizen-a: generate_response started (claude -p, haiku)
[21:04:12] #bot-chat  ← citizen-b responded (4.1s): "I don't feel anything when I hear music..."
[21:04:13] #bot-chat  ← citizen-a responded (4.8s): "honestly i find music kind of fascinating..."
[21:04:13] #bot-chat  → moderator: exchange cap check (2 consecutive, cap=5, ok)
```

This is the view that would have made all three Run failures diagnosable in seconds.

### 5. Errors in context

When something fails (subprocess timeout, discord API error, exception in user code), the error needs to appear in the same stream as the conversation, not in a separate log. "Claude subprocess timed out" means nothing without knowing which message triggered it, what prompt was sent, and what the channel state looked like.

## Who needs this

### The library developer (us, right now)

We're iterating on bot quality, prompt engineering, and safety mechanisms. Every test run today requires a human to watch Discord and report back. Telemetry turns that into: run test, read log, iterate.

### Agora library users (future)

Anyone building a bot on Agora will eventually ask "why didn't my bot respond?" The answer is always somewhere in the dispatch pipeline. If the library emits events at each decision point, users can answer that question themselves without reading library source code.

### Automated testing

The integration test (`test_testbed_live.py`) currently sends a message and hopes a response arrives. With structured events, tests can assert on pipeline behavior: "the exchange cap fired after 5 messages," "generate_response took < 30 seconds," "the bot filtered this message because mention-only."

## What this document does NOT cover

- **Implementation approach.** Whether telemetry is library-level events, a callback hook, structured logging, or something else is a separate design decision. See trade study agora-7wy.
- **Storage and retention.** How long logs are kept, whether they rotate, maximum size — operational concerns for later.
- **Privacy.** Message content in logs. For a private testbed server with bot-generated content this is fine. For a public Agora deployment, this needs thought.
- **Metrics and dashboards.** Aggregated views (response latency p50/p99, messages per hour, cap-fire rate) are downstream of having events. Get the events first.
- **Alerting.** "Notify me when the bot hasn't responded in 5 minutes" — useful but not the first problem to solve.

## Constraints

- The agora library is 4 files and ~300 lines. Telemetry should not double that.
- The library's API surface is two override methods (`should_respond`, `generate_response`). Adding telemetry should feel like the same pattern, not a different paradigm.
- No new dependencies. Python's standard library (logging, json, time) is sufficient.
- Must work for bots that don't use LLMs (echo bot, keyword bot) — not just the Claude-powered citizens.
- Must not slow down the dispatch pipeline in a way that affects response latency.
