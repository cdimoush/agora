"""Tests for agora.voice — audio transcription via Vox CLI."""

import json
from unittest.mock import AsyncMock, patch

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


def _mock_proc(returncode=0, stdout=b"", stderr=b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = AsyncMock()
    proc.wait = AsyncMock()
    return proc


class TestTranscribe:
    @pytest.mark.asyncio
    async def test_vox_not_installed(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")
        with patch("shutil.which", return_value=None):
            with pytest.raises(TranscriptionError, match="vox CLI not installed"):
                await transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_missing_api_key(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")
        with patch("shutil.which", return_value="/usr/local/bin/vox"):
            with patch.dict("os.environ", {}, clear=True):
                with pytest.raises(TranscriptionError, match="No OpenAI API key"):
                    await transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_file_not_found(self):
        with patch("shutil.which", return_value="/usr/local/bin/vox"):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with pytest.raises(TranscriptionError, match="not found"):
                    await transcribe("/nonexistent/audio.ogg")

    @pytest.mark.asyncio
    async def test_successful_json_transcription(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")
        result_json = json.dumps({"text": "Hello, this is a test.", "error": ""})
        proc = _mock_proc(returncode=0, stdout=result_json.encode())
        with patch("shutil.which", return_value="/usr/local/bin/vox"):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch("asyncio.create_subprocess_exec", return_value=proc):
                    result = await transcribe(audio_file)
        assert result == "Hello, this is a test."

    @pytest.mark.asyncio
    async def test_successful_plain_text(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")
        proc = _mock_proc(returncode=0, stdout=b"Hello plain text")
        with patch("shutil.which", return_value="/usr/local/bin/vox"):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch("asyncio.create_subprocess_exec", return_value=proc):
                    result = await transcribe(audio_file)
        assert result == "Hello plain text"

    @pytest.mark.asyncio
    async def test_empty_transcription_raises(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")
        result_json = json.dumps({"text": "", "error": ""})
        proc = _mock_proc(returncode=0, stdout=result_json.encode())
        with patch("shutil.which", return_value="/usr/local/bin/vox"):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch("asyncio.create_subprocess_exec", return_value=proc):
                    with pytest.raises(TranscriptionError, match="empty"):
                        await transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_exit_code_3_missing_key(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")
        proc = _mock_proc(returncode=3, stderr=b"missing key")
        with patch("shutil.which", return_value="/usr/local/bin/vox"):
            with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
                with patch("asyncio.create_subprocess_exec", return_value=proc):
                    with pytest.raises(TranscriptionError, match="No OpenAI API key"):
                        await transcribe(audio_file)

    @pytest.mark.asyncio
    async def test_explicit_api_key(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data")
        result_json = json.dumps({"text": "transcript", "error": ""})
        proc = _mock_proc(returncode=0, stdout=result_json.encode())
        with patch("shutil.which", return_value="/usr/local/bin/vox"):
            with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
                result = await transcribe(audio_file, api_key="explicit-key")
        assert result == "transcript"
        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["env"]["OPENAI_API_KEY"] == "explicit-key"
