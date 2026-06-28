import express from 'express';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { CodeAgent } from '../agents/codeAgent.js';
import { ReviewAgent } from '../agents/reviewAgent.js';
import { PlannerAgent } from '../agents/plannerAgent.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, '../../../');
const GENERATED_ROOT = path.join(PROJECT_ROOT, 'generated');

const router = express.Router();
const codeAgent = new CodeAgent();
const reviewAgent = new ReviewAgent();
const plannerAgent = new PlannerAgent();

// Single entry point for the user-facing "Nova AI" assistant. Internally
// chains Planner -> Code -> Review agents, but the caller only ever sees
// one task: plan + generated files + review notes. No agent name leaks
// into the response shape.
const FILE_MARKER_RE = /\/\/\s*FILE:\s*(\S+)|#\s*FILE:\s*(\S+)/;

function extractFiles(markdown) {
  const lines = markdown.split('\n');
  const files = [];
  let pendingPath = null;
  let currentPath = null;
  let inFence = false;
  let fenceLines = [];

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (!inFence) {
        inFence = true;
        fenceLines = [];
        currentPath = pendingPath;
        pendingPath = null;
      } else {
        inFence = false;
        if (currentPath) {
          files.push({ path: currentPath, content: fenceLines.join('\n').trim() });
          currentPath = null;
        }
      }
      continue;
    }

    const marker = line.match(FILE_MARKER_RE);
    if (marker) {
      // Marker can appear right before the fence, or as the leading line(s)
      // inside it (models don't always respect "before" literally) — either
      // way it's metadata, never actual file content.
      if (inFence && !currentPath && fenceLines.every((l) => !l.trim())) {
        currentPath = marker[1] || marker[2];
      } else if (!inFence) {
        pendingPath = marker[1] || marker[2];
      }
      continue;
    }

    if (inFence) fenceLines.push(line);
  }
  return files;
}

function writeGeneratedFile(relPath, content) {
  const safeRel = relPath.replace(/^[/\\]+/, '').replace(/\.\./g, '');
  const target = path.resolve(GENERATED_ROOT, safeRel);
  if (!target.startsWith(GENERATED_ROOT)) throw new Error('Path escapes generated root');
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, 'utf-8');
  return path.relative(PROJECT_ROOT, target).split(path.sep).join('/');
}

router.post('/task', async (req, res) => {
  const { prompt } = req.body;
  if (!prompt) return res.status(400).json({ error: 'prompt is required' });

  try {
    const planResult = await plannerAgent.run(prompt);
    const plan = planResult.output;

    const codePrompt = `${prompt}\n\nIf this requires multiple files, precede EVERY fenced code block with a marker line exactly like:\n// FILE: relative/path/to/file.ext\n(use # FILE: for Python/shell). Always include this marker, even for a single file.`;
    const codeResult = await codeAgent.run(codePrompt);
    const answer = codeResult.output.answer;

    const extracted = extractFiles(answer);
    const writtenFiles = extracted.map((f) => ({
      path: writeGeneratedFile(f.path, f.content),
      content: f.content,
    }));

    const critique = await reviewAgent.critique(answer, {
      question: prompt,
      evidenceSummary: prompt,
      contradictions: [],
    });

    res.json({
      task: prompt,
      plan: {
        intent: plan.intent,
        steps: plan.steps,
      },
      files: writtenFiles,
      summary: answer,
      changes: writtenFiles.map((f) => `Created ${f.path}`),
      review: {
        pass: critique.pass,
        issues: critique.issues,
        confidence: critique.confidenceScore,
      },
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

export default router;
