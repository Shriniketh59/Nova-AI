import express from 'express';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Project root = repo root (two levels up from server/src/routes).
const PROJECT_ROOT = path.resolve(__dirname, '../../../');

const IGNORE = new Set(['node_modules', '.git', 'dist', 'uploads', 'qdrant']);

const router = express.Router();

// Resolves a user-supplied relative path against PROJECT_ROOT and rejects
// anything that escapes it (../../etc) — the only thing standing between
// "edit this project's files" and "read any file on the machine".
function resolveSafe(relPath) {
  const target = path.resolve(PROJECT_ROOT, '.' + path.sep + (relPath || ''));
  if (!target.startsWith(PROJECT_ROOT)) {
    throw new Error('Path escapes project root');
  }
  return target;
}

function buildTree(dirAbs, relPath = '') {
  const entries = fs.readdirSync(dirAbs, { withFileTypes: true })
    .filter((e) => !IGNORE.has(e.name) && !e.name.startsWith('.'));

  return entries.map((e) => {
    const entryRel = relPath ? `${relPath}/${e.name}` : e.name;
    if (e.isDirectory()) {
      return { name: e.name, path: entryRel, type: 'dir', children: buildTree(path.join(dirAbs, e.name), entryRel) };
    }
    return { name: e.name, path: entryRel, type: 'file' };
  }).sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'dir' ? -1 : 1));
}

router.get('/tree', (req, res) => {
  try {
    const tree = buildTree(PROJECT_ROOT);
    res.json({ name: path.basename(PROJECT_ROOT), path: '', type: 'dir', children: tree });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

router.get('/file', (req, res) => {
  try {
    const target = resolveSafe(req.query.path);
    const content = fs.readFileSync(target, 'utf-8');
    res.json({ path: req.query.path, content });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

router.put('/file', express.json({ limit: '5mb' }), (req, res) => {
  try {
    const { path: relPath, content } = req.body;
    const target = resolveSafe(relPath);
    fs.writeFileSync(target, content ?? '', 'utf-8');
    res.json({ ok: true });
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

export default router;
