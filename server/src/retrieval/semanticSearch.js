import { generateEmbedding, searchRelevantChunks, fetchFileIdsForChat } from '../rag.js';
import { search as qdrantSearch, COLLECTIONS } from './qdrantClient.js';

// When QDRANT_URL is set, search the vector DB instead of the in-JS cosine
// loop — falls back to searchRelevantChunks() on any Qdrant error (down
// container, collection not ready yet) so retrieval never hard-fails on an
// infra issue. Callers (hybridSearch.js -> retrievalService.js) don't change
// either way: same chunk shape (id, content, similarity, file_id, ...) out.
export async function semanticSearch(query, chatId, topK = 10) {
  if (!process.env.QDRANT_URL) {
    return searchRelevantChunks(query, chatId, topK);
  }

  try {
    const fileIds = await fetchFileIdsForChat(chatId);
    if (fileIds.length === 0) return [];

    const queryVector = await generateEmbedding(query);
    const results = await qdrantSearch(COLLECTIONS.documents.name, queryVector, {
      limit: topK,
      filter: { must: [{ key: 'file_id', match: { any: fileIds } }] }
    });

    return results.map(r => ({
      id: r.id,
      file_id: r.payload.file_id,
      content: r.payload.content,
      page_number: r.payload.page_number,
      original_filename: r.payload.original_filename,
      similarity: r.score
    }));
  } catch (err) {
    console.warn('⚠️ Qdrant search failed, falling back to in-JS cosine search:', err.message);
    return searchRelevantChunks(query, chatId, topK);
  }
}

export async function embedQuery(query) {
  return generateEmbedding(query);
}
