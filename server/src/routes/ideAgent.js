import express from 'express';
import { CodeAgent } from '../agents/codeAgent.js';
import { ReviewAgent } from '../agents/reviewAgent.js';
import { PlannerAgent } from '../agents/plannerAgent.js';

const router = express.Router();
const codeAgent = new CodeAgent();
const reviewAgent = new ReviewAgent();
const plannerAgent = new PlannerAgent();

// Thin endpoint for the IDE Agent Panel — reuses the existing agent classes
// as-is (no new agent logic), just exposes each one standalone instead of
// only through the chat pipeline's classifyTask routing.
router.post('/', async (req, res) => {
  const { agent, input } = req.body;
  if (!agent || !input) {
    return res.status(400).json({ error: 'agent and input are required' });
  }

  try {
    if (agent === 'code') {
      const result = await codeAgent.run(input);
      return res.json({ output: result.output.answer, confidence: result.output.confidence });
    }

    if (agent === 'planner') {
      const result = await plannerAgent.run(input);
      const plan = result.output;
      const md = `# Intent\n${plan.intent}\n\n# Task Type\n${plan.taskType}\n\n# Steps\n${plan.steps.map((s, i) => `${i + 1}. ${s}`).join('\n')}`;
      return res.json({ output: md });
    }

    if (agent === 'review') {
      const critique = await reviewAgent.critique(input, {
        question: input,
        evidenceSummary: input,
        contradictions: []
      });
      const md = `# Verdict\n${critique.pass ? 'Pass' : 'Issues found'}\n\n# Issues\n${critique.issues.length ? critique.issues.map(i => `- ${i}`).join('\n') : '- None'}\n\n# Confidence\n${critique.confidenceScore}% — ${critique.confidenceReason}`;
      return res.json({ output: md });
    }

    return res.status(400).json({ error: `Unknown agent: ${agent}` });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

export default router;
