import uuid

from app.retrieval.hybrid import _is_image_chunk, _min_max_normalize
from app.retrieval.metadata import build_metadata_filter


def test_min_max_normalize_scales_to_unit_range():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scores = {a: 0.2, b: 0.6, c: 1.0}
    normalized = _min_max_normalize(scores)

    assert normalized[a] == 0.0
    assert normalized[c] == 1.0
    assert 0.0 < normalized[b] < 1.0


def test_min_max_normalize_handles_all_equal_scores():
    a, b = uuid.uuid4(), uuid.uuid4()
    normalized = _min_max_normalize({a: 0.5, b: 0.5})
    assert normalized[a] == normalized[b] == 1.0


def test_min_max_normalize_handles_empty():
    assert _min_max_normalize({}) == {}


def test_build_metadata_filter_none_when_no_filters():
    assert build_metadata_filter(None) is None
    assert build_metadata_filter({}) is None


def test_build_metadata_filter_produces_clause_when_filters_present():
    clause = build_metadata_filter({"department": "hr"})
    assert clause is not None


def test_is_image_chunk_detects_section_prefixed_image_content():
    chunk = (
        'This image appears in the section titled "2. Square Text Wrapping (Right-Aligned)".\n\n'
        'This image depicts: The image features a wooden table with a white coffee cup and a laptop computer.'
    )

    assert _is_image_chunk(chunk) is True
    assert _is_image_chunk("This image depicts: a drawing") is True
    assert _is_image_chunk("Some text about an image") is False
