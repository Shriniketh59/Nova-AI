import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import multer from 'multer';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
import pool, { initDb, DEFAULT_USER_ID } from './db.js';
import { parseDocument, chunkText, generateEmbedding, searchRelevantChunks } from './rag.js';
import { runRagQuery } from './services/ragService.js';
import { retrieve } from './retrieval/retrievalService.js';
import { ReviewAgent } from './agents/reviewAgent.js';
import { memoryAgent } from './agents/memoryAgent.js';
import logger from './utils/logger.js';
import agentChatRouter from './routes/agentChat.js';
import { TranslationAgent, SUPPORTED_LANGUAGES } from './agents/translationAgent.js';

const reviewAgent = new ReviewAgent();

dotenv.config();

const RAG_API_URL = process.env.RAG_API_URL || 'http://127.0.0.1:8008';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Configure upload directory
const uploadDir = path.join(__dirname, '../uploads');
if (!fs.existsSync(uploadDir)) {
  fs.mkdirSync(uploadDir, { recursive: true });
}

// Multer storage configuration
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, uploadDir);
  },
  filename: (req, file, cb) => {
    const uniqueSuffix = Date.now() + '-' + Math.round(Math.random() * 1E9);
    cb(null, uniqueSuffix + path.extname(file.originalname));
  }
});

const upload = multer({
  storage,
  limits: { fileSize: 10 * 1024 * 1024 } // 10MB limit
});

const app = express();
const PORT = process.env.PORT || 5001;

app.use(cors());
app.use(express.json());

// Serve static files from Vite build directory
const distPath = path.join(__dirname, '../../dist');
app.use(express.static(distPath));

// Get all chats for the default user
app.get('/api/chats', async (req, res) => {
  try {
    const result = await pool.query(
      'SELECT * FROM chats WHERE user_id = $1 ORDER BY updated_at DESC',
      [DEFAULT_USER_ID]
    );
    res.json(result.rows);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error fetching chats' });
  }
}	);

// Create a new chat session
app.post('/api/chats', async (req, res) => {
  const { title } = req.body;
  try {
    const result = await pool.query(
      'INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *',
      [DEFAULT_USER_ID, title || 'New Chat']
    );
    res.status(201).json(result.rows[0]);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error creating chat' });
  }
});

// Rename a chat session
app.put('/api/chats/:id', async (req, res) => {
  const { id } = req.params;
  const { title } = req.body;
  try {
    const result = await pool.query(
      'UPDATE chats SET title = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2 AND user_id = $3 RETURNING *',
      [title, id, DEFAULT_USER_ID]
    );
    if (result.rowCount === 0) {
      return res.status(404).json({ error: 'Chat not found' });
    }
    res.json(result.rows[0]);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error updating chat' });
  }
});

// Delete a chat session
app.delete('/api/chats/:id', async (req, res) => {
  const { id } = req.params;
  try {
    const result = await pool.query(
      'DELETE FROM chats WHERE id = $1 AND user_id = $2 RETURNING *',
      [id, DEFAULT_USER_ID]
    );
    if (result.rowCount === 0) {
      return res.status(404).json({ error: 'Chat not found' });
    }
    res.json({ message: 'Chat deleted successfully' });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error deleting chat' });
  }
});

// Get all messages for a specific chat
app.get('/api/chats/:chatId/messages', async (req, res) => {
  const { chatId } = req.params;
  try {
    // Verify chat ownership first
    const chatCheck = await pool.query(
      'SELECT id FROM chats WHERE id = $1 AND user_id = $2',
      [chatId, DEFAULT_USER_ID]
    );
    if (chatCheck.rowCount === 0) {
      return res.status(404).json({ error: 'Chat not found' });
    }

    const messages = await pool.query(
      'SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC',
      [chatId]
    );

    // Fetch associated file attachments for these messages
    const messageIds = messages.rows.map(m => m.id);
    let files = [];
    if (messageIds.length > 0) {
      const filesResult = await pool.query(
        'SELECT id, message_id, filename, original_filename, mime_type, size_bytes FROM uploaded_files WHERE message_id = ANY($1::uuid[])',
        [messageIds]
      );
      files = filesResult.rows;
    }

    // Attach file info to messages
    const enrichedMessages = messages.rows.map(m => {
      const file = files.find(f => f.message_id === m.id);
      return {
        ...m,
        attachment: file ? {
          id: file.id,
          name: file.original_filename,
          type: file.mime_type,
          size: file.size_bytes
        } : null
      };
    });

    res.json(enrichedMessages);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error fetching messages' });
  }
});

// Save a new message (user or AI response) to a chat session
app.post('/api/chats/:chatId/messages', async (req, res) => {
  const { chatId } = req.params;
  const { role, content, fileId } = req.body;
  
  if (!role || !content) {
    return res.status(400).json({ error: 'Role and content are required' });
  }

  try {
    // Verify chat ownership
    const chatCheck = await pool.query(
      'SELECT id FROM chats WHERE id = $1 AND user_id = $2',
      [chatId, DEFAULT_USER_ID]
    );
    if (chatCheck.rowCount === 0) {
      return res.status(404).json({ error: 'Chat not found' });
    }

    // Insert the message
    const result = await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *',
      [chatId, role, content]
    );
    const message = result.rows[0];

    // If fileId is provided, associate the file with this message
    if (fileId) {
      await pool.query(
        'UPDATE uploaded_files SET message_id = $1 WHERE id = $2 AND user_id = $3',
        [message.id, fileId, DEFAULT_USER_ID]
      );
    }

    // Also update the chat's updated_at timestamp
    await pool.query(
      'UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1',
      [chatId]
    );

    res.status(201).json(message);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error saving message' });
  }
});

// Server-side RAG Query and Streaming Endpoint
app.post('/api/chats/:chatId/query', async (req, res) => {
  const { chatId } = req.params;
  const { query, fileId } = req.body;

  if (!query) {
    return res.status(400).json({ error: 'Query text is required' });
  }

  const reqId = `${chatId}-${Date.now()}`;
  const OLLAMA_TIMEOUT_MS = 60000;
  const controller = new AbortController();
  let timedOut = false;
  const timeoutHandle = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, OLLAMA_TIMEOUT_MS);

  console.log(`[CHAT_START] ${reqId} query="${query.slice(0, 80)}"`);

  try {
    // 1. Save user message to database
    const userMsgResult = await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *',
      [chatId, 'user', query]
    );
    const userMsg = userMsgResult.rows[0];

    // If fileId is provided, associate the file with this user message
    if (fileId) {
      await pool.query(
        'UPDATE uploaded_files SET message_id = $1 WHERE id = $2 AND user_id = $3',
        [userMsg.id, fileId, DEFAULT_USER_ID]
      );
    }

    // 2. Fetch context: hybrid+expanded+reranked document retrieval, plus
    // lightweight keyword-overlap memory of earlier turns in this chat.
    // Priority order — Retrieved Sources > Memory > Model Knowledge — is
    // enforced by ordering the context blocks and by gating web_search off
    // when document retrieval already has high confidence (don't dilute a
    // well-grounded answer with open-web noise).
    console.log(`[RETRIEVAL_START] ${reqId}`);
    const [retrieval, memories] = await Promise.all([
      retrieve(query, chatId, { topK: 8 }),
      memoryAgent.getRelevantMemories(chatId, query, userMsg.id, 3)
    ]);
    const contextBlocks = [];
    if (retrieval.contextText) contextBlocks.push(`[Document context]\n${retrieval.contextText}`);
    if (memories.length > 0) contextBlocks.push(`[Earlier in this conversation]\n${memories.join('\n---\n')}`);
    const contextText = contextBlocks.join('\n\n');
    const useWebSearch = retrieval.confidence.label !== 'high';
    console.log(`[RETRIEVAL_END] ${reqId} chunks=${retrieval.chunks.length} confidence=${retrieval.confidence.label} memories=${memories.length}`);

    // 3. Initialize SSE headers
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    // 4. Query local RAG/LLM Python API, streaming tokens as Ollama generates them
    // so the UI shows text immediately instead of waiting for the full answer.
    // AbortController guards against Ollama hanging indefinitely (was the
    // root cause of "Thinking..." never resolving).
    console.log(`[OLLAMA_START] ${reqId}`);
    const ragRes = await fetch(`${RAG_API_URL}/query/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, context: contextText, web_search: useWebSearch }),
      signal: controller.signal
    });
    if (!ragRes.ok) {
      throw new Error(`RAG API error: ${ragRes.status}`);
    }
    console.log(`[OLLAMA_END] ${reqId} status=${ragRes.status}`);

    let accumulatedText = '';
    let sources = [];
    let buffer = '';
    let chunkCount = 0;

    for await (const chunk of ragRes.body) {
      buffer += Buffer.from(chunk).toString('utf8');
      const lines = buffer.split('\n');
      buffer = lines.pop(); // last line may be incomplete, keep for next chunk

      for (const line of lines) {
        if (!line.trim()) continue;
        let data;
        try {
          data = JSON.parse(line);
        } catch (parseErr) {
          console.error(`[STREAM_PARSE_ERROR] ${reqId} line="${line.slice(0, 100)}"`, parseErr.message);
          continue;
        }
        if (data.sources) {
          sources = data.sources;
          res.write(`data: ${JSON.stringify({ text: '', sources })}\n\n`);
        }
        if (data.token) {
          chunkCount++;
          accumulatedText += data.token;
          res.write(`data: ${JSON.stringify({ text: accumulatedText, sources })}\n\n`);
        }
      }
    }
    console.log(`[STREAM_COMPLETE] ${reqId} chunks=${chunkCount} len=${accumulatedText.length}`);

    clearTimeout(timeoutHandle);

    // 4b. Merge document-grounded sources (with retrieval confidence) and
    // web sources into one source-card list for the frontend, and surface
    // the retrieval confidence so the UI can show "low confidence" instead
    // of presenting every answer with equal certainty.
    const webSourceCards = sources.map(s => ({ ...s, type: 'web' }));
    const allSourceCards = [...retrieval.sources, ...webSourceCards];
    res.write(`data: ${JSON.stringify({ text: accumulatedText, sources: allSourceCards, confidence: retrieval.confidence })}\n\n`);

    // 5. Save final AI response to database
    await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)',
      [chatId, 'ai', accumulatedText]
    );

    // Update chat timestamp
    await pool.query(
      'UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1',
      [chatId]
    );

    res.write('data: [DONE]\n\n');
    res.end();
    console.log(`[RESPONSE_SENT] ${reqId}`);

  } catch (err) {
    clearTimeout(timeoutHandle);
    const message = timedOut ? `Ollama timed out after ${OLLAMA_TIMEOUT_MS / 1000}s` : err.message;
    console.error(`[CHAT_ERROR] ${reqId}`, message);
    if (!res.headersSent) {
      res.setHeader('Content-Type', 'text/event-stream');
      res.flushHeaders();
    }
    res.write(`data: ${JSON.stringify({ error: message })}\n\n`);
    res.write('data: [DONE]\n\n');
    res.end();
  }
});

// Multi-agent entry point (currently routes through SupervisorAgent -> KnowledgeAgent).
app.use('/api/agent/chat', agentChatRouter);

// Multilingual translation endpoint, isolated from the chat/RAG flow per
// the "translation only, never answer/explain/summarize" system prompt.
const translationAgent = new TranslationAgent();
app.post('/api/translate', async (req, res) => {
  const { text, targetLanguage } = req.body;

  if (!text || !targetLanguage) {
    return res.status(400).json({
      error: 'text and targetLanguage are required',
      supportedLanguages: SUPPORTED_LANGUAGES
    });
  }

  const result = await translationAgent.run(text, { targetLanguage });
  if (!result.success) {
    return res.status(400).json({ error: result.error });
  }

  res.json(result.output);
});

// Document-grounded RAG Endpoint: answers strictly from uploaded document chunks,
// returning structured sources for citation UI. Distinct from /api/chats/:chatId/query,
// which is the general assistant (web search + own knowledge allowed).
app.post('/api/chat/rag', async (req, res) => {
  const { chatId, message } = req.body;

  if (!chatId || !message) {
    return res.status(400).json({ error: 'chatId and message are required' });
  }

  try {
    await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)',
      [chatId, 'user', message]
    );

    const { answer, sources } = await runRagQuery(message, chatId);

    await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)',
      [chatId, 'ai', answer]
    );
    await pool.query(
      'UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1',
      [chatId]
    );

    res.json({ answer, sources });
  } catch (err) {
    logger.error('rag.chat.failed', { chatId, error: err.message });
    res.status(500).json({ error: 'Failed to generate RAG response' });
  }
});

// RAG Upload Endpoint: Handles file upload, parses, chunks, embeds, and saves to vector db
app.post('/api/upload', upload.single('file'), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: 'No file uploaded' });
  }

  const { originalname, filename, mimetype, size, path: filePath } = req.file;

  const RAG_INDEXABLE_MIME_TYPES = new Set([
    'application/pdf',
    'text/plain',
    'text/markdown',
    'text/csv',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
  ]);
  const isImage = mimetype.startsWith('image/');
  if (!isImage && !RAG_INDEXABLE_MIME_TYPES.has(mimetype)) {
    fs.unlinkSync(filePath);
    return res.status(400).json({
      error: `Unsupported file type "${mimetype}". Supported now: PDF, DOCX, TXT, Markdown, CSV, images. PPTX/Excel support is planned (see ARCHITECTURE.md).`
    });
  }

  try {
    // 1. Insert file record with message_id as null initially
    const fileResult = await pool.query(
      'INSERT INTO uploaded_files (message_id, user_id, filename, original_filename, mime_type, size_bytes, file_path) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *',
      [null, DEFAULT_USER_ID, filename, originalname, mimetype, size, filePath]
    );
    const fileRecord = fileResult.rows[0];

    // Images are stored for display only — no local vision model to index
    // them against, so skip text parsing/embedding entirely.
    if (isImage) {
      console.log(`Stored image ${originalname} (${mimetype}) without RAG indexing — no vision model available.`);
      return res.status(201).json({
        success: true,
        file: {
          id: fileRecord.id,
          name: fileRecord.original_filename,
          type: fileRecord.mime_type,
          size: fileRecord.size_bytes
        }
      });
    }

    // 2. Parse and chunk the document for RAG indexing
    console.log(`Parsing document ${originalname} (${mimetype})...`);
    const docText = await parseDocument(filePath, mimetype);
    const chunks = chunkText(docText);

    console.log(`Generating embeddings for ${chunks.length} chunks...`);
    // 3. Generate embeddings and save chunks
    for (const chunk of chunks) {
      if (!chunk.trim()) continue;
      const embedding = await generateEmbedding(chunk);
      await pool.query(
        'INSERT INTO document_chunks (file_id, content, embedding) VALUES ($1, $2, $3)',
        [fileRecord.id, chunk, JSON.stringify(embedding)]
      );
    }

    console.log(`Successfully indexed ${originalname} with ${chunks.length} chunks.`);

    res.status(201).json({
      success: true,
      file: {
        id: fileRecord.id,
        name: fileRecord.original_filename,
        type: fileRecord.mime_type,
        size: fileRecord.size_bytes
      }
    });
  } catch (err) {
    console.error("Error processing file upload:", err);
    // Cleanup physical file on failure
    if (fs.existsSync(filePath)) {
      fs.unlinkSync(filePath);
    }
    res.status(500).json({ error: `Failed to index file for RAG: ${err.message}` });
  }
});

// RAG Retrieve Endpoint: Returns relevant chunks for a user query in a chat session
app.post('/api/chats/:chatId/query-context', async (req, res) => {
  const { chatId } = req.params;
  const { query, limit } = req.body;

  if (!query) {
    return res.status(400).json({ error: 'Query text is required' });
  }

  try {
    const topK = limit || 3;
    const relevantChunks = await searchRelevantChunks(query, chatId, topK);
    
    res.json({
      success: true,
      chunks: relevantChunks.map(c => ({
        content: c.content,
        similarity: c.similarity,
        fileId: c.file_id
      }))
    });
  } catch (err) {
    console.error("Error retrieving context:", err);
    res.status(500).json({ error: `Failed to retrieve context: ${err.message}` });
  }
});

// Get all files uploaded in a chat session
app.get('/api/chats/:chatId/files', async (req, res) => {
  const { chatId } = req.params;
  try {
    const files = await pool.query(
      `SELECT id, original_filename as name, mime_type as type, size_bytes as size, created_at 
       FROM uploaded_files 
       WHERE message_id IN (SELECT id FROM messages WHERE chat_id = $1)
       ORDER BY created_at DESC`,
      [chatId]
    );
    res.json(files.rows);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Server error fetching files' });
  }
});

// Serve index.html for all non-API client routing requests
app.get('*', (req, res) => {
  if (req.path.startsWith('/api/')) {
    return res.status(404).json({ error: 'API route not found' });
  }
  res.sendFile(path.join(distPath, 'index.html'));
});

// Initialize DB and start listening
initDb().then(() => {
  app.listen(PORT, () => {
    console.log(`Server is running on port ${PORT}`);
  });
}).catch(err => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
