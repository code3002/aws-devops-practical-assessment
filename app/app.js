import express from 'express';
export function createApp(db) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '4kb' }));
  app.get('/', (_req, res) => res.type('html').send(`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Assessment clock</title><script src="/clock.js" defer></script></head><body><h1>Server time</h1><time id="clock">${new Date().toISOString()}</time></body></html>`));
  app.use(express.static(new URL('./public', import.meta.url).pathname));
  app.get('/time', (_req, res) => res.set('Cache-Control', 'no-store').json({ timestamp: new Date().toISOString() }));
  app.get('/health', (_req, res) => res.json({ status: 'ok' }));
  app.post('/messages', async (req, res) => {
    const text = req.body?.text;
    if (typeof text !== 'string' || !text.trim() || text.length > 200) return res.status(400).json({ error: 'Provide text of 1–200 characters' });
    // Read back exactly the inserted row; user input is never executable SQL or HTML.
    const inserted = await db.query('INSERT INTO messages (text) VALUES ($1) RETURNING id', [text]);
    const result = await db.query('SELECT id, text FROM messages WHERE id = $1', [inserted.rows[0].id]);
    res.status(201).json(result.rows[0]);
  });
  app.use((_req, res) => res.status(404).json({ error: 'Not found' }));
  app.use((err, _req, res, _next) => res.status(err.type === 'entity.too.large' ? 413 : err.type === 'entity.parse.failed' ? 400 : 503).json({ error: 'Request could not be completed' }));
  return app;
}
