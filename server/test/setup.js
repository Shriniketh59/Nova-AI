import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
import { afterAll } from 'vitest';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Unique per test file's module instance so parallel files don't clobber
// each other's JSON fallback state.
const TEST_DB_PATH = path.join(__dirname, `.test_db.${crypto.randomUUID()}.json`);

// Force the JSON fallback path (no real Postgres needed) and isolate it
// from the dev database file. DATABASE_URL deliberately points at a port
// nothing listens on, so db.js's connect-fails-fall-back-to-JSON path
// triggers immediately (ECONNREFUSED, not a slow timeout).
process.env.JSON_DB_PATH = TEST_DB_PATH;
process.env.DATABASE_URL = 'postgres://postgres:postgres@127.0.0.1:1/nova_ai_test?sslmode=disable';

if (fs.existsSync(TEST_DB_PATH)) fs.unlinkSync(TEST_DB_PATH);

afterAll(() => {
  if (fs.existsSync(TEST_DB_PATH)) fs.unlinkSync(TEST_DB_PATH);
});
