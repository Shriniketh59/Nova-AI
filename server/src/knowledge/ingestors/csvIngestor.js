import fs from 'fs';
import { BaseIngestor } from '../baseIngestor.js';

// Real implementation — one chunk per row, header repeated for context so
// each chunk is independently meaningful to the embedding model.
export class CsvIngestor extends BaseIngestor {
  constructor() {
    super('document');
  }

  async ingest(source) {
    const raw = fs.readFileSync(source.filePath, 'utf8');
    const lines = raw.split(/\r?\n/).filter(l => l.trim().length > 0);
    if (lines.length === 0) return [];

    const header = lines[0];
    return lines.slice(1).map((row, i) => ({
      content: `${header}\n${row}`,
      metadata: { line_start: i + 2, line_end: i + 2 }
    }));
  }
}
