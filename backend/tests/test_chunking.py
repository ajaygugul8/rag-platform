from app.ingestion.chunking import ChunkingStrategy, chunk_document, recursive_chunk
from app.ingestion.parsers import ParsedUnit


def test_recursive_chunk_keeps_short_paragraphs_together():
    text = "Para one is short.\n\nPara two is also short."
    units = [ParsedUnit(text=text, page_number=1)]
    chunks = recursive_chunk(units, chunk_size=100, overlap=10)

    assert len(chunks) == 1
    assert "Para one" in chunks[0].text
    assert "Para two" in chunks[0].text
    assert chunks[0].page_number == 1


def test_recursive_chunk_splits_when_over_budget():
    para_a = "word " * 50
    para_b = "term " * 50
    units = [ParsedUnit(text=f"{para_a}\n\n{para_b}", page_number=2)]

    chunks = recursive_chunk(units, chunk_size=40, overlap=5)

    assert len(chunks) > 1
    assert all(c.page_number == 2 for c in chunks)


def test_chunk_document_dispatches_by_strategy():
    units = [ParsedUnit(text="Some text here.", page_number=1)]
    fixed = chunk_document(units, ChunkingStrategy.FIXED, chunk_size=10, overlap=2)
    recursive = chunk_document(units, ChunkingStrategy.RECURSIVE, chunk_size=10, overlap=2)

    assert len(fixed) >= 1
    assert len(recursive) >= 1
