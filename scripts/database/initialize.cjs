const fs = require('node:fs');
const crypto = require('node:crypto');

// PostgreSQL accepts this verifier, so password-setting SQL contains no plaintext password.
function verifier(password) {
  const salt = crypto.randomBytes(16);
  const salted = crypto.pbkdf2Sync(password, salt, 4096, 32, 'sha256');
  const client = crypto.createHmac('sha256', salted).update('Client Key').digest();
  const stored = crypto.createHash('sha256').update(client).digest('base64');
  const server = crypto.createHmac('sha256', salted).update('Server Key').digest('base64');
  return `SCRAM-SHA-256$4096:${salt.toString('base64')}$${stored}:${server}`;
}
async function initialize(client, password) {
  await client.query('BEGIN');
  try {
    // Transaction lock makes concurrent initialization serialize without persistent infrastructure.
    await client.query("SELECT pg_advisory_xact_lock(740052)");
    const role = await client.query("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = 'assessment_app'");
    const memberships = await client.query("SELECT 1 FROM pg_auth_members WHERE member = (SELECT oid FROM pg_roles WHERE rolname = 'assessment_app')");
    const ownership = await client.query("SELECT 1 FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass AND refobjid = (SELECT oid FROM pg_roles WHERE rolname = 'assessment_app') AND deptype = 'o'");
    if (ownership.rows.length || memberships.rows.length || role.rows.some(r => Object.values(r).some(Boolean))) throw new Error('Unsafe existing role');
    await client.query(fs.readFileSync(__dirname + '/initialize.sql', 'utf8'));
    await client.query(`ALTER ROLE assessment_app PASSWORD '${verifier(password)}'`);
    await client.query('COMMIT');
  } catch (_) {
    await client.query('ROLLBACK');
    throw new Error('Database initialization failed');
  }
}
async function main() {
  const { Client } = require('/app/node_modules/pg');
  let data = '';
  for await (const chunk of process.stdin) data += chunk;
  const config = JSON.parse(data);
  const ssl = { rejectUnauthorized: true, servername: config.host, ca: fs.readFileSync('/certs/rds-ca.pem', 'utf8') };
  const connection = { host: config.host, port: 5432, database: 'assessment', ssl, connectionTimeoutMillis: 10000, query_timeout: 15000, statement_timeout: 15000 };
  const admin = new Client({ ...connection, user: 'assessment_admin', password: config.adminPassword });
  try { await admin.connect(); await initialize(admin, config.appPassword); }
  finally { await admin.end(); }
  const app = new Client({ ...connection, user: 'assessment_app', password: config.appPassword });
  try {
    await app.connect();
    await app.query('BEGIN');
    const inserted = await app.query('INSERT INTO public.messages (text) VALUES ($1) RETURNING id', ['Database integration check']);
    await app.query('SELECT id, text FROM public.messages WHERE id = $1', [inserted.rows[0].id]);
    await app.query('ROLLBACK');
  } finally { await app.end(); }
}
module.exports = { verifier, initialize };
if (require.main === module) main().catch(() => { console.error('Database setup failed; details withheld'); process.exitCode = 1; });
