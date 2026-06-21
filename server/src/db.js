import pg from 'pg';
import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import crypto from 'crypto';

dotenv.config();

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const baseConnectionString = process.env.DATABASE_URL || 'postgres://postgres:postgres@127.0.0.1:54329/postgres?sslmode=disable';
const dbName = 'nova_ai';

const originalPool = new pg.Pool({
  connectionString: baseConnectionString.includes('nova_ai') 
    ? baseConnectionString 
    : `postgres://postgres:postgres@127.0.0.1:54329/${dbName}?sslmode=disable`
});

export const DEFAULT_USER_ID = '00000000-0000-0000-0000-000000000000';

let isFallback = false;
const JSON_DB_PATH = path.join(__dirname, '../nova_ai_db.json');

function readJsonDb() {
  if (!fs.existsSync(JSON_DB_PATH)) {
    const initialDb = {
      users: [
        {
          id: DEFAULT_USER_ID,
          email: 'dr.john.doe@nova.ai',
          password_hash: 'hashedpassword',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        }
      ],
      chats: [],
      messages: [],
      uploaded_files: [],
      document_chunks: []
    };
    fs.writeFileSync(JSON_DB_PATH, JSON.stringify(initialDb, null, 2), 'utf8');
    return initialDb;
  }
  try {
    return JSON.parse(fs.readFileSync(JSON_DB_PATH, 'utf8'));
  } catch (e) {
    console.error("Failed to read JSON DB, returning empty structure", e);
    return { users: [], chats: [], messages: [], uploaded_files: [], document_chunks: [] };
  }
}

function writeJsonDb(data) {
  fs.writeFileSync(JSON_DB_PATH, JSON.stringify(data, null, 2), 'utf8');
}

// SQL Query parser and handler for JSON database
function queryJsonDb(text, params = []) {
  const sql = text.toLowerCase().replace(/\s+/g, ' ').trim();
  const db = readJsonDb();

  // 1. SELECT * FROM chats WHERE user_id = $1 ORDER BY updated_at DESC
  if (sql.includes('select * from chats') && sql.includes('order by updated_at desc')) {
    const userId = params[0] || DEFAULT_USER_ID;
    const rows = db.chats
      .filter(c => c.user_id === userId)
      .sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at));
    return { rows, rowCount: rows.length };
  }

  // 2. INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *
  if (sql.includes('insert into chats') && sql.includes('returning *')) {
    const userId = params[0] || DEFAULT_USER_ID;
    const title = params[1] || 'New Chat';
    const newChat = {
      id: crypto.randomUUID(),
      user_id: userId,
      title,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
    db.chats.push(newChat);
    writeJsonDb(db);
    return { rows: [newChat], rowCount: 1 };
  }

  // 3. UPDATE chats SET title = $1, updated_at = CURRENT_TIMESTAMP WHERE id = $2 AND user_id = $3 RETURNING *
  if (sql.includes('update chats set title') && sql.includes('returning *')) {
    const title = params[0];
    const id = params[1];
    const userId = params[2] || DEFAULT_USER_ID;
    const chatIndex = db.chats.findIndex(c => c.id === id && c.user_id === userId);
    if (chatIndex === -1) return { rows: [], rowCount: 0 };
    
    db.chats[chatIndex].title = title;
    db.chats[chatIndex].updated_at = new Date().toISOString();
    writeJsonDb(db);
    return { rows: [db.chats[chatIndex]], rowCount: 1 };
  }

  // 4. DELETE FROM chats WHERE id = $1 AND user_id = $2 RETURNING *
  if (sql.includes('delete from chats') && sql.includes('returning *')) {
    const id = params[0];
    const userId = params[1] || DEFAULT_USER_ID;
    const chatIndex = db.chats.findIndex(c => c.id === id && c.user_id === userId);
    if (chatIndex === -1) return { rows: [], rowCount: 0 };
    
    const [deletedChat] = db.chats.splice(chatIndex, 1);
    db.messages = db.messages.filter(m => m.chat_id !== id);
    writeJsonDb(db);
    return { rows: [deletedChat], rowCount: 1 };
  }

  // 5. SELECT id FROM chats WHERE id = $1 AND user_id = $2
  if (sql.includes('select id from chats') && sql.includes('where id = $1')) {
    const id = params[0];
    const userId = params[1] || DEFAULT_USER_ID;
    const chat = db.chats.find(c => c.id === id && c.user_id === userId);
    return { rows: chat ? [{ id: chat.id }] : [], rowCount: chat ? 1 : 0 };
  }

  // 6. SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC
  if (sql.includes('from messages') && sql.includes('where chat_id = $1')) {
    const chatId = params[0];
    let rows = db.messages
      .filter(m => m.chat_id === chatId)
      .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    if (sql.startsWith('select id from messages')) {
      rows = rows.map(m => ({ id: m.id }));
    }
    return { rows, rowCount: rows.length };
  }

  // 7. INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) [RETURNING *]
  if (sql.includes('insert into messages')) {
    const chatId = params[0];
    const role = params[1];
    const content = params[2];
    const newMessage = {
      id: crypto.randomUUID(),
      chat_id: chatId,
      role,
      content,
      created_at: new Date().toISOString()
    };
    db.messages.push(newMessage);
    writeJsonDb(db);
    return { rows: [newMessage], rowCount: 1 };
  }

  // 8. UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1
  if (sql.includes('update chats set updated_at') && sql.includes('where id = $1')) {
    const chatId = params[0];
    const chatIndex = db.chats.findIndex(c => c.id === chatId);
    if (chatIndex !== -1) {
      db.chats[chatIndex].updated_at = new Date().toISOString();
      writeJsonDb(db);
    }
    return { rows: [], rowCount: chatIndex !== -1 ? 1 : 0 };
  }

  // 8b. UPDATE uploaded_files SET message_id = $1 WHERE id = $2 AND user_id = $3
  if (sql.includes('update uploaded_files set message_id')) {
    const messageId = params[0];
    const id = params[1];
    const userId = params[2] || DEFAULT_USER_ID;
    const fileIndex = db.uploaded_files.findIndex(f => f.id === id && f.user_id === userId);
    if (fileIndex !== -1) {
      db.uploaded_files[fileIndex].message_id = messageId;
      writeJsonDb(db);
    }
    return { rows: [], rowCount: fileIndex !== -1 ? 1 : 0 };
  }

  // 9. INSERT INTO uploaded_files
  if (sql.includes('insert into uploaded_files')) {
    const [messageId, userId, filename, originalFilename, mimeType, sizeBytes, filePath] = params;
    const newFile = {
      id: crypto.randomUUID(),
      message_id: messageId,
      user_id: userId || DEFAULT_USER_ID,
      filename,
      original_filename: originalFilename,
      mime_type: mimeType,
      size_bytes: parseInt(sizeBytes),
      file_path: filePath,
      created_at: new Date().toISOString()
    };
    db.uploaded_files.push(newFile);
    writeJsonDb(db);
    return { rows: [newFile], rowCount: 1 };
  }

  // 10. INSERT INTO document_chunks
  if (sql.includes('insert into document_chunks')) {
    const [fileId, content, embedding] = params;
    const newChunk = {
      id: crypto.randomUUID(),
      file_id: fileId,
      content,
      embedding: Array.isArray(embedding) ? embedding : JSON.parse(embedding),
      created_at: new Date().toISOString()
    };
    db.document_chunks.push(newChunk);
    writeJsonDb(db);
    return { rows: [newChunk], rowCount: 1 };
  }

  // 11. SELECT ... FROM uploaded_files
  if (sql.includes('from uploaded_files')) {
    let rows = db.uploaded_files;
    if (sql.includes('where message_id = any')) {
      const messageIds = params[0] || [];
      rows = rows.filter(f => messageIds.includes(f.message_id));
    } else if (sql.includes('where message_id in (select id from messages where chat_id')) {
      const chatId = params[0];
      const chatMessageIds = db.messages.filter(m => m.chat_id === chatId).map(m => m.id);
      rows = rows.filter(f => chatMessageIds.includes(f.message_id));
    } else if (sql.includes('where user_id = $1')) {
      const userId = params[0] || DEFAULT_USER_ID;
      rows = rows.filter(f => f.user_id === userId);
    } else if (sql.includes('where id = $1')) {
      const id = params[0];
      rows = rows.filter(f => f.id === id);
    }
    return { rows, rowCount: rows.length };
  }

  // 12. SELECT * FROM document_chunks
  if (sql.includes('select * from document_chunks')) {
    let rows = db.document_chunks;
    if (sql.includes('where file_id = any')) {
      const fileIds = params[0] || [];
      rows = rows.filter(c => fileIds.includes(c.file_id));
    } else if (sql.includes('where file_id = $1')) {
      const fileId = params[0];
      rows = rows.filter(c => c.file_id === fileId);
    }
    return { rows, rowCount: rows.length };
  }

  // Fallback default response for unhandled queries
  console.warn("⚠️ Unhandled SQL query in JSON fallback:", sql);
  return { rows: [], rowCount: 0 };
}

async function ensureDatabaseExists() {
  const adminClient = new pg.Client({ connectionString: baseConnectionString });
  await adminClient.connect();
  try {
    const res = await adminClient.query(`SELECT 1 FROM pg_database WHERE datname = $1`, [dbName]);
    if (res.rowCount === 0) {
      console.log(`Database "${dbName}" does not exist. Creating it...`);
      await adminClient.query(`CREATE DATABASE ${dbName}`);
      console.log(`Database "${dbName}" created successfully.`);
    } else {
      console.log(`Database "${dbName}" already exists.`);
    }
  } catch (err) {
    console.error('Error ensuring database exists:', err);
    throw err;
  } finally {
    await adminClient.end();
  }
}

export async function initDb() {
  try {
    await ensureDatabaseExists();

    const client = await originalPool.connect();
    try {
      console.log(`Connecting to "${dbName}" PostgreSQL database...`);
      const migrationPath = path.join(__dirname, '../migrations/001_initial_schema.sql');
      const sql = fs.readFileSync(migrationPath, 'utf8');
      
      await client.query('BEGIN');
      
      const tableCheck = await client.query(`
        SELECT EXISTS (
          SELECT FROM information_schema.tables 
          WHERE table_schema = 'public' 
          AND table_name = 'users'
        );
      `);
      
      if (!tableCheck.rows[0].exists) {
        console.log('Running initial database migrations...');
        await client.query(sql);
        console.log('Database migrations completed successfully.');
      } else {
        console.log('Tables already exist. Skipping migrations.');
      }

      await client.query(`
        INSERT INTO users (id, email, password_hash)
        VALUES ($1, $2, $3)
        ON CONFLICT (id) DO NOTHING;
      `, [DEFAULT_USER_ID, 'dr.john.doe@nova.ai', 'hashedpassword']);
      
      await client.query('COMMIT');
    } finally {
      client.release();
    }
  } catch (err) {
    console.warn("⚠️ Failed to connect to PostgreSQL. Falling back to local JSON database database!", err.message);
    isFallback = true;
    readJsonDb(); // Ensure local DB exists
  }
}

export const pool = {
  async query(text, params) {
    if (isFallback) {
      return queryJsonDb(text, params);
    }
    try {
      return await originalPool.query(text, params);
    } catch (err) {
      console.error("Postgres query error, attempting JSON fallback:", err);
      isFallback = true;
      return queryJsonDb(text, params);
    }
  },
  async connect() {
    if (isFallback) {
      return {
        query: (text, params) => queryJsonDb(text, params),
        release: () => {}
      };
    }
    try {
      return await originalPool.connect();
    } catch (err) {
      console.error("Postgres connect error, attempting JSON fallback:", err);
      isFallback = true;
      return {
        query: (text, params) => queryJsonDb(text, params),
        release: () => {}
      };
    }
  },
  async end() {
    if (!isFallback) {
      await originalPool.end();
    }
  }
};

export default pool;
