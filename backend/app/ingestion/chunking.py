"""
Two chunking strategies, per spec section 5 ("Compare fixed-size,
recursive/structure-aware, and optionally semantic chunking").

- Fixed-size: naive sliding window over the raw text. Fast, simple,
  ignores structure — this is the Phase 2 baseline.
- Recursive/structure-aware: splits on paragraph boundaries first (and
  section headings, carried from the parser), only falling back to a
  fixed-size split when a single paragraph still exceeds chunk_size.
  This keeps semantically coherent units together instead of cutting
  mid-sentence, which is what actually improves retrieval quality —
  Phase 5's evaluation harness is what will let us prove that
  quantitatively rather than just asserting it.

Token counting uses a word-based approximation (~1.3 tokens/word for
English) rather than tiktoken, so ingestion has zero external model
downloads. This is swappable — see `approx_token_count` — and is exactly
the kind of Phase 6 hardening item ("use exact tokenizer for the target
LLM") the README roadmap should call out explicitly once billing accuracy
matters.
"""

import re
from dataclasses import dataclass
from enum import Enum

from app.ingestion.parsers import ParsedUnit

_WORD_RE = re.compile(r"\S+")


def approx_token_count(text: str) -> int:
    words = len(_WORD_RE.findall(text))
    return int(words * 1.3)


@dataclass
class RawChunk:
    text: str
    page_number: int | None
    section_title: str | None
    token_count: int


class ChunkingStrategy(str, Enum):
    FIXED = "fixed"
    RECURSIVE = "recursive"


def _split_words_with_overlap(text: str, chunk_size: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = max(chunk_size - overlap, 1)
    return [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), step)]


def fixed_size_chunk(units: list[ParsedUnit], chunk_size: int = 300, overlap: int = 50) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    for unit in units:
        for piece in _split_words_with_overlap(unit.text, chunk_size, overlap):
            chunks.append(
                RawChunk(
                    text=piece,
                    page_number=unit.page_number,
                    section_title=unit.section_title,
                    token_count=approx_token_count(piece),
                )
            )
    return chunks


def recursive_chunk(units: list[ParsedUnit], chunk_size: int = 300, overlap: int = 50) -> list[RawChunk]:
    chunks: list[RawChunk] = []

    for unit in units:
        paragraphs = [p.strip() for p in unit.text.split("\n\n") if p.strip()]
        buffer_paras: list[str] = []
        buffer_tokens = 0

        def flush():
            if buffer_paras:
                text = "\n\n".join(buffer_paras)
                chunks.append(
                    RawChunk(
                        text=text,
                        page_number=unit.page_number,
                        section_title=unit.section_title,
                        token_count=approx_token_count(text),
                    )
                )
                buffer_paras.clear()

        for para in paragraphs:
            para_tokens = approx_token_count(para)

            if para_tokens > chunk_size:
                # A single paragraph is too big on its own — fall back to a
                # fixed-size split for just this paragraph.
                flush()
                buffer_tokens = 0
                for piece in _split_words_with_overlap(para, chunk_size, overlap):
                    chunks.append(
                        RawChunk(
                            text=piece,
                            page_number=unit.page_number,
                            section_title=unit.section_title,
                            token_count=approx_token_count(piece),
                        )
                    )
                continue

            if buffer_tokens + para_tokens > chunk_size:
                flush()
                buffer_tokens = 0

            buffer_paras.append(para)
            buffer_tokens += para_tokens

        flush()

    return chunks


def chunk_document(
    units: list[ParsedUnit], strategy: ChunkingStrategy, chunk_size: int = 300, overlap: int = 50
) -> list[RawChunk]:
    if strategy == ChunkingStrategy.FIXED:
        return fixed_size_chunk(units, chunk_size, overlap)
    return recursive_chunk(units, chunk_size, overlap)
