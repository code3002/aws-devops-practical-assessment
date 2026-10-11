import { readFileSync } from 'node:fs';
import pg from 'pg';
import { createApp } from './app.js';
const required = ['PGHOST', 'PGDATABASE', 'PGUSER', 'PGPASSWORD'];
if (required.some(key => !process.env[key])) throw new Error('Missing database configuration');
const sslMode = process.env.PGSSLMODE ?? 'verify-full';
if (!['verify-full', 'disable'].includes(sslMode)) throw new Error('Unsupported PGSSLMODE');
const pool = new pg.Pool({ max: 5, connectionTimeoutMillis: 5000, query_timeout: 5000,
  ssl: sslMode === 'disable' ? false : { rejectUnauthorized: true, ca: process.env.PGSSLROOTCERT ? readFileSync(process.env.PGSSLROOTCERT, 'utf8') : undefined } });
pool.on('error', () => console.error('Database connection error'));
const server = createApp(pool).listen(3000, '0.0.0.0');
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => server.close(async () => { await pool.end(); process.exit(0); }));
