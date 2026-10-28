"""
Deterministic text chunking for immutable record versions.
Breaks markdown and text into retrieval-sized chunks with token estimates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class TextChunk:
    chunk_index: int
    content: str
    token_count: int


def estimate_token_count(text: str) -> int:
    """
    Estimate token count using whitespace and word boundary heuristic.
    Roughly 1 token ~= 0.75 words or ~4 characters.
    """
    if not text.strip():
        return 0
    words = re.findall(r"\S+", text)
    # Estimate max of word count * 1.25 or character length // 4
    return max(1, max(int(len(words) * 1.25), len(text) // 4))


def chunk_text(
    text: str,
    target_chunk_size: int = 800,
    overlap_size: int = 100,
    min_chunk_size: int = 50,
) -> List[TextChunk]:
    """
    Split text deterministically into manageable chunks for vector and full-text search.
    Preserves paragraph breaks where possible.
    """
    clean_text = text.strip()
    if not clean_text:
        return []

    # If entire text is smaller than target chunk size, return single chunk
    if len(clean_text) <= target_chunk_size:
        return [
            TextChunk(
                chunk_index=0,
                content=clean_text,
                token_count=estimate_token_count(clean_text),
            )
        ]

    # Split into paragraphs by double newlines or markdown headers
    paragraphs = re.split(r"(\n\s*\n|(?=^#{1,3}\s))", clean_text, flags=re.MULTILINE)
    blocks = [p.strip() for p in paragraphs if p.strip()]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_length = 0

    for block in blocks:
        block_len = len(block)
        if current_length + block_len > target_chunk_size and current_chunk:
            combined = "\n\n".join(current_chunk).strip()
            if combined:
                chunks.append(combined)

            # Keep the last block for overlap if suitable
            if overlap_size > 0 and len(current_chunk[-1]) <= overlap_size:
                current_chunk = [current_chunk[-1], block]
                current_length = len(current_chunk[0]) + block_len
            else:
                current_chunk = [block]
                current_length = block_len
        else:
            current_chunk.append(block)
            current_length += block_len

    if current_chunk:
        combined = "\n\n".join(current_chunk).strip()
        if combined:
            chunks.append(combined)

    # Edge case: if a single block was longer than target_chunk_size, break it by lines or length
    final_chunks: List[str] = []
    for c in chunks:
        if len(c) > target_chunk_size * 2:
            # Sub-split long monolithic blocks
            sub_start = 0
            while sub_start < len(c):
                sub_end = min(sub_start + target_chunk_size, len(c))
                # Try finding a newline near sub_end
                nl_pos = c.rfind("\n", sub_start + target_chunk_size // 2, sub_end)
                if nl_pos != -1:
                    sub_end = nl_pos
                part = c[sub_start:sub_end].strip()
                if part:
                    final_chunks.append(part)
                sub_start = sub_end
        else:
            final_chunks.append(c)

    # Filter out empty or too small chunks unless it's the only one
    filtered: List[str] = []
    for fc in final_chunks:
        if len(fc) >= min_chunk_size or not filtered:
            filtered.append(fc)
        elif filtered:
            # Append tiny trailing leftover to previous chunk
            filtered[-1] = filtered[-1] + "\n\n" + fc

    return [
        TextChunk(
            chunk_index=idx,
            content=chunk_content,
            token_count=estimate_token_count(chunk_content),
        )
        for idx, chunk_content in enumerate(filtered)
    ]

