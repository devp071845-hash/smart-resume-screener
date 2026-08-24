"""
parser.py — Extracts raw text from uploaded resumes (PDF or plain text).

Structured field extraction (skills / experience / education) is delegated
to the LLM in llm_matcher.py, since regex-based extraction is brittle across
resume formats. This module's job is just: file bytes -> clean text.
"""

import io
import re
import pdfplumber


def extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from a resume file (.pdf or .txt)."""
    if filename.lower().endswith(".pdf"):
        return _extract_pdf_text(file_bytes)
    else:
        # Treat everything else as plain text (.txt, .md, pasted text, etc.)
        return file_bytes.decode("utf-8", errors="ignore")


def _extract_pdf_text(file_bytes: bytes) -> str:
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts)


def clean_text(text: str) -> str:
    """Light normalization: collapse excess whitespace, strip odd control chars."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
