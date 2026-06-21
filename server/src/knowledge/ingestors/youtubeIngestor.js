import { BaseIngestor } from '../baseIngestor.js';

// Target design: fetch auto-generated/manual transcript (timestamps preserved
// in metadata for "jump to this part of the video" citations).
export class YoutubeIngestor extends BaseIngestor {
  constructor() {
    super('youtube');
  }

  async ingest(_source) {
    throw new Error('YoutubeIngestor not implemented — needs transcript fetch (e.g. youtube-transcript)');
  }
}
