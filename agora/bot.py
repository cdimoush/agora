"""AgoraBot base class — the core dispatch pipeline for Agora agents."""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from contextlib import contextmanager
from typing import Self

import discord

from agora.chunker import chunk_message
from agora.config import Config
from agora.message import Message
from agora.safety import ExchangeCapChecker
from agora.telemetry import LogProcessor, Span, _NullSpan, _null_span, _trace_ctx

logger = logging.getLogger("agora")


class AgoraBot:
    """Base class for Agora agents.

    Subclass and override should_respond() and generate_response().
    """

    def __init__(self, config: Config):
        self.config = config

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = False
        self._client = discord.Client(intents=intents)

        self._exchange_cap = ExchangeCapChecker(config.exchange_cap)
        self._channel_map: dict[str, str] = {}
        self._channel_ids: dict[str, int] = {}
        self._processors: list = []

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
        return trace_id

    def _end_trace(self) -> None:
        _trace_ctx.set(None)

    # ── Public: lifecycle ─────────────────────────────────────

    @classmethod
    def from_config(cls, path: str) -> Self:
        """Create an instance (or subclass instance) from a YAML config file."""
        config = Config.from_yaml(path)
        return cls(config)

    def run(self) -> None:
        """Start the bot. Blocks until stopped."""
        logger.info("Starting Agora bot...")
        self._client.run(self.config.token)

    # ── Internal: discord.py event handlers ───────────────────

    async def _on_ready(self) -> None:
        logger.info(
            f"Connected as {self._client.user} (ID: {self._client.user.id})"
        )
        self._resolve_channels()
        self._check_intents()

    async def _on_message(self, discord_message: discord.Message) -> None:
        """Main dispatch pipeline."""
        # Step 1: Ignore own messages (pre-trace)
        if discord_message.author.id == self._client.user.id:
            return

        # Step 2: Check channel config (pre-trace)
        channel_name = discord_message.channel.name
        mode = self._get_channel_mode(channel_name)
        if mode is None or mode == "write-only":
            return

        # ── Trace starts ──
        self._start_trace(channel_name, discord_message)
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

            # Step 4.5: Exchange cap check
            with self.span("exchange_cap") as s:
                if await self._exchange_cap.is_capped(discord_message.channel):
                    s["decision"] = "filtered"
                    s["reason"] = f"exchange cap reached (cap={self.config.exchange_cap})"
                    filter_step, filter_reason = "exchange_cap", s["reason"]
                    return
                s["decision"] = "pass"

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
            with self.span("typing_indicator", enabled=self.config.typing_indicator) as s:
                if self.config.typing_indicator:
                    await discord_message.channel.typing().__aenter__()

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
                        await discord_message.reply(chunk)
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
            if name not in self._channel_map:
                logger.warning(
                    f"Channel '{name}' in config but not found on server"
                )

    def _get_channel_mode(self, channel_name: str) -> str | None:
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

    def _check_intents(self) -> None:
        self._intent_warned = False
