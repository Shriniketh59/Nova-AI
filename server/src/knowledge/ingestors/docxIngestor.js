import { BaseIngestor } from '../baseIngestor.js';

// Needs a real docx parser (e.g. `mammoth`) — not installed yet.
export class DocxIngestor extends BaseIngestor {
  constructor() {
    super('document');
  }

  async ingest(_source) {
    throw new Error('DocxIngestor not implemented — add `mammoth` package for text extraction');
  }
}
