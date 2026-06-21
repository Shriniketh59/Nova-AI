import { BaseIngestor } from '../baseIngestor.js';

// Needs a real xlsx parser (e.g. `xlsx` / `exceljs`) — not installed yet.
export class ExcelIngestor extends BaseIngestor {
  constructor() {
    super('document');
  }

  async ingest(_source) {
    throw new Error('ExcelIngestor not implemented — add `xlsx` package and sheet-to-row chunking');
  }
}
