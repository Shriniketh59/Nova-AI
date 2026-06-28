import { describe, it, expect } from 'vitest';
import request from 'supertest';
import app from '../src/index.js';

describe('chat workflow', () => {
  it('creates a chat, saves messages, and lists multiple conversations', async () => {
    const chatA = await request(app).post('/api/chats').send({ title: 'Chat A' });
    expect(chatA.status).toBe(201);
    expect(chatA.body.id).toBeDefined();

    const chatB = await request(app).post('/api/chats').send({ title: 'Chat B' });
    expect(chatB.status).toBe(201);

    const msg = await request(app)
      .post(`/api/chats/${chatA.body.id}/messages`)
      .send({ role: 'user', content: 'hello nova' });
    expect(msg.status).toBe(201);
    expect(msg.body.content).toBe('hello nova');

    const messages = await request(app).get(`/api/chats/${chatA.body.id}/messages`);
    expect(messages.status).toBe(200);
    expect(messages.body).toHaveLength(1);

    const allChats = await request(app).get('/api/chats');
    expect(allChats.status).toBe(200);
    const ids = allChats.body.map(c => c.id);
    expect(ids).toContain(chatA.body.id);
    expect(ids).toContain(chatB.body.id);
  });
});
