import { BaseIngestor } from '../baseIngestor.js';
import { parseDocument, chunkText } from '../../rag.js';

// Real implementation — wraps the existing parseDocument/chunkText pair used
// by /api/upload today, normalized to the BaseIngestor contract.
export class PdfIngestor extends BaseIngestor {
  constructor() {
    super('document');
  }

  async ingest(source) {
    const text = await parseDocument(source.filePath, 'application/pdf');
    const chunks = chunkText(text);
    // pdf-parse does not give us per-page boundaries for free; page_number
    // stays null until a page-aware parser replaces pdf-parse.
    return chunks.map(content => ({ content, metadata: { page_number: null } }));
  }
}
