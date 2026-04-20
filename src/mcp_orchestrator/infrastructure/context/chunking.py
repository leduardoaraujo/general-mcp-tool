from __future__ import annotations


def chunk_text(text: str, max_chars: int = 900) -> list[str]:
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if not current:
            current = paragraph
            continue

        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}"
            continue

        chunks.append(current)
        current = paragraph

    if current:
        chunks.append(current)

    return chunks or [text.strip()] if text.strip() else []
