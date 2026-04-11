"""Agora gateway — the core dispatch pipeline for Agora agents."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Self

import discord

from agora.chunker import chunk_message
from agora.config import Config
from agora.errors import ErrorContext
from agora.events import Event, EventCollector, EventProcessor
from agora.message import Message
from agora.safety import ExchangeCapChecker
from agora.scheduler import SchedulerTask, parse_interval
from agora.telemetry import LogProcessor, Span, _NullSpan, _null_span, _trace_ctx

logger = logging.getLogger("agora")


class Agora:
    """Base class for Agora agents.

    Subclass and override on_message() (preferred) or the legacy
    should_respond() + generate_response() pair.
    """

    def __init__(self, config: Config):
        self.config = config

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = config.mention_resolution
        self._client = discord.Client(intents=intents)

        self._exchange_cap = ExchangeCapChecker(config.exchange_cap)
        self._channel_map: dict[str, str] = {}
        self._channel_ids: dict[str, int] = {}
        self._member_map: dict[str, int] = {}
        self._mention_pattern = None  # compiled regex, built in _resolve_members
        self._processors: list = []
        data_dir = Path(config.data_dir) if config.data_dir else None
        self._collector = EventCollector(
            config.name or config.token_env, data_dir
        )
        self._ready_event = asyncio.Event()
        self._run_task = None
        self._scheduler_task = None
        self._last_dm_channel: discord.DMChannel | None = None

        # Detect which API the subclass uses
        self._use_legacy_api = (
            type(self).on_message is Agora.on_message
        )

        if config.telemetry:
            self._setup_telemetry()

        # discord.py matches events by function __name__
        @self._client.event
        async def on_ready():
            await self._on_ready()

        @self._client.event
        async def on_message(message):
            await self._on_message(message)

    # ── Public: operators override these ──────────────────────

    async def should_respond(self, message: Message) -> bool:
        """Return True to trigger response generation.

        Respects config.respond_mode:
        - "mention-only": respond only when @mentioned (default)
        - "all": respond to every message
        """
        if self.config.respond_mode == "all":
            return True
        return message.is_mention

    async def generate_response(self, message: Message) -> str | None:
        """Return response text or None. Called only when should_respond() is True."""
        return None

    async def on_message(self, message: Message) -> str | None:
        """Handle an incoming message. Return response text or None.

        Override this in subclasses (preferred over should_respond + generate_response).
        Default: return None (no response).
        """
        return None

    async def on_error(self, error: Exception, context: ErrorContext) -> str | None:
        """Called when on_message (or on_schedule) raises an exception.

        Return a string to send as reply, or None for silent handling.
        Default: logs the error and returns None.
        """
        logger.error(f"on_error [{context.stage}]: {error}")
        return None

    async def on_schedule(self) -> dict[str, str] | None:
        """Called on each schedule tick. Return {channel: message} or None.

        Override this for Tier 2 (scheduled) agents. Posts go through send()
        with cap enforcement. Default: return None (no posts).
        """
        return None

    # ── Public: send/reply ────────────────────────────────────

    async def get_history(self, channel: str, limit: int = 20) -> list[Message]:
        """Fetch recent messages from a channel.

        Returns list of Message objects, most recent first.
        Raises ValueError if channel not in config, RuntimeError if not connected.
        """
        self._ensure_connected()
        if channel not in self.config.channels:
            available = ", ".join(sorted(self.config.channels.keys()))
            raise ValueError(
                f"Channel '{channel}' not in config. Available: {available}"
            )
        discord_channel = self._get_discord_channel(channel)
        messages = []
        async for msg in discord_channel.history(limit=limit):
            messages.append(Message(msg, self._client.user.id))
        return messages

    def get_channels(self) -> dict[str, str]:
        """Return a copy of configured channels {name: mode}."""
        self._ensure_connected()
        return dict(self.config.channels)

    def _ensure_connected(self) -> None:
        """Raise RuntimeError if the bot is not connected."""
        if self._client.user is None:
            raise RuntimeError("Not connected — call start() or run() first")

    async def send(self, channel: str, content: str) -> None:
        """Send a message to a named channel. Enforces exchange cap.

        For DMs, sends to the last DM interlocutor (cached on receipt).
        Raises ValueError if channel is not in config.
        Logs warning and skips cap check for write-only channels.
        """
        self._ensure_connected()

        # DM send path — use cached DM channel
        if channel == "dm":
            if self._last_dm_channel is None:
                logger.info("send('dm', ...) skipped — no DM received yet")
                return
            content = content[: self.config.max_response_length]
            for chunk in chunk_message(content):
                await self._last_dm_channel.send(chunk)
            return

        mode = self.config.channels.get(channel)
        if mode is None:
            available = ", ".join(sorted(self.config.channels.keys()))
            raise ValueError(
                f"Channel '{channel}' not in config. Available: {available}"
            )

        discord_channel = self._get_discord_channel(channel)

        if mode == "write-only":
            logger.warning(f"send() to write-only channel '{channel}' — skipping cap check")
        else:
            if await self._exchange_cap.is_capped(discord_channel):
                logger.info(f"send() to '{channel}' suppressed by exchange cap")
                return

        content = content[: self.config.max_response_length]
        chunks = chunk_message(content)
        for chunk in chunks:
            await discord_channel.send(chunk)

    async def reply(self, message: Message, content: str) -> None:
        """Reply to a message. Always threads. Enforces exchange cap."""
        self._ensure_connected()
        discord_channel = self._client.get_channel(message.channel_id)
        if discord_channel is None:
            raise ValueError(f"Cannot resolve channel ID {message.channel_id}")

        if await self._exchange_cap.is_capped(discord_channel):
            logger.info(f"reply() suppressed by exchange cap in #{message.channel_name}")
            return

        content = content[: self.config.max_response_length]
        chunks = chunk_message(content)
        for i, chunk in enumerate(chunks):
            if i == 0:
                await message._msg.reply(chunk, mention_author=False)
            else:
                await discord_channel.send(chunk)

    def _get_discord_channel(self, channel_name: str):
        """Resolve channel name to discord channel object."""
        channel_id = self._channel_ids.get(channel_name)
        if channel_id is None:
            raise ValueError(f"Channel '{channel_name}' not resolved — is the bot connected?")
        return self._client.get_channel(channel_id)

    # ── Public: telemetry ──────────────────────────────────────

    def add_processor(self, processor) -> None:
        """Register a telemetry processor."""
        self._processors.append(processor)

    @contextmanager
    def span(self, name: str, **attrs):
        """Create a timed span for a pipeline step.

        Returns _NullSpan (no-op) when no processors are registered.
        """
        if not self._processors:
            yield _null_span
            return

        ctx = _trace_ctx.get()
        if ctx is None:
            yield _null_span
            return

        s = Span(
            trace_id=ctx["trace_id"],
            name=name,
            bot=ctx["bot"],
            channel=ctx["channel"],
            message_id=ctx["message_id"],
            author=ctx["author"],
            timestamp=time.time(),
        )
        for k, v in attrs.items():
            s[k] = v

        start = time.monotonic()
        try:
            yield s
        finally:
            s.duration_ms = (time.monotonic() - start) * 1000
            for proc in self._processors:
                try:
                    proc.on_span(s)
                except Exception:
                    pass  # never crash the pipeline for telemetry

    def _start_trace(self, channel_name: str, discord_message) -> str:
        trace_id = uuid.uuid4().hex[:8]
        _trace_ctx.set({
            "trace_id": trace_id,
            "bot": self.config.name or self.config.token_env,
            "channel": channel_name,
            "message_id": discord_message.id,
            "author": discord_message.author.display_name,
        })
        self._collector._trace_id = trace_id
        return trace_id

    def _end_trace(self) -> None:
        _trace_ctx.set(None)
        self._collector._trace_id = None

    # ── Public: events ─────────────────────────────────────────

    def emit(self, event_type: str, **payload) -> Event:
        """Emit a telemetry event."""
        return self._collector.emit(event_type, **payload)

    def add_event_processor(self, processor: EventProcessor) -> None:
        """Register an event processor for real-time event consumption."""
        self._collector.add_processor(processor)

    # ── Public: lifecycle ─────────────────────────────────────

    @classmethod
    def from_config(cls, path: str) -> Self:
        """Create an instance (or subclass instance) from a YAML config file."""
        config = Config.from_yaml(path)
        return cls(config)

    async def start(self) -> None:
        """Start the bot (non-blocking). Returns after on_ready fires.

        Must be called from within an existing event loop.
        """
        logger.info("Starting Agora bot...")
        self._ready_event.clear()
        self._run_task = asyncio.create_task(
            self._client.start(self.config.token)
        )
        await self._ready_event.wait()

        # Start scheduler if configured
        if self.config.schedule:
            interval = parse_interval(self.config.schedule)
            sched = SchedulerTask(interval, self._on_schedule_tick)
            sched.start()
            self._scheduler_task = sched

    async def stop(self) -> None:
        """Stop the bot and clean up."""
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            self._scheduler_task = None
        await self._client.close()
        if self._run_task is not None:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            self._run_task = None

    async def wait_until_ready(self) -> None:
        """Block until the bot is connected and ready."""
        await self._ready_event.wait()

    def watch_config(self, path: str | Path, interval: float = 2.0) -> None:
        """Start watching a config file for changes. On change, exit for restart.

        Relies on Docker restart policy (or supervisor) to bring the agent
        back up with the new config.
        """
        path = Path(path)
        if not path.exists():
            logger.warning("watch_config: %s does not exist, skipping", path)
            return
        self._config_watch_task = asyncio.create_task(
            self._poll_config(path, interval)
        )

    async def _poll_config(self, path: Path, interval: float) -> None:
        """Poll config file mtime; exit on change."""
        last_mtime = os.path.getmtime(path)
        logger.info("Watching %s for changes (mtime=%s)", path, last_mtime)
        while True:
            await asyncio.sleep(interval)
            try:
                current_mtime = os.path.getmtime(path)
            except OSError:
                continue
            if current_mtime != last_mtime:
                logger.info(
                    "Config %s changed (mtime %s -> %s), restarting...",
                    path, last_mtime, current_mtime,
                )
                # Validate before committing to restart
                try:
                    Config.from_yaml(path)
                except Exception as e:
                    logger.error("New config is invalid, ignoring change: %s", e)
                    last_mtime = current_mtime
                    continue
                await self.stop()
                sys.exit(0)

    def run(self) -> None:
        """Start the bot. Blocks until stopped (convenience wrapper)."""
        logger.info("Starting Agora bot...")
        self._client.run(self.config.token)

    async def _on_schedule_tick(self) -> None:
        """Called by the scheduler. Dispatches on_schedule results via send()."""
        self._collector.start_session()
        try:
            try:
                result = await self.on_schedule()
            except Exception as e:
                ctx = ErrorContext(stage="on_schedule")
                try:
                    await self.on_error(e, ctx)
                except Exception:
                    logger.error("on_error itself raised during on_schedule — swallowing")
                return

            if not result:
                return

            for channel_name, content in result.items():
                if not content:
                    continue
                try:
                    await self.send(channel_name, content)
                except Exception as e:
                    logger.error(f"on_schedule send to '{channel_name}' failed: {e}")
        finally:
            self._collector.end_session()

    # ── Internal: discord.py event handlers ───────────────────

    async def _on_ready(self) -> None:
        logger.info(
            f"Connected as {self._client.user} (ID: {self._client.user.id})"
        )
        self._resolve_channels()
        if self.config.display_name:
            await self._set_display_name()
        if self.config.mention_resolution:
            self._resolve_members()
        self._ready_event.set()

    async def _on_message(self, discord_message: discord.Message) -> None:
        """Main dispatch pipeline."""
        # Step 1: Ignore own messages (pre-trace)
        if discord_message.author.id == self._client.user.id:
            return

        # Step 2: Check channel config (pre-trace)
        if isinstance(discord_message.channel, discord.DMChannel):
            channel_name = "dm"
            self._last_dm_channel = discord_message.channel
        else:
            channel_name = discord_message.channel.name
        mode = self._get_channel_mode(channel_name)
        if mode is None or mode == "write-only":
            return

        # ── Trace + session start ──
        self._start_trace(channel_name, discord_message)
        self._collector.start_session()
        outcome = "filtered"
        filter_step = None
        filter_reason = None
        response_preview = None

        try:
            # Step 3: Build Message wrapper
            message = Message(discord_message, self._client.user.id)
            with self.span("message_received", content=message.content) as s:
                s["is_bot"] = message.is_bot
                s["is_mention"] = message.is_mention

            # Step 4: Enforce mention-only mode
            with self.span("mention_filter", mode=mode) as s:
                if mode == "mention-only" and not message.is_mention:
                    s["decision"] = "filtered"
                    s["reason"] = "mention-only mode, no mention"
                    filter_step, filter_reason = "mention_filter", s["reason"]
                    return
                s["decision"] = "pass"

            # Step 4.5: Exchange cap check (skipped for DMs)
            if channel_name != "dm":
                with self.span("exchange_cap") as s:
                    if await self._exchange_cap.is_capped(discord_message.channel):
                        s["decision"] = "filtered"
                        s["reason"] = f"exchange cap reached (cap={self.config.exchange_cap})"
                        filter_step, filter_reason = "exchange_cap", s["reason"]
                        return
                    s["decision"] = "pass"

            if self._use_legacy_api:
                # Legacy path: should_respond + generate_response
                # Step 5: Operator's should_respond
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
                        logger.error(f"should_respond raised: {e}")
                        return

                # Step 6: Jitter delay
                jitter = random.uniform(*self.config.jitter_seconds)
                with self.span("jitter_delay", jitter_seconds=jitter):
                    await asyncio.sleep(jitter)

                # Step 7: Typing indicator
                _typing_ctx = None
                if self.config.typing_indicator:
                    _typing_ctx = discord_message.channel.typing()
                    await _typing_ctx.__aenter__()

                # Step 8: Operator's generate_response
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
                        logger.error(f"generate_response raised: {e}")
                        return
                    finally:
                        if _typing_ctx is not None:
                            try:
                                await _typing_ctx.__aexit__(None, None, None)
                            except Exception:
                                pass
            else:
                # New path: on_message
                # Step 6: Jitter delay
                jitter = random.uniform(*self.config.jitter_seconds)
                with self.span("jitter_delay", jitter_seconds=jitter):
                    await asyncio.sleep(jitter)

                # Step 7: Typing indicator
                _typing_ctx = None
                if self.config.typing_indicator:
                    _typing_ctx = discord_message.channel.typing()
                    await _typing_ctx.__aenter__()

                # Step 8: Operator's on_message
                with self.span("on_message") as s:
                    try:
                        response = await self.on_message(message)
                        if response is None:
                            s["decision"] = "filtered"
                            s["reason"] = "on_message returned None"
                            filter_step, filter_reason = "on_message", s["reason"]
                            return
                        s["decision"] = "pass"
                        s["response_length"] = len(response)
                    except Exception as e:
                        s["decision"] = "error"
                        s["error"] = str(e)
                        filter_step, filter_reason = "on_message", f"exception: {e}"
                        logger.error(f"on_message raised: {e}")
                        # Route to on_error
                        ctx = ErrorContext(stage="on_message", message=message)
                        try:
                            fallback = await self.on_error(e, ctx)
                        except Exception:
                            logger.error("on_error itself raised — swallowing")
                            return
                        if fallback is not None:
                            response = fallback
                        else:
                            return
                    finally:
                        if _typing_ctx is not None:
                            try:
                                await _typing_ctx.__aexit__(None, None, None)
                            except Exception:
                                pass

            # Step 8.5: Resolve @name mentions to <@ID>
            with self.span("mention_resolution") as s:
                if self.config.mention_resolution and self._mention_pattern:
                    before = response
                    response = self._resolve_mentions(response)
                    resolved = response.count("<@") - before.count("<@")
                    s["resolved"] = resolved
                else:
                    s["resolved"] = 0

            # Step 9: Truncate and chunk
            with self.span("truncate_chunk") as s:
                original_length = len(response)
                response = response[: self.config.max_response_length]
                chunks = chunk_message(response)
                s["truncated"] = len(response) < original_length
                s["chunks"] = len(chunks)

            # Step 10: Send (reply-threaded for first chunk if enabled)
            with self.span("send_response", chunks=len(chunks)) as s:
                for i, chunk in enumerate(chunks):
                    if i == 0 and self.config.reply_threading:
                        await discord_message.reply(chunk, mention_author=False)
                    else:
                        await discord_message.channel.send(chunk)
                s["decision"] = "sent"

            outcome = "responded"
            response_preview = response[:100]

        finally:
            with self.span("pipeline_result") as s:
                s["outcome"] = outcome
                if outcome == "filtered":
                    s["filter_step"] = filter_step
                    s["filter_reason"] = filter_reason
                elif outcome == "responded":
                    s["response_preview"] = response_preview
            self._collector.end_session()
            self._end_trace()

    # ── Internal: helpers ─────────────────────────────────────

    def _resolve_channels(self) -> None:
        for guild in self._client.guilds:
            for channel in guild.text_channels:
                if channel.name in self.config.channels:
                    self._channel_map[channel.name] = self.config.channels[
                        channel.name
                    ]
                    self._channel_ids[channel.name] = channel.id

        for name in self.config.channels:
            if name == "dm":
                continue  # DMs are not guild channels
            if name not in self._channel_map:
                logger.warning(
                    f"Channel '{name}' in config but not found on server"
                )

    def _resolve_members(self) -> None:
        """Build name→ID map from guild members + config aliases."""
        for guild in self._client.guilds:
            for member in guild.members:
                self._member_map[member.display_name.lower()] = member.id
                self._member_map[member.name.lower()] = member.id
                if member.nick:
                    self._member_map[member.nick.lower()] = member.id

        # Apply persona aliases: alias → display_name → ID
        for alias, display_name in self.config.mention_aliases.items():
            target_id = self._member_map.get(display_name.lower())
            if target_id:
                self._member_map[alias.lower()] = target_id
            else:
                logger.warning(
                    f"Mention alias '{alias}' → '{display_name}' "
                    f"not found in guild members"
                )

        # Build regex pattern from known names (longest first to avoid partial matches)
        if self._member_map:
            names = sorted(self._member_map.keys(), key=len, reverse=True)
            escaped = [re.escape(n) for n in names]
            self._mention_pattern = re.compile(
                r"@(" + "|".join(escaped) + r")(?=[\s,!?.\"\']|$)",
                re.IGNORECASE,
            )

        logger.info(
            f"Mention resolution: {len(self._member_map)} names mapped"
        )

    def _resolve_mentions(self, text: str) -> str:
        """Replace @displayname with <@ID> in outgoing text."""
        if not self._mention_pattern:
            return text
        return self._mention_pattern.sub(
            lambda m: f"<@{self._member_map[m.group(1).lower()]}>",
            text,
        )

    async def _set_display_name(self) -> None:
        """Set the bot's server nickname from config.display_name."""
        for guild in self._client.guilds:
            try:
                await guild.me.edit(nick=self.config.display_name)
                logger.info(f"Display name set to '{self.config.display_name}'")
            except discord.Forbidden:
                logger.warning(
                    f"No permission to set nickname in {guild.name}"
                )

    def _get_channel_mode(self, channel_name: str) -> str | None:
        if channel_name == "dm":
            return self.config.channels.get("dm")
        if not self.config.channels:
            return "mention-only"
        return self._channel_map.get(channel_name)

    def _setup_telemetry(self) -> None:
        """Auto-register a file-writing LogProcessor when telemetry is enabled."""
        from pathlib import Path

        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        bot_name = self.config.name or self.config.token_env
        log_file = log_dir / f"{bot_name}.jsonl"

        tel_logger = logging.getLogger(f"agora.telemetry.{bot_name}")
        tel_logger.setLevel(logging.INFO)
        tel_logger.propagate = False  # don't duplicate to root logger

        handler = logging.FileHandler(log_file, mode="a")
        handler.setFormatter(logging.Formatter("%(message)s"))  # raw JSONL
        tel_logger.addHandler(handler)

        self.add_processor(LogProcessor(logger_name=f"agora.telemetry.{bot_name}"))
        logger.info("Telemetry enabled → %s", log_file)

