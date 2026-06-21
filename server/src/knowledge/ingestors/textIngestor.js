import { BaseIngestor } from '../baseIngestor.js';
import { parseDocument, chunkText } from '../../rag.js';

// Real implementation for txt/markdown — same chunker, no page concept.
export class TextIngestor extends BaseIngestor {
  constructor() {
    super('document');
  }

  async ingest(source) {
    const text = await parseDocument(source.filePath, source.mimeType || 'text/plain');
    const chunks = chunkText(text);
    return chunks.map(content => ({ content, metadata: {} }));
  }
}
