import { BaseIngestor } from '../baseIngestor.js';

// Target design: local speech-to-text (whisper.cpp via Ollama or a dedicated
// binary) producing timestamped segments, chunked like a transcript.
export class AudioIngestor extends BaseIngestor {
  constructor() {
    super('audio');
  }

  async ingest(_source) {
    throw new Error('AudioIngestor not implemented — needs local whisper transcription');
  }
}
