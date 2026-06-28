// Minimal structured logger. Swap for pino/winston later without touching call sites.
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOG_DIR = path.join(__dirname, '../../logs');
const LOG_FILE = path.join(LOG_DIR, 'app.log');
if (!fs.existsSync(LOG_DIR)) fs.mkdirSync(LOG_DIR, { recursive: true });

function timestamp() {
  return new Date().toISOString();
}

function format(level, message, meta) {
  const metaStr = meta && Object.keys(meta).length ? ` ${JSON.stringify(meta)}` : '';
  return `[${timestamp()}] ${level} ${message}${metaStr}`;
}

// Fire-and-forget append — a logging failure must never break the request
// it's logging, so errors here are swallowed rather than thrown.
function writeToFile(level, message, meta) {
  const line = JSON.stringify({ timestamp: timestamp(), level, message, ...meta }) + '\n';
  fs.appendFile(LOG_FILE, line, () => {});
}

export default {
  info(message, meta = {}) {
    console.log(format('INFO', message, meta));
    writeToFile('INFO', message, meta);
  },
  warn(message, meta = {}) {
    console.warn(format('WARN', message, meta));
    writeToFile('WARN', message, meta);
  },
  error(message, meta = {}) {
    console.error(format('ERROR', message, meta));
    writeToFile('ERROR', message, meta);
  }
};
