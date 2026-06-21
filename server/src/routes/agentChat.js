import express from 'express';
import { SupervisorAgent } from '../agents/supervisorAgent.js';
import pool from '../db.js';
import logger from '../utils/logger.js';

const router = express.Router();
const supervisor = new SupervisorAgent();

// SSE endpoint for the future multi-agent flow. Today this streams a single
// final event (SupervisorAgent currently routes everything to KnowledgeAgent,
// which is not itself token-streaming) — once an agent supports incremental
// output, switch the single res.write below to a streaming loop like the
// existing /api/chats/:chatId/query endpoint in index.js.
router.post('/', async (req, res) => {
  const { chatId, message } = req.body;

  if (!chatId || !message) {
    return res.status(400).json({ error: 'chatId and message are required' });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  try {
    await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)',
      [chatId, 'user', message]
    );

    const result = await supervisor.run(message, { chatId });

    if (!result.success) {
      throw new Error(result.error || 'Agent execution failed');
    }

    const { answer, sources } = result.output;

    await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)',
      [chatId, 'ai', answer]
    );
    await pool.query('UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1', [chatId]);

    res.write(`data: ${JSON.stringify({ text: answer, sources })}\n\n`);
    res.write('data: [DONE]\n\n');
    res.end();
  } catch (err) {
    logger.error('agentChat.failed', { chatId, error: err.message });
    res.write(`data: ${JSON.stringify({ error: err.message })}\n\n`);
    res.end();
  }
});

export default router;
