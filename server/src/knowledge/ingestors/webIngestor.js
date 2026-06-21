import { BaseIngestor } from '../baseIngestor.js';

// Target design: fetch HTML, run readability-style main-content extraction
// (strip nav/ads/footers), then chunkText() the cleaned text. source_url
// stored in metadata for citation.
export class WebIngestor extends BaseIngestor {
  constructor() {
    super('web');
  }

  async ingest(_source) {
    throw new Error('WebIngestor not implemented — needs fetch + readability extraction (e.g. @mozilla/readability + jsdom)');
  }
}
