// Common contract every source-type ingestor implements. ingestorRegistry.js
// picks the right one by mime-type/source-type and the rest of the pipeline
// (embedding, storage, retrieval) never needs to know which ingestor ran.
export class BaseIngestor {
  constructor(sourceType) {
    if (this.constructor === BaseIngestor) {
      throw new Error('BaseIngestor is abstract and cannot be instantiated directly');
    }
    this.sourceType = sourceType; // 'document' | 'code' | 'web' | 'youtube' | 'audio' | 'video'
  }

  /**
   * @param {{ filePath?: string, url?: string, mimeType?: string }} source
   * @returns {Promise<Array<{ content: string, metadata: object }>>}
   *   metadata may include page_number, line_start, line_end, source_url, etc.
   *   depending on sourceType — consumed by sourceAttribution.js downstream.
   */
  async ingest(_source) {
    throw new Error(`${this.constructor.name}.ingest() not implemented`);
  }
}
