import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const pdfParse = require('pdf-parse');
import mammoth from 'mammoth';
import dotenv from 'dotenv';
import pool from './db.js';

dotenv.config();

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://127.0.0.1:11434';
const OLLAMA_EMBED_MODEL = process.env.OLLAMA_EMBED_MODEL || 'all-minilm';

// Generate embedding for a given text via local Ollama
export async function generateEmbedding(text) {
  try {
    const res = await fetch(`${OLLAMA_URL}/api/embeddings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: OLLAMA_EMBED_MODEL, prompt: text })
    });
    if (!res.ok) throw new Error(`Ollama embeddings error: ${res.status}`);
    const data = await res.json();
    return data.embedding;
  } catch (err) {
    console.error("Embedding generation error:", err);
    throw err;
  }
}

// Chunk text preserving paragraph/sentence boundaries
export function chunkText(text, chunkSize = 800, chunkOverlap = 150) {
  if (!text) return [];
  const paragraphs = text.split('\n\n');
  const chunks = [];
  let currentChunk = '';

  for (const paragraph of paragraphs) {
    const trimmedParagraph = paragraph.trim();
    if (!trimmedParagraph) continue;

    if ((currentChunk + '\n\n' + trimmedParagraph).length <= chunkSize) {
      currentChunk = currentChunk ? currentChunk + '\n\n' + trimmedParagraph : trimmedParagraph;
    } else {
      if (currentChunk) {
        chunks.push(currentChunk);
      }
      
      if (trimmedParagraph.length > chunkSize) {
        const sentences = trimmedParagraph.split(/(?<=[.!?])\s+/);
        let tempChunk = '';
        for (const sentence of sentences) {
          const trimmedSentence = sentence.trim();
          if (!trimmedSentence) continue;
          
          if ((tempChunk + ' ' + trimmedSentence).length <= chunkSize) {
            tempChunk = tempChunk ? tempChunk + ' ' + trimmedSentence : trimmedSentence;
          } else {
            if (tempChunk) chunks.push(tempChunk);
            tempChunk = trimmedSentence;
          }
        }
        currentChunk = tempChunk;
      } else {
        currentChunk = trimmedParagraph;
      }
    }
  }
  if (currentChunk) {
    chunks.push(currentChunk);
  }
  return chunks;
}

// Parse document text based on mime-type
export async function parseDocument(filePath, mimeType) {
  try {
    const dataBuffer = fs.readFileSync(filePath);
    if (mimeType === 'application/pdf') {
      const data = await pdfParse(dataBuffer);
      return data.text;
    } else if (mimeType === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
      const { value } = await mammoth.extractRawText({ buffer: dataBuffer });
      return value;
    } else {
      // Handles text/plain, text/markdown, text/csv, etc.
      return dataBuffer.toString('utf8');
    }
  } catch (err) {
    console.error(`Error parsing file ${filePath}:`, err);
    throw err;
  }
}

// Cosine similarity between two vectors
export function cosineSimilarity(vecA, vecB) {
  let dotProduct = 0.0;
  let normA = 0.0;
  let normB = 0.0;
  const length = Math.min(vecA.length, vecB.length);
  for (let i = 0; i < length; i++) {
    dotProduct += vecA[i] * vecB[i];
    normA += vecA[i] * vecA[i];
    normB += vecB[i] * vecB[i];
  }
  if (normA === 0 || normB === 0) return 0;
  return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
}

// Fetches every document chunk belonging to files uploaded in a chat session,
// without scoring. Shared by semantic search (cosine) and keyword search (BM25-lite)
// so both passes of hybrid search hit the same candidate pool.
export async function fetchChunksForChat(chatId) {
  const messagesRes = await pool.query(
    'SELECT id FROM messages WHERE chat_id = $1',
    [chatId]
  );
  if (messagesRes.rowCount === 0) return [];

  const messageIds = messagesRes.rows.map(m => m.id);

  const filesRes = await pool.query(
    'SELECT id, original_filename FROM uploaded_files WHERE message_id = ANY($1::uuid[])',
    [messageIds]
  );
  if (filesRes.rowCount === 0) return [];

  const fileIds = filesRes.rows.map(f => f.id);
  const filenameByFileId = new Map(filesRes.rows.map(f => [f.id, f.original_filename]));

  const chunksRes = await pool.query(
    'SELECT * FROM document_chunks WHERE file_id = ANY($1::uuid[])',
    [fileIds]
  );
  if (chunksRes.rowCount === 0) return [];

  return chunksRes.rows.map(chunk => ({
    ...chunk,
    original_filename: filenameByFileId.get(chunk.file_id) || 'unknown document'
  }));
}

// Retrieve relevant chunks for a query from files uploaded in a chat session
export async function searchRelevantChunks(queryText, chatId, topK = 3) {
  try {
    const queryVector = await generateEmbedding(queryText);
    const chunks = await fetchChunksForChat(chatId);
    if (chunks.length === 0) return [];

    const chunksWithSimilarity = chunks.map(chunk => ({
      ...chunk,
      similarity: cosineSimilarity(queryVector, chunk.embedding)
    }));

    chunksWithSimilarity.sort((a, b) => b.similarity - a.similarity);
    return chunksWithSimilarity.slice(0, topK);
  } catch (err) {
    console.error("Error searching relevant chunks:", err);
    return [];
  }
}
