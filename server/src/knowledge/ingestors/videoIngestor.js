import { BaseIngestor } from '../baseIngestor.js';

// Target design: extract audio track -> AudioIngestor for transcript chunks;
// optionally sample frames for visual-grounded retrieval later (out of scope
// for v1 — text/transcript grounding only).
export class VideoIngestor extends BaseIngestor {
  constructor() {
    super('video');
  }

  async ingest(_source) {
    throw new Error('VideoIngestor not implemented — needs audio extraction (ffmpeg) + AudioIngestor');
  }
}
