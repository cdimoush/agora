"""Audio transcription for Agora agents.

Transcribes audio files using the OpenAI Whisper API. Modeled after
the voice module in cdimoush/relay and cdimoush/vox.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("agora.voice")

AUDIO_EXTENSIONS = frozenset({".ogg", ".oga", ".wav", ".mp3", ".m4a", ".webm", ".opus"})


class TranscriptionError(Exception):
    """Raised when audio transcription fails."""


def is_audio_file(filename: str) -> bool:
    """Check if a filename has a recognized audio extension."""
    return Path(filename).suffix.lower() in AUDIO_EXTENSIONS


async def transcribe(audio_path: str | Path, api_key: str | None = None) -> str:
    """Transcribe an audio file using OpenAI Whisper API.

    Args:
        audio_path: Path to the audio file (.ogg, .wav, .mp3, etc.)
        api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.

    Returns:
        Transcribed text.

    Raises:
        TranscriptionError: On missing API key, API errors, or empty results.
    """
    try:
        import openai
    except ImportError:
        raise TranscriptionError(
            "openai package not installed — run: pip install openai"
        )

    if api_key is None:
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError(
            "No OpenAI API key — set OPENAI_API_KEY or pass api_key"
        )

    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise TranscriptionError(f"Audio file not found: {audio_path}")

    client = openai.AsyncOpenAI(api_key=api_key)

    try:
        with open(audio_path, "rb") as f:
            response = await client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe",
                file=f,
            )
        text = response.text.strip()
        if not text:
            raise TranscriptionError("Transcription returned empty text")
        logger.info("Transcribed %s (%d chars)", audio_path.name, len(text))
        return text
    except TranscriptionError:
        raise
    except openai.APIError as e:
        raise TranscriptionError(f"OpenAI API error: {e}") from e
    except Exception as e:
        raise TranscriptionError(f"Transcription failed: {e}") from e
