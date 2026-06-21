import { BaseIngestor } from '../baseIngestor.js';

// Target design: shallow `git clone`, walk tree respecting .gitignore,
// dispatch each file to CodeIngestor (or textIngestor for README/docs).
export class RepoIngestor extends BaseIngestor {
  constructor() {
    super('code');
  }

  async ingest(_source) {
    throw new Error('RepoIngestor not implemented — needs clone + file-walk + per-file CodeIngestor dispatch');
  }
}
