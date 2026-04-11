"""Tests for agora.voice — audio transcription module."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agora.voice import TranscriptionError, is_audio_file, transcribe


class TestIsAudioFile:
    @pytest.mark.parametrize(
        "filename",
        ["voice.ogg", "clip.mp3", "song.wav", "memo.m4a", "note.webm", "talk.opus", "old.oga"],
    )
    def test_audio_extensions(self, filename):
        assert is_audio_file(filename) is True

    @pytest.mark.parametrize(
        "filename",
        ["image.png", "doc.pdf", "code.py", "readme.md", "data.json", "noext"],
    )
    def test_non_audio_extensions(self, filename):
        assert is_audio_file(filename) is False

    def test_case_insensitive(self):
        assert is_audio_file("voice.OGG") is True
        assert is_audio_file("clip.Mp3") is True


class TestTranscribe:
    @pytest.mark.asyncio
    async def test_missing_api_key(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(TranscriptionError, match="No OpenAI API key"):
                await transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with pytest.raises(TranscriptionError, match="not found"):
                await transcribe("/nonexistent/audio.ogg")

    @pytest.mark.asyncio
    async def test_successful_transcription(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")

        mock_response = SimpleNamespace(text="Hello, this is a test transcript.")
        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("openai.AsyncOpenAI", return_value=mock_client):
                result = await transcribe(audio_file)

        assert result == "Hello, this is a test transcript."
        mock_client.audio.transcriptions.create.assert_awaited_once()
        call_kwargs = mock_client.audio.transcriptions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini-transcribe"

    @pytest.mark.asyncio
    async def test_empty_transcription_raises(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")

        mock_response = SimpleNamespace(text="")
        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            with patch("openai.AsyncOpenAI", return_value=mock_client):
                with pytest.raises(TranscriptionError, match="empty"):
                    await transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_explicit_api_key(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")

        mock_response = SimpleNamespace(text="transcript")
        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

        with patch("openai.AsyncOpenAI", return_value=mock_client) as mock_cls:
            result = await transcribe(audio_file, api_key="explicit-key")

        assert result == "transcript"
        mock_cls.assert_called_once_with(api_key="explicit-key")
