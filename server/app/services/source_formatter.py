def format_sources(chunks: list[dict]) -> list[dict]:
    seen = set()
    sources = []

    for chunk in chunks:
        filename = chunk.get("original_filename") or "unknown document"
        if filename in seen:
            continue
        seen.add(filename)
        sources.append(filename)

    return [{"index": i + 1, "filename": filename} for i, filename in enumerate(sources)]


def format_answer_with_sources(answer: str, sources: list[dict]) -> str:
    if not sources:
        return answer
    listing = "\n".join(f"{s['index']}. {s['filename']}" for s in sources)
    return f"{answer}\n\nSources:\n{listing}"
