"""
Normalize extracted text without destroying structure that matters for
chunking and readability: keep paragraph breaks and heading-like lines,
collapse only the noise (repeated whitespace, page-break artifacts,
hyphenation from PDF line-wrapping).
"""

import re


def clean_text(text: str) -> str:
    # Rejoin words that got hyphenated across a line break by the PDF extractor.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Collapse runs of 3+ blank lines to a single paragraph break.
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Collapse repeated spaces/tabs (but keep single newlines intact).
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Strip trailing whitespace on each line.
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    return text.strip()
