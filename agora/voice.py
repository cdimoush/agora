"""Audio transcription for Agora agents.

Transcribes audio files using the Vox CLI (github.com/cdimoush/vox),
which wraps the OpenAI Whisper API with automatic chunking for long files.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("agora.voice")

AUDIO_EXTENSIONS = frozenset({".ogg", ".oga", ".wav", ".mp3", ".m4a", ".webm", ".opus"})


class TranscriptionError(Exception):
    """Raised when audio transcription fails."""


def is_audio_file(filename: str) -> bool:
    """Check if a filename has a recognized audio extension."""
    return Path(filename).suffix.lower() in AUDIO_EXTENSIONS


async def transcribe(audio_path: str | Path, api_key: str | None = None) -> str:
    """Transcribe an audio file using the Vox CLI.

    Args:
        audio_path: Path to the audio file (.ogg, .wav, .mp3, etc.)
        api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
                 Passed to vox via environment.

    Returns:
        Transcribed text.

    Raises:
        TranscriptionError: On missing vox binary, API errors, or empty results.
    """
    if shutil.which("vox") is None:
        raise TranscriptionError(
            "vox CLI not installed — see https://github.com/cdimoush/vox"
        )

    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    env = os.environ.copy()
    if api_key:
        env["OPENAI_API_KEY"] = api_key

    if not env.get("OPENAI_API_KEY"):
        raise TranscriptionError(
            "No OpenAI API key — set OPENAI_API_KEY or pass api_key"
        )

    proc = await asyncio.create_subprocess_exec(
        "vox", "file", str(audio_path), "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TranscriptionError("Vox transcription timed out")

    if proc.returncode == 3:
        raise TranscriptionError(
            "No OpenAI API key — set OPENAI_API_KEY or pass api_key"
        )
    if proc.returncode == 2:
        raise TranscriptionError(
            f"Vox API error: {stderr.decode().strip()}"
        )
    if proc.returncode != 0:
        raise TranscriptionError(
            f"Vox failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )

    raw = stdout.decode().strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Non-JSON output — treat raw stdout as the transcript text
        text = raw
    else:
        if data.get("error"):
            raise TranscriptionError(f"Vox error: {data['error']}")
        text = data.get("text", "").strip()

    if not text:
        raise TranscriptionError("Transcription returned empty text")

    logger.info("Transcribed %s (%d chars)", audio_path.name, len(text))
    return text
