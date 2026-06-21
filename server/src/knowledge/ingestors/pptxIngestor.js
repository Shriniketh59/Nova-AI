import { BaseIngestor } from '../baseIngestor.js';

// Needs a pptx text-extraction lib (e.g. `pptx-parser` or manual zip/XML walk).
export class PptxIngestor extends BaseIngestor {
  constructor() {
    super('document');
  }

  async ingest(_source) {
    throw new Error('PptxIngestor not implemented — slide-by-slide text + speaker notes extraction needed');
  }
}
