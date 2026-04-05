# Agora Telemetry — System Design

## Executive Summary

A lightweight, stdlib-only event system for the Agora library that instruments the `AgoraBot._on_message` dispatch pipeline. Each incoming message creates a trace; each pipeline step emits a span with its decision, reason, and timing. Processors consume spans for logging, conversation replay, and test assertions. Zero overhead when unused. ~80-100 lines of new code in a single file (`agora/telemetry.py`), with ~20 lines of instrumentation added to `bot.py`.

## Problem Statement

Agora's 10-step dispatch pipeline is a black box. Out of 10 steps, only Step 4.5 (exchange cap) produces a log line, and only on the failure path. The happy path is completely silent. When bots don't respond, developers can't distinguish "crashed" from "filtered" from "LLM returned empty." The first live test of the Phase 3 testbed failed three times, and each failure required a human to paste Discord screenshots for diagnosis.

**Who has this problem:**
- **Library developers (us, now):** iterating on bot quality and safety mechanisms with no server-side visibility
- **Library users (future):** anyone building an AgoraBot who asks "why didn't my bot respond?"
- **Automated tests:** need to assert on pipeline behavior, not just final output

## Value Proposition

No existing tool solves this. Commercial LLM observability platforms (Langfuse, LangSmith, Helicone) model "LLM calls with context" — Agora needs "dispatch decisions where LLM is one leaf." All require heavy dependencies. The dispatch pipeline is Agora-specific; the telemetry must be too.

What this design adds that nothing else provides:
1. **Pipeline decision visibility** — every step explains what it decided and why
2. **Conversation replay** — reconstruct full channel interactions from server-side events
3. **Testbed diagnostics** — live multi-bot view without watching Discord
4. **Subclass extensibility** — CitizenBot adds LLM-specific spans through the same mechanism
5. **Zero-dependency** — Python stdlib only, proportional to a 300-line library

See [landscape-synthesis.md](landscape-synthesis.md) for the full competitive analysis.

## User Stories

1. **As a library developer running the testbed**, I want to see a conversation replay of all bot interactions in a channel so I can diagnose prompt quality issues without watching Discord.

2. **As a library developer debugging a silent bot**, I want to see which pipeline step filtered a message and why, so I can distinguish "exchange cap fired" from "subprocess crashed" from "should_respond returned False."

3. **As a CitizenBot developer**, I want to emit LLM-specific telemetry (model, latency, cost, prompt) through the same system the library uses, so all observability is in one stream.

4. **As a test author**, I want to assert on pipeline behavior ("the exchange cap fired after 5 messages", "generate_response took < 30s") without parsing log output.

5. **As a future Agora user**, I want telemetry to be off by default with zero overhead, and trivially enable it by adding one processor.

## Architecture Overview

```
                    ┌─────────────────────────────────────────────┐
                    │              _on_message()                   │
                    │                                             │
                    │  ┌─ Step 1: Ignore own ──── (no trace)      │
                    │  ├─ Step 2: Channel check ─ (no trace)      │
                    │  │                                          │
                    │  │  ══ Trace starts here ═══════════════    │
                    │  │                                          │
                    │  ├─ Step 3: Build Message ── message_received│
                    │  ├─ Step 4: Mention filter ─ mention_filter │
                    │  ├─ Step 4.5: Exchange cap ─ exchange_cap   │
                    │  ├─ Step 5: should_respond ─ should_respond │
                    │  ├─ Step 6: Jitter delay ─── jitter_delay   │
                    │  ├─ Step 7: Typing ───────── typing_indicator│
                    │  ├─ Step 8: generate_response─generate_response│
                    │  ├─ Step 9: Truncate/chunk ─ truncate_chunk │
                    │  └─ Step 10: Send ──────────send_response   │
                    │                                             │
                    │  ══ pipeline_result (summary) ══════════    │
                    └──────────────┬──────────────────────────────┘
                                   │
                                   │ completed Span objects
                                   ▼
                    ┌──────────────────────────────────────┐
                    │         Processor List                │
                    │                                      │
                    │  ┌─ LogProcessor ──→ structured JSON  │
                    │  ├─ ReplayProcessor ──→ conversation  │
                    │  │                       view         │
                    │  └─ TestProcessor ──→ in-memory       │
                    │                       collection      │
                    └──────────────────────────────────────┘
```

**Data flow:**
1. `_on_message` is called by discord.py
2. Steps 1-2 are pre-trace (bot ignores these messages entirely — no telemetry noise)
3. At Step 3, a trace context is created and stored in a `ContextVar`
4. Steps 3-10 each execute inside `with self.span("step_name", **attrs)` context managers
5. When the span exits, it captures duration and is passed to all registered processors
6. On pipeline exit (normal completion or early return), a `pipeline_result` summary span is emitted
7. Trace context is cleared

**Key architectural pattern:** Message-as-Trace. Each `_on_message` invocation is one trace. Each pipeline step is one span within that trace. Spans carry denormalized context (bot name, channel, author, message ID) so they're self-contained — no joins needed for analysis.

**Zero-cost when unused:** `self.span()` checks `if not self._processors` and returns a `_NullSpan` — a no-op context manager that accepts attribute writes silently and calls no processors. No timing, no UUID generation, no contextvar manipulation.

## Component Breakdown

### Component 1: `agora/telemetry.py` (~80-100 lines)

**Purpose:** Core telemetry primitives — Span dataclass, processor protocol, context management, NullSpan, and built-in processors.

#### Span

```python
@dataclass
class Span:
    """A timed operation within a message dispatch trace."""
    trace_id: str
    name: str
    bot: str
    channel: str
    message_id: int
    author: str
    timestamp: float          # time.time() — wall clock
    duration_ms: float = 0.0  # filled on __exit__
    _attrs: dict = field(default_factory=dict, repr=False)
    
    def __setitem__(self, key, value):
        self._attrs[key] = value
    
    def __getitem__(self, key):
        return self._attrs[key]
    
    def to_dict(self) -> dict:
        """Flat dict for JSON serialization."""
        d = {
            "trace_id": self.trace_id,
            "span": self.name,
            "bot": self.bot,
            "channel": self.channel,
            "message_id": self.message_id,
            "author": self.author,
            "ts": self.timestamp,
            "duration_ms": round(self.duration_ms, 2),
        }
        d.update(self._attrs)
        return d
```

Key decisions:
- Fixed fields for common context (typed, documented) + `_attrs` dict for step-specific data (flexible, extensible)
- `to_dict()` produces a flat JSON-serializable dict — no nesting, easy to grep/filter
- `__setitem__` allows natural `span["decision"] = "filtered"` syntax inside `with` blocks

#### _NullSpan

```python
class _NullSpan:
    """No-op span returned when no processors are registered."""
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def __setitem__(self, k, v): pass
    def __getitem__(self, k): return None
```

4 lines. Makes telemetry truly zero-cost when off.

#### Trace context

```python
from contextvars import ContextVar

_trace_ctx: ContextVar[dict | None] = ContextVar("agora_trace", default=None)
```

Set at trace start (Step 3) with `{trace_id, bot, channel, message_id, author}`. Read by `self.span()` to auto-populate span fields. Cleared on pipeline exit. Works correctly with asyncio — each concurrent `_on_message` call gets its own context.

#### Processor protocol

```python
class TelemetryProcessor(Protocol):
    def on_span(self, span: Span) -> None: ...
```

Single method. No lifecycle hooks, no batching, no async. Processors that need async (e.g., writing to a remote service) should use their own queue internally. Keeping the protocol synchronous means the hot path doesn't await processor code.

#### Built-in processors

**LogProcessor** — Emits each span as a single-line JSON string to Python's `logging` module.

```python
class LogProcessor:
    def __init__(self, logger_name: str = "agora.telemetry"):
        self._logger = logging.getLogger(logger_name)
    
    def on_span(self, span: Span) -> None:
        self._logger.info(json.dumps(span.to_dict()))
```

Integrates with existing logging config (file handlers, rotation, etc.). Users who already have `logging.basicConfig()` get telemetry for free.

**ReplayProcessor** — Collects spans and formats a human-readable conversation replay.

```python
class ReplayProcessor:
    def __init__(self):
        self.spans: list[Span] = []
    
    def on_span(self, span: Span) -> None:
        self.spans.append(span)
    
    def replay(self, channel: str | None = None) -> str:
        """Format collected spans as a conversation replay."""
        # Filter by channel if specified
        # Sort by timestamp
        # Format as timeline view
        ...
```

Output format (matches the problem-scope doc's desired view):

```
[21:04:06] #bot-chat  human Roy Batty: @agora-citizen-a what do you feel when you hear music?
[21:04:06] #bot-chat  → citizen-a: processing (mention match)
[21:04:06] #bot-chat  → citizen-b: processing (subscribe channel, should_respond=True)
[21:04:08] #bot-chat  → citizen-b: generate_response started
[21:04:08] #bot-chat  → citizen-a: generate_response started
[21:04:12] #bot-chat  ← citizen-b responded (4.1s): "I don't feel anything when I hear music..."
[21:04:13] #bot-chat  ← citizen-a responded (4.8s): "honestly i find music kind of fascinating..."
[21:04:13] #bot-chat  → moderator: exchange cap check (2 consecutive, cap=5, ok)
```

**TestProcessor** — Collects spans in memory for test assertions.

```python
class TestProcessor:
    def __init__(self):
        self.spans: list[Span] = []
    
    def on_span(self, span: Span) -> None:
        self.spans.append(span)
    
    def find(self, name: str = None, **attrs) -> list[Span]:
        """Find spans matching criteria."""
        results = self.spans
        if name:
            results = [s for s in results if s.name == name]
        for k, v in attrs.items():
            results = [s for s in results if s._attrs.get(k) == v]
        return results
    
    def assert_span(self, name: str, **attrs) -> Span:
        """Assert exactly one span matches. Return it."""
        matches = self.find(name, **attrs)
        assert len(matches) == 1, f"Expected 1 '{name}' span, found {len(matches)}"
        return matches[0]
    
    def clear(self):
        self.spans.clear()
```

Enables test assertions like:

```python
proc = TestProcessor()
bot.add_processor(proc)

# ... trigger message ...

proc.assert_span("exchange_cap", decision="filtered")
proc.assert_span("pipeline_result", outcome="filtered", filter_step="exchange_cap")
```

### Component 2: Instrumentation in `bot.py` (~20 lines added)

**Purpose:** Wrap each pipeline step in `self.span()` context managers.

**Interfaces:** `self.span(name, **attrs)` → context manager returning Span or _NullSpan

**Key decisions:**
- Steps 1-2 are NOT instrumented (pre-trace, noise reduction)
- The trace starts at Step 3 (Build Message)
- Early returns emit `pipeline_result` with `outcome="filtered"` before returning
- `pipeline_result` is emitted in a `finally` block to capture errors too

**Concrete instrumented `_on_message`:**

```python
async def _on_message(self, discord_message):
    # Step 1: Ignore own messages (pre-trace)
    if discord_message.author.id == self._client.user.id:
        return

    # Step 2: Check channel config (pre-trace)
    channel_name = discord_message.channel.name
    mode = self._get_channel_mode(channel_name)
    if mode is None or mode == "write-only":
        return

    # ── Trace starts ──
    trace_id = self._start_trace(channel_name, discord_message)
    outcome = "filtered"
    filter_step = None
    filter_reason = None
    response_preview = None
    
    try:
        # Step 3: Build Message
        message = Message(discord_message, self._client.user.id)
        with self.span("message_received", content=message.content) as s:
            s["is_bot"] = message.is_bot
            s["is_mention"] = message.is_mention

        # Step 4: Mention-only filter
        with self.span("mention_filter", mode=mode) as s:
            if mode == "mention-only" and not message.is_mention:
                s["decision"] = "filtered"
                s["reason"] = "mention-only mode, no mention"
                filter_step, filter_reason = "mention_filter", s["reason"]
                return
            s["decision"] = "pass"

        # Step 4.5: Exchange cap
        with self.span("exchange_cap") as s:
            if await self._exchange_cap.is_capped(discord_message.channel):
                s["decision"] = "filtered"
                s["reason"] = f"exchange cap reached (cap={self.config.exchange_cap})"
                filter_step, filter_reason = "exchange_cap", s["reason"]
                return
            s["decision"] = "pass"

        # Step 5: should_respond
        with self.span("should_respond") as s:
            try:
                result = await self.should_respond(message)
                s["result"] = result
                if not result:
                    s["decision"] = "filtered"
                    s["reason"] = "should_respond returned False"
                    filter_step, filter_reason = "should_respond", s["reason"]
                    return
                s["decision"] = "pass"
            except Exception as e:
                s["decision"] = "error"
                s["error"] = str(e)
                filter_step, filter_reason = "should_respond", f"exception: {e}"
                return

        # Step 6: Jitter delay
        jitter = random.uniform(*self.config.jitter_seconds)
        with self.span("jitter_delay", jitter_seconds=jitter):
            await asyncio.sleep(jitter)

        # Step 7: Typing indicator
        with self.span("typing_indicator", enabled=self.config.typing_indicator) as s:
            if self.config.typing_indicator:
                await discord_message.channel.typing().__aenter__()

        # Step 8: generate_response
        with self.span("generate_response") as s:
            try:
                response = await self.generate_response(message)
                if response is None:
                    s["decision"] = "filtered"
                    s["reason"] = "generate_response returned None"
                    filter_step, filter_reason = "generate_response", s["reason"]
                    return
                s["decision"] = "pass"
                s["response_length"] = len(response)
            except Exception as e:
                s["decision"] = "error"
                s["error"] = str(e)
                filter_step, filter_reason = "generate_response", f"exception: {e}"
                return

        # Step 9: Truncate and chunk
        with self.span("truncate_chunk") as s:
            original_length = len(response)
            response = response[: self.config.max_response_length]
            chunks = chunk_message(response)
            s["truncated"] = len(response) < original_length
            s["chunks"] = len(chunks)

        # Step 10: Send
        with self.span("send_response", chunks=len(chunks)) as s:
            for i, chunk in enumerate(chunks):
                if i == 0 and self.config.reply_threading:
                    await discord_message.reply(chunk)
                else:
                    await discord_message.channel.send(chunk)
            s["decision"] = "sent"

        outcome = "responded"
        response_preview = response[:100]

    finally:
        # Pipeline summary
        with self.span("pipeline_result") as s:
            s["outcome"] = outcome
            if outcome == "filtered":
                s["filter_step"] = filter_step
                s["filter_reason"] = filter_reason
            elif outcome == "responded":
                s["response_preview"] = response_preview
        self._end_trace()
```

### Component 3: Subclass telemetry (convention, not code)

**Purpose:** Let subclasses like CitizenBot emit domain-specific spans.

**Interface:** Subclasses call `self.span()` inside their `generate_response()` or `should_respond()` overrides. The trace context is already set by the parent pipeline.

**Example — CitizenBot with LLM telemetry:**

```python
class CitizenBot(AgoraBot):
    async def generate_response(self, message):
        # ... build prompt ...
        
        with self.span("llm_call", model="haiku", prompt_length=len(prompt)) as s:
            result = await self._call_claude(prompt)
            if result:
                s["response_length"] = len(result)
                s["cost_usd"] = result.get("cost", 0)
            else:
                s["decision"] = "error"
        
        return result
```

The `llm_call` span appears nested within the `generate_response` span in the trace — same trace_id, timestamped within the generate_response window. Processors see it alongside all other pipeline spans.

This pattern works for any LLM, any API, or no LLM at all. An echo bot would have no subclass spans; a keyword bot might emit a `keyword_match` span. The telemetry system doesn't know or care about LLMs.

## Technology Choices

| Choice | What | Why |
|---|---|---|
| `dataclasses.dataclass` | Span schema | Typed fields, `asdict()` serialization, zero-dep |
| `contextvars.ContextVar` | Trace context propagation | Async-safe, task-local, stdlib since 3.7 |
| `time.time()` | Wall-clock timestamps | Human-readable, sortable across processes |
| `time.monotonic()` | Duration measurement | Not affected by clock adjustments |
| `uuid.uuid4().hex[:8]` | Trace IDs | Short, unique enough for local use |
| `json.dumps()` | Event serialization | Universal, grep-friendly as JSONL |
| `logging` module | LogProcessor sink | Integrates with existing handler/rotation config |
| `Protocol` (typing) | Processor interface | Duck-typed, no base class inheritance needed |

**What we're NOT using and why:**
- OpenTelemetry SDK — too heavy, too many packages
- structlog — external dependency, we only need 10% of it
- asyncio.Queue — processors are sync; async export is the processor's concern
- Separate event types per step — 1 Span type with attributes dict is proportional to a 300-line library

## Visibility Model and Limitations

### What one AgoraBot instance can see

Each bot runs its own `AgoraBot` instance with its own telemetry. It can see:

| Visible | Example |
|---|---|
| Inbound messages to this bot's configured channels | "Roy Batty said X in #bot-chat" |
| This bot's pipeline decisions | "I filtered because exchange cap" |
| This bot's response generation | "I called claude, took 4.1s, cost $0.003" |
| This bot's outbound messages | "I sent Y to #bot-chat" |
| Other users' messages (as inbound events) | "citizen-b said Z" (seen as an incoming message) |

### What one AgoraBot instance CANNOT see

| Invisible | Why |
|---|---|
| Other bots' pipeline decisions | Each bot is an independent process/server |
| Other bots' internal errors | No shared state |
| Other bots' LLM calls, costs, prompts | Private to each operator |
| Messages in channels this bot isn't configured for | By design (channel config) |
| Discord events this bot doesn't subscribe to (reactions, edits, deletes) | discord.py intent limits |

### Multi-bot visibility strategies

**Testbed (single process):** `testbed/run.py` runs 3 bots in one Python process. Register a shared `ReplayProcessor` on all 3 bots → get a unified conversation view with all pipeline decisions interleaved.

**Production (separate processes):** Each bot writes JSONL to its own log file. A post-hoc script merges files sorted by timestamp:

```bash
# Merge and sort by timestamp
cat citizen-a.jsonl citizen-b.jsonl moderator.jsonl | \
  python -c "import sys,json; lines=[json.loads(l) for l in sys.stdin]; lines.sort(key=lambda x:x['ts']); [print(json.dumps(l)) for l in lines]"
```

**Decentralized (different servers):** Each operator chooses what telemetry to export. No central collection by default — this is a feature, not a bug. Operators control their own data. A future protocol could define voluntary telemetry sharing, but that's out of scope.

## Concrete Example: Diagnosing the Three Test Failures

### Run 1 — Silent subprocess failure

With telemetry:
```json
{"span":"generate_response","bot":"citizen-a","decision":"error","error":"CalledProcessError exit=1","duration_ms":2340}
{"span":"pipeline_result","bot":"citizen-a","outcome":"filtered","filter_step":"generate_response","filter_reason":"exception: CalledProcessError exit=1"}
```

**Diagnosis in seconds:** `generate_response` errored with a subprocess failure. The span includes duration (not a timeout) and the error message. With the CitizenBot `llm_call` subclass span, we'd also see the prompt that was sent.

### Run 2 — Exchange cap blocked silently

With telemetry:
```json
{"span":"exchange_cap","bot":"citizen-a","decision":"filtered","reason":"exchange cap reached (cap=5)","consecutive_bot_msgs":5}
{"span":"pipeline_result","bot":"citizen-a","outcome":"filtered","filter_step":"exchange_cap","filter_reason":"exchange cap reached (cap=5)"}
```

**Diagnosis in seconds:** `pipeline_result.filter_step == "exchange_cap"`. Not a crash. The channel had stale bot messages from a previous run.

### Run 3 — Bad conversation quality

With telemetry:
```json
{"span":"message_received","bot":"citizen-a","author":"Roy Batty","content":"@agora-citizen-a what do you feel when you hear music?"}
{"span":"generate_response","bot":"citizen-a","duration_ms":4800,"response_length":142}
{"span":"pipeline_result","bot":"citizen-a","outcome":"responded","response_preview":"you showing me the convo for context, or is there something you want me to say next?"}
```

With CitizenBot's `llm_call` span:
```json
{"span":"llm_call","bot":"citizen-a","model":"haiku","prompt_length":456,"prompt_preview":"Channel: #bot-chat\nRecent messages:\n[bot] citizen-b: ..."}
```

**Diagnosis in seconds:** The response is visible in `pipeline_result.response_preview`. The prompt is visible in `llm_call.prompt_preview`. The developer can see the citizen broke character and immediately knows to fix the system prompt — no need to check Discord.

## Testbed Integration

### `testbed/run.py` changes

```python
from agora.telemetry import LogProcessor, ReplayProcessor

async def main():
    # ... existing bot creation ...
    
    # Add telemetry
    replay = ReplayProcessor()
    log_proc = LogProcessor()
    
    for bot in [mod, citizen_a, citizen_b]:
        bot.add_processor(log_proc)     # structured JSON to stderr
        bot.add_processor(replay)       # conversation replay collector
    
    # ... existing startup code ...
    
    # On shutdown, print conversation replay
    print(replay.replay(channel="bot-chat"))
```

### `tests/integration/test_testbed_live.py` changes

```python
from agora.telemetry import TestProcessor

async def test_exchange_cap_fires():
    proc = TestProcessor()
    bot.add_processor(proc)
    
    # ... send 6 bot messages ...
    
    # Assert the cap fired
    cap_spans = proc.find("exchange_cap", decision="filtered")
    assert len(cap_spans) >= 1
    
    # Assert the pipeline result shows filtering
    result = proc.find("pipeline_result", outcome="filtered", filter_step="exchange_cap")
    assert len(result) >= 1

async def test_response_latency():
    proc = TestProcessor()
    bot.add_processor(proc)
    
    # ... trigger conversation ...
    
    gen_spans = proc.find("generate_response", decision="pass")
    for span in gen_spans:
        assert span.duration_ms < 30_000, f"Response took {span.duration_ms}ms"
```

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Telemetry adds latency to dispatch pipeline | High (defeats purpose) | Low | NullSpan pattern; processors are sync and fast; async export is processor's concern |
| Span attributes dict becomes inconsistent across steps | Medium (confusing for consumers) | Medium | Document attribute names per step; ReplayProcessor validates expected attributes |
| Message content in logs is a privacy concern | High (for public deployments) | Low (private testbed now) | Content always included now; future `PrivacyFilterProcessor` can redact |
| Instrumented `_on_message` becomes hard to read | Medium (maintenance burden) | Low | Spans replace comments; net readability neutral; span names document the pipeline |
| Subclasses forget to emit spans | Low (their choice) | High | Library spans cover the full pipeline; subclass spans are bonus, not required |
| contextvars leak across concurrent messages | High (corrupted traces) | Very low | asyncio creates new context per task; tested in testbed with 3 concurrent bots |

## Implementation Roadmap

### Step 1: Core telemetry module
- `agora/telemetry.py`: Span, _NullSpan, _trace_ctx, TelemetryProcessor protocol
- `LogProcessor`, `ReplayProcessor`, `TestProcessor`
- Add `add_processor()`, `span()`, `_start_trace()`, `_end_trace()` to AgoraBot

### Step 2: Instrument the pipeline
- Wrap Steps 3-10 of `_on_message` in `self.span()` calls
- Add `pipeline_result` summary span in `finally` block
- Verify zero overhead when no processors registered

### Step 3: Wire up testbed
- Add `LogProcessor` and `ReplayProcessor` to `testbed/run.py`
- Print conversation replay on shutdown
- Verify the three Run failures would now be diagnosable

### Step 4: Instrument CitizenBot
- Add `llm_call` span inside `_call_claude()` with model, prompt_length, cost
- Add `prompt_preview` attribute (first 200 chars) for debugging

### Step 5: Update tests
- Add `TestProcessor` to integration tests
- Add assertions on pipeline behavior (exchange cap, response latency, filtering)

Build order rationale: Core module first (no behavior change), then instrumentation (enriches existing pipeline), then consumers (testbed, tests). Each step is independently useful and testable.

## Open Questions

1. **ReplayProcessor output format** — The human-readable format shown above is a starting point. Should it also support machine-readable output (filtered JSONL) for tooling? Defer to implementation.

2. **Span attribute naming convention** — Should attributes follow OTel GenAI semantic conventions (`gen_ai.operation.name`) or use short names (`decision`, `reason`)? Short names for now; add OTel aliases if/when we bridge to OTel exporters.

3. **Trace ID format** — `uuid4().hex[:8]` is short and readable for testbed use. Production might want full UUIDs. Make it configurable? Defer — 8 chars is fine for now.

4. **Log level for LogProcessor** — Should all spans be INFO, or should errors be WARNING/ERROR? Start with all INFO; a future `LevelAwareLogProcessor` can map span decisions to log levels.

5. **Processor error handling** — If a processor's `on_span` raises, should it crash the pipeline? No — catch, log warning, continue. But this is an implementation detail.

## Appendix

- [Scope](scope.md)
- [Landscape Synthesis](landscape-synthesis.md)
- [Design Journal](design-journal.md)
- Research: [OSS](research/open-source-landscape.md) | [Commercial](research/commercial-products.md) | [Libraries](research/libraries-and-sdks.md) | [Community](research/community-patterns.md)
