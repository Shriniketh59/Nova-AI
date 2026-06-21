// Turns retrieved chunks into a deduplicated, numbered source list for citation UI.
export function formatSources(chunks) {
  const seen = new Set();
  const sources = [];

  for (const chunk of chunks) {
    const filename = chunk.original_filename || 'unknown document';
    if (seen.has(filename)) continue;
    seen.add(filename);
    sources.push(filename);
  }

  return sources.map((filename, i) => ({ index: i + 1, filename }));
}

// Renders "Answer\n\nSources:\n1. file.pdf\n2. notes.pdf" style text, for clients
// that want a single flat string instead of structured { answer, sources }.
export function formatAnswerWithSources(answer, sources) {
  if (!sources.length) return answer;
  const list = sources.map(s => `${s.index}. ${s.filename}`).join('\n');
  return `${answer}\n\nSources:\n${list}`;
}
