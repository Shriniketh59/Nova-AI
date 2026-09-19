import fs from 'fs';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const pdfParse = require('pdf-parse');
import { GoogleGenerativeAI } from '@google/generative-ai';
import dotenv from 'dotenv';
import pool from './db.js';

dotenv.config();

const genAI = new GoogleGenerativeAI(process.env.GEMINI_API_KEY);

// Generate embedding for a given text
export async function generateEmbedding(text) {
  try {
    const model = genAI.getGenerativeModel({ model: "text-embedding-004" });
    const result = await model.embedContent(text);
    return result.embedding.values;
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
    } else {
      // Handles text/plain, text/markdown, etc.
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

// Retrieve relevant chunks for a query from files uploaded in a chat session
export async function searchRelevantChunks(queryText, chatId, topK = 3) {
  try {
    // 1. Get query embedding
    const queryVector = await generateEmbedding(queryText);

    // 2. Fetch all files uploaded in this chat session
    // First, find all messages in this chat session
    const messagesRes = await pool.query(
      'SELECT id FROM messages WHERE chat_id = $1',
      [chatId]
    );
    
    if (messagesRes.rowCount === 0) {
      return [];
    }

    const messageIds = messagesRes.rows.map(m => m.id);

    // Get files associated with these messages
    // Or we can just get all files matching the user_id / chat context
    const filesRes = await pool.query(
      'SELECT id, original_filename FROM uploaded_files WHERE message_id = ANY($1::uuid[])',
      [messageIds]
    );

    if (filesRes.rowCount === 0) {
      return [];
    }

    const fileIds = filesRes.rows.map(f => f.id);

    // Fetch all document chunks for these files
    const chunksRes = await pool.query(
      'SELECT * FROM document_chunks WHERE file_id = ANY($1::uuid[])',
      [fileIds]
    );

    if (chunksRes.rowCount === 0) {
      return [];
    }

    // 3. Compute cosine similarity for each chunk
    const chunksWithSimilarity = chunksRes.rows.map(chunk => {
      const sim = cosineSimilarity(queryVector, chunk.embedding);
      return {
        ...chunk,
        similarity: sim
      };
    });

    // 4. Sort and return topK chunks
    chunksWithSimilarity.sort((a, b) => b.similarity - a.similarity);
    return chunksWithSimilarity.slice(0, topK);
  } catch (err) {
    console.error("Error searching relevant chunks:", err);
    return [];
  }
}
