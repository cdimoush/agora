"""Tests for agora.chunker — message splitting for Discord's 2000 char limit."""

import pytest

from agora.chunker import chunk_message, DISCORD_MAX_LENGTH


class TestSingleChunk:
    def test_short_message(self):
        result = chunk_message("Hello, world!")
        assert result == ["Hello, world!"]

    def test_exactly_2000_chars(self):
        text = "a" * 2000
        result = chunk_message(text)
        assert result == [text]

    def test_empty_string(self):
        assert chunk_message("") == [""]

    def test_whitespace_only(self):
        assert chunk_message("   \n\n  ") == [""]


class TestMultipleChunks:
    def test_2001_chars_splits(self):
        text = "a" * 2001
        result = chunk_message(text)
        assert len(result) == 2
        assert all(len(c) <= 2000 for c in result)
        # Recombine should give original (minus any stripped whitespace)
        assert "".join(result) == text

    def test_paragraph_split(self):
        para1 = "a" * 1000
        para2 = "b" * 1000
        text = para1 + "\n\n" + para2
        result = chunk_message(text)
        assert len(result) == 2
        assert result[0] == para1
        assert result[1] == para2

    def test_newline_split(self):
        line1 = "a" * 1500
        line2 = "b" * 1500
        text = line1 + "\n" + line2
        result = chunk_message(text)
        assert len(result) == 2
        assert result[0] == line1
        assert result[1] == line2

    def test_space_split(self):
        word1 = "a" * 1500
        word2 = "b" * 1500
        text = word1 + " " + word2
        result = chunk_message(text)
        assert len(result) == 2
        assert result[0] == word1
        assert result[1] == word2

    def test_hard_split_no_whitespace(self):
        text = "a" * 3000
        result = chunk_message(text)
        assert len(result) == 2
        assert result[0] == "a" * 2000
        assert result[1] == "a" * 1000


class TestCodeBlockPreservation:
    def test_code_block_across_chunks(self):
        code = "x = 1\n" * 400  # ~2400 chars
        text = "```python\n" + code + "```"
        result = chunk_message(text)
        assert len(result) >= 2
        # First chunk should end with closing fence
        assert result[0].endswith("```")
        # Second chunk should start with opening fence
        assert result[1].startswith("```")

    def test_no_code_block_no_fences_added(self):
        text = "a " * 1500  # ~3000 chars, splits on spaces
        result = chunk_message(text)
        for chunk in result:
            assert "```" not in chunk


class TestUnicode:
    def test_emoji(self):
        text = "😀" * 2001
        result = chunk_message(text)
        assert len(result) >= 2
        assert all(len(c) <= 2000 for c in result)

    def test_cjk(self):
        text = "漢" * 2001
        result = chunk_message(text)
        assert len(result) >= 2
        assert all(len(c) <= 2000 for c in result)
