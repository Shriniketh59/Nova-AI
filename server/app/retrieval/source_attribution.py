def attribute_sources(chunks: list[dict]) -> list[dict]:
    seen = set()
    sources = []

    for chunk in chunks:
        filename = chunk.get("original_filename") or "unknown source"
        key = f"{filename}:{chunk.get('page_number', '')}:{chunk.get('line_start', '')}-{chunk.get('line_end', '')}"
        if key in seen:
            continue
        seen.add(key)

        similarity = chunk.get("similarity")
        source = {
            "index": len(sources) + 1,
            "chunk_id": chunk.get("id"),
            "filename": filename,
            "type": chunk.get("source_type") or "document",
            "similarity": round(similarity, 4) if similarity is not None else None,
            "confidence": round(similarity, 2) if similarity is not None else None,
        }
        if chunk.get("page_number") is not None:
            source["page"] = chunk["page_number"]
        if chunk.get("line_start") is not None and chunk.get("line_end") is not None:
            source["lines"] = f"{chunk['line_start']}-{chunk['line_end']}"
        sources.append(source)

    return sources
