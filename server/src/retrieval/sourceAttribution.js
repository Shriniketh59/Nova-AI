// Real implementation — extends sourceFormatter.js's filename-only citation
// with page/line ranges and a confidence score derived from similarity, per
// the target response shape in ARCHITECTURE.md section 6.
export function attributeSources(chunks) {
  const seen = new Set();
  const sources = [];

  for (const chunk of chunks) {
    const filename = chunk.original_filename || 'unknown source';
    const key = `${filename}:${chunk.page_number ?? ''}:${chunk.line_start ?? ''}-${chunk.line_end ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const source = {
      index: sources.length + 1,
      filename,
      type: chunk.source_type || 'document',
      confidence: chunk.similarity != null ? Number(chunk.similarity.toFixed(2)) : null
    };
    if (chunk.page_number != null) source.page = chunk.page_number;
    if (chunk.line_start != null && chunk.line_end != null) {
      source.lines = `${chunk.line_start}-${chunk.line_end}`;
    }
    sources.push(source);
  }

  return sources;
}
