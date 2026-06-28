import express from 'express';
import { SupervisorAgent } from '../agents/supervisorAgent.js';
import pool, { DEFAULT_USER_ID } from '../db.js';
import { memoryAgent } from '../agents/memoryAgent.js';
import { detectDocumentRequest, buildSummary } from '../services/documentTypeDetector.js';
import logger from '../utils/logger.js';
import { fetchChunksForChat, fetchImagesForChat } from '../rag.js';
import { classifyTask } from '../services/taskRouter.js';
import { calculateAtsScore, formatAtsAnswer } from '../services/atsService.js';
import { DocumentAnalysisAgent } from '../agents/documentAnalysisAgent.js';
import { DocumentComparisonAgent } from '../agents/documentComparisonAgent.js';
import { ResumeAnalysisAgent } from '../agents/resumeAnalysisAgent.js';
import { VisionAgent } from '../agents/visionAgent.js';
import { CodeAgent } from '../agents/codeAgent.js';

const router = express.Router();
const supervisor = new SupervisorAgent();
const documentAnalysisAgent = new DocumentAnalysisAgent();
const documentComparisonAgent = new DocumentComparisonAgent();
const resumeAnalysisAgent = new ResumeAnalysisAgent();
const visionAgent = new VisionAgent();
const codeAgent = new CodeAgent();

const STAGE_LABELS = {
  planning: 'Analyzing your question...',
  memory: 'Checking earlier context...',
  researching: 'Gathering evidence from sources...',
  reasoning: 'Reasoning through the evidence...',
  reviewing: 'Reviewing the answer for accuracy...',
  regenerating: 'Found an issue — revising the answer...'
};

// Critical-thinking pipeline endpoint: streams stage progress ("Planning...",
// "Researching...", ...) while SupervisorAgent runs its full
// plan -> research -> reason -> review loop (no token streaming mid-answer —
// the answer only exists once reasoning+review finish, unlike the simple
// single-shot /api/chats/:chatId/query path). This trades the 60s timeout
// budget of that endpoint for minutes of real deliberation, intentionally,
// per the "Reasoning > Speed" priority for this pipeline.
router.post('/', async (req, res) => {
  const { chatId, message } = req.body;

  if (!chatId || !message) {
    return res.status(400).json({ error: 'chatId and message are required' });
  }

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();

  const reqId = `${chatId}-${Date.now()}`;
  console.log(`[CRITICAL_THINK_START] ${reqId}`);

  try {
    const userMsgResult = await pool.query(
      'INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *',
      [chatId, 'user', message]
    );
    const userMsg = userMsgResult.rows[0];
    memoryAgent.extractMemory(DEFAULT_USER_ID, chatId, message).catch(() => {});

    // Task Router applies here too — "analyze/evaluate" keywords can route
    // a message to this deep pipeline (see Chat.jsx's complexity heuristic),
    // but an attached file still means Uploaded Document > Web Search. Same
    // short-circuit as the fast path, before SupervisorAgent (and its
    // ResearchAgent web search) ever runs.
    const [allChatChunks, chatImages] = await Promise.all([
      fetchChunksForChat(chatId),
      fetchImagesForChat(chatId)
    ]);
    const hasFiles = allChatChunks.length > 0;
    const hasImages = chatImages.length > 0;
    const fileCount = new Set(allChatChunks.map(c => c.file_id)).size;
    const task = classifyTask(message, { hasFiles, hasImages, fileCount });
    console.log(`[TASK_ROUTE] ${reqId} type=${task.type} hasFiles=${hasFiles} hasImages=${hasImages}`);

    if (task.type === 'vision') {
      const image = chatImages[chatImages.length - 1];
      const result = await visionAgent.run(message, { filePath: image.file_path, fileName: image.original_filename });
      const answer = result.output.answer;
      const confidence = { score: result.success ? 75 : 0, label: result.success ? 'high' : 'low', reason: 'Based on uploaded image content only.' };

      await pool.query('INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)', [chatId, 'ai', answer]);
      await pool.query('UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1', [chatId]);
      res.write(`data: ${JSON.stringify({ text: answer, sources: [{ filename: image.original_filename, type: 'image' }], confidence })}\n\n`);
      res.write('data: [DONE]\n\n');
      return res.end();
    }

    if (task.type === 'coding') {
      // Coding questions never belong in the 1-3min critical-thinking
      // pipeline (planner->research->reasoning->review) — they're
      // self-contained, the research stages add latency with no accuracy
      // benefit. Same fast path as the single-shot endpoint.
      let codeAnswer = '';
      try {
        const { answer, confidence } = await codeAgent.runStream(message, (token) => {
          codeAnswer += token;
          res.write(`data: ${JSON.stringify({ text: codeAnswer, sources: [] })}\n\n`);
        });
        codeAnswer = answer;
        await pool.query('INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)', [chatId, 'ai', codeAnswer]);
        await pool.query('UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1', [chatId]);
        res.write(`data: ${JSON.stringify({ text: codeAnswer, sources: [], confidence })}\n\n`);
      } catch (err) {
        res.write(`data: ${JSON.stringify({ error: err.message })}\n\n`);
      }
      res.write('data: [DONE]\n\n');
      return res.end();
    }

    if (task.type !== 'general') {
      const documentText = allChatChunks.map(c => c.content).join('\n');
      const fileName = allChatChunks[0]?.original_filename || 'document';
      let answer, confidence;

      if (task.type === 'document_comparison') {
        const byFile = new Map();
        for (const chunk of allChatChunks) {
          const existing = byFile.get(chunk.file_id) || { fileName: chunk.original_filename, text: '' };
          existing.text += `${chunk.content}\n`;
          byFile.set(chunk.file_id, existing);
        }
        const documents = [...byFile.values()];
        const result = await documentComparisonAgent.run(message, { documents });
        answer = result.output.answer;
        confidence = { score: result.success ? 75 : 0, label: result.success ? 'high' : 'low', reason: 'Based on the uploaded documents only.' };
        const sourceCards = documents.map(d => ({ filename: d.fileName, type: 'document' }));

        await pool.query('INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)', [chatId, 'ai', answer]);
        await pool.query('UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1', [chatId]);
        res.write(`data: ${JSON.stringify({ text: answer, sources: sourceCards, confidence })}\n\n`);
        res.write('data: [DONE]\n\n');
        return res.end();
      }

      if (task.type === 'ats') {
        const atsResult = calculateAtsScore(documentText);
        answer = formatAtsAnswer(atsResult);
        confidence = { score: atsResult.score, label: atsResult.score >= 70 ? 'high' : atsResult.score >= 30 ? 'medium' : 'low', reason: 'Calculated from parsed resume content.' };
      } else if (task.type === 'resume_analysis') {
        const result = await resumeAnalysisAgent.run(message, { documentText, fileName });
        answer = result.output.answer;
        confidence = { score: result.success ? 75 : 0, label: result.success ? 'high' : 'low', reason: 'Based on uploaded resume content only.' };
      } else {
        const result = await documentAnalysisAgent.run(message, { documentText, fileName });
        answer = result.output.answer;
        confidence = { score: result.success ? 75 : 0, label: result.success ? 'high' : 'low', reason: 'Based on uploaded document content only.' };
      }

      await pool.query('INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)', [chatId, 'ai', answer]);
      await pool.query('UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1', [chatId]);
      res.write(`data: ${JSON.stringify({ text: answer, sources: [{ filename: fileName, type: 'document' }], confidence })}\n\n`);
      res.write('data: [DONE]\n\n');
      return res.end();
    }

    const onStage = (stage) => {
      console.log(`[STAGE] ${reqId} ${stage}`);
      res.write(`data: ${JSON.stringify({ stage, stageLabel: STAGE_LABELS[stage] || stage })}\n\n`);
    };

    const result = await supervisor.run(message, { chatId, excludeMessageId: userMsg.id, onStage, hasFiles });

    if (!result.success) {
      throw new Error(result.error || 'Agent execution failed');
    }

    const { answer, evidence, confidence, contradictions, regenerated } = result.output;

    const docType = detectDocumentRequest(message);
    const document = docType ? {
      title: docType.label,
      subtitle: null,
      type: docType.type,
      summary: buildSummary(answer),
      content: answer,
      createdAt: new Date().toISOString(),
      exportFormats: ['docx', 'pdf', 'pptx', 'xlsx', 'markdown', 'txt']
    } : null;

    await pool.query(
      'INSERT INTO messages (chat_id, role, content, document) VALUES ($1, $2, $3, $4)',
      [chatId, 'ai', answer, document ? JSON.stringify(document) : null]
    );
    await pool.query('UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1', [chatId]);

    console.log(`[CRITICAL_THINK_DONE] ${reqId} regenerated=${regenerated} confidence=${confidence.score}`);

    res.write(`data: ${JSON.stringify({ text: answer, sources: evidence, confidence, contradictions, document })}\n\n`);
    res.write('data: [DONE]\n\n');
    res.end();
  } catch (err) {
    logger.error('agentChat.failed', { chatId, error: err.message });
    console.error(`[CRITICAL_THINK_ERROR] ${reqId}`, err.message);
    res.write(`data: ${JSON.stringify({ error: err.message })}\n\n`);
    res.write('data: [DONE]\n\n');
    res.end();
  }
});

export default router;
