// Source of truth for Qdrant collection definitions — imported by
// retrieval/qdrantClient.js (COLLECTIONS) and by a future setup script
// (`node qdrant/setup.js`) that calls ensureAllCollections() once a Qdrant
// instance is reachable at QDRANT_URL.
export const COLLECTIONS = {
  nova_documents: { vectorSize: 384, distance: 'Cosine' }, // pdf/docx/pptx/csv/xlsx/txt/md
  nova_code: { vectorSize: 384, distance: 'Cosine' },      // js/ts/py/java/cpp/repos
  nova_web: { vectorSize: 384, distance: 'Cosine' },       // websites/docs/papers
  nova_media: { vectorSize: 384, distance: 'Cosine' }      // youtube/audio/video transcripts
};

// 384 matches the local `all-minilm` Ollama embedding model currently used
// by rag.js's generateEmbedding(). Changing embedding models requires
// recreating every collection at the new vector size — embeddings from
// different models are not comparable/interchangeable.
