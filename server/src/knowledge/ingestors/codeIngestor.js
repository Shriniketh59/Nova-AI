import { BaseIngestor } from '../baseIngestor.js';

// Target design: chunk by function/class boundary (AST-aware per language)
// instead of fixed character windows, so retrieved code chunks are always
// syntactically complete. line_start/line_end populate sourceAttribution.
export class CodeIngestor extends BaseIngestor {
  constructor() {
    super('code');
  }

  async ingest(_source) {
    throw new Error('CodeIngestor not implemented — needs per-language AST chunking (e.g. tree-sitter)');
  }
}
