"""Message chunking for responses that exceed Discord's character limit."""

from __future__ import annotations

DISCORD_MAX_LENGTH = 2000


def chunk_message(text: str, max_length: int = DISCORD_MAX_LENGTH) -> list[str]:
    """Split a message into chunks that fit within Discord's character limit.

    Splitting strategy (in priority order):
    1. Split on double newline (paragraph boundary)
    2. Split on single newline
    3. Split on space (word boundary)
    4. Hard split at max_length (last resort)

    Preserves code blocks across chunk boundaries.
    Returns [""] for empty input (never returns an empty list).
    Each chunk is stripped and <= max_length characters.
    """
    if not text or not text.strip():
        return [""]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_length:
            stripped = remaining.strip()
            if stripped:
                chunks.append(stripped)
            break

        # Try split strategies in priority order
        split_pos = _find_split(remaining, max_length)
        chunk = remaining[:split_pos].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_pos:]

    # Fix code blocks that span chunk boundaries
    chunks = _fix_code_blocks(chunks)

    return chunks if chunks else [""]


def _find_split(text: str, max_length: int) -> int:
    """Find the best position to split text at, up to max_length."""
    segment = text[:max_length]

    # 1. Paragraph boundary (double newline)
    pos = segment.rfind("\n\n")
    if pos > 0:
        return pos + 2

    # 2. Single newline
    pos = segment.rfind("\n")
    if pos > 0:
        return pos + 1

    # 3. Space (word boundary)
    pos = segment.rfind(" ")
    if pos > 0:
        return pos + 1

    # 4. Hard split
    return max_length


def _fix_code_blocks(chunks: list[str]) -> list[str]:
    """Ensure code blocks are properly opened/closed across chunks."""
    fixed: list[str] = []
    in_code_block = False

    for chunk in chunks:
        if in_code_block:
            chunk = "```\n" + chunk

        # Count triple-backtick fences in this chunk
        fence_count = chunk.count("```")
        # If odd number of fences, the chunk ends inside a code block
        if fence_count % 2 == 1:
            in_code_block = not in_code_block

        if in_code_block:
            chunk = chunk + "\n```"

        fixed.append(chunk)

    return fixed
